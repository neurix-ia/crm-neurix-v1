"""Disparador CRM — membros, campanhas e integração n8n."""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, status
from supabase import Client as SupabaseClient

from app.config import Settings, get_settings
from app.services.hq_n8n_service import parse_n8n_instances
from app.services.n8n_instance_client import N8nInstanceClient
from app.services.phone_normalize import digits_only

logger = logging.getLogger(__name__)

UAZAPI_TOKEN_KEY = "instance_token"
# Delay entre envios em segundos (UI do Comunicados usa minutos: 3–9 → 180–540).
DEFAULT_MIN_DELAY = 180
DEFAULT_MAX_DELAY = 540


def normalize_phone_e164(raw: str) -> Optional[str]:
    digits = digits_only(raw)
    if len(digits) < 10:
        return None
    if not digits.startswith("55"):
        digits = "55" + digits
    if len(digits) < 12 or len(digits) > 13:
        return None
    return digits


def parse_members_csv(content: bytes) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """Retorna (rows válidas, linhas inválidas com motivo)."""
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CSV vazio ou sem cabeçalho.")

    field_map = {f.strip().lower(): f for f in reader.fieldnames if f}
    name_key = field_map.get("nome") or field_map.get("name")
    phone_key = field_map.get("telefone") or field_map.get("phone") or field_map.get("celular")
    if not phone_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CSV deve ter coluna telefone (ou phone/celular).",
        )

    valid: list[dict[str, str]] = []
    invalid: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=2):
        phone_raw = (row.get(phone_key) or "").strip()
        name = (row.get(name_key) or "").strip() if name_key else ""
        if not phone_raw:
            invalid.append({"line": i, "reason": "telefone vazio", "row": row})
            continue
        phone_e164 = normalize_phone_e164(phone_raw)
        if not phone_e164:
            invalid.append({"line": i, "reason": "telefone inválido", "phone": phone_raw})
            continue
        valid.append({"name": name or phone_e164, "phone": phone_raw, "phone_e164": phone_e164})
    return valid, invalid


def _legacy_settings_token(supabase: SupabaseClient, user_id: str) -> Optional[str]:
    response = (
        supabase.table("settings")
        .select("value")
        .eq("tenant_id", user_id)
        .eq("key", "uazapi_instance_token")
        .execute()
    )
    if not response.data:
        return None
    return response.data[0]["value"]


def _token_from_inbox_row(row: dict[str, Any]) -> Optional[str]:
    settings = row.get("uazapi_settings") or {}
    if isinstance(settings, dict):
        t = settings.get(UAZAPI_TOKEN_KEY)
        return str(t) if t else None
    return None


def resolve_instance_token(
    supabase: SupabaseClient,
    tenant_id: str,
    inbox_id: Optional[str] = None,
) -> str:
    if inbox_id:
        res = supabase.table("inboxes").select("*").eq("id", inbox_id).limit(1).execute()
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caixa de entrada não encontrada.")
        row = rows[0]
        if str(row["tenant_id"]) != tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Caixa não pertence ao tenant.")
        token = _token_from_inbox_row(row)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nenhum token WhatsApp configurado nesta caixa.",
            )
        return token

    token = _legacy_settings_token(supabase, tenant_id)
    if not token:
        inbox_res = (
            supabase.table("inboxes")
            .select("uazapi_settings")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        for row in inbox_res.data or []:
            token = _token_from_inbox_row(row)
            if token:
                return token
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum token WhatsApp configurado. Configure em Configurações > WhatsApp.",
        )
    return token


def upsert_members(supabase: SupabaseClient, tenant_id: str, rows: list[dict[str, str]]) -> int:
    if not rows:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    payload = [
        {
            "tenant_id": tenant_id,
            "name": r["name"],
            "phone": r["phone"],
            "phone_e164": r["phone_e164"],
            "updated_at": now,
        }
        for r in rows
    ]
    supabase.table("dispatch_members").upsert(payload, on_conflict="tenant_id,phone_e164").execute()
    return len(payload)


def resolve_dispatch_n8n_client(settings: Settings | None = None) -> Optional[N8nInstanceClient]:
    settings = settings or get_settings()
    instances = parse_n8n_instances(settings)
    if not instances:
        return None
    preferred = (settings.N8N_DISPATCH_INSTANCE_ID or "").strip()
    if preferred:
        for cfg in instances:
            if cfg.id == preferred:
                return N8nInstanceClient(cfg, verify_ssl=settings.N8N_SSL_VERIFY)
    webhook = (settings.N8N_DISPATCH_WEBHOOK_URL or "").strip()
    host = urlparse(webhook).netloc.lower() if webhook else ""
    if host:
        for cfg in instances:
            if urlparse(cfg.base_url).netloc.lower() == host:
                return N8nInstanceClient(cfg, verify_ssl=settings.N8N_SSL_VERIFY)
    return None


async def cancel_n8n_execution(execution_id: str) -> dict[str, Any]:
    client = resolve_dispatch_n8n_client()
    if not client:
        return {
            "n8n_stopped": False,
            "n8n_deleted": False,
            "n8n_error": "N8N_INSTANCES não configurado para stop/delete.",
        }
    stopped = False
    deleted = False
    err: Optional[str] = None
    try:
        await client.stop_execution(execution_id)
        stopped = True
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            err = f"stop: {exc}"
    except Exception as exc:
        err = f"stop: {exc}"
    try:
        await client.delete_execution(execution_id)
        deleted = True
    except Exception as exc:
        err = (err + "; " if err else "") + f"delete: {exc}"
    return {"n8n_stopped": stopped, "n8n_deleted": deleted, "n8n_error": err}


def save_campaign_execution_id(
    supabase: SupabaseClient, campaign_id: str, execution_id: str
) -> None:
    supabase.table("dispatch_campaigns").update(
        {
            "n8n_execution_id": execution_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", campaign_id).execute()


async def trigger_n8n_dispatch(payload: dict[str, Any]) -> None:
    settings = get_settings()
    webhook_url = (settings.N8N_DISPATCH_WEBHOOK_URL or "").strip()
    if not webhook_url:
        logger.warning("N8N_DISPATCH_WEBHOOK_URL não configurada — campanha criada mas n8n não disparado.")
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        logger.exception("Falha ao chamar webhook n8n disparador: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao iniciar disparo no n8n: {exc}",
        )


def refresh_campaign_counters(supabase: SupabaseClient, campaign_id: str) -> dict[str, Any]:
    targets_res = (
        supabase.table("dispatch_targets")
        .select("status")
        .eq("campaign_id", campaign_id)
        .execute()
    )
    rows = targets_res.data or []
    total = len(rows)
    sent = sum(1 for r in rows if r.get("status") == "sent")
    failed = sum(1 for r in rows if r.get("status") == "failed")
    pending = sum(1 for r in rows if r.get("status") == "pending")

    camp_status = "running"
    finished_at = None
    if total > 0 and pending == 0:
        camp_status = "failed" if failed == total else "done"
        finished_at = datetime.now(timezone.utc).isoformat()

    update: dict[str, Any] = {
        "total": total,
        "sent": sent,
        "failed": failed,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if finished_at:
        update["status"] = camp_status
        update["finished_at"] = finished_at

    supabase.table("dispatch_campaigns").update(update).eq("id", campaign_id).execute()
    return {"total": total, "sent": sent, "failed": failed, "pending": pending, "status": camp_status}
