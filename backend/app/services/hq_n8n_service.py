"""Agregação de métricas n8n para Neurix HQ."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
import redis.asyncio as aioredis

from app.config import Settings
from app.models.hq import (
    HqPeriod,
    N8nAgentsTreeFolderOption,
    N8nAgentsTreeInstanceStatus,
    N8nAgentWorkflowItem,
    N8nAgentsTreeResponse,
    N8nClientFolderNode,
    N8nExecutionErrorDetail,
    N8nInstanceMetrics,
    N8nOverviewResponse,
    N8nWorkflowErrorRow,
    N8nWorkflowErrorsResponse,
)
from app.services.hq_cache import hq_cache_get, hq_cache_set
from app.services.n8n_agent_detector import is_agent_workflow
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
    if isinstance(payload.get("workflow"), dict) and (
        "name" in payload["workflow"] or "id" in payload["workflow"]
    ):
        return payload["workflow"]
    if isinstance(payload.get("data"), dict) and (
        "name" in payload["data"] or "id" in payload["data"]
    ):
        return payload["data"]
    return payload


def _workflow_project_id(workflow: dict[str, Any]) -> Optional[str]:
    owner = workflow.get("owner")
    if isinstance(owner, dict) and owner.get("projectId"):
        return str(owner["projectId"])
    home = workflow.get("homeProject")
    if isinstance(home, dict) and home.get("id"):
        return str(home["id"])
    project = workflow.get("project")
    if isinstance(project, dict) and project.get("id"):
        return str(project["id"])
    shared = workflow.get("shared")
    if isinstance(shared, list):
        for item in shared:
            if not isinstance(item, dict):
                continue
            if item.get("projectId"):
                return str(item["projectId"])
            nested = item.get("project")
            if isinstance(nested, dict) and nested.get("id"):
                return str(nested["id"])
    return None


def _normalize_workflow_tags(workflow: dict[str, Any]) -> list[str]:
    raw = workflow.get("tags")
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            tags.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if name:
                tags.append(str(name))
    return tags


def _merge_workflow_summary(detail: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(detail)
    for key in ("parentFolder", "parentFolderId", "folderPath", "homeProject", "owner", "project", "tags"):
        if merged.get(key) in (None, [], {}) and summary.get(key) not in (None, [], {}):
            merged[key] = summary[key]
    return merged


def _folder_name_for_workflow(
    workflow: dict[str, Any],
    folder_map: dict[str, str],
) -> tuple[Optional[str], str]:
    parent_folder = workflow.get("parentFolder")
    if isinstance(parent_folder, dict):
        folder_id = parent_folder.get("id")
        folder_name = parent_folder.get("name")
        if folder_name:
            return (str(folder_id) if folder_id else None), str(folder_name)

    folder_path = workflow.get("folderPath")
    if isinstance(folder_path, list) and folder_path:
        parts = [str(p) for p in folder_path if p]
        if parts:
            leaf_id = None
            parent_folder_id = workflow.get("parentFolderId")
            if parent_folder_id:
                leaf_id = str(parent_folder_id)
            return leaf_id, " / ".join(parts)

    parent_folder_id = workflow.get("parentFolderId")
    project_id = _workflow_project_id(workflow)
    if parent_folder_id and project_id:
        key = f"{project_id}:{parent_folder_id}"
        if key in folder_map:
            return str(parent_folder_id), folder_map[key]

    return None, "Sem pasta"


async def _folder_label_for_workflow(
    client: N8nInstanceClient,
    workflow: dict[str, Any],
    folder_cache: dict[str, str],
) -> Optional[str]:
    _, label = _folder_name_for_workflow(workflow, folder_cache)
    if label != "Sem pasta":
        return label

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


async def _paginate_workflows(
    client: N8nInstanceClient,
    *,
    include_folders: bool,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        payload = await client.list_workflows(limit=250, cursor=cursor, include_folders=include_folders)
        chunk = payload.get("data") or []
        if isinstance(chunk, list):
            for row in chunk:
                if not isinstance(row, dict):
                    continue
                if row.get("resource") == "folder":
                    continue
                if row.get("id"):
                    items.append(row)
        cursor = payload.get("nextCursor")
        if not cursor:
            break
    return items


async def _list_all_workflows(client: N8nInstanceClient) -> list[dict[str, Any]]:
    try:
        return await _paginate_workflows(client, include_folders=True)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code in (400, 404, 422):
            logger.info(
                "list_workflows includeFolders rejeitado (HTTP %s) em %s — retry sem flag",
                code,
                client.config.id,
            )
            return await _paginate_workflows(client, include_folders=False)
        raise


_FOLDER_SELECT_FIELDS = [
    "id",
    "name",
    "path",
    "parentFolderId",
    "parentFolder",
    "workflowCount",
    "subFolderCount",
    "tags",
    "project",
]


async def _fetch_folders_page(
    client: N8nInstanceClient,
    project_id: str,
    *,
    parent_folder_id: Optional[str],
    skip: int,
    use_select: bool,
) -> tuple[list[dict[str, Any]], bool]:
    """Retorna (pastas, use_select ainda válido)."""
    try:
        if use_select:
            folders_payload = await client.list_folders(
                project_id,
                take=100,
                skip=skip,
                select_fields=_FOLDER_SELECT_FIELDS,
                parent_folder_id=parent_folder_id,
            )
        else:
            folders_payload = await client.list_folders(
                project_id,
                take=100,
                skip=skip,
                parent_folder_id=parent_folder_id,
            )
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if use_select and code in (400, 422):
            logger.info("list_folders select rejeitado project=%s — retry sem select", project_id)
            return await _fetch_folders_page(
                client,
                project_id,
                parent_folder_id=parent_folder_id,
                skip=skip,
                use_select=False,
            )
        raise
    chunk = folders_payload.get("data") or []
    if not isinstance(chunk, list):
        chunk = []
    return [f for f in chunk if isinstance(f, dict)], use_select


async def _fetch_all_folders_for_project(
    client: N8nInstanceClient,
    project_id: str,
) -> list[dict[str, Any]]:
    """Lista pastas recursivamente (raiz + subpastas via parentFolderId)."""
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    queue: list[Optional[str]] = [None]
    use_select = True

    while queue:
        parent_id = queue.pop(0)
        skip = 0
        while True:
            chunk, use_select = await _fetch_folders_page(
                client,
                project_id,
                parent_folder_id=parent_id,
                skip=skip,
                use_select=use_select,
            )
            if not chunk:
                break
            for folder in chunk:
                fid = folder.get("id")
                if not fid:
                    continue
                fid_str = str(fid)
                if fid_str in seen_ids:
                    continue
                seen_ids.add(fid_str)
                rows.append(folder)
                sub_count = folder.get("subFolderCount")
                if sub_count is None or int(sub_count or 0) > 0:
                    queue.append(fid_str)
            if len(chunk) < 100:
                break
            skip += 100
    return rows


async def _discover_project_ids(
    client: N8nInstanceClient,
    workflows: list[dict[str, Any]],
) -> list[str]:
    found: set[str] = set()
    for wf in workflows:
        pid = _workflow_project_id(wf)
        if pid:
            found.add(pid)
    try:
        cursor: Optional[str] = None
        while True:
            payload = await client.list_projects(limit=100, cursor=cursor)
            for project in payload.get("data") or []:
                if isinstance(project, dict) and project.get("id"):
                    found.add(str(project["id"]))
            cursor = payload.get("nextCursor")
            if not cursor:
                break
    except Exception as exc:
        logger.warning("list_projects falhou: %s", exc)
    return list(found)


def _folder_label_from_record(folder: dict[str, Any]) -> str:
    path = folder.get("path")
    if isinstance(path, list) and path:
        parts = [str(p) for p in path if p]
        if parts:
            return parts[-1]
    name = folder.get("name")
    return str(name) if name else "Sem pasta"


def _folder_group_key(folder_id: Optional[str], folder_name: str) -> str:
    return f"{folder_id or 'root'}:{folder_name}"


def _ensure_empty_folders_in_tree(
    grouped: dict[str, N8nClientFolderNode],
    all_folders: list[dict[str, Any]],
    config: N8nInstanceConfig,
) -> None:
    for folder in all_folders:
        fid = folder.get("id")
        display = _folder_label_from_record(folder)
        group_key = _folder_group_key(str(fid) if fid else None, display)
        if group_key in grouped:
            continue
        grouped[group_key] = N8nClientFolderNode(
            folder_id=str(fid) if fid else None,
            folder_name=display,
            instance_id=config.id,
            instance_label=config.label,
        )


def _folder_tag_names(folder: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in folder.get("tags") or []:
        if isinstance(item, str) and item.strip():
            names.add(item.strip().lower())
        elif isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]).lower())
    return names


def _match_folder_for_workflow(
    workflow: dict[str, Any],
    folders: list[dict[str, Any]],
    folder_by_id: dict[str, dict[str, Any]],
) -> tuple[Optional[str], str]:
    name_map: dict[str, str] = {}
    for folder in folders:
        fid = folder.get("id")
        if not fid:
            continue
        project = folder.get("project") or folder.get("homeProject")
        pid = project.get("id") if isinstance(project, dict) else None
        fname = folder.get("name")
        if pid and fname:
            name_map[f"{pid}:{fid}"] = str(fname)
        path = folder.get("path")
        if pid and isinstance(path, list) and path:
            name_map[f"{pid}:{fid}:path"] = " / ".join(str(p) for p in path if p)

    folder_id, folder_name = _folder_name_for_workflow(workflow, name_map)
    if folder_name != "Sem pasta":
        return folder_id, folder_name

    parent_folder_id = workflow.get("parentFolderId")
    if parent_folder_id:
        parent = folder_by_id.get(str(parent_folder_id))
        if parent:
            return str(parent_folder_id), _folder_label_from_record(parent)

    wf_tags = {t.lower() for t in _normalize_workflow_tags(workflow)}
    if wf_tags:
        for folder in folders:
            if _folder_tag_names(folder) & wf_tags:
                fid = str(folder.get("id") or "")
                return (fid or None), _folder_label_from_record(folder)

    wf_name = str(workflow.get("name") or "").lower()
    best: Optional[tuple[str, str]] = None
    best_len = 0
    for folder in folders:
        fname = str(folder.get("name") or "")
        if len(fname) < 3:
            continue
        if fname.lower() in wf_name and len(fname) > best_len:
            fid = str(folder.get("id") or "")
            best = (fid or None, _folder_label_from_record(folder))
            best_len = len(fname)
    if best:
        return best

    return None, "Sem pasta"


async def _load_folder_name_map(client: N8nInstanceClient) -> dict[str, str]:
    """Mapa projectId:folderId -> nome da pasta."""
    names: dict[str, str] = {}
    project_ids = await _discover_project_ids(client, [])
    for project_id in project_ids:
        try:
            folder_rows = await _fetch_all_folders_for_project(client, project_id)
        except Exception as exc:
            logger.debug("list_folders falhou project=%s: %s", project_id, exc)
            continue
        for folder in folder_rows:
            fid = folder.get("id")
            if not fid:
                continue
            label = _folder_label_from_record(folder)
            names[f"{project_id}:{fid}"] = label
            path = folder.get("path")
            if isinstance(path, list) and path:
                names[f"{project_id}:{fid}:path"] = " / ".join(str(p) for p in path if p)
    return names


async def _resolve_folder_for_workflow(
    client: N8nInstanceClient,
    workflow: dict[str, Any],
    folder_map: dict[str, str],
) -> tuple[Optional[str], str]:
    folder_id, folder_name = _folder_name_for_workflow(workflow, folder_map)
    if folder_name != "Sem pasta":
        return folder_id, folder_name

    label = await _folder_label_for_workflow(client, workflow, folder_map)
    if label:
        parent_folder_id = workflow.get("parentFolderId")
        return (str(parent_folder_id) if parent_folder_id else None), label

    project_id = _workflow_project_id(workflow)
    parent_folder_id = workflow.get("parentFolderId")
    if project_id and parent_folder_id:
        path_key = f"{project_id}:{parent_folder_id}:path"
        if path_key in folder_map:
            return str(parent_folder_id), folder_map[path_key]

    return None, "Sem pasta"


@dataclass
class _InstanceTreeResult:
    folders: list[N8nClientFolderNode]
    workflow_count: int = 0
    error: Optional[str] = None


async def _fetch_agents_tree_for_instance(
    config: N8nInstanceConfig,
    *,
    verify_ssl: bool = True,
) -> _InstanceTreeResult:
    client = N8nInstanceClient(config, verify_ssl=verify_ssl)
    try:
        summaries = await _list_all_workflows(client)
    except Exception as exc:
        logger.warning("agents tree list workflows falhou instance=%s: %s", config.id, exc)
        return _InstanceTreeResult([], error=str(exc)[:300])

    if not summaries:
        return _InstanceTreeResult(
            [],
            error="Nenhum workflow retornado — verifique scope workflow:list na API key.",
        )

    sem = asyncio.Semaphore(8)

    async def load_detail(summary: dict[str, Any]) -> Optional[dict[str, Any]]:
        wid = summary.get("id")
        if not wid:
            return None
        async with sem:
            try:
                detail = _unwrap_workflow(await client.get_workflow(str(wid)))
                return _merge_workflow_summary(detail, summary)
            except Exception as exc:
                logger.debug("get_workflow falhou id=%s: %s", wid, exc)
                return summary

    details = [wf for wf in await asyncio.gather(*[load_detail(s) for s in summaries]) if wf]
    project_ids = await _discover_project_ids(client, details)

    all_folders: list[dict[str, Any]] = []
    for project_id in project_ids:
        try:
            all_folders.extend(await _fetch_all_folders_for_project(client, project_id))
        except Exception as exc:
            logger.warning("list_folders falhou project=%s instance=%s: %s", project_id, config.id, exc)

    folder_by_id = {str(f["id"]): f for f in all_folders if f.get("id")}
    folder_cache = await _load_folder_name_map(client)
    grouped: dict[str, N8nClientFolderNode] = {}

    for wf in details:
        if wf.get("isArchived"):
            continue

        folder_id, folder_name = _match_folder_for_workflow(wf, all_folders, folder_by_id)
        if folder_name == "Sem pasta" and wf.get("parentFolderId"):
            label = await _folder_label_for_workflow(client, wf, folder_cache)
            if label:
                folder_id = str(wf.get("parentFolderId"))
                folder_name = label

        group_key = _folder_group_key(folder_id, folder_name)
        if group_key not in grouped:
            grouped[group_key] = N8nClientFolderNode(
                folder_id=folder_id,
                folder_name=folder_name,
                instance_id=config.id,
                instance_label=config.label,
            )

        wid = str(wf.get("id") or "")
        active = bool(wf.get("active"))
        agent = is_agent_workflow(wf)
        item = N8nAgentWorkflowItem(
            workflow_id=wid,
            workflow_name=str(wf.get("name") or "Sem nome"),
            active=active,
            is_agent=agent,
            is_archived=bool(wf.get("isArchived")),
            tags=_normalize_workflow_tags(wf),
            n8n_url=f"{config.base_url.rstrip('/')}/workflow/{wid}" if wid else None,
        )
        node = grouped[group_key]
        node.workflows.append(item)
        node.total_workflows += 1
        if agent and active:
            node.active_agents += 1

    _ensure_empty_folders_in_tree(grouped, all_folders, config)

    folders = list(grouped.values())
    folders.sort(key=lambda f: (-f.active_agents, -f.total_workflows, f.folder_name.lower()))
    for folder in folders:
        folder.workflows.sort(key=lambda w: (not w.is_agent, not w.active, w.workflow_name.lower()))
    return _InstanceTreeResult(folders=folders, workflow_count=len(summaries))


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

    async def get_agents_tree(self, *, force_refresh: bool = False) -> N8nAgentsTreeResponse:
        cache_key = "hq:n8n:agents_tree:v4"
        if not force_refresh:
            cached = await hq_cache_get(self.redis, cache_key, N8nAgentsTreeResponse)
            if cached:
                return cached

        now = datetime.now(timezone.utc)
        if not self.instances:
            result = N8nAgentsTreeResponse(generated_at=now)
            await hq_cache_set(self.redis, cache_key, result, self.cache_ttl)
            return result

        per_instance = await asyncio.gather(
            *[
                _fetch_agents_tree_for_instance(cfg, verify_ssl=self._verify_ssl)
                for cfg in self.instances
            ],
            return_exceptions=True,
        )

        folders: list[N8nClientFolderNode] = []
        instance_statuses: list[N8nAgentsTreeInstanceStatus] = []
        for cfg, chunk in zip(self.instances, per_instance):
            if isinstance(chunk, Exception):
                logger.warning("agents tree falhou instance=%s: %s", cfg.id, chunk)
                instance_statuses.append(
                    N8nAgentsTreeInstanceStatus(
                        instance_id=cfg.id,
                        instance_label=cfg.label,
                        status="error",
                        error_message=str(chunk)[:300],
                    )
                )
                continue
            folders.extend(chunk.folders)
            instance_statuses.append(
                N8nAgentsTreeInstanceStatus(
                    instance_id=cfg.id,
                    instance_label=cfg.label,
                    status="ok" if chunk.folders else "error",
                    error_message=chunk.error,
                    workflow_count=chunk.workflow_count,
                )
            )

        folders.sort(
            key=lambda f: (
                f.instance_label.lower(),
                -f.active_agents,
                f.folder_name.lower(),
            )
        )
        total_agents = sum(f.active_agents for f in folders)
        tag_set: set[str] = set()
        folder_options: list[N8nAgentsTreeFolderOption] = []
        seen_folders: set[str] = set()
        for folder in folders:
            key = f"{folder.instance_id}:{folder.folder_id or folder.folder_name}"
            if key not in seen_folders:
                seen_folders.add(key)
                folder_options.append(
                    N8nAgentsTreeFolderOption(
                        folder_id=folder.folder_id,
                        folder_name=folder.folder_name,
                        instance_id=folder.instance_id,
                        instance_label=folder.instance_label,
                    )
                )
            for wf in folder.workflows:
                tag_set.update(wf.tags)
        sem_pasta_key = "sem pasta"
        folder_options = [
            opt
            for opt in folder_options
            if opt.folder_name.strip().lower() != sem_pasta_key
            or opt.folder_id is not None
        ]
        folder_options.sort(key=lambda f: (f.instance_label.lower(), f.folder_name.lower()))
        result = N8nAgentsTreeResponse(
            total_active_agents=total_agents,
            total_folders=len(folders),
            available_tags=sorted(tag_set, key=str.lower),
            available_folders=folder_options,
            folders=folders,
            instances=instance_statuses,
            generated_at=now,
        )
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
