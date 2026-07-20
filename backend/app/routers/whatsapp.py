"""
WhatsApp Integration Router
Handles Uazapi instance management — escopado por inbox (Sprint 7) ou legado via settings.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from supabase import Client as SupabaseClient

from app.config import get_settings
from app.dependencies import get_current_user, get_supabase
from app.services.uazapi_service import UazapiService

router = APIRouter()
uazapi = UazapiService()

UAZAPI_TOKEN_KEY = "instance_token"
_MAX_INSTANCE_NAME_LEN = 60


class ConnectRequest(BaseModel):
    instance_name: str
    inbox_id: Optional[str] = Field(
        None,
        description="UUID da caixa de entrada — credenciais ficam em inboxes.uazapi_settings.",
    )


class TokenRequest(BaseModel):
    instance_token: str
    inbox_id: Optional[str] = Field(None, description="Se omitido, usa settings legado por tenant.")
    instance_name: Optional[str] = Field(
        None,
        description="Nome da instância na Uazapi (o webhook envia em instanceName) — usado para resolver a caixa se o token não vier no payload.",
    )


class ConnectBody(BaseModel):
    phone: Optional[str] = Field(
        None,
        description="Só dígitos (ex. 5511999999999). Com telefone → código de pareamento; vazio → QR.",
    )


def dispatch_instance_name(email: str) -> str:
    """Nome estável: disp-crm-{email sanitizado}."""
    raw = (email or "").strip().lower()
    raw = raw.replace("@", "-").replace(".", "-")
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = "user"
    name = f"disp-crm-{cleaned}"
    return name[:_MAX_INSTANCE_NAME_LEN].rstrip("-")


def _extract_instance_token(payload: dict[str, Any], fallback_name: str = "") -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    token = payload.get("token")
    if token:
        return str(token)
    inst = payload.get("instance")
    if isinstance(inst, dict):
        t = inst.get("token")
        if t:
            return str(t)
    if fallback_name:
        return fallback_name
    return None


def _instance_name_from_row(inst: dict[str, Any]) -> str:
    nested = inst.get("instance") if isinstance(inst.get("instance"), dict) else {}
    return str(
        nested.get("instanceName")
        or nested.get("name")
        or inst.get("instanceName")
        or inst.get("name")
        or ""
    )


def _pick_pairing_code(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in ("pairingCode", "paircode", "pairCode", "pairing_code", "code", "linkCode"):
        val = obj.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def _normalize_connect_response(connect_data: dict[str, Any], phone: Optional[str]) -> dict[str, Any]:
    """Espelha a lógica do workflow n8n GeraQRCode-uazapi."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    instance = connect_data.get("instance") if isinstance(connect_data.get("instance"), dict) else {}
    state = (
        instance.get("state")
        or instance.get("status")
        or connect_data.get("state")
        or connect_data.get("status")
    )
    if state in ("open", "connected"):
        return {"mode": "already_connected", "status": state, "data": connect_data}

    if digits:
        pairing = _pick_pairing_code(instance) or _pick_pairing_code(connect_data)
        if not pairing:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Telefone informado, mas a Uazapi não retornou código de pareamento.",
            )
        return {
            "mode": "pairing",
            "pairingCode": pairing,
            "phone": digits,
            "status": state,
            "data": connect_data,
        }

    qrcode = (
        instance.get("qrcode")
        or instance.get("qr")
        or connect_data.get("base64")
        or connect_data.get("qrcode")
        or connect_data.get("qr")
        or ""
    )
    if not qrcode:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Resposta sem QR Code. Deixe o telefone vazio para gerar QR ou confira a instância.",
        )
    return {
        "mode": "qrcode",
        "qrcode": str(qrcode),
        "status": state or "connecting",
        "data": connect_data,
    }


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


def _load_inbox_row(supabase: SupabaseClient, inbox_id: str, user_id: str) -> dict[str, Any]:
    res = supabase.table("inboxes").select("*").eq("id", inbox_id).limit(1).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Caixa de entrada não encontrada.")
    row = rows[0]
    if str(row["tenant_id"]) != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Esta caixa não pertence ao seu tenant.")
    return row


