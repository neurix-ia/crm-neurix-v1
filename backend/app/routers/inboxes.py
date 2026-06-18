"""
Caixas de entrada (inboxes) — CRUD (Sprint 7).

Regra: cada caixa tem exatamente um funil (`funnel_id NOT NULL`). O `tenant_id` da
caixa segue o dono do funil (`funnels.tenant_id`) para alinhar pipeline e webhooks.
Admin de org pode vincular funis de qualquer admin da mesma organização (escopo org).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from supabase import Client as SupabaseClient

from app.authz import EffectiveRole, get_effective_role, require_org_admin
from app.dependencies import get_current_user, get_supabase
from app.models.inbox import InboxCreate, InboxResponse, InboxUpdate, inbox_response_from_row
from app.org_scope import (
    admin_user_ids_for_organization,
    assert_funnel_assignable_to_org,
    funnel_ids_for_organization,
)

router = APIRouter()


def _row_to_response(row: dict[str, Any]) -> InboxResponse:
    try:
        return inbox_response_from_row(row)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e


def _assert_funnel_usable_for_inbox(
    supabase: SupabaseClient,
    funnel_id: str,
    eff: EffectiveRole,
    uid: str,
) -> dict[str, Any]:
    """Funil próprio do usuário ou funil atribuível à organização (admins da org)."""
    res = (
        supabase.table("funnels")
        .select("id, tenant_id")
        .eq("id", funnel_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado.")
    row = rows[0]
    ftid = str(row["tenant_id"])
    if ftid == uid:
        return row
    oid = eff.effective_organization_id
    if oid:
        try:
            assert_funnel_assignable_to_org(supabase, oid, funnel_id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(e),
            ) from e
        return row
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="O funil não pertence ao seu tenant nem à sua organização.",
    )


def _get_inbox_for_user(
    supabase: SupabaseClient,
    inbox_id: str,
    user_id: str,
    eff: EffectiveRole,
) -> dict[str, Any]:
    res = supabase.table("inboxes").select("*").eq("id", inbox_id).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caixa de entrada não encontrada.")
    row = rows[0]
    tid = str(row["tenant_id"])
    if tid != user_id:
        if eff.is_read_only and eff.assigned_funnel_id and str(row.get("funnel_id")) == eff.assigned_funnel_id:
            return row
        oid = eff.effective_organization_id
        if (
            eff.is_org_admin
            and not eff.is_read_only
            and oid
            and tid in admin_user_ids_for_organization(supabase, oid)
            and str(row.get("funnel_id")) in funnel_ids_for_organization(supabase, oid)
        ):
            return row
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado a esta caixa.")
    return row


def _require_inbox_mutable_by_org_admin(
    supabase: SupabaseClient,
    inbox_id: str,
    eff: EffectiveRole,
    uid: str,
) -> dict[str, Any]:
    res = supabase.table("inboxes").select("*").eq("id", inbox_id).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caixa de entrada não encontrada.")
    row = rows[0]
    tid = str(row["tenant_id"])
    if tid == uid:
        return row
    oid = eff.effective_organization_id
    if (
        eff.is_org_admin
        and not eff.is_read_only
        and oid
        and tid in admin_user_ids_for_organization(supabase, oid)
        and str(row.get("funnel_id")) in funnel_ids_for_organization(supabase, oid)
    ):
        return row
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado a esta caixa.")


@router.get("/", response_model=list[InboxResponse])
async def list_inboxes(
    tenant_id: Optional[str] = Query(None, description="Superadmin: filtrar por tenant (auth.users.id)."),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(get_effective_role),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Lista caixas de entrada. Org admin: caixas dos tenants admin da org; senão só o próprio tenant."""
    uid = str(user.id)

    if eff.is_superadmin and tenant_id:
        res = (
            supabase.table("inboxes")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=False)
            .execute()
        )
        return [_row_to_response(r) for r in (res.data or [])]

    if eff.is_read_only and eff.assigned_funnel_id:
        res = (
            supabase.table("inboxes")
            .select("*")
            .eq("funnel_id", eff.assigned_funnel_id)
            .order("created_at", desc=False)
            .execute()
        )
        return [_row_to_response(r) for r in (res.data or [])]

    oid = eff.effective_organization_id
    if eff.is_org_admin and not eff.is_read_only and oid:
        admins = admin_user_ids_for_organization(supabase, oid)
        if admins:
            res = (
                supabase.table("inboxes")
                .select("*")
                .in_("tenant_id", list(admins))
                .order("created_at", desc=False)
                .execute()
            )
            return [_row_to_response(r) for r in (res.data or [])]

    res = (
        supabase.table("inboxes")
        .select("*")
        .eq("tenant_id", uid)
        .order("created_at", desc=False)
        .execute()
    )
    return [_row_to_response(r) for r in (res.data or [])]


