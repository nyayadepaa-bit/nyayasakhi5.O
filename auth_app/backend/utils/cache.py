"""Redis caching layer.

Provides async get/set/delete with JSON serialization.
Falls back gracefully when Redis is unavailable.
"""

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    """Return a shared Redis connection (lazy-init)."""
    global _redis
    if _redis is None:
        try:
            _redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
            )
            await _redis.ping()
            logger.info("✓ Redis connected")
        except Exception as exc:
            logger.warning(f"Redis not available ({exc}), caching disabled")
            _redis = None
    return _redis


async def cache_get(key: str) -> Optional[Any]:
    """Get a JSON-serialized value from cache. Returns None on miss or error."""
    r = await get_redis()
    if not r:
        return None
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def cache_set(key: str, value: Any, ttl: int = 0) -> None:
    """Store a JSON-serialized value. ttl=0 uses default from settings."""
    r = await get_redis()
    if not r:
        return
    try:
        await r.set(key, json.dumps(value, default=str), ex=ttl or settings.CACHE_TTL)
    except Exception:
        pass


async def cache_delete(key: str) -> None:
    """Delete a key from cache."""
    r = await get_redis()
    if not r:
        return
    try:
        await r.delete(key)
    except Exception:
        pass


async def cache_delete_pattern(pattern: str) -> None:
    """Delete all keys matching a glob pattern."""
    r = await get_redis()
    if not r:
        return
    try:
        keys = []
        async for key in r.scan_iter(match=pattern, count=100):
            keys.append(key)
        if keys:
            await r.delete(*keys)
    except Exception:
        pass


async def close_redis() -> None:
    """Close the Redis connection (call on shutdown)."""
    global _redis
    if _redis:
        await _redis.close()
        _redis = None