def _token_from_inbox_row(row: dict[str, Any]) -> Optional[str]:
    settings = row.get("uazapi_settings") or {}
    if isinstance(settings, dict):
        t = settings.get(UAZAPI_TOKEN_KEY)
        return str(t) if t else None
    return None


def _resolve_instance_token(
    supabase: SupabaseClient,
    user_id: str,
    inbox_id: Optional[str],
) -> tuple[Optional[str], str]:
    """
    Retorna (token, modo): modo 'inbox' ou 'legacy'.
    """
    if inbox_id:
        row = _load_inbox_row(supabase, inbox_id, user_id)
        return _token_from_inbox_row(row), "inbox"
    return _legacy_settings_token(supabase, user_id), "legacy"


def _save_token_to_inbox(
    supabase: SupabaseClient,
    inbox_id: str,
    user_id: str,
    instance_token: str,
    *,
    instance_name: Optional[str] = None,
) -> None:
    row = _load_inbox_row(supabase, inbox_id, user_id)
    settings = dict(row.get("uazapi_settings") or {})
    if not isinstance(settings, dict):
        settings = {}
    settings[UAZAPI_TOKEN_KEY] = instance_token
    if instance_name and str(instance_name).strip():
        settings["instance_name"] = str(instance_name).strip()
    now = datetime.now(timezone.utc).isoformat()
    supabase.table("inboxes").update({"uazapi_settings": settings, "updated_at": now}).eq("id", inbox_id).eq(
        "tenant_id", user_id
    ).execute()


def _save_token_legacy(supabase: SupabaseClient, user_id: str, instance_token: str) -> None:
    supabase.table("settings").upsert(
        {"tenant_id": user_id, "key": "uazapi_instance_token", "value": instance_token},
        on_conflict="tenant_id,key",
    ).execute()


def _clear_token_legacy(supabase: SupabaseClient, user_id: str) -> None:
    supabase.table("settings").delete().eq("tenant_id", user_id).eq("key", "uazapi_instance_token").execute()


async def _instance_token_alive(instance_token: str) -> bool:
    """False se a Uazapi rejeitar o token (instância apagada → 401/403/404)."""
    import httpx

    try:
        await uazapi.get_instance_status(instance_token=instance_token)
        return True
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code in (401, 403, 404):
            return False
        # Outros erros HTTP: não descartar token automaticamente
        return True
    except Exception as exc:
        msg = str(exc).lower()
        if "401" in msg or "unauthorized" in msg or "403" in msg or "404" in msg:
            return False
        return True


async def _configure_webhook(instance_token: str) -> None:
    from app.config import get_settings

    settings = get_settings()
    webhook_url = settings.uazapi_webhook_callback_url
    try:
        await uazapi.set_webhook(url=webhook_url, instance_token=instance_token)
    except Exception as e:
        print(f"Error setting webhook: {e}")


