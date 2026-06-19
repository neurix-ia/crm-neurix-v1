"""Agregação de métricas n8n para Neurix HQ."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import redis.asyncio as aioredis

from app.config import Settings
from app.models.hq import (
    HqPeriod,
    N8nExecutionErrorDetail,
    N8nInstanceMetrics,
    N8nOverviewResponse,
    N8nWorkflowErrorRow,
    N8nWorkflowErrorsResponse,
)
from app.services.hq_cache import hq_cache_get, hq_cache_set
from app.services.n8n_execution_parser import extract_execution_error
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


def _parse_iso_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _extract_insights_workflow_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    return []


def _execution_duration_seconds(ex: dict[str, Any]) -> float:
    started = _parse_iso_dt(ex.get("startedAt"))
    stopped = _parse_iso_dt(ex.get("stoppedAt"))
    if started and stopped:
        return max(0.0, (stopped - started).total_seconds())
    return 0.0


def _row_from_insights(cfg: N8nInstanceConfig, row: dict[str, Any]) -> Optional[N8nWorkflowErrorRow]:
    failed = int(row.get("failed") or 0)
    if failed <= 0:
        return None
    fr = float(row.get("failureRate") or 0)
    if fr > 1:
        fr = fr / 100.0
    return N8nWorkflowErrorRow(
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


async def _fetch_errors_from_executions(
    cfg: N8nInstanceConfig,
    start: datetime,
    end: datetime,
    *,
    verify_ssl: bool,
    max_pages: int = 6,
) -> list[N8nWorkflowErrorRow]:
    """Ranking via Public API /executions (insights/by-workflow não está na Public API)."""
    client = N8nInstanceClient(cfg, verify_ssl=verify_ssl)
    aggregated: dict[str, dict[str, Any]] = {}
    cursor: Optional[str] = None

    for _ in range(max_pages):
        try:
            payload = await client.list_executions(status="error", limit=100, cursor=cursor)
        except Exception as exc:
            logger.warning("n8n list_executions falhou instance=%s: %s", cfg.id, exc)
            break

        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            break

        for ex in items:
            if not isinstance(ex, dict):
                continue
            started = _parse_iso_dt(ex.get("startedAt"))
            if started and started < start:
                continue
            if started and started > end:
                continue
            wid = ex.get("workflowId")
            if wid is None:
                continue
            key = str(wid)
            entry = aggregated.get(key)
            if not entry:
                entry = {
                    "workflow_id": key,
                    "workflow_name": str(ex.get("workflowName") or "Sem nome"),
                    "failed_executions": 0,
                    "total_duration": 0.0,
                    "last_execution_id": None,
                    "last_failed_at": None,
                }
                aggregated[key] = entry
            entry["failed_executions"] += 1
            entry["total_duration"] += _execution_duration_seconds(ex)
            ex_id = ex.get("id")
            if ex_id and started and (
                entry["last_failed_at"] is None or started > entry["last_failed_at"]
            ):
                entry["last_failed_at"] = started
                entry["last_execution_id"] = str(ex_id)
            if ex.get("workflowName"):
                entry["workflow_name"] = str(ex["workflowName"])

        cursor = payload.get("nextCursor") if isinstance(payload, dict) else None
        if not cursor:
            break

    rows: list[N8nWorkflowErrorRow] = []
    for entry in aggregated.values():
        failed = int(entry["failed_executions"])
        if failed <= 0:
            continue
        avg_rt = entry["total_duration"] / failed if failed else 0.0
        rows.append(
            N8nWorkflowErrorRow(
                instance_id=cfg.id,
                instance_label=cfg.label,
                workflow_id=entry["workflow_id"],
                workflow_name=entry["workflow_name"],
                failed_executions=failed,
                failure_rate=0.0,
                average_run_time_seconds=round(avg_rt, 2),
                last_execution_id=entry["last_execution_id"],
                last_failed_at=entry["last_failed_at"],
            )
        )
    return rows


def _unwrap_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("data"), dict) and (
        "name" in payload["data"] or "id" in payload["data"]
    ):
        return payload["data"]
    return payload


def _workflow_project_id(workflow: dict[str, Any]) -> Optional[str]:
    shared = workflow.get("shared")
    if isinstance(shared, list):
        for item in shared:
            if not isinstance(item, dict):
                continue
            if item.get("projectId"):
                return str(item["projectId"])
            project = item.get("project")
            if isinstance(project, dict) and project.get("id"):
                return str(project["id"])
    home = workflow.get("homeProject")
    if isinstance(home, dict) and home.get("id"):
        return str(home["id"])
    return None


async def _folder_label_for_workflow(
    client: N8nInstanceClient,
    workflow: dict[str, Any],
    folder_cache: dict[str, str],
) -> Optional[str]:
    folder_path = workflow.get("folderPath")
    if isinstance(folder_path, list) and folder_path:
        parts = [str(p) for p in folder_path if p]
        if parts:
            return " / ".join(parts)

    parent_folder_id = workflow.get("parentFolderId")
    if not parent_folder_id:
        return None
    project_id = _workflow_project_id(workflow)
    if not project_id:
        return None

    cache_key = f"{project_id}:{parent_folder_id}"
    if cache_key in folder_cache:
        return folder_cache[cache_key]

    try:
        payload = await client.get_folder(project_id, str(parent_folder_id))
        folder = _unwrap_workflow(payload)
        name = folder.get("name")
        if name:
            folder_cache[cache_key] = str(name)
            return str(name)
    except Exception as exc:
        logger.debug("folder lookup falhou project=%s folder=%s: %s", project_id, parent_folder_id, exc)
    return None


async def _enrich_rows_metadata(
    client: N8nInstanceClient,
    rows: list[N8nWorkflowErrorRow],
) -> list[N8nWorkflowErrorRow]:
    if not rows:
        return rows

    folder_cache: dict[str, str] = {}
    workflow_cache: dict[str, dict[str, Any]] = {}

    async def enrich_one(row: N8nWorkflowErrorRow) -> N8nWorkflowErrorRow:
        wid = row.workflow_id
        if not wid:
            return row
        if wid not in workflow_cache:
            try:
                workflow_cache[wid] = _unwrap_workflow(await client.get_workflow(wid))
            except Exception as exc:
                logger.warning("get_workflow falhou id=%s: %s", wid, exc)
                workflow_cache[wid] = {}

        wf = workflow_cache[wid]
        updates: dict[str, Any] = {}
        name = wf.get("name")
        if name and row.workflow_name in ("", "Sem nome"):
            updates["workflow_name"] = str(name)

        folder_label = await _folder_label_for_workflow(client, wf, folder_cache)
        if folder_label:
            updates["project_name"] = folder_label

        if updates:
            return row.model_copy(update=updates)
        return row

    return list(await asyncio.gather(*[enrich_one(row) for row in rows]))


async def _attach_last_failure(
    client: N8nInstanceClient,
    row: N8nWorkflowErrorRow,
    start: datetime,
    end: datetime,
) -> N8nWorkflowErrorRow:
    if row.last_execution_id or not row.workflow_id:
        return row
    try:
        payload = await client.list_executions(
            workflow_id=row.workflow_id, status="error", limit=5
        )
    except Exception:
        return row
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return row
    best_id: Optional[str] = None
    best_at: Optional[datetime] = None
    for ex in items:
        if not isinstance(ex, dict):
            continue
        started = _parse_iso_dt(ex.get("startedAt"))
        if started and (started < start or started > end):
            continue
        ex_id = ex.get("id")
        if ex_id and started and (best_at is None or started > best_at):
            best_at = started
            best_id = str(ex_id)
    if best_id:
        return row.model_copy(update={"last_execution_id": best_id, "last_failed_at": best_at})
    return row


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
            out: list[N8nWorkflowErrorRow] = []

            try:
                payload = await client.get_insights_by_workflow(start, end, take=min(limit, 50))
                for row in _extract_insights_workflow_rows(payload):
                    parsed = _row_from_insights(cfg, row)
                    if parsed:
                        out.append(parsed)
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code != 404:
                    logger.warning(
                        "n8n by-workflow falhou instance=%s status=%s",
                        cfg.id,
                        exc.response.status_code,
                    )
            except Exception as exc:
                logger.warning("n8n by-workflow falhou instance=%s: %s", cfg.id, exc)

            if not out:
                out = await _fetch_errors_from_executions(
                    cfg, start, end, verify_ssl=self._verify_ssl
                )

            enriched: list[N8nWorkflowErrorRow] = []
            for row in out:
                enriched.append(await _attach_last_failure(client, row, start, end))
            return await _enrich_rows_metadata(client, enriched)

        per_instance = await asyncio.gather(*[fetch_errors(cfg) for cfg in self.instances])
        for chunk in per_instance:
            rows.extend(chunk)
        rows.sort(key=lambda r: r.failed_executions, reverse=True)
        rows = rows[:limit]

        result = N8nWorkflowErrorsResponse(period=period, rows=rows, generated_at=now)
        await hq_cache_set(self.redis, cache_key, result, self.cache_ttl)
        return result

    def _instance_config(self, instance_id: str) -> N8nInstanceConfig:
        for cfg in self.instances:
            if cfg.id == instance_id:
                return cfg
        raise KeyError(f"Instância n8n desconhecida: {instance_id}")

    async def get_execution_error(
        self,
        instance_id: str,
        execution_id: str,
        *,
        workflow_id: Optional[str] = None,
    ) -> N8nExecutionErrorDetail:
        cfg = self._instance_config(instance_id)
        client = N8nInstanceClient(cfg, verify_ssl=self._verify_ssl)
        payload = await client.get_execution(execution_id, include_data=True)
        root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        parsed = extract_execution_error(payload if isinstance(payload, dict) else {})

        wf_id = workflow_id or (str(root.get("workflowId")) if root.get("workflowId") else None)
        wf_name = root.get("workflowName")
        started = _parse_iso_dt(root.get("startedAt"))
        stopped = _parse_iso_dt(root.get("stoppedAt"))
        status = root.get("status")

        n8n_url = None
        if wf_id:
            n8n_url = f"{cfg.base_url.rstrip('/')}/workflow/{wf_id}/executions/{execution_id}"

        return N8nExecutionErrorDetail(
            instance_id=cfg.id,
            instance_label=cfg.label,
            instance_base_url=cfg.base_url,
            workflow_id=wf_id,
            workflow_name=str(wf_name) if wf_name else None,
            execution_id=execution_id,
            status=str(status) if status else None,
            started_at=started,
            stopped_at=stopped,
            node_name=parsed.get("node_name"),
            message=parsed.get("message") or "Erro desconhecido",
            description=parsed.get("description"),
            stack=parsed.get("stack"),
            n8n_execution_url=n8n_url,
        )

    async def invalidate_cache(self) -> int:
        from app.services.hq_cache import hq_cache_delete_pattern

        return await hq_cache_delete_pattern(self.redis, "hq:n8n:*")
