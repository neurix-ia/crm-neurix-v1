"""Admin (superadmin) — configuração de relatórios por cliente + saúde dos agentes.

Observação de design: NÃO cria tenant/usuário aqui. O cliente (usuário read_only,
organização, funil) é criado pelo fluxo existente de Organizações/Usuários. Este
router apenas associa um tenant EXISTENTE à sua planilha de conversas e parâmetros
de relatório (client_report_config), e gerencia os relatórios de melhoria de agente.

`tenant_id` = tenant dos DADOS (dono do funil), o mesmo que _resolve_kanban_scope
resolve para o login read_only do cliente.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client as SupabaseClient

from app.authz import EffectiveRole, require_superadmin
from app.dependencies import get_supabase

router = APIRouter()


class ReportClientIn(BaseModel):
    tenant_id: str
    spreadsheet_id: str
    worksheet: str = "Conversas"
    date_column: str = "data"
    agent_keys: list[str] = Field(default_factory=list)
    notify_whatsapp: str | None = None
    timezone: str = "America/Sao_Paulo"
    enabled: bool = True


class ReportClientPatch(BaseModel):
    spreadsheet_id: str | None = None
    worksheet: str | None = None
    date_column: str | None = None
    agent_keys: list[str] | None = None
    notify_whatsapp: str | None = None
    timezone: str | None = None
    enabled: bool | None = None


class AgentReportPatch(BaseModel):
    status: str  # aberto | revisado | aplicado


@router.get("/report-clients")
async def list_report_clients(
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    res = supabase.table("client_report_config").select("*").order("created_at", desc=True).execute()
    return res.data or []


@router.post("/report-clients")
async def upsert_report_client(
    payload: ReportClientIn,
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Associa um tenant existente à config de relatório (upsert por tenant_id)."""
    row = payload.model_dump()
    res = supabase.table("client_report_config").upsert(row, on_conflict="tenant_id").execute()
    data = res.data or []
    return {"status": "ok", "tenant_id": payload.tenant_id, "config": data[0] if data else row}


@router.patch("/report-clients/{tenant_id}")
async def patch_report_client(
    tenant_id: str,
    payload: ReportClientPatch,
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nada para atualizar.")
    res = (
        supabase.table("client_report_config")
        .update(patch)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not (res.data or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config não encontrada para este tenant.")
    return {"status": "ok", "config": res.data[0]}


@router.get("/agent-reports")
async def list_agent_reports(
    week_key: str | None = Query(None),
    severidade: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    agent_key: str | None = Query(None, description="Filtro por um agent_key (workflow id n8n)."),
    agent_keys: str | None = Query(
        None,
        description="Filtro por vários agent_keys separados por vírgula.",
    ),
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    q = supabase.table("agent_improvement_reports").select("*")
    if week_key:
        q = q.eq("week_key", week_key)
    if severidade:
        q = q.eq("severidade", severidade)
    if status_filter:
        q = q.eq("status", status_filter)

    keys: list[str] = []
    if agent_keys:
        keys.extend(k.strip() for k in agent_keys.split(",") if k.strip())
    if agent_key and agent_key.strip():
        keys.append(agent_key.strip())
    uniq: list[str] = []
    seen: set[str] = set()
    for k in keys:
        if k not in seen:
            seen.add(k)
            uniq.append(k)
    if len(uniq) == 1:
        q = q.eq("agent_key", uniq[0])
    elif len(uniq) > 1:
        q = q.in_("agent_key", uniq)

    res = q.order("week_start", desc=True).execute()
    return res.data or []


@router.patch("/agent-reports/{report_id}")
async def patch_agent_report(
    report_id: str,
    payload: AgentReportPatch,
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    if payload.status not in ("aberto", "revisado", "aplicado"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="status inválido.")
    res = (
        supabase.table("agent_improvement_reports")
        .update({"status": payload.status})
        .eq("id", report_id)
        .execute()
    )
    if not (res.data or []):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Relatório de agente não encontrado.")
    return {"status": "ok", "report": res.data[0]}


# ── Evals (DeepEval) — histórico de runs por agente ──────────────────────────

_EVAL_LIST_COLUMNS = (
    "id, agent_key, agent_name, job_id, mode, pass_rate, total, passed, "
    "suggestions, started_at, finished_at, created_at"
)


@router.get("/agent-evals")
async def list_agent_evals(
    agent_key: str | None = Query(None, description="Filtro por agent_key (workflow id n8n)."),
    agent_keys: str | None = Query(None, description="Vários agent_keys separados por vírgula."),
    mode: str | None = Query(None, description="baseline | mangle"),
    limit: int = Query(50, ge=1, le=200),
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Lista runs de eval (sem o JSONB `result`, que é pesado — use o GET por id)."""
    q = supabase.table("agent_eval_runs").select(_EVAL_LIST_COLUMNS)
    keys: list[str] = []
    if agent_keys:
        keys.extend(k.strip() for k in agent_keys.split(",") if k.strip())
    if agent_key and agent_key.strip():
        keys.append(agent_key.strip())
    uniq = list(dict.fromkeys(keys))
    if len(uniq) == 1:
        q = q.eq("agent_key", uniq[0])
    elif len(uniq) > 1:
        q = q.in_("agent_key", uniq)
    if mode:
        q = q.eq("mode", mode)
    res = q.order("created_at", desc=True).limit(limit).execute()
    return res.data or []


@router.get("/agent-evals/{run_id}")
async def get_agent_eval(
    run_id: str,
    _eff: EffectiveRole = Depends(require_superadmin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Run completo, incluindo o JSONB `result` (test_cases + summary)."""
    res = (
        supabase.table("agent_eval_runs")
        .select("*")
        .eq("id", run_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run de eval não encontrado.")
    return rows[0]
