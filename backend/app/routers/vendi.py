"""
Vendi — API do tenant (JWT).

GET  /api/vendi/sales          — lista + agregados (filtro período / since)
GET  /api/vendi/sales/export   — CSV do período
GET  /api/vendi/clients        — clientes ativos (última compra)
GET  /api/vendi/sales/{id}     — detalhe
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from supabase import Client as SupabaseClient

from app.authz import EffectiveRole, get_effective_role
from app.dependencies import get_current_user, get_supabase
from app.models.vendi import (
    StreetSaleRow,
    VendiActiveClient,
    VendiSalesAggregates,
    VendiSalesListResponse,
)
from app.org_scope import admin_user_ids_for_organization

router = APIRouter()

TZ_BR = ZoneInfo("America/Sao_Paulo")


def _resolve_tenant(
    supabase: SupabaseClient,
    eff: EffectiveRole,
    uid: str,
    tenant_id: Optional[str],
) -> str:
    tid = (tenant_id or "").strip()
    if eff.is_superadmin:
        if not tid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Parâmetro tenant_id é obrigatório para superadmin.",
            )
        return tid
    if eff.is_read_only:
        return uid
    if not tid or tid == uid:
        return uid
    if eff.is_org_admin and eff.org_member_organization_id:
        allowed = admin_user_ids_for_organization(supabase, eff.org_member_organization_id)
        if tid in allowed:
            return tid
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para este tenant.")


def _period_bounds(
    period: Optional[str],
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
) -> tuple[Optional[datetime], Optional[datetime]]:
    """Resolve from/to. period: day|week|month (America/Sao_Paulo)."""
    if from_ts or to_ts:
        return from_ts, to_ts

    now = datetime.now(TZ_BR)
    start_local: datetime
    if period == "week":
        start_local = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start_local = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        # default day
        start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)

    end_local = now
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _street_sales_error_detail(exc: Exception) -> str:
    msg = str(exc).lower()
    if "street_sales" in msg and (
        "does not exist" in msg or "undefined_table" in msg or "42p01" in msg
    ):
        return (
            "Tabela street_sales inexistente. Aplique a migration "
            "backend/migrations/022_street_sales.sql no Supabase."
        )
    if "permission denied" in msg or "rls" in msg:
        return f"Sem permissão para ler street_sales: {exc}"
    return f"Falha ao consultar street_sales: {exc}"


def _fetch_sales(
    supabase: SupabaseClient,
    tenant_id: str,
    *,
    from_ts: Optional[datetime],
    to_ts: Optional[datetime],
    since: Optional[datetime],
    since_id: Optional[str],
    limit: int = 200,
) -> list[dict[str, Any]]:
    try:
        q = (
            supabase.table("street_sales")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("sold_at", desc=True)
            .limit(limit)
        )
        if from_ts:
            q = q.gte("sold_at", from_ts.isoformat())
        if to_ts:
            q = q.lte("sold_at", to_ts.isoformat())
        if since:
            q = q.gt("sold_at", since.isoformat())
        if since_id:
            # delta: vendas com created_at > da venda since_id — fallback por sold_at já cobre poll
            pass

        res = q.execute()
        return list(res.data or [])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_street_sales_error_detail(exc),
        ) from exc


def _client_names(supabase: SupabaseClient, client_ids: list[str]) -> dict[str, str]:
    ids = [c for c in client_ids if c]
    if not ids:
        return {}
    try:
        res = (
            supabase.table("crm_clients")
            .select("id, display_name")
            .in_("id", ids)
            .execute()
        )
        return {str(r["id"]): str(r.get("display_name") or "") for r in (res.data or [])}
    except Exception:
        return {}


def _aggregates(rows: list[dict[str, Any]]) -> VendiSalesAggregates:
    italiano = sum(int(r.get("pao_italiano_qtd") or 0) for r in rows)
    integral = sum(int(r.get("pao_integral_qtd") or 0) for r in rows)
    return VendiSalesAggregates(
        total_sales=len(rows),
        pao_italiano_qtd=italiano,
        pao_integral_qtd=integral,
        total_units=italiano + integral,
    )


@router.get("/sales", response_model=VendiSalesListResponse)
async def list_vendi_sales(
    period: Optional[str] = Query(None, pattern="^(day|week|month)$"),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    since: Optional[datetime] = Query(None, description="Delta para poll (sold_at > since)"),
    since_id: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(get_effective_role),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _resolve_tenant(supabase, eff, str(user.id), tenant_id)
    if since is not None:
        rows = _fetch_sales(
            supabase, tid, from_ts=None, to_ts=None, since=since, since_id=since_id, limit=limit
        )
        f, t = since, None
    else:
        f, t = _period_bounds(period, from_ts, to_ts)
        rows = _fetch_sales(
            supabase, tid, from_ts=f, to_ts=t, since=None, since_id=None, limit=limit
        )
    names = _client_names(supabase, [str(r.get("client_id") or "") for r in rows])
    sales = [
        StreetSaleRow.from_row(r, names.get(str(r.get("client_id") or "")))
        for r in rows
    ]
    # aggregates over the list (for period queries); for since-delta still ok
    if since is not None:
        # full period aggregates not requested; return delta aggregates
        aggs = _aggregates(rows)
    else:
        aggs = _aggregates(rows)

    return VendiSalesListResponse(sales=sales, aggregates=aggs, from_ts=f, to_ts=t)


@router.get("/sales/export")
async def export_vendi_sales(
    period: Optional[str] = Query(None, pattern="^(day|week|month)$"),
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    tenant_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(get_effective_role),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _resolve_tenant(supabase, eff, str(user.id), tenant_id)
    f, t = _period_bounds(period, from_ts, to_ts)
    rows = _fetch_sales(supabase, tid, from_ts=f, to_ts=t, since=None, since_id=None, limit=500)
    names = _client_names(supabase, [str(r.get("client_id") or "") for r in rows])
    aggs = _aggregates(rows)

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "id",
            "sold_at",
            "vendedor",
            "cliente",
            "phone_typed",
            "phone_from_audio",
            "phone_final",
            "match_status",
            "pao_italiano_qtd",
            "pao_integral_qtd",
            "photo_url",
            "audio_url",
            "transcript",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.get("id"),
                r.get("sold_at"),
                r.get("seller_name"),
                names.get(str(r.get("client_id") or ""), ""),
                r.get("phone_typed") or "",
                r.get("phone_from_audio") or "",
                r.get("phone_final") or "",
                r.get("match_status") or "",
                r.get("pao_italiano_qtd") or 0,
                r.get("pao_integral_qtd") or 0,
                r.get("photo_url") or "",
                r.get("audio_url") or "",
                (r.get("transcript") or "").replace("\n", " ")[:2000],
            ]
        )
    writer.writerow([])
    writer.writerow(["TOTAIS", "", "", "", "", "", "", "", aggs.pao_italiano_qtd, aggs.pao_integral_qtd, "", "", ""])
    writer.writerow(["total_vendas", aggs.total_sales])
    writer.writerow(["total_unidades", aggs.total_units])

    filename = f"vendi_{period or 'custom'}_{datetime.now(TZ_BR).strftime('%Y%m%d_%H%M')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/sales/{sale_id}", response_model=StreetSaleRow)
async def get_vendi_sale(
    sale_id: str,
    tenant_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(get_effective_role),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _resolve_tenant(supabase, eff, str(user.id), tenant_id)
    try:
        res = (
            supabase.table("street_sales")
            .select("*")
            .eq("id", sale_id)
            .eq("tenant_id", tid)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_street_sales_error_detail(exc),
        ) from exc
    row = (res.data or [None])[0]
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venda não encontrada.")
    names = _client_names(supabase, [str(row.get("client_id") or "")])
    return StreetSaleRow.from_row(row, names.get(str(row.get("client_id") or "")))


@router.get("/clients", response_model=list[VendiActiveClient])
async def list_vendi_active_clients(
    from_ts: Optional[datetime] = Query(None, alias="from"),
    to_ts: Optional[datetime] = Query(None, alias="to"),
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(get_effective_role),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Clientes com pelo menos uma street_sale no período (default: últimos 90 dias)."""
    tid = _resolve_tenant(supabase, eff, str(user.id), tenant_id)
    if not from_ts:
        from_ts = datetime.now(timezone.utc) - timedelta(days=90)

    rows = _fetch_sales(supabase, tid, from_ts=from_ts, to_ts=to_ts, since=None, since_id=None, limit=500)
    by_client: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = str(r.get("client_id") or "")
        if not cid:
            continue
        units = int(r.get("pao_italiano_qtd") or 0) + int(r.get("pao_integral_qtd") or 0)
        sold_at = r.get("sold_at")
        if cid not in by_client:
            by_client[cid] = {
                "last_sale_at": sold_at,
                "sales_count": 1,
                "total_units": units,
                "phone": r.get("phone_final"),
            }
        else:
            by_client[cid]["sales_count"] += 1
            by_client[cid]["total_units"] += units
            if sold_at and (not by_client[cid]["last_sale_at"] or sold_at > by_client[cid]["last_sale_at"]):
                by_client[cid]["last_sale_at"] = sold_at
                by_client[cid]["phone"] = r.get("phone_final")

    names = _client_names(supabase, list(by_client.keys()))
    out: list[VendiActiveClient] = []
    for cid, meta in by_client.items():
        out.append(
            VendiActiveClient(
                client_id=cid,
                display_name=names.get(cid) or meta.get("phone") or cid,
                phone=meta.get("phone"),
                last_sale_at=meta["last_sale_at"],
                sales_count=meta["sales_count"],
                total_units=meta["total_units"],
            )
        )
    out.sort(key=lambda c: c.last_sale_at, reverse=True)
    return out[:limit]