@router.get("/{inbox_id}", response_model=InboxResponse)
async def get_inbox(
    inbox_id: str,
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(get_effective_role),
    supabase: SupabaseClient = Depends(get_supabase),
):
    row = _get_inbox_for_user(supabase, inbox_id, str(user.id), eff)
    return _row_to_response(row)


@router.post("/", response_model=InboxResponse, status_code=status.HTTP_201_CREATED)
async def create_inbox(
    body: InboxCreate,
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Cria caixa com um funil obrigatório; tenant da caixa = tenant dono do funil."""
    uid = str(user.id)
    funnel_row = _assert_funnel_usable_for_inbox(supabase, body.funnel_id, eff, uid)
    inbox_tenant = str(funnel_row["tenant_id"])

    now = datetime.now(timezone.utc).isoformat()
    insert_payload = {
        "tenant_id": inbox_tenant,
        "funnel_id": body.funnel_id,
        "name": body.name.strip(),
        "provider": body.provider,
        "uazapi_settings": body.uazapi_settings or {},
        "chatwoot_settings": body.chatwoot_settings or {},
        "created_at": now,
        "updated_at": now,
    }
    res = supabase.table("inboxes").insert(insert_payload).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao criar inbox.")
    return _row_to_response(rows[0])


@router.patch("/{inbox_id}", response_model=InboxResponse)
async def update_inbox(
    inbox_id: str,
    body: InboxUpdate,
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    uid = str(user.id)
    existing = _require_inbox_mutable_by_org_admin(supabase, inbox_id, eff, uid)
    new_funnel = body.funnel_id if body.funnel_id is not None else str(existing["funnel_id"])
    funnel_row = _assert_funnel_usable_for_inbox(supabase, new_funnel, eff, uid)

    patch: dict[str, Any] = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.name is not None:
        patch["name"] = body.name.strip()
    if body.funnel_id is not None:
        patch["funnel_id"] = body.funnel_id
        patch["tenant_id"] = str(funnel_row["tenant_id"])
    if body.provider is not None:
        patch["provider"] = body.provider
    if body.uazapi_settings is not None:
        merged = dict(existing.get("uazapi_settings") or {})
        merged.update(body.uazapi_settings)
        patch["uazapi_settings"] = merged
    if body.chatwoot_settings is not None:
        merged_cw = dict(existing.get("chatwoot_settings") or {})
        merged_cw.update(body.chatwoot_settings)
        patch["chatwoot_settings"] = merged_cw

    if len(patch) <= 1 and body.uazapi_settings is None and body.chatwoot_settings is None:
        return _row_to_response(existing)

    res = supabase.table("inboxes").update(patch).eq("id", inbox_id).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao atualizar inbox.")
    return _row_to_response(rows[0])


@router.delete("/{inbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbox(
    inbox_id: str,
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    uid = str(user.id)
    _require_inbox_mutable_by_org_admin(supabase, inbox_id, eff, uid)
    supabase.table("inboxes").delete().eq("id", inbox_id).execute()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
