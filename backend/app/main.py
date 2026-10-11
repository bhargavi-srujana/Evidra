"""Evidra FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.db.mongo import close_mongo, ensure_indexes, ping_mongo

logger = logging.getLogger(__name__)

# Reject oversized request bodies before routing (Pydantic max_length caps
# fields, but never sees the raw bytes). Enforced via Content-Length when
# present; chunked bodies without it are bounded by reading at most
# MAX_BODY_BYTES + 1 bytes below.
MAX_BODY_BYTES = 1_000_000


async def _body_limit_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large (max 1 MB)."},
                )
        except ValueError:
            pass
        return await call_next(request)
    # No Content-Length (e.g. chunked): read body with a cap so an unbounded
    # stream cannot bypass the limit. Re-inject for downstream handlers.
    try:
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large (max 1 MB)."},
                )
        body = b"".join(chunks)

        async def _receive() -> dict:  # type: ignore[no-untyped-def]
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _receive  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001 - on read failure let routing handle it
        logger.debug("Chunked body read failed: %s", exc)
    return await call_next(request)


# Cache Mongo ping for health probes so scrapers don't pay a 3s
# serverSelectionTimeout on every scrape.
_HEALTH_CACHE_TTL = 10.0
_health_cache: dict[str, object] = {"mongo": False, "at": 0.0}

import time as _time


async def _cached_ping() -> bool:
    try:
        now = _time.monotonic()
        if now - float(_health_cache.get("at", 0.0)) < _HEALTH_CACHE_TTL:
            return bool(_health_cache.get("mongo", False))
    except Exception as exc:  # noqa: BLE001 - cache read never breaks health
        logger.debug("Health cache read failed: %s", exc)
    ok = await ping_mongo()
    _health_cache["mongo"] = ok
    _health_cache["at"] = _time.monotonic()
    return ok


def llm_health() -> dict:
    """LLM key status for /health (counts and shape flags only, never secrets).

    The detailed warning (with masked key fragments) stays server-side in
    logs; the public endpoint reports only whether action is needed.
    """
    settings = get_settings()
    warning = settings.llm_key_warning()
    return {
        "keys_configured": len(settings.API_KEYS),
        "keys_ok": warning is None,
        "key_warning": (
            "A configured LLM key looks malformed; check backend logs "
            "and key shape (Groq keys start with gsk_)." if warning else None
        ),
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


def _cors_origins(settings) -> list[str]:
    origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    for chunk in (settings.FRONTEND_URL or "").split(","):
        url = chunk.strip().rstrip("/")
        if url and url not in origins:
            origins.append(url)
    for chunk in (settings.CORS_EXTRA_ORIGINS or "").split(","):
        url = chunk.strip().rstrip("/")
        if url and url not in origins:
            origins.append(url)
    return origins


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
        allow_origins=_cors_origins(settings),
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.middleware("http")(_body_limit_middleware)

    # Extension point for Phase 2+: mount versioned routers when they exist.
    try:
        from app.api.v1.router import api_router  # type: ignore

        app.include_router(api_router, prefix=settings.API_V1_PREFIX)
    except (ImportError, AttributeError) as exc:
        logger.error("API v1 router failed to load; /api/v1 routes unavailable: %s", exc)

    @app.get("/", tags=["root"])
    async def root() -> dict:
        return {"service": settings.APP_NAME, "env": settings.APP_ENV, "docs": "/docs"}

    @app.get("/health", tags=["health"])
    @limiter.limit("60/minute")
    async def health(request: Request) -> dict:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "mongo_connected": await _cached_ping(),
            "llm": llm_health(),
        }

    @app.get(f"{settings.API_V1_PREFIX}/health", tags=["health"])
    @limiter.limit("60/minute")
    async def v1_health(request: Request) -> dict:
        return {
            "status": "ok",
            "env": settings.APP_ENV,
            "mongo_connected": await _cached_ping(),
            "llm": llm_health(),
        }

    return app


app = create_app()
