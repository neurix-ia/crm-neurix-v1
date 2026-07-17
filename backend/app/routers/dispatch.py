"""Disparador CRM — gestão de membros e campanhas (JWT)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from supabase import Client as SupabaseClient

from app.config import get_settings
from app.dependencies import get_current_user, get_supabase
from app.services.dispatch_service import (
    DEFAULT_MAX_DELAY,
    DEFAULT_MIN_DELAY,
    parse_members_csv,
    refresh_campaign_counters,
    resolve_instance_token,
    trigger_n8n_dispatch,
    upsert_members,
)

router = APIRouter()


class DispatchMemberOut(BaseModel):
    id: str
    name: str
    phone: str
    phone_e164: str
    created_at: Optional[str] = None


class ImportMembersResponse(BaseModel):
    imported: int
    invalid: list[dict[str, Any]]
    preview: list[DispatchMemberOut]


class CreateCampaignRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    member_ids: Optional[list[str]] = None
    select_all: bool = False
    inbox_id: Optional[str] = None
    min_delay: int = Field(default=DEFAULT_MIN_DELAY, ge=1, le=3600)
    max_delay: int = Field(default=DEFAULT_MAX_DELAY, ge=1, le=7200)


class CampaignOut(BaseModel):
    id: str
    message: str
    status: str
    min_delay: int
    max_delay: int
    total: int
    sent: int
    failed: int
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class CampaignDetailOut(CampaignOut):
    targets: list[dict[str, Any]]


def _tenant_id(user) -> str:
    return str(user.id)


@router.post("/members/import", response_model=ImportMembersResponse)
async def import_members(
    file: UploadFile = File(...),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Arquivo vazio.")
    valid, invalid = parse_members_csv(content)
    tid = _tenant_id(user)
    count = upsert_members(supabase, tid, valid)

    preview_res = (
        supabase.table("dispatch_members")
        .select("id,name,phone,phone_e164,created_at")
        .eq("tenant_id", tid)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    preview = [DispatchMemberOut(**row) for row in (preview_res.data or [])]
    return ImportMembersResponse(imported=count, invalid=invalid, preview=preview)


@router.get("/members", response_model=list[DispatchMemberOut])
async def list_members(
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _tenant_id(user)
    res = (
        supabase.table("dispatch_members")
        .select("id,name,phone,phone_e164,created_at")
        .eq("tenant_id", tid)
        .order("name")
        .execute()
    )
    return [DispatchMemberOut(**row) for row in (res.data or [])]


@router.delete("/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(
    member_id: UUID,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _tenant_id(user)
    res = (
        supabase.table("dispatch_members")
        .delete()
        .eq("id", str(member_id))
        .eq("tenant_id", tid)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membro não encontrado.")


@router.post("/campaigns", response_model=CampaignOut)
async def create_campaign(
    body: CreateCampaignRequest,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    if body.min_delay > body.max_delay:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_delay não pode ser maior que max_delay.",
        )

    tid = _tenant_id(user)
    members_query = supabase.table("dispatch_members").select("id,name,phone_e164").eq("tenant_id", tid)
    if body.select_all:
        members_res = members_query.execute()
    elif body.member_ids:
        members_res = members_query.in_("id", body.member_ids).execute()
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe member_ids ou select_all=true.",
        )

    members = members_res.data or []
    if not members:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum membro selecionado.")

    instance_token = resolve_instance_token(supabase, tid, body.inbox_id)
    now = datetime.now(timezone.utc).isoformat()
    camp_res = (
        supabase.table("dispatch_campaigns")
        .insert(
            {
                "tenant_id": tid,
                "message": body.message.strip(),
                "status": "running",
                "min_delay": body.min_delay,
                "max_delay": body.max_delay,
                "total": len(members),
                "instance_token": instance_token,
                "started_at": now,
                "updated_at": now,
            }
        )
        .execute()
    )
    if not camp_res.data:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao criar campanha.")
    campaign = camp_res.data[0]
    campaign_id = str(campaign["id"])

    targets = [
        {
            "campaign_id": campaign_id,
            "tenant_id": tid,
            "member_id": m["id"],
            "name": m.get("name") or m["phone_e164"],
            "phone_e164": m["phone_e164"],
            "status": "pending",
            "updated_at": now,
        }
        for m in members
    ]
    supabase.table("dispatch_targets").insert(targets).execute()

    settings = get_settings()
    await trigger_n8n_dispatch(
        {
            "campaign_id": campaign_id,
            "instance_token": instance_token,
            "message": body.message.strip(),
            "min_delay": body.min_delay,
            "max_delay": body.max_delay,
            "crm_base_url": settings.PUBLIC_API_BASE_URL.rstrip("/"),
        }
    )

    return CampaignOut(
        id=campaign_id,
        message=campaign["message"],
        status=campaign["status"],
        min_delay=campaign["min_delay"],
        max_delay=campaign["max_delay"],
        total=len(members),
        sent=0,
        failed=0,
        created_at=campaign.get("created_at"),
        started_at=campaign.get("started_at"),
    )


@router.get("/campaigns/{campaign_id}", response_model=CampaignDetailOut)
async def get_campaign(
    campaign_id: UUID,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _tenant_id(user)
    camp_res = (
        supabase.table("dispatch_campaigns")
        .select("*")
        .eq("id", str(campaign_id))
        .eq("tenant_id", tid)
        .limit(1)
        .execute()
    )
    rows = camp_res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    campaign = rows[0]

    targets_res = (
        supabase.table("dispatch_targets")
        .select("id,member_id,name,phone_e164,status,error,sent_at")
        .eq("campaign_id", str(campaign_id))
        .order("created_at")
        .execute()
    )

    return CampaignDetailOut(
        id=str(campaign["id"]),
        message=campaign["message"],
        status=campaign["status"],
        min_delay=campaign["min_delay"],
        max_delay=campaign["max_delay"],
        total=campaign.get("total") or 0,
        sent=campaign.get("sent") or 0,
        failed=campaign.get("failed") or 0,
        created_at=campaign.get("created_at"),
        started_at=campaign.get("started_at"),
        finished_at=campaign.get("finished_at"),
        targets=targets_res.data or [],
    )


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(
    limit: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tid = _tenant_id(user)
    res = (
        supabase.table("dispatch_campaigns")
        .select("id,message,status,min_delay,max_delay,total,sent,failed,created_at,started_at,finished_at")
        .eq("tenant_id", tid)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        CampaignOut(
            id=str(r["id"]),
            message=r["message"],
            status=r["status"],
            min_delay=r["min_delay"],
            max_delay=r["max_delay"],
            total=r.get("total") or 0,
            sent=r.get("sent") or 0,
            failed=r.get("failed") or 0,
            created_at=r.get("created_at"),
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
        )
        for r in (res.data or [])
    ]
