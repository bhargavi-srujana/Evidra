"""Evidra FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.mongo import close_mongo, ping_mongo


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify Mongo connectivity (non-fatal — /health reports status).
    app.state.mongo_connected = await ping_mongo()
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
        }

    @app.get(f"{settings.API_V1_PREFIX}/health", tags=["health"])
    async def v1_health() -> dict:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "mongo_connected": await ping_mongo(),
        }

    return app


app = create_app()
