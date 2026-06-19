"""Cache Redis para Neurix HQ."""

from __future__ import annotations

import json
from typing import Any, Optional, TypeVar

import redis.asyncio as aioredis
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def hq_cache_get(redis: aioredis.Redis, key: str, model: type[T]) -> Optional[T]:
    raw = await redis.get(key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload["cached"] = True
            return model.model_validate(payload)
    except (json.JSONDecodeError, ValueError):
        await redis.delete(key)
    return None


async def hq_cache_set(
    redis: aioredis.Redis,
    key: str,
    value: BaseModel,
    ttl_seconds: int,
) -> None:
    data = value.model_dump(mode="json")
    data["cached"] = False
    await redis.set(key, json.dumps(data, default=str), ex=ttl_seconds)


async def hq_cache_delete_pattern(redis: aioredis.Redis, pattern: str) -> int:
    deleted = 0
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)
        deleted += 1
    return deleted
