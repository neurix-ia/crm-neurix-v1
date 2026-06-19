"""Neurix HQ — módulo Automação / n8n (superadmin)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
import redis.asyncio as aioredis

from app.authz import EffectiveRole, require_superadmin
from app.config import Settings, get_settings
from app.dependencies import get_redis
from app.models.hq import HqPeriod, N8nOverviewResponse, N8nWorkflowErrorsResponse
from app.services.hq_n8n_service import HqN8nService

router = APIRouter(prefix="/hq/n8n", tags=["Neurix HQ — n8n"])


def _service(settings: Settings, redis: aioredis.Redis) -> HqN8nService:
    return HqN8nService(settings, redis)


@router.get("/overview", response_model=N8nOverviewResponse, summary="KPIs consolidados n8n")
async def n8n_overview(
    period: HqPeriod = Query("7d"),
    refresh: bool = Query(False, description="Ignorar cache Redis"),
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis = Depends(get_redis),
):
    return await _service(settings, redis).get_overview(period, force_refresh=refresh)


@router.get(
    "/workflows/errors",
    response_model=N8nWorkflowErrorsResponse,
    summary="Ranking de workflows com mais falhas",
)
async def n8n_workflow_errors(
    period: HqPeriod = Query("7d"),
    limit: int = Query(20, ge=1, le=50),
    refresh: bool = Query(False),
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis = Depends(get_redis),
):
    return await _service(settings, redis).get_workflow_errors(period, limit=limit, force_refresh=refresh)


@router.post("/refresh", summary="Invalidar cache n8n HQ")
async def n8n_refresh_cache(
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis = Depends(get_redis),
):
    deleted = await _service(settings, redis).invalidate_cache()
    return {"ok": True, "keys_deleted": deleted}
