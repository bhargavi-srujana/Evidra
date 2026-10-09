"""MongoDB connection management using Motor (async driver)."""

from __future__ import annotations

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 7-day TTL for cached search responses (matches routes_search retention).
SEARCH_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 604800

_client: AsyncIOMotorClient | None = None


def get_mongo_client() -> AsyncIOMotorClient:
    """Return a shared Motor client, creating it on first use."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = AsyncIOMotorClient(settings.MONGO_URL, serverSelectionTimeoutMS=3000)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """Return the configured database handle."""
    settings = get_settings()
    return get_mongo_client()[settings.MONGO_DB]


async def ping_mongo() -> bool:
    """Return True if MongoDB responds to ping, else False (never raises)."""
    try:
        client = get_mongo_client()
        await client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001 - ping must never raise; health reports False
        return False


async def close_mongo() -> None:
    """Close the shared client (used on app shutdown)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ensure_indexes() -> None:
    """Create required indexes on database startup (best-effort, never raises).

    - `search_cache.key` unique + `search_cache.created_at` TTL
      (`expireAfterSeconds=604800`, 7 days) so repeat queries stay instant
      and stale entries self-evict without app-side cleanup.
    - `studies.study_id` unique and `claims.claim_id` unique for the upsert
      filters used across the search/compare pipeline.
    - `claims.study_id` (non-unique) for the `_fetch_claims` filter in
      compare, avoiding full scans as claims grow.
    """
    try:
        try:
            await get_mongo_client().admin.command("ping")
        except Exception:  # noqa: BLE001 - no server means skip, never raise
            logger.debug("Mongo unreachable; skipping index setup")
            return
        db = get_db()
        index_specs = [
            ("search_cache", "key", {"unique": True}),
            (
                "search_cache",
                "created_at",
                {"expireAfterSeconds": SEARCH_CACHE_TTL_SECONDS},
            ),
            ("studies", "study_id", {"unique": True}),
            ("claims", "claim_id", {"unique": True}),
            ("claims", "study_id", {}),
        ]
        for coll, key, kwargs in index_specs:
            try:
                await db[coll].create_index(key, **kwargs)
            except Exception as exc:  # noqa: BLE001 - isolate per-index failures
                logger.warning("Mongo index %s.%s skipped: %s", coll, key, exc)
        logger.info("Mongo indexes ensured")
    except Exception as exc:  # noqa: BLE001 - indexes must never break startup
        logger.warning("Mongo index setup skipped: %s", exc)
