"""Cache Redis para Neurix HQ (opcional — falha de Redis não derruba o HQ)."""

from __future__ import annotations

import json
import logging
from typing import Optional, TypeVar

import redis.asyncio as aioredis
from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


async def hq_cache_get(redis: aioredis.Redis | None, key: str, model: type[T]) -> Optional[T]:
    if redis is None:
        return None
    try:
        raw = await redis.get(key)
        if not raw:
            return None
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload["cached"] = True
            return model.model_validate(payload)
    except (json.JSONDecodeError, ValueError):
        try:
            await redis.delete(key)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("hq_cache_get falhou key=%s: %s", key, exc)
    return None


async def hq_cache_set(
    redis: aioredis.Redis | None,
    key: str,
    value: BaseModel,
    ttl_seconds: int,
) -> None:
    if redis is None:
        return
    try:
        data = value.model_dump(mode="json")
        data["cached"] = False
        await redis.set(key, json.dumps(data, default=str), ex=ttl_seconds)
    except Exception as exc:
        logger.warning("hq_cache_set falhou key=%s: %s", key, exc)


async def hq_cache_delete_pattern(redis: aioredis.Redis | None, pattern: str) -> int:
    if redis is None:
        return 0
    deleted = 0
    try:
        async for key in redis.scan_iter(match=pattern):
            await redis.delete(key)
            deleted += 1
    except Exception as exc:
        logger.warning("hq_cache_delete_pattern falhou pattern=%s: %s", pattern, exc)
    return deleted
