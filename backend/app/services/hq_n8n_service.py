"""Agregação de métricas n8n para Neurix HQ."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import redis.asyncio as aioredis

from app.config import Settings
from app.models.hq import (
    HqPeriod,
    N8nInstanceMetrics,
    N8nOverviewResponse,
    N8nWorkflowErrorRow,
    N8nWorkflowErrorsResponse,
)
from app.services.hq_cache import hq_cache_get, hq_cache_set
from app.services.n8n_instance_client import N8nInstanceClient, N8nInstanceConfig

logger = logging.getLogger(__name__)


def parse_n8n_instances(settings: Settings) -> list[N8nInstanceConfig]:
    raw = (settings.N8N_INSTANCES or "").strip()
    if not raw:
        return []
    if (raw.startswith("'") and raw.endswith("'")) or (
        len(raw) > 2 and raw[0] == raw[-1] == '"'
    ):
        raw = raw[1:-1].strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("N8N_INSTANCES JSON inválido: %s", exc)
        return []
    if not isinstance(items, list):
        return []
    out: list[N8nInstanceConfig] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        inst_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or inst_id).strip()
        base_url = str(item.get("base_url") or "").strip()
        api_key = str(item.get("api_key") or "").strip()
        if inst_id and base_url and api_key:
            out.append(N8nInstanceConfig(id=inst_id, label=label, base_url=base_url, api_key=api_key))
    return out


def period_to_dates(period: HqPeriod, *, now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    end = now or datetime.now(timezone.utc)
    if period == "24h":
        start = end - timedelta(hours=24)
    elif period == "30d":
        start = end - timedelta(days=30)
    else:
        start = end - timedelta(days=7)
    return start, end


def _metric_value(payload: dict[str, Any], key: str) -> float:
    block = payload.get(key)
    if not isinstance(block, dict):
        return 0.0
    val = block.get("value")
    try:
        return float(val) if val is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _metric_deviation(payload: dict[str, Any], key: str) -> Optional[float]:
    block = payload.get(key)
    if not isinstance(block, dict):
        return None
    dev = block.get("deviation")
    try:
        return float(dev) if dev is not None else None
    except (TypeError, ValueError):
        return None


def _parse_instance_metrics(
    config: N8nInstanceConfig,
    summary: dict[str, Any],
) -> N8nInstanceMetrics:
    total = int(_metric_value(summary, "total"))
    failed = int(_metric_value(summary, "failed"))
    failure_rate = _metric_value(summary, "failureRate")
    # API retorna ratio (0.006 = 0.6%); se > 1 assume já em %
    if failure_rate > 1:
        failure_rate = failure_rate / 100.0
    time_saved = _metric_value(summary, "timeSaved")
    avg_rt = _metric_value(summary, "averageRunTime")
    return N8nInstanceMetrics(
        id=config.id,
        label=config.label,
        status="ok",
        total_executions=total,
        failed_executions=failed,
        failure_rate=round(failure_rate * 100, 2),
        time_saved_minutes=time_saved,
        average_run_time_seconds=avg_rt,
        metrics_raw={
            "deviations": {
                "total": _metric_deviation(summary, "total"),
                "failed": _metric_deviation(summary, "failed"),
                "failureRate": _metric_deviation(summary, "failureRate"),
                "timeSaved": _metric_deviation(summary, "timeSaved"),
                "averageRunTime": _metric_deviation(summary, "averageRunTime"),
            }
        },
    )


def _consolidate_metrics(instances: list[N8nInstanceMetrics]) -> N8nInstanceMetrics:
    ok_instances = [i for i in instances if i.status == "ok"]
    total = sum(i.total_executions for i in ok_instances)
    failed = sum(i.failed_executions for i in ok_instances)
    failure_rate = round((failed / total * 100) if total else 0.0, 2)
    time_saved = sum(i.time_saved_minutes for i in ok_instances)
    if total:
        avg_rt = sum(i.average_run_time_seconds * i.total_executions for i in ok_instances) / total
    else:
        avg_rt = 0.0
    any_error = any(i.status == "error" for i in instances)
    return N8nInstanceMetrics(
        id="consolidated",
        label="Consolidado",
        status="error" if any_error and not ok_instances else "ok",
        total_executions=total,
        failed_executions=failed,
        failure_rate=failure_rate,
        time_saved_minutes=time_saved,
        average_run_time_seconds=round(avg_rt, 2),
    )


async def _fetch_instance_overview(
    config: N8nInstanceConfig,
    start: datetime,
    end: datetime,
    *,
    verify_ssl: bool = True,
) -> N8nInstanceMetrics:
    client = N8nInstanceClient(config, verify_ssl=verify_ssl)
    try:
        summary = await client.get_insights_summary(start, end)
        return _parse_instance_metrics(config, summary)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:200] if exc.response else str(exc)
        logger.warning("n8n insights falhou instance=%s status=%s", config.id, exc.response.status_code if exc.response else "?")
        return N8nInstanceMetrics(
            id=config.id,
            label=config.label,
            status="error",
            error_message=f"HTTP {exc.response.status_code}: {detail}" if exc.response else str(exc),
        )
    except Exception as exc:
        logger.warning("n8n insights erro instance=%s: %s", config.id, exc)
        return N8nInstanceMetrics(
            id=config.id,
            label=config.label,
            status="error",
            error_message=str(exc)[:300],
        )


class HqN8nService:
    def __init__(self, settings: Settings, redis: aioredis.Redis | None = None) -> None:
        self.settings = settings
        self.redis = redis
        self.instances = parse_n8n_instances(settings)
        self.cache_ttl = settings.HQ_CACHE_TTL_SECONDS
        self._verify_ssl = settings.N8N_SSL_VERIFY

    def _cache_key(self, suffix: str, period: HqPeriod) -> str:
        return f"hq:n8n:{suffix}:{period}"

    async def get_overview(self, period: HqPeriod = "7d", *, force_refresh: bool = False) -> N8nOverviewResponse:
        cache_key = self._cache_key("overview", period)
        if not force_refresh:
            cached = await hq_cache_get(self.redis, cache_key, N8nOverviewResponse)
            if cached:
                return cached

        start, end = period_to_dates(period)
        now = datetime.now(timezone.utc)

        if not self.instances:
            result = N8nOverviewResponse(
                period=period,
                start_date=start,
                end_date=end,
                instances=[],
                consolidated=N8nInstanceMetrics(id="consolidated", label="Consolidado", status="error", error_message="N8N_INSTANCES não configurado"),
                generated_at=now,
            )
            await hq_cache_set(self.redis, cache_key, result, self.cache_ttl)
            return result

        import asyncio

        instance_metrics = await asyncio.gather(
            *[
                _fetch_instance_overview(cfg, start, end, verify_ssl=self._verify_ssl)
                for cfg in self.instances
            ]
        )
        consolidated = _consolidate_metrics(list(instance_metrics))
        result = N8nOverviewResponse(
            period=period,
            start_date=start,
            end_date=end,
            instances=list(instance_metrics),
            consolidated=consolidated,
            generated_at=now,
        )
        await hq_cache_set(self.redis, cache_key, result, self.cache_ttl)
        return result

    async def get_workflow_errors(
        self,
        period: HqPeriod = "7d",
        *,
        limit: int = 20,
        force_refresh: bool = False,
    ) -> N8nWorkflowErrorsResponse:
        cache_key = self._cache_key(f"errors:{limit}", period)
        if not force_refresh:
            cached = await hq_cache_get(self.redis, cache_key, N8nWorkflowErrorsResponse)
            if cached:
                return cached

        start, end = period_to_dates(period)
        now = datetime.now(timezone.utc)
        rows: list[N8nWorkflowErrorRow] = []

        import asyncio

        async def fetch_errors(cfg: N8nInstanceConfig) -> list[N8nWorkflowErrorRow]:
            client = N8nInstanceClient(cfg, verify_ssl=self._verify_ssl)
            try:
                payload = await client.get_insights_by_workflow(start, end, take=min(limit, 50))
            except Exception as exc:
                logger.warning("n8n by-workflow falhou instance=%s: %s", cfg.id, exc)
                return []
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, list):
                return []
            out: list[N8nWorkflowErrorRow] = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                failed = int(row.get("failed") or 0)
                if failed <= 0:
                    continue
                fr = float(row.get("failureRate") or 0)
                if fr > 1:
                    fr = fr / 100.0
                out.append(
                    N8nWorkflowErrorRow(
                        instance_id=cfg.id,
                        instance_label=cfg.label,
                        workflow_id=row.get("workflowId"),
                        workflow_name=str(row.get("workflowName") or "Sem nome"),
                        project_name=row.get("projectName"),
                        total_executions=int(row.get("total") or 0),
                        failed_executions=failed,
                        failure_rate=round(fr * 100, 2),
                        average_run_time_seconds=float(row.get("averageRunTime") or 0),
                    )
                )
            return out

        per_instance = await asyncio.gather(*[fetch_errors(cfg) for cfg in self.instances])
        for chunk in per_instance:
            rows.extend(chunk)
        rows.sort(key=lambda r: r.failed_executions, reverse=True)
        rows = rows[:limit]

        result = N8nWorkflowErrorsResponse(period=period, rows=rows, generated_at=now)
        await hq_cache_set(self.redis, cache_key, result, self.cache_ttl)
        return result

    async def invalidate_cache(self) -> int:
        from app.services.hq_cache import hq_cache_delete_pattern

        return await hq_cache_delete_pattern(self.redis, "hq:n8n:*")
