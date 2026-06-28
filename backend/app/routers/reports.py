"""Relatórios semanais — leitura do cliente (JWT).

O cliente (papel read_only) enxerga só o próprio tenant, via _resolve_report_tenant.
"ver detalhes" lê as conversas da semana direto do Google Sheets (sob demanda).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client as SupabaseClient

from app.authz import EffectiveRole, get_effective_role
from app.dependencies import get_current_user, get_redis_optional, get_supabase
from app.services.sheets_reader import parse_report_bounds, read_week_rows

router = APIRouter()


def _resolve_report_tenant(supabase, user, eff) -> str:
    """tenant_id dos dados do relatório — NÃO exige funil (o relatório vem da planilha).

    - read_only: tenant dos dados = dono do funil atribuído.
    - demais: o próprio usuário logado é o tenant.
    """
    uid = str(user.id)
    if getattr(eff, "is_read_only", False):
        fid = getattr(eff, "assigned_funnel_id", None)
        if fid:
            try:
                r = (
                    supabase.table("funnels")
                    .select("tenant_id")
                    .eq("id", fid)
                    .limit(1)
                    .execute()
                )
                if r.data:
                    return str(r.data[0]["tenant_id"])
            except Exception:
                pass
    return uid


@router.get("/weekly")
async def list_weekly(
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
):
    """Semanas disponíveis para o tenant logado (navegação)."""
    data_tenant = _resolve_report_tenant(supabase, user, eff)
    res = (
        supabase.table("weekly_reports")
        .select("week_key, week_start, week_end, status, problema_principal")
        .eq("tenant_id", data_tenant)
        .order("week_start", desc=True)
        .execute()
    )
    return res.data or []


@router.get("/weekly/{week_key}")
async def get_weekly(
    week_key: str,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
):
    """Relatório de uma semana específica do tenant."""
    data_tenant = _resolve_report_tenant(supabase, user, eff)
    res = (
        supabase.table("weekly_reports")
        .select("*")
        .eq("tenant_id", data_tenant)
        .eq("week_key", week_key)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado para esta semana.",
        )
    return rows[0]


@router.get("/weekly/{week_key}/conversations")
async def get_weekly_conversations(
    week_key: str,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
    redis=Depends(get_redis_optional),
):
    """'Ver detalhes': conversas daquela semana (somente leitura, lidas do Sheets)."""
    data_tenant = _resolve_report_tenant(supabase, user, eff)
    res = (
        supabase.table("weekly_reports")
        .select("week_start, week_end")
        .eq("tenant_id", data_tenant)
        .eq("week_key", week_key)
        .limit(1)
        .execute()
    )
    report_rows = res.data or []
    if not report_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório não encontrado para esta semana.",
        )
    report = report_rows[0]
    week_start, week_end = parse_report_bounds(
        report["week_start"], report["week_end"]
    )
    rows = await read_week_rows(
        supabase, redis, tenant_id=data_tenant, week_start=week_start, week_end=week_end
    )
    return {"week_key": week_key, "total": len(rows), "conversations": rows}
