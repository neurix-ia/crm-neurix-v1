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
