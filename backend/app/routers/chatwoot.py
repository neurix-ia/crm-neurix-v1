"""
Chatwoot Integration Router — conexão da API oficial (WhatsApp Cloud via Chatwoot),
escopada por inbox. Credenciais ficam em inboxes.chatwoot_settings.

Espelha o fluxo do router whatsapp.py (Uazapi), mas com modal/credenciais próprios.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client as SupabaseClient

from app.dependencies import get_current_user, get_supabase
from app.services.chatwoot_service import ChatwootConfigError, ChatwootService

router = APIRouter()

CHATWOOT_SETTINGS_KEYS = ("base_url", "account_id", "inbox_id", "api_access_token", "webhook_secret", "phone_number_id")


class ChatwootConnectRequest(BaseModel):
    inbox_id: str = Field(..., description="UUID da caixa de entrada do CRM.")
    base_url: str = Field(..., description="URL base do Chatwoot, ex.: https://chatwoot.suaempresa.com")
    account_id: str = Field(..., description="ID da conta no Chatwoot.")
    chatwoot_inbox_id: str = Field(..., description="ID do inbox no Chatwoot.")
    api_access_token: str = Field(..., description="Token de acesso (api_access_token).")
    webhook_secret: Optional[str] = Field(None, description="Secret de assinatura HMAC do webhook.")
    phone_number_id: Optional[str] = Field(None, description="phone_number_id da Meta (opcional).")


def _load_inbox_row(supabase: SupabaseClient, inbox_id: str, user_id: str) -> dict[str, Any]:
    res = supabase.table("inboxes").select("*").eq("id", inbox_id).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caixa de entrada não encontrada.")
    row = rows[0]
    if str(row["tenant_id"]) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta caixa não pertence ao seu tenant.")
    return row


def _settings_from_row(row: dict[str, Any]) -> dict[str, Any]:
    s = row.get("chatwoot_settings") or {}
    return s if isinstance(s, dict) else {}


@router.post("/connect")
async def connect_chatwoot(
    payload: ChatwootConnectRequest,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Valida as credenciais Chatwoot e grava em inboxes.chatwoot_settings (provider='chatwoot')."""
    uid = str(user.id)
    _load_inbox_row(supabase, payload.inbox_id, uid)

    try:
        service = ChatwootService(
            base_url=payload.base_url,
            account_id=payload.account_id,
            api_access_token=payload.api_access_token,
        )
        labels = await service.verify()
    except ChatwootConfigError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        detail = "Token inválido ou sem permissão." if code in (401, 403) else f"Falha ao validar no Chatwoot (HTTP {code})."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Erro ao conectar no Chatwoot: {e}") from e

    new_settings = {
        "base_url": str(payload.base_url).rstrip("/"),
        "account_id": str(payload.account_id),
        "inbox_id": str(payload.chatwoot_inbox_id),
        "api_access_token": payload.api_access_token,
    }
    if payload.webhook_secret:
        new_settings["webhook_secret"] = payload.webhook_secret
    if payload.phone_number_id:
        new_settings["phone_number_id"] = payload.phone_number_id

    now = datetime.now(timezone.utc).isoformat()
    supabase.table("inboxes").update(
        {"provider": "chatwoot", "chatwoot_settings": new_settings, "updated_at": now}
    ).eq("id", payload.inbox_id).eq("tenant_id", uid).execute()

    return {"status": "connected", "labels_count": len(labels)}


@router.get("/status")
async def chatwoot_status(
    inbox_id: str = Query(..., description="UUID da caixa de entrada do CRM."),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Testa a conexão Chatwoot da caixa."""
    uid = str(user.id)
    row = _load_inbox_row(supabase, inbox_id, uid)
    settings = _settings_from_row(row)

    if not settings.get("api_access_token"):
        return {"status": "disconnected", "message": "Nenhuma credencial Chatwoot nesta caixa."}

    try:
        service = ChatwootService.from_settings(settings)
        labels = await service.verify()
        return {"status": "connected", "labels_count": len(labels), "account_id": settings.get("account_id")}
    except ChatwootConfigError as e:
        return {"status": "disconnected", "message": str(e)}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "message": f"HTTP {e.response.status_code} ao validar no Chatwoot."}
    except Exception as e:
        return {"status": "error", "message": f"Erro ao consultar Chatwoot: {e}"}


@router.delete("/disconnect")
async def disconnect_chatwoot(
    inbox_id: str = Query(..., description="UUID da caixa de entrada do CRM."),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Remove as credenciais Chatwoot da caixa (mantém o funil; provider volta a 'uazapi')."""
    uid = str(user.id)
    _load_inbox_row(supabase, inbox_id, uid)
    now = datetime.now(timezone.utc).isoformat()
    supabase.table("inboxes").update(
        {"provider": "uazapi", "chatwoot_settings": {}, "updated_at": now}
    ).eq("id", inbox_id).eq("tenant_id", uid).execute()
    return {"status": "disconnected"}
