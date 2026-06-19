"""Neurix HQ — agregador semáforo (superadmin)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
import redis.asyncio as aioredis

from app.authz import EffectiveRole, require_superadmin
from app.config import Settings, get_settings
from app.dependencies import get_redis_optional
from app.models.hq import HqPeriod, HqSummaryResponse
from app.services.hq_summary_service import HqSummaryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hq", tags=["Neurix HQ"])


@router.get("/summary", response_model=HqSummaryResponse, summary="Semáforo HQ (todos os módulos)")
async def hq_summary(
    period: HqPeriod = Query("7d"),
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis | None = Depends(get_redis_optional),
):
    try:
        service = HqSummaryService(settings, redis)
        return await service.get_summary(period)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("hq_summary falhou")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"HQ indisponível: {type(exc).__name__}",
        ) from exc
