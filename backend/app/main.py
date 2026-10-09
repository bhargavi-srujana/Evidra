"""Evidra FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.mongo import close_mongo, ensure_indexes, ping_mongo

logger = logging.getLogger(__name__)


def llm_health() -> dict:
    """LLM key status for /health (counts and shape warnings only, never secrets)."""
    settings = get_settings()
    return {
        "keys_configured": len(settings.API_KEYS),
        "key_warning": settings.llm_key_warning(),
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify Mongo connectivity (non-fatal — /health reports status).
    app.state.mongo_connected = await ping_mongo()
    # Startup: ensure unique + TTL indexes (best-effort, never raises).
    await ensure_indexes()
    # Startup: a malformed LLM key 401s every extraction call and yields hollow
    # results — log the actionable warning once instead of failing silently.
    warning = get_settings().llm_key_warning()
    if warning:
        logger.warning("LLM key problem at startup: %s", warning)
    yield
    # Shutdown: release Motor client.
    await close_mongo()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Research Evidence & Contradiction Engine",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Extension point for Phase 2+: mount versioned routers when they exist.
    try:
        from app.api.v1.router import api_router  # type: ignore

        app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    except (ImportError, AttributeError):
        pass

    @app.get("/", tags=["root"])
    async def root() -> dict:
        return {"service": settings.APP_NAME, "env": settings.APP_ENV, "docs": "/docs"}

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "mongo_connected": await ping_mongo(),
            "llm": llm_health(),
        }

    @app.get(f"{settings.API_V1_PREFIX}/health", tags=["health"])
    async def v1_health() -> dict:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "mongo_connected": await ping_mongo(),
            "llm": llm_health(),
        }

    return app


app = create_app()