@router.get("/status")
async def get_status(
    inbox_id: Optional[str] = Query(None, description="Escopo da instância Uazapi (caixa de entrada)."),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Status da conexão WhatsApp — por inbox ou legado (settings)."""
    uid = str(user.id)
    instance_token, mode = _resolve_instance_token(supabase, uid, inbox_id)

    if not instance_token:
        msg = "Nenhum token configurado para esta caixa." if mode == "inbox" else "Nenhum token configurado."
        return {"status": "disconnected", "message": msg, "scope": mode}

    try:
        status_data = await uazapi.get_instance_status(instance_token=instance_token)

        instance_state = "unknown"
        if "instance" in status_data:
            instance_state = status_data["instance"].get(
                "state", status_data["instance"].get("status", "unknown")
            )
        elif "state" in status_data:
            instance_state = status_data["state"]
        elif "status" in status_data:
            instance_state = status_data["status"]

        return {"status": instance_state, "data": status_data, "scope": mode}
    except Exception as e:
        return {"status": "error", "message": f"Erro ao consultar Uazapi: {str(e)}", "scope": mode}


@router.post("/init")
async def init_instance_route(
    payload: ConnectRequest,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Inicializa instância Uazapi e grava token na caixa (inbox) ou em settings (legado)."""
    uid = str(user.id)
    instance_name = payload.instance_name
    instance_token = None

    try:
        instances = await uazapi.list_instances()
        for inst in instances:
            inst_name = inst.get("instance", {}).get("instanceName", inst.get("name", ""))
            if inst_name == instance_name:
                instance_token = inst.get("instance", {}).get("token", inst.get("token", ""))
                break
    except Exception as e:
        print(f"Error listing instances: {e}")

    if not instance_token:
        try:
            init_res = await uazapi.init_instance(name=instance_name)
            instance_token = init_res.get("token", instance_name)
            if "instance" in init_res and "token" in init_res["instance"]:
                instance_token = init_res["instance"]["token"]
        except Exception as e:
            print(f"Error init_instance: {e}")
            raise HTTPException(status_code=500, detail=f"Erro ao inicializar instância Uazapi: {e}")

    if not instance_token:
        raise HTTPException(status_code=400, detail="Não foi possível obter ou criar um token para a instância.")

    if payload.inbox_id:
        _save_token_to_inbox(supabase, payload.inbox_id, uid, instance_token, instance_name=instance_name)
    else:
        _save_token_legacy(supabase, uid, instance_token)

    await _configure_webhook(instance_token)

    return {"message": "Instância inicializada e webhook configurado", "token": instance_token}


@router.post("/ensure-dispatch")
async def ensure_dispatch_instance(
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """
    Garante instância do Comunicados (legado settings) nomeada disp-crm-{email}.
    Cria via admintoken se ainda não existir token válido no tenant.
    Se o token salvo estiver morto (instância apagada na Uazapi), limpa e recria.
    """
    uid = str(user.id)
    email = (getattr(user, "email", None) or "") or ""
    instance_name = dispatch_instance_name(email)

    existing, _mode = _resolve_instance_token(supabase, uid, None)
    if existing:
        if await _instance_token_alive(existing):
            return {
                "token_ready": True,
                "created": False,
                "recovered": False,
                "instance_name": instance_name,
                "message": "Token já configurado para este tenant.",
            }
        # Token órfão (ex.: instância deletada no painel Uazapi)
        _clear_token_legacy(supabase, uid)
        existing = None

    settings = get_settings()
    if not (settings.UAZAPI_ADMIN_TOKEN or "").strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="UAZAPI_ADMIN_TOKEN não configurado no servidor. Configure o WhatsApp em Configurações ou defina o admin token.",
        )

    instance_token: Optional[str] = None
    try:
        instances = await uazapi.list_instances()
        for inst in instances or []:
            if _instance_name_from_row(inst) == instance_name:
                instance_token = _extract_instance_token(inst)
                if not instance_token and isinstance(inst.get("instance"), dict):
                    instance_token = _extract_instance_token(inst["instance"])
                break
    except Exception as e:
        print(f"Error listing instances (ensure-dispatch): {e}")

    created = False
    recovered = True  # chegou aqui sem token válido prévio
    if not instance_token:
        try:
            create_res = await uazapi.create_instance(name=instance_name)
            instance_token = _extract_instance_token(create_res, fallback_name=instance_name)
            created = True
        except Exception as e:
            print(f"Error create_instance (ensure-dispatch): {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Falha ao criar instância Uazapi: {e}",
            ) from e

    if not instance_token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível obter token da instância de disparo.",
        )

    _save_token_legacy(supabase, uid, instance_token)
    await _configure_webhook(instance_token)

    return {
        "token_ready": True,
        "created": created,
        "recovered": recovered,
        "instance_name": instance_name,
        "message": "Instância de disparo pronta.",
    }


