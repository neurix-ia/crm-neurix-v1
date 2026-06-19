"""Neurix HQ — agregador semáforo (superadmin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import redis.asyncio as aioredis

from app.authz import EffectiveRole, require_superadmin
from app.config import Settings, get_settings
from app.dependencies import get_redis
from app.models.hq import HqPeriod, HqSummaryResponse
from app.services.hq_summary_service import HqSummaryService

router = APIRouter(prefix="/hq", tags=["Neurix HQ"])


@router.get("/summary", response_model=HqSummaryResponse, summary="Semáforo HQ (todos os módulos)")
async def hq_summary(
    period: HqPeriod = Query("7d"),
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis = Depends(get_redis),
):
    service = HqSummaryService(settings, redis)
    return await service.get_summary(period)
