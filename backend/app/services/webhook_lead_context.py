"""
Resolução de inbox Uazapi, estágio inicial e cliente CRM para o worker de webhook (Sprint 9).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from supabase import Client as SupabaseClient

from app.services.phone_normalize import digits_only

# Alinhado a backend/app/routers/whatsapp.py — token da instância na caixa
UAZAPI_INSTANCE_TOKEN_KEY = "instance_token"
# Gravado no init da instância — fallback quando o webhook só manda instanceName (sem token no body)
UAZAPI_INSTANCE_NAME_KEY = "instance_name"


def _token_from_uazapi_settings(settings: Any) -> Optional[str]:
    if not isinstance(settings, dict):
        return None
    t = settings.get(UAZAPI_INSTANCE_TOKEN_KEY)
    return str(t).strip() if t else None


def find_inbox_by_instance_token(supabase: SupabaseClient, instance_token: str) -> Optional[dict[str, Any]]:
    """Varre inboxes (volume típico baixo) e compara instance_token em uazapi_settings."""
    if not instance_token:
        return None
    try:
        res = supabase.table("inboxes").select("id, tenant_id, funnel_id, name, uazapi_settings").execute()
        for row in res.data or []:
            settings = row.get("uazapi_settings") or {}
            if not isinstance(settings, dict):
                continue
            t = settings.get(UAZAPI_INSTANCE_TOKEN_KEY)
            if t is not None and str(t).strip() == str(instance_token).strip():
                return row
    except Exception:
        return None
    return None


def find_inbox_by_instance_name(supabase: SupabaseClient, instance_name: str) -> Optional[dict[str, Any]]:
    """Correlaciona payload.instanceName (Uazapi) com uazapi_settings.instance_name gravado no init."""
    name = (instance_name or "").strip()
    if not name:
        return None
    name_lower = name.casefold()
    try:
        res = supabase.table("inboxes").select("id, tenant_id, funnel_id, name, uazapi_settings").execute()
        for row in res.data or []:
            settings = row.get("uazapi_settings") or {}
            if not isinstance(settings, dict):
                continue
            stored = settings.get(UAZAPI_INSTANCE_NAME_KEY)
            if stored is not None and str(stored).strip().casefold() == name_lower:
                return row
    except Exception:
        return None
    return None


def get_uazapi_instance_token_for_tenant(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    inbox_id: Optional[str],
) -> Optional[str]:
    """
    Token Uazapi para chamadas de API.
    Prioridade: 1) inbox específico, 2) settings legado, 3) qualquer inbox do tenant com token.
    """
    if inbox_id:
        try:
            r = (
                supabase.table("inboxes")
                .select("uazapi_settings")
                .eq("id", inbox_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            if r.data:
                t = _token_from_uazapi_settings(r.data[0].get("uazapi_settings"))
                if t:
                    return t
        except Exception:
            pass
    try:
        resp = (
            supabase.table("settings")
            .select("value")
            .eq("tenant_id", tenant_id)
            .eq("key", "uazapi_instance_token")
            .limit(1)
            .execute()
        )
        if resp.data:
            val = resp.data[0].get("value")
            if val is not None:
                s = val.strip('"') if isinstance(val, str) else str(val)
                if s.strip():
                    return s.strip()
    except Exception:
        pass

    # Fallback: scan all inboxes for this tenant and return first valid token
    try:
        all_inboxes = (
            supabase.table("inboxes")
            .select("id, uazapi_settings")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        for row in all_inboxes.data or []:
            t = _token_from_uazapi_settings(row.get("uazapi_settings"))
            if t:
                return t
    except Exception:
        pass
    return None


def find_inbox_for_tenant(supabase: SupabaseClient, tenant_id: str) -> Optional[dict[str, Any]]:
    """Retorna a primeira inbox do tenant que possua token Uazapi configurado."""
    if not tenant_id:
        return None
    try:
        res = supabase.table("inboxes").select("id, tenant_id, funnel_id, name, uazapi_settings").eq("tenant_id", tenant_id).execute()
        for row in res.data or []:
            t = _token_from_uazapi_settings(row.get("uazapi_settings"))
            if t:
                return row
    except Exception:
        return None
    return None


def find_legacy_tenant_id_for_token(supabase: SupabaseClient, instance_token: str) -> Optional[str]:
    """Resolve tenant_id pela linha legada em settings (valor pode ser string JSON ou texto)."""
    if not instance_token:
        return None
    candidates = [
        instance_token,
        json.dumps(instance_token),
        f'"{instance_token}"',
    ]
    for val in candidates:
        try:
            resp = (
                supabase.table("settings")
                .select("tenant_id")
                .eq("key", "uazapi_instance_token")
                .eq("value", val)
                .limit(1)
                .execute()
            )
            if resp.data:
                return str(resp.data[0]["tenant_id"])
        except Exception:
            continue
    return None


def slugify_stage_name(name: str) -> str:
    """Converte nome de coluna do funil em slug."""
    return "_".join(name.strip().lower().split())


def get_first_stage_slug_for_funnel(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    funnel_id: str,
) -> str:
    """Primeiro estágio do funil (order_position); retorna nome real do pipeline_stages."""
    try:
        res = (
            supabase.table("pipeline_stages")
            .select("name, order_position")
            .eq("tenant_id", tenant_id)
            .eq("funnel_id", funnel_id)
            .order("order_position")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return str(rows[0]["name"]).strip()
    except Exception:
        pass
    return ""


def resolve_or_create_crm_client(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    sender_phone_raw: str,
    sender_name: str,
) -> Optional[str]:
    """
    Resolve cliente por telefone normalizado; cria PF se não existir.
    Retorna UUID do crm_clients ou None se falhar gravação.
    """
    digits = digits_only(sender_phone_raw)
    if not digits:
        return None

    try:
        existing = (
            supabase.table("crm_clients")
            .select("id, phones")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        for row in existing.data or []:
            phones = row.get("phones")
            if not isinstance(phones, list):
                continue
            for p in phones:
                if digits_only(str(p)) == digits:
                    return str(row["id"])
    except Exception:
        pass

    display = (sender_name or "").strip() or digits
    contact = (sender_name or "").strip() or None
    phones_json = [digits]
    insert_payload = {
        "tenant_id": tenant_id,
        "person_type": "PF",
        "display_name": display[:500],
        "contact_name": contact[:500] if contact else display[:500],
        "phones": phones_json,
    }
    try:
        ins = supabase.table("crm_clients").insert(insert_payload).execute()
        if ins.data:
            return str(ins.data[0]["id"])
    except Exception:
        return None
    return None


# =============================================================================
# Chatwoot (provider oficial) — resolução de inbox e mapeamento etiqueta→etapa
# =============================================================================

def _chatwoot_ids(payload: dict) -> tuple[str, str]:
    """Extrai (account_id, chatwoot_inbox_id) de qualquer evento Chatwoot."""
    account_id = ""
    inbox_id = ""
    acc = payload.get("account")
    if isinstance(acc, dict) and acc.get("id") is not None:
        account_id = str(acc.get("id"))
    inb = payload.get("inbox")
    if isinstance(inb, dict) and inb.get("id") is not None:
        inbox_id = str(inb.get("id"))
    if not inbox_id and payload.get("inbox_id") is not None:
        inbox_id = str(payload.get("inbox_id"))
    conv = payload.get("conversation") if isinstance(payload.get("conversation"), dict) else None
    if not inbox_id and conv and conv.get("inbox_id") is not None:
        inbox_id = str(conv.get("inbox_id"))
    if not account_id:
        msgs = payload.get("messages")
        if not msgs and conv:
            msgs = conv.get("messages")
        if isinstance(msgs, list) and msgs and msgs[0].get("account_id") is not None:
            account_id = str(msgs[0].get("account_id"))
    if not inbox_id:
        ci = payload.get("contact_inbox") or (conv.get("contact_inbox") if conv else None)
        if isinstance(ci, dict) and ci.get("inbox_id") is not None:
            inbox_id = str(ci.get("inbox_id"))
    return account_id, inbox_id


def find_inbox_by_chatwoot(
    supabase: SupabaseClient, account_id: str, chatwoot_inbox_id: str
) -> Optional[dict[str, Any]]:
    """Resolve a caixa do CRM por (account_id, inbox_id) gravados em chatwoot_settings."""
    if not (account_id and chatwoot_inbox_id):
        return None
    try:
        res = (
            supabase.table("inboxes")
            .select("id, tenant_id, funnel_id, name, provider, chatwoot_settings")
            .eq("provider", "chatwoot")
            .execute()
        )
        for row in res.data or []:
            cfg = row.get("chatwoot_settings") or {}
            if not isinstance(cfg, dict):
                continue
            if str(cfg.get("account_id")) == str(account_id) and str(cfg.get("inbox_id")) == str(chatwoot_inbox_id):
                return row
    except Exception:
        return None
    return None


def ensure_stage_for_label(
    supabase: SupabaseClient, *, tenant_id: str, funnel_id: str, label: str
) -> str:
    """Garante a etapa (coluna) correspondente à etiqueta; cria se faltar. Retorna o nome da etapa."""
    label = (label or "").strip()
    if not label:
        return ""
    try:
        res = (
            supabase.table("pipeline_stages")
            .select("id, name, source_label, order_position")
            .eq("tenant_id", tenant_id)
            .eq("funnel_id", funnel_id)
            .execute()
        )
        rows = res.data or []
        max_pos = -1
        for r in rows:
            sl = (r.get("source_label") or "").strip()
            nm = (r.get("name") or "").strip()
            if sl == label or nm.casefold() == label.casefold():
                return str(r.get("name") or label)
            try:
                max_pos = max(max_pos, int(r.get("order_position") or 0))
            except Exception:
                pass
        new_stage = {
            "tenant_id": tenant_id,
            "funnel_id": funnel_id,
            "name": label,
            "source_label": label,
            "order_position": max_pos + 1,
        }
        ins = supabase.table("pipeline_stages").insert(new_stage).execute()
        if ins.data:
            return str(ins.data[0].get("name") or label)
    except Exception:
        pass
    return label
