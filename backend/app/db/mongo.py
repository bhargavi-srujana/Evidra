"""MongoDB connection management using Motor (async driver)."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import get_settings

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
