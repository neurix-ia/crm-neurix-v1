"""Neurix HQ — módulo Automação / n8n (superadmin)."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
import redis.asyncio as aioredis

from app.authz import EffectiveRole, require_superadmin
from app.config import Settings, get_settings
from app.dependencies import get_redis_optional
from app.models.hq import HqPeriod, N8nExecutionErrorDetail, N8nOverviewResponse, N8nWorkflowErrorsResponse
from app.services.hq_n8n_service import HqN8nService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hq/n8n", tags=["Neurix HQ — n8n"])


def _service(settings: Settings, redis: aioredis.Redis | None) -> HqN8nService:
    return HqN8nService(settings, redis)


@router.get("/overview", response_model=N8nOverviewResponse, summary="KPIs consolidados n8n")
async def n8n_overview(
    period: HqPeriod = Query("7d"),
    refresh: bool = Query(False, description="Ignorar cache Redis"),
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis | None = Depends(get_redis_optional),
):
    try:
        return await _service(settings, redis).get_overview(period, force_refresh=refresh)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("hq n8n overview falhou")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"HQ n8n indisponível: {type(exc).__name__}",
        ) from exc


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
    redis: aioredis.Redis | None = Depends(get_redis_optional),
):
    try:
        return await _service(settings, redis).get_workflow_errors(
            period, limit=limit, force_refresh=refresh
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("hq n8n workflow errors falhou")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"HQ n8n indisponível: {type(exc).__name__}",
        ) from exc


@router.get(
    "/executions/{instance_id}/{execution_id}",
    response_model=N8nExecutionErrorDetail,
    summary="Detalhe da causa de uma execução com erro",
)
async def n8n_execution_error(
    instance_id: str,
    execution_id: str,
    workflow_id: str | None = Query(None),
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis | None = Depends(get_redis_optional),
):
    try:
        return await _service(settings, redis).get_execution_error(
            instance_id, execution_id, workflow_id=workflow_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response else str(exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"n8n HTTP {exc.response.status_code}: {detail}" if exc.response else str(exc),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("hq n8n execution error falhou")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Não foi possível carregar execução: {type(exc).__name__}",
        ) from exc


@router.post("/refresh", summary="Invalidar cache n8n HQ")
async def n8n_refresh_cache(
    _sa: EffectiveRole = Depends(require_superadmin),
    settings: Settings = Depends(get_settings),
    redis: aioredis.Redis | None = Depends(get_redis_optional),
):
    deleted = await _service(settings, redis).invalidate_cache()
    return {"ok": True, "keys_deleted": deleted}