@router.post("/connect")
async def connect_instance(
    body: Optional[ConnectBody] = None,
    inbox_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """QR / pareamento — requer token já salvo na caixa ou settings legado."""
    uid = str(user.id)
    phone = body.phone if body else None
    instance_token, mode = _resolve_instance_token(supabase, uid, inbox_id)

    if not instance_token:
        raise HTTPException(
            status_code=400,
            detail="Nenhum token configurado. Use ensure-dispatch no Comunicados ou configure em Configurações.",
        )

    try:
        connect_data = await uazapi.connect_instance(instance_token=instance_token, phone=phone)
        normalized = _normalize_connect_response(
            connect_data if isinstance(connect_data, dict) else {},
            phone,
        )
        normalized["scope"] = mode
        normalized["message"] = "Connection initiated"
        return normalized
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        # Token morto: limpa settings legado para o próximo Conectar recriar via ensure-dispatch
        if mode == "legacy" and ("401" in err or "Unauthorized" in err or "unauthorized" in err.lower()):
            _clear_token_legacy(supabase, uid)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "Token WhatsApp inválido (instância provavelmente foi apagada na Uazapi). "
                    "O token antigo foi removido — clique em Conectar novamente para criar outra instância."
                ),
            ) from e
        raise HTTPException(status_code=500, detail=f"Erro ao conectar: {err}") from e


@router.post("/token")
async def save_manual_token(
    payload: TokenRequest,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Salva token manual (Leads Infinitos / instância existente)."""
    uid = str(user.id)

    resolved_name = payload.instance_name
    if not resolved_name and payload.inbox_id:
        try:
            status_data = await uazapi.get_instance_status(instance_token=payload.instance_token)
            resolved_name = (
                status_data.get("instance", {}).get("instanceName")
                or status_data.get("instanceName")
                or status_data.get("name")
            )
        except Exception:
            pass

    if payload.inbox_id:
        _save_token_to_inbox(
            supabase,
            payload.inbox_id,
            uid,
            payload.instance_token,
            instance_name=resolved_name,
        )
    else:
        _save_token_legacy(supabase, uid, payload.instance_token)

    await _configure_webhook(payload.instance_token)

    return {"message": "Token salvo com sucesso", "status": "saved"}


@router.delete("/disconnect")
async def disconnect_instance(
    inbox_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Remove token da caixa ou do settings legado e desconecta na Uazapi quando possível."""
    uid = str(user.id)

    if inbox_id:
        row = _load_inbox_row(supabase, inbox_id, uid)
        instance_token = _token_from_inbox_row(row)
        if instance_token:
            try:
                await uazapi.disconnect_instance(instance_token=instance_token)
            except Exception as e:
                print(f"Aviso ao desconectar na Uazapi: {e}")
        settings = dict(row.get("uazapi_settings") or {})
        if isinstance(settings, dict) and UAZAPI_TOKEN_KEY in settings:
            del settings[UAZAPI_TOKEN_KEY]
        if isinstance(settings, dict) and "instance_name" in settings:
            del settings["instance_name"]
        now = datetime.now(timezone.utc).isoformat()
        supabase.table("inboxes").update({"uazapi_settings": settings, "updated_at": now}).eq("id", inbox_id).eq(
            "tenant_id", uid
        ).execute()
        return {"message": "Instância desconectada e token removido da caixa."}

    response = (
        supabase.table("settings").select("value").eq("tenant_id", uid).eq("key", "uazapi_instance_token").execute()
    )
    if response.data:
        instance_token = response.data[0]["value"]
        try:
            await uazapi.disconnect_instance(instance_token=instance_token)
        except Exception as e:
            print(f"Aviso ao desconectar na Uazapi: {e}")

        supabase.table("settings").delete().eq("tenant_id", uid).eq("key", "uazapi_instance_token").execute()

    return {"message": "Instância desconectada e token removido."}


@router.get("/webhook-debug")
async def webhook_debug(
    inbox_id: Optional[str] = Query(None),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Diagnostico: mostra URL configurada e configuracao atual do webhook na Uazapi."""
    from app.config import get_settings

    uid = str(user.id)
    instance_token, mode = _resolve_instance_token(supabase, uid, inbox_id)

    settings = get_settings()
    expected_url = settings.uazapi_webhook_callback_url

    result: dict = {
        "expected_webhook_url": expected_url,
        "public_api_base_url": settings.PUBLIC_API_BASE_URL,
        "has_instance_token": bool(instance_token),
        "scope": mode,
    }

    if instance_token:
        try:
            current = await uazapi.get_webhook(instance_token=instance_token)
            result["uazapi_current_webhook"] = current
        except Exception as e:
            result["uazapi_current_webhook_error"] = str(e)

    return result
