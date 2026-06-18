"""
Ferramentas HTTP usadas pelo agente n8n (busca_cliente, busca_ultimo_pedido).
Resolve tenant pelo instance_token da inbox Uazapi e consulta Supabase com service role.

Saneamento de ``crm_clients.phones`` (JSONB) no Supabase — diagnóstico, preview e
UPDATE idempotente (só dígitos, sem deduplicação): ver
``_bmad-output/implementation-artifacts/sql-saneamento-crm_clients-phones-legado.sql``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from supabase import Client as SupabaseClient

from app.services.phone_normalize import digits_only
from app.services.webhook_lead_context import find_inbox_by_instance_token

logger = logging.getLogger(__name__)

# public.orders — mesma ordem que information_schema (validação no Supabase).
_ORDERS_FULL_SELECT = (
    "id, tenant_id, lead_id, client_name, client_company, product_summary, "
    "total, payment_status, created_at, stage, notes, products_json, "
    "applied_promotions_json, subtotal, discount_total, payment_method, client_id"
)


def _json_safe_for_n8n(value: Any) -> Any:
    """Normaliza valores vindos do Supabase para JSON (tool HTTP / n8n)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _json_safe_for_n8n(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe_for_n8n(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def phone_from_whatsapp_jid_or_raw(value: str | None) -> str:
    """RemoteJid tipo 5541999999999@s.whatsapp.net → apenas dígitos do usuário."""
    if not value:
        return ""
    s = str(value).strip().split("@", 1)[0].strip()
    return digits_only(s)


# Lookup por telefone — canônico BR + match tolerante (strict > last11 > last10).
MIN_PHONE_LOOKUP_DIGITS = 4
PHONE_MATCH_RANK_NONE = 0
PHONE_MATCH_RANK_LAST10 = 1
PHONE_MATCH_RANK_LAST11 = 2
PHONE_MATCH_RANK_STRICT = 3

PhoneMatchTier = Literal["strict", "last11", "last10"]


def crm_phone_entry_digits(value: Any) -> str:
    """Dígitos de um item em ``crm_clients.phones`` (jsonb), via ``digits_only``."""
    if value is None:
        return ""
    return digits_only(str(value))


def to_canonical_br_phone_digits(raw_digits: str) -> str:
    """
    Forma canônica BR para comparação: DDI 55 + DDD (2) + 8 ou 9 dígitos locais.
    Espera string já só com dígitos (ex.: saída de ``phone_from_whatsapp_jid_or_raw``).
    Números nacionais com zero à esquerda (ex. 041...) têm o 0 removido antes do 55.
    Demais formatos são devolvidos como ``digits_only`` sem inferência de DDI.
    """
    d = digits_only(raw_digits)
    if not d:
        return ""
    if d.startswith("55") and len(d) >= 12:
        return d
    if not d.startswith("55"):
        d = d.lstrip("0") or d
        if not d:
            return ""
        if len(d) in (10, 11):
            return "55" + d
    return d


def is_insufficient_phone_lookup_digits(
    digits_or_jid_fragment: str,
    *,
    min_len: int = MIN_PHONE_LOOKUP_DIGITS,
) -> bool:
    """True se a entrada é curta demais para lookup (alinhado ao ``min_length`` da API)."""
    return len(digits_only(digits_or_jid_fragment)) < min_len


def phone_match_rank(query_digits: str, stored_phone_raw: Any) -> int:
    """
    Pontua match entre busca e um telefone armazenado: strict (3) > last11 (2) > last10 (1) > 0.

    ``query_digits``: dígitos da busca (ex.: resultado de ``phone_from_whatsapp_jid_or_raw``).
    Não valida comprimento mínimo global — o chamador deve rejeitar entrada curta antes.
    """
    q = digits_only(query_digits)
    s = crm_phone_entry_digits(stored_phone_raw)
    if not q or not s:
        return PHONE_MATCH_RANK_NONE
    qc = to_canonical_br_phone_digits(q)
    sc = to_canonical_br_phone_digits(s)
    if not qc or not sc:
        return PHONE_MATCH_RANK_NONE
    if qc == sc:
        return PHONE_MATCH_RANK_STRICT
    if len(qc) >= 11 and len(sc) >= 11 and qc[-11:] == sc[-11:]:
        return PHONE_MATCH_RANK_LAST11
    if len(qc) >= 10 and len(sc) >= 10 and qc[-10:] == sc[-10:]:
        return PHONE_MATCH_RANK_LAST10
    return PHONE_MATCH_RANK_NONE


def phone_match_tier(query_digits: str, stored_phone_raw: Any) -> PhoneMatchTier | None:
    """Nome do tier de match ou None se não houver match."""
    r = phone_match_rank(query_digits, stored_phone_raw)
    if r == PHONE_MATCH_RANK_STRICT:
        return "strict"
    if r == PHONE_MATCH_RANK_LAST11:
        return "last11"
    if r == PHONE_MATCH_RANK_LAST10:
        return "last10"
    return None


def format_cnpj_display(digits_raw: str | None) -> str:
    d = digits_only(digits_raw or "")
    if len(d) != 14:
        return (digits_raw or "").strip()
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _parse_datetime_sort(value: Any) -> Optional[datetime]:
    """Parse created_at-like values from Supabase/JSON para comparação."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


_DT_MIN = datetime.min.replace(tzinfo=timezone.utc)


def best_phone_match_rank_for_client_row(
    phone_digits: str,
    row: dict[str, Any],
) -> int:
    """Melhor ``phone_match_rank`` entre os telefones do cliente."""
    phones_raw = row.get("phones")
    if not isinstance(phones_raw, list):
        return PHONE_MATCH_RANK_NONE
    best = PHONE_MATCH_RANK_NONE
    for p in phones_raw:
        best = max(best, phone_match_rank(phone_digits, p))
    return best


def _phone_tier_label(rank: int) -> str:
    if rank == PHONE_MATCH_RANK_STRICT:
        return "strict"
    if rank == PHONE_MATCH_RANK_LAST11:
        return "last11"
    if rank == PHONE_MATCH_RANK_LAST10:
        return "last10"
    return "none"


def _normalize_client_person_type(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    return normalized if normalized in {"PF", "PJ"} else None


def _person_type_from_lead_stage(stage_name: Any) -> str | None:
    normalized = str(stage_name or "").strip().lower()
    if normalized == "b2b":
        return "PJ"
    if normalized == "b2c":
        return "PF"
    return None


def _prefer_phone_match_candidate_from_context(
    candidates: list[dict[str, Any]],
    *,
    lead_row: dict[str, Any] | None,
) -> tuple[dict[str, Any], str] | None:
    if not candidates or not lead_row:
        return None

    stage_person_type = _person_type_from_lead_stage(lead_row.get("stage"))
    if stage_person_type:
        stage_matches = [
            row
            for row in candidates
            if _normalize_client_person_type(row.get("person_type")) == stage_person_type
        ]
        if len(stage_matches) == 1:
            return stage_matches[0], f"lead_stage:{stage_person_type}"

    linked_client_id = str(lead_row.get("client_id") or "").strip()
    if not linked_client_id:
        return None
    for row in candidates:
        if str(row.get("id") or "").strip() == linked_client_id:
            return row, "lead_client_id"
    return None


def find_crm_client_row_by_phone(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    phone_digits: str,
    lead_row: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """
    Resolve um ``crm_clients`` por telefone: maior score de match (strict > last11 > last10),
    depois contexto do lead atual (estágio B2B/B2C ou ``lead.client_id``),
    depois pedido não cancelado mais recente (``client_id`` + fallback ``lead_id``),
    depois ``crm_clients.created_at`` descendente.
    """
    if len(phone_digits) < 4:
        return None
    try:
        res = (
            supabase.table("crm_clients")
            .select("*")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = res.data or []
    except Exception:
        return None

    scored: list[tuple[dict[str, Any], int]] = []
    for r in rows:
        rank = best_phone_match_rank_for_client_row(phone_digits, r)
        if rank > PHONE_MATCH_RANK_NONE:
            scored.append((r, rank))

    if not scored:
        return None

    max_rank = max(sr for _, sr in scored)
    candidates = [r for r, sr in scored if sr == max_rank]
    if len(candidates) == 1:
        chosen = candidates[0]
        logger.debug(
            "n8n client-by-phone: client_id=%s tenant_id=%s match_tier=%s (single candidate)",
            chosen.get("id"),
            tenant_id,
            _phone_tier_label(max_rank),
        )
        return chosen

    contextual_choice = _prefer_phone_match_candidate_from_context(
        candidates, lead_row=lead_row
    )
    if contextual_choice is not None:
        chosen, reason = contextual_choice
        logger.debug(
            "n8n client-by-phone: client_id=%s tenant_id=%s match_tier=%s "
            "tie_break=%s lead_stage=%s lead_client_id=%s candidates=%s",
            chosen.get("id"),
            tenant_id,
            _phone_tier_label(max_rank),
            reason,
            lead_row.get("stage") if lead_row else None,
            lead_row.get("client_id") if lead_row else None,
            len(candidates),
        )
        return chosen

    def tie_break_key(row: dict[str, Any]) -> tuple[datetime, datetime]:
        order = fetch_last_order_for_client(
            supabase, tenant_id=tenant_id, client_id=str(row["id"])
        )
        o_raw = order.get("created_at") if order else None
        o_dt = _parse_datetime_sort(o_raw) or _DT_MIN
        c_dt = _parse_datetime_sort(row.get("created_at")) or _DT_MIN
        return (o_dt, c_dt)

    keyed = [(r, tie_break_key(r)) for r in candidates]
    chosen, (o_dt, c_dt) = max(keyed, key=lambda item: item[1])
    logger.debug(
        "n8n client-by-phone: client_id=%s tenant_id=%s match_tier=%s "
        "tie_break=order_then_client order_ts=%s client_ts=%s candidates=%s",
        chosen.get("id"),
        tenant_id,
        _phone_tier_label(max_rank),
        o_dt.isoformat() if o_dt != _DT_MIN else None,
        c_dt.isoformat() if c_dt != _DT_MIN else None,
        len(candidates),
    )
    return chosen


def resolve_crm_client_for_n8n_phone(
    supabase: SupabaseClient,
    *,
    instance_token: str,
    phone: str,
) -> tuple[Optional[str], str, Optional[dict[str, Any]]]:
    """
    Caminho único para ``client-by-phone`` e ``last-order-by-phone``: tenant, dígitos
    e linha ``crm_clients`` via ``find_crm_client_row_by_phone`` (mesmo score e desempate).
    """
    inbox = resolve_inbox_row_for_n8n(supabase, instance_token.strip())
    if not inbox:
        return None, "", None
    tid = str(inbox.get("tenant_id") or "").strip()
    if not tid:
        return None, "", None
    digits = phone_from_whatsapp_jid_or_raw(phone)
    if len(digits) < MIN_PHONE_LOOKUP_DIGITS:
        return tid, digits, None
    lead_row = find_lead_by_whatsapp_chat(
        supabase,
        inbox_id=str(inbox.get("id") or "").strip(),
        tenant_id=tid,
        whatsapp_chat_id=normalize_whatsapp_chat_id(phone),
    )
    row = find_crm_client_row_by_phone(
        supabase,
        tenant_id=tid,
        phone_digits=digits,
        lead_row=lead_row,
    )
    return tid, digits, row


def fetch_last_order_for_client(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    client_id: str,
) -> Optional[dict[str, Any]]:
    try:
        r = (
            supabase.table("orders")
            .select(_ORDERS_FULL_SELECT)
            .eq("tenant_id", tenant_id)
            .eq("client_id", client_id)
            .neq("payment_status", "cancelado")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]
    except Exception:
        pass

    try:
        lr = supabase.table("leads").select("id").eq("client_id", client_id).execute()
        lead_ids = [str(x["id"]) for x in (lr.data or [])]
        if not lead_ids:
            return None
        r2 = (
            supabase.table("orders")
            .select(_ORDERS_FULL_SELECT)
            .eq("tenant_id", tenant_id)
            .in_("lead_id", lead_ids)
            .neq("payment_status", "cancelado")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if r2.data:
            return r2.data[0]
    except Exception:
        pass
    return None


def resolve_tenant_id_for_n8n(supabase: SupabaseClient, instance_token: str) -> Optional[str]:
    inbox = find_inbox_by_instance_token(supabase, instance_token)
    if not inbox:
        return None
    return str(inbox.get("tenant_id") or "").strip() or None


def resolve_inbox_row_for_n8n(supabase: SupabaseClient, instance_token: str) -> Optional[dict[str, Any]]:
    """Inbox completa (id, tenant_id, funnel_id) para lookup de lead."""
    row = find_inbox_by_instance_token(supabase, instance_token)
    if not row:
        return None
    return row


def normalize_whatsapp_chat_id(phone_or_jid: str | None) -> str:
    """RemoteJid completo ou só dígitos → JID padrão leads.whatsapp_chat_id."""
    if not phone_or_jid:
        return ""
    s = str(phone_or_jid).strip()
    if "@" in s:
        return s
    d = digits_only(s)
    if len(d) >= 4:
        return f"{d}@s.whatsapp.net"
    return s


def find_lead_by_whatsapp_chat(
    supabase: SupabaseClient,
    *,
    inbox_id: str,
    tenant_id: str,
    whatsapp_chat_id: str,
) -> Optional[dict[str, Any]]:
    """Mesma resolução que o webhook n8n — lead por inbox + chat, fallback tenant + chat."""
    chat = (whatsapp_chat_id or "").strip()
    if not chat:
        return None
    try:
        r = (
            supabase.table("leads")
            .select("id, stage, client_id, tenant_id, contact_name, inbox_id, whatsapp_chat_id")
            .eq("inbox_id", inbox_id)
            .eq("whatsapp_chat_id", chat)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]
    except Exception:
        pass
    try:
        r2 = (
            supabase.table("leads")
            .select("id, stage, client_id, tenant_id, contact_name, inbox_id, whatsapp_chat_id")
            .eq("tenant_id", tenant_id)
            .eq("whatsapp_chat_id", chat)
            .limit(1)
            .execute()
        )
        if r2.data:
            return r2.data[0]
    except Exception:
        pass
    return None


def route_hint_from_stage(stage_name: str | None) -> str:
    """
    Valor estável para Switch no n8n (sem Redis).
    Alinhado aos nomes usados em POST /api/n8n/webhook (INTENT_TO_STAGE).
    """
    s = (stage_name or "").strip().lower()
    if s == "b2b":
        return "b2b"
    if s == "b2c":
        return "b2c"
    if s == "quero vender":
        return "revenda"
    if s == "pedido feito":
        return "pedido_feito"
    if s == "pagto confirmado":
        return "pagto_confirmado"
    if s == "finalizado":
        return "finalizado"
    return "other"


_BR_TZ = ZoneInfo("America/Sao_Paulo")


def format_brl_pt(value: Any) -> str:
    """Valor numérico → texto tipo R$ 1.234,56 (pt-BR)."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        d = Decimal("0")
    neg = d < 0
    d = abs(d).quantize(Decimal("0.01"))
    s = f"{d:.2f}"
    int_s, _, dec_s = s.partition(".")
    rev = int_s[::-1]
    parts = [rev[i : i + 3] for i in range(0, len(rev), 3)]
    body = ".".join(p[::-1] for p in reversed(parts))
    out = f"R$ {body},{dec_s}"
    return f"- {out}" if neg else out


def _created_at_to_br_date(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        s = str(value).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return "—"
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BR_TZ).strftime("%d/%m/%Y")


def format_last_order_client_message(order: dict[str, Any]) -> str:
    """
    Texto curto para WhatsApp (n8n: campo message_last).
    Usa product_summary, total e created_at (fuso America/Sao_Paulo).
    """
    summary = str(order.get("product_summary") or "").strip() or "Itens do pedido"
    total_txt = format_brl_pt(order.get("total"))
    date_txt = _created_at_to_br_date(order.get("created_at"))
    return (
        f"Seu último pedido foi:\n"
        f"{summary}\n"
        f"Total {total_txt}\n"
        f"Data: {date_txt}\n\n"
        f"Gostaria de repetir este pedido ou adicionar um novo?"
    )


def build_client_tool_payload(row: dict[str, Any]) -> dict[str, Any]:
    cnpj = row.get("cnpj")
    cnpj_d = digits_only(str(cnpj)) if cnpj else ""
    return {
        "found": True,
        "client_id": str(row["id"]),
        "person_type": row.get("person_type"),
        "display_name": row.get("display_name"),
        "contact_name": row.get("contact_name"),
        "cnpj": cnpj_d or None,
        "cnpj_formatted": format_cnpj_display(cnpj_d) if cnpj_d else None,
        "cpf": row.get("cpf"),
        "phones": row.get("phones") if isinstance(row.get("phones"), list) else [],
    }


def build_last_order_tool_payload(order: dict[str, Any] | None) -> dict[str, Any]:
    if not order:
        return {
            "has_previous_order": False,
            "order": None,
            "message": "Nenhum pedido anterior encontrado para este cadastro.",
            "message_last": (
                "Não encontramos um pedido anterior para este cadastro. "
                "Quer começar um pedido novo?"
            ),
        }
    order_out: dict[str, Any] = {}
    for key, raw in order.items():
        if key == "product_summary":
            order_out[key] = str(raw or "").strip()
        else:
            order_out[key] = _json_safe_for_n8n(raw)
    if order_out.get("id") is not None:
        order_out["id"] = str(order_out["id"])
    return {
        "has_previous_order": True,
        "order": order_out,
        "message": "Use product_summary e products_json para recapitular o pedido ao lojista.",
        "message_last": format_last_order_client_message(order),
    }
