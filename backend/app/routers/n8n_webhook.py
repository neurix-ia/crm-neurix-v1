"""
N8n Unified Webhook Router — POST /api/n8n/webhook
Routes by intent: perfil_b2c, perfil_b2b, perfil_revenda, cart_update, pedido, pagto_confirmado.
Auth: API key via X-CRM-API-Key header (no JWT).
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client as SupabaseClient

from app.dependencies import get_supabase, verify_n8n_api_key
from app.models.n8n_webhook import (
    N8nWebhookPayload,
    N8nWebhookResponse,
    OrderItem,
    build_products_json,
    generate_client_name,
    generate_product_summary,
    merge_notes_with_orphan_catalog_block,
    parse_brl_to_float,
    partition_products_by_match,
)
from app.observability import get_logger
from app.services.lead_stock import apply_stock_delta, compute_stock_delta, invert_delta
from app.services.lead_board import (
    fetch_stage_automation_for_source_stage,
    apply_destination_mirror,
    insert_lead_activity,
    upsert_pipeline_position,
)
from app.services.webhook_lead_context import (
    find_inbox_by_instance_token,
    get_first_stage_slug_for_funnel,
    resolve_or_create_crm_client,
)
from app.services.phone_normalize import digits_only, format_brazil_phone_display

router = APIRouter()
logger = get_logger("n8n_webhook")

INTENT_TO_STAGE = {
    "perfil_b2c": "B2C",
    "perfil_b2b": "B2B",
    "perfil_revenda": "Quero Vender",
    "pedido": "Pedido Feito",
    "pagto_confirmado": "Pagto Confirmado",
}

PROFILE_ALLOWED_CATEGORY_SLUGS = {
    "PF": ("cliente-final",),
    "PJ": ("lojista-b2b",),
}


def _resolve_inbox(supabase: SupabaseClient, instance_token: str) -> dict:
    inbox = find_inbox_by_instance_token(supabase, instance_token)
    if not inbox:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox não encontrada para o instance_token informado.",
        )
    return inbox


def _resolve_lead(
    supabase: SupabaseClient,
    *,
    inbox_id: str,
    tenant_id: str,
    whatsapp_chat_id: str,
) -> dict:
    chat = whatsapp_chat_id.strip()

    try:
        r = (
            supabase.table("leads")
            .select("*")
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
            .select("*")
            .eq("tenant_id", tenant_id)
            .eq("whatsapp_chat_id", chat)
            .limit(1)
            .execute()
        )
        if r2.data:
            return r2.data[0]
    except Exception:
        pass

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Lead não encontrado para este chat. Verifique se o webhook Uazapi já processou a primeira mensagem.",
    )


def _format_lead_phone(phone_raw: str | None, whatsapp_chat_id: str) -> str | None:
    sender_phone = (phone_raw or "").strip() or whatsapp_chat_id.replace("@s.whatsapp.net", "").replace("@g.us", "")
    if not sender_phone:
        return None
    p = digits_only(sender_phone)
    if len(p) == 12 and p.startswith("55") and len(p) > 4 and p[4] in "6789":
        p = p[:4] + "9" + p[4:]
    return format_brazil_phone_display(p) or p


def _insert_lead_row(supabase: SupabaseClient, payload: dict):
    """Insert lead; retry sem `phone` se o schema ainda não tiver a coluna (staging antigo)."""
    try:
        return supabase.table("leads").insert(payload).execute()
    except Exception as exc:
        err = str(exc).lower()
        if "phone" in payload and ("phone" in err or "pgrst204" in err):
            slim = {k: v for k, v in payload.items() if k != "phone"}
            return supabase.table("leads").insert(slim).execute()
        raise


def _create_lead_for_n8n(
    supabase: SupabaseClient,
    *,
    inbox: dict,
    whatsapp_chat_id: str,
    lead_name: str | None,
    phone: str | None,
) -> dict:
    """Cria lead no funil da caixa quando o webhook Uazapi→CRM não rodou (fluxo n8n-first)."""
    tenant_id = str(inbox["tenant_id"])
    funnel_id = str(inbox["funnel_id"])
    inbox_id = str(inbox["id"])
    chat = whatsapp_chat_id.strip()

    stage_slug = get_first_stage_slug_for_funnel(
        supabase,
        tenant_id=tenant_id,
        funnel_id=funnel_id,
    )
    formatted_phone = _format_lead_phone(phone, chat)
    sender_phone_raw = (phone or "").strip() or chat.replace("@s.whatsapp.net", "").replace("@g.us", "")
    display_name = (lead_name or "").strip() or sender_phone_raw or "Desconhecido"

    client_id: str | None = None
    if sender_phone_raw:
        client_id = resolve_or_create_crm_client(
            supabase,
            tenant_id=tenant_id,
            sender_phone_raw=sender_phone_raw,
            sender_name=lead_name or "",
        )

    new_lead: dict = {
        "tenant_id": tenant_id,
        "inbox_id": inbox_id,
        "funnel_id": funnel_id,
        "whatsapp_chat_id": chat,
        "contact_name": display_name[:500],
        "company_name": display_name[:500],
        "stage": stage_slug,
        "value": 0,
    }
    if formatted_phone:
        new_lead["phone"] = formatted_phone
    if client_id:
        new_lead["client_id"] = client_id

    try:
        ins = _insert_lead_row(supabase, new_lead)
        if ins.data:
            logger.info(
                "n8n_lead_auto_created",
                extra={"lead_id": ins.data[0]["id"], "inbox_id": inbox_id, "chat_id": chat},
            )
            return ins.data[0]
    except Exception as exc:
        logger.exception("n8n_lead_auto_create_failed", extra={"inbox_id": inbox_id, "chat_id": chat})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao criar lead: {exc}",
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Falha ao criar lead (resposta vazia do banco).",
    )


def _resolve_or_create_lead(
    supabase: SupabaseClient,
    *,
    inbox: dict,
    whatsapp_chat_id: str,
    lead_name: str | None,
    phone: str | None,
    create_if_missing: bool,
) -> tuple[dict, bool]:
    tenant_id = str(inbox["tenant_id"])
    inbox_id = str(inbox["id"])
    try:
        return (
            _resolve_lead(
                supabase,
                inbox_id=inbox_id,
                tenant_id=tenant_id,
                whatsapp_chat_id=whatsapp_chat_id,
            ),
            False,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND or not create_if_missing:
            raise
    return (
        _create_lead_for_n8n(
            supabase,
            inbox=inbox,
            whatsapp_chat_id=whatsapp_chat_id,
            lead_name=lead_name,
            phone=phone,
        ),
        True,
    )


def _resolve_stage_case_insensitive(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    funnel_id: str,
    target_stage_name: str,
) -> dict | None:
    try:
        res = (
            supabase.table("pipeline_stages")
            .select("id, name, order_position")
            .eq("tenant_id", tenant_id)
            .eq("funnel_id", funnel_id)
            .order("order_position")
            .execute()
        )
        target_lower = target_stage_name.strip().lower()
        for row in res.data or []:
            if str(row.get("name", "")).strip().lower() == target_lower:
                return row
    except Exception:
        pass
    return None


def _move_lead_to_stage(
    supabase: SupabaseClient,
    *,
    lead_row: dict,
    stage_row: dict,
    funnel_id: str,
    tenant_id: str,
    intent: str,
    button_id: str | None,
) -> str:
    """Move lead to the resolved stage. Returns the canonical stage name."""
    canonical_name = str(stage_row["name"])
    stage_id = str(stage_row["id"])
    lead_id = str(lead_row["id"])

    supabase.table("leads").update({"stage": canonical_name}).eq("id", lead_id).execute()

    upsert_pipeline_position(
        supabase,
        lead_id=lead_id,
        funnel_id=funnel_id,
        stage_id=stage_id,
        board_owner_user_id=tenant_id,
    )

    prev_stage_name = str(lead_row.get("stage") or "").strip().lower()
    from_stage_id: str | None = None
    try:
        stages_res = (
            supabase.table("pipeline_stages")
            .select("id, name")
            .eq("tenant_id", tenant_id)
            .eq("funnel_id", funnel_id)
            .execute()
        )
        for s in stages_res.data or []:
            if str(s.get("name", "")).strip().lower() == prev_stage_name:
                from_stage_id = str(s["id"])
                break
    except Exception:
        pass

    insert_lead_activity(
        supabase,
        lead_id=lead_id,
        event_type="stage_move",
        actor_user_id=tenant_id,
        from_stage_id=from_stage_id,
        to_stage_id=stage_id,
        metadata={"source": "n8n", "intent": intent, "button_id": button_id, "funnel_id": funnel_id},
    )

    auto = fetch_stage_automation_for_source_stage(
        supabase, source_funnel_id=funnel_id, source_stage_id=stage_id,
    )
    if auto:
        apply_destination_mirror(supabase, lead_id=lead_id, automation=auto)

    return canonical_name


def _fetch_tenant_products(supabase: SupabaseClient, tenant_id: str) -> list[dict]:
    """Lista produtos do tenant para match no webhook (inclui inativos por nome).

    Pedidos retroativos do agente podem referenciar SKUs desativados; o match
    por nome ainda resolve para o registro correto sem expor listagem pública.
    """
    try:
        res = (
            supabase.table("products")
            .select("id, name, price, category, category_id, tenant_id, is_active")
            .eq("tenant_id", tenant_id)
            .execute()
        )
        return res.data or []
    except Exception:
        return []


def _normalize_person_type(person_type: str | None) -> str | None:
    normalized = str(person_type or "").strip().upper()
    return normalized if normalized in PROFILE_ALLOWED_CATEGORY_SLUGS else None


def _resolve_profile_from_stage(stage_name: str | None) -> str | None:
    normalized_stage = str(stage_name or "").strip().lower()
    if normalized_stage == "b2b":
        return "PJ"
    if normalized_stage == "b2c":
        return "PF"
    return None


def _fetch_client_person_type(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    client_id: str | None,
) -> str | None:
    if not client_id:
        return None

    try:
        response = (
            supabase.table("crm_clients")
            .select("person_type")
            .eq("tenant_id", tenant_id)
            .eq("id", client_id)
            .execute()
        )
    except Exception:
        return None

    row = (response.data or [None])[0]
    if not row:
        return None
    return _normalize_person_type(row.get("person_type"))


def _resolve_effective_order_profile(
    supabase: SupabaseClient,
    *,
    lead_row: dict,
    tenant_id: str,
) -> str:
    client_person_type = _fetch_client_person_type(
        supabase,
        tenant_id=tenant_id,
        client_id=str(lead_row.get("client_id") or "").strip() or None,
    )
    if client_person_type:
        return client_person_type

    stage_person_type = _resolve_profile_from_stage(lead_row.get("stage"))
    if stage_person_type:
        return stage_person_type

    return "PF"


def _fetch_allowed_category_ids(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    allowed_category_slugs: tuple[str, ...],
) -> tuple[set[str], bool]:
    try:
        response = (
            supabase.table("product_categories")
            .select("id, slug")
            .eq("tenant_id", tenant_id)
            .in_("slug", list(allowed_category_slugs))
            .execute()
        )
    except Exception:
        return set(), False

    category_ids = {
        str(row["id"])
        for row in (response.data or [])
        if row.get("id")
    }
    return category_ids, True


def _filter_products_by_allowed_categories(
    products_db: list[dict],
    *,
    allowed_category_ids: set[str],
    allowed_category_slugs: tuple[str, ...],
    category_lookup_available: bool,
) -> list[dict]:
    allowed_slugs = {slug.strip().lower() for slug in allowed_category_slugs}
    filtered_products: list[dict] = []

    for product in products_db:
        product_category_id = str(product.get("category_id") or "").strip()
        product_category_slug = str(product.get("category") or "").strip().lower()

        if category_lookup_available:
            if product_category_id and product_category_id in allowed_category_ids:
                filtered_products.append(product)
            continue

        if product_category_slug in allowed_slugs:
            filtered_products.append(product)

    return filtered_products


def _build_unmatched_order_line(item: OrderItem) -> dict:
    line_total = parse_brl_to_float(item.total)
    unit_price = round(line_total / max(item.quantity, 1), 2) if line_total > 0 else 0.0
    if line_total <= 0:
        line_total = round(unit_price * item.quantity, 2)

    return {
        "id": "",
        "product_id": item.product_id or "",
        "name": item.product,
        "price": unit_price,
        "quantity": item.quantity,
        "qty": item.quantity,
        "category_id": None,
        "line_subtotal": round(unit_price * item.quantity, 2),
        "line_discount": 0.0,
        "line_total": line_total,
        "applied_promotion_name": None,
        "unmatched": True,
    }


def _separate_disallowed_product_id_items(
    items: list[OrderItem],
    *,
    all_products_by_id: dict[str, dict],
    allowed_product_ids: set[str],
    effective_profile: str,
) -> tuple[list[OrderItem], list[dict], list[str]]:
    items_for_catalog_match: list[OrderItem] = []
    forced_unmatched_lines: list[dict] = []
    warnings: list[str] = []

    for item in items:
        product_id = str(item.product_id or "").strip()
        if not product_id:
            items_for_catalog_match.append(item)
            continue

        catalog_product = all_products_by_id.get(product_id)
        if catalog_product and product_id not in allowed_product_ids:
            warnings.append(
                f"Produto '{item.product}' (product_id '{product_id}') não pertence ao catálogo "
                f"permitido para o perfil {effective_profile} e foi tratado como item sem match."
            )
            forced_unmatched_lines.append(_build_unmatched_order_line(item))
            continue

        items_for_catalog_match.append(item)

    return items_for_catalog_match, forced_unmatched_lines, warnings


def _update_products_json(
    supabase: SupabaseClient,
    *,
    lead_row: dict,
    payload: N8nWebhookPayload,
    tenant_id: str,
) -> tuple[list[dict], list[str]]:
    """Process order_summary → update leads.products_json, value e stock_reserved_json.
    Aplica a mesma reserva de estoque que PATCH /leads/{id}. No-op se order_summary vazio."""
    if not payload.order_summary:
        return lead_row.get("products_json") or [], []

    effective_profile = _resolve_effective_order_profile(
        supabase,
        lead_row=lead_row,
        tenant_id=tenant_id,
    )
    allowed_category_slugs = PROFILE_ALLOWED_CATEGORY_SLUGS[effective_profile]

    all_products_db = _fetch_tenant_products(supabase, tenant_id)
    allowed_category_ids, category_lookup_available = _fetch_allowed_category_ids(
        supabase,
        tenant_id=tenant_id,
        allowed_category_slugs=allowed_category_slugs,
    )
    products_db = _filter_products_by_allowed_categories(
        all_products_db,
        allowed_category_ids=allowed_category_ids,
        allowed_category_slugs=allowed_category_slugs,
        category_lookup_available=category_lookup_available,
    )
    all_products_by_id = {
        str(product.get("id") or ""): product
        for product in all_products_db
        if product.get("id")
    }
    allowed_product_ids = {
        str(product.get("id") or "")
        for product in products_db
        if product.get("id")
    }
    matchable_items, forced_unmatched_lines, forced_warnings = _separate_disallowed_product_id_items(
        payload.order_summary,
        all_products_by_id=all_products_by_id,
        allowed_product_ids=allowed_product_ids,
        effective_profile=effective_profile,
    )

    raw_lines, warnings = build_products_json(matchable_items, products_db, tenant_id)
    warnings.extend(forced_warnings)
    raw_lines.extend(forced_unmatched_lines)
    matched_lines, unmatched_lines = partition_products_by_match(raw_lines)
    products_json = matched_lines

    total_value = round(
        sum(float(line.get("line_total") or 0) for line in products_json),
        2,
    )

    lead_id = str(lead_row["id"])
    current_lead = (
        supabase.table("leads")
        .select("id, tenant_id, products_json, stock_reserved_json, notes")
        .eq("id", lead_id)
        .single()
        .execute()
    )
    if not current_lead.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado.",
        )
    row = current_lead.data
    lead_tenant_id = str(row["tenant_id"])
    if lead_tenant_id != str(tenant_id):
        logger.warning(
            "n8n_update_products_tenant_mismatch",
            extra={"lead_id": lead_id, "inbox_tenant": tenant_id, "lead_tenant": lead_tenant_id},
        )

    previous_reserved = row.get("stock_reserved_json") or row.get("products_json") or []
    next_reserved, applied_delta = compute_stock_delta(previous_reserved, products_json)
    rollback_needed = bool(applied_delta)

    apply_stock_delta(supabase=supabase, tenant_id=lead_tenant_id, delta=applied_delta)

    existing_notes = str(row.get("notes") or "")
    new_notes, notes_truncated = merge_notes_with_orphan_catalog_block(
        existing_notes,
        unmatched_lines,
    )
    if notes_truncated:
        logger.warning(
            "n8n_orphan_catalog_notes_truncated",
            extra={"lead_id": lead_id, "notes_len": len(new_notes)},
        )

    update_data: dict = {
        "products_json": products_json,
        "stock_reserved_json": next_reserved,
        "value": total_value,
    }
    if (new_notes or "").strip() != existing_notes.strip():
        update_data["notes"] = new_notes

    try:
        response = (
            supabase.table("leads")
            .update(update_data)
            .eq("id", lead_id)
            .eq("tenant_id", lead_tenant_id)
            .execute()
        )
    except Exception:
        if rollback_needed and applied_delta:
            try:
                apply_stock_delta(
                    supabase=supabase,
                    tenant_id=lead_tenant_id,
                    delta=invert_delta(applied_delta),
                )
            except Exception:
                logger.exception(
                    "n8n_webhook_stock_rollback_failed",
                    extra={"tenant_id": lead_tenant_id, "lead_id": lead_id},
                )
        raise

    if not response.data:
        if rollback_needed and applied_delta:
            try:
                apply_stock_delta(
                    supabase=supabase,
                    tenant_id=lead_tenant_id,
                    delta=invert_delta(applied_delta),
                )
            except Exception:
                logger.exception(
                    "n8n_webhook_stock_rollback_failed",
                    extra={"tenant_id": lead_tenant_id, "lead_id": lead_id},
                )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead não encontrado ao atualizar produtos.",
        )

    return products_json, warnings


def _append_note_timeline(
    supabase: SupabaseClient,
    *,
    lead_row: dict,
    payload: N8nWebhookPayload,
) -> None:
    if not payload.note_timeline:
        return
    existing_notes = str(lead_row.get("notes") or "")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    new_entries = "\n".join(
        f"[{e.timestamp or ts}] {e.content}" for e in payload.note_timeline
    )
    separator = "\n---\n" if existing_notes.strip() else ""
    updated = f"{existing_notes}{separator}{new_entries}"
    try:
        supabase.table("leads").update({"notes": updated[:4000]}).eq("id", lead_row["id"]).execute()
    except Exception:
        logger.warning("n8n_note_timeline_append_failed", extra={"lead_id": lead_row["id"]})


def _link_client_to_lead(
    supabase: SupabaseClient,
    *,
    lead_row: dict,
    client_id: str,
) -> None:
    if lead_row.get("client_id"):
        return
    try:
        supabase.table("leads").update({"client_id": client_id}).eq("id", lead_row["id"]).execute()
    except Exception:
        logger.warning("n8n_client_link_failed", extra={"lead_id": lead_row["id"], "client_id": client_id})


def _confirm_order_payment(
    supabase: SupabaseClient,
    *,
    tenant_id: str,
    lead_id: str,
    order_id: str | None,
) -> tuple[str | None, bool]:
    """Marca pedido como pago. Retorna (order_id, já_estava_pago)."""
    order_row: dict | None = None

    if order_id:
        try:
            r = (
                supabase.table("orders")
                .select("id, lead_id, tenant_id, payment_status")
                .eq("id", order_id)
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            order_row = (r.data or [None])[0]
            if order_row and str(order_row.get("lead_id") or "") not in ("", lead_id):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="order_id não pertence ao lead informado.",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("n8n_order_lookup_failed", extra={"order_id": order_id, "error": str(exc)})

    if not order_row:
        try:
            r = (
                supabase.table("orders")
                .select("id, lead_id, tenant_id, payment_status")
                .eq("lead_id", lead_id)
                .eq("tenant_id", tenant_id)
                .eq("payment_status", "pendente")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            order_row = (r.data or [None])[0]
        except Exception as exc:
            logger.warning("n8n_pending_order_lookup_failed", extra={"lead_id": lead_id, "error": str(exc)})

    if not order_row:
        return None, False

    resolved_order_id = str(order_row["id"])
    if str(order_row.get("payment_status") or "").lower() == "pago":
        return resolved_order_id, True

    try:
        supabase.table("orders").update({"payment_status": "pago"}).eq("id", resolved_order_id).execute()
    except Exception as exc:
        logger.exception("n8n_order_payment_confirm_failed", extra={"order_id": resolved_order_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao confirmar pagamento do pedido: {exc}",
        ) from exc

    return resolved_order_id, False


@router.post("/webhook", response_model=N8nWebhookResponse)
async def n8n_webhook(
    payload: N8nWebhookPayload,
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
):
    inbox = _resolve_inbox(supabase, payload.instance_token)
    tenant_id = str(inbox["tenant_id"])
    funnel_id = str(inbox["funnel_id"])
    inbox_id = str(inbox["id"])

    profile_intents = ("perfil_b2c", "perfil_b2b", "perfil_revenda")
    lead_row, lead_created = _resolve_or_create_lead(
        supabase,
        inbox=inbox,
        whatsapp_chat_id=payload.whatsapp_chat_id,
        lead_name=payload.lead_name,
        phone=payload.phone,
        create_if_missing=payload.intent in profile_intents,
    )
    lead_id = str(lead_row["id"])
    warnings: list[str] = []
    if lead_created:
        warnings.append(
            "Lead criado automaticamente pelo n8n (webhook Uazapi→CRM não havia processado este contato)."
        )

    _append_note_timeline(supabase, lead_row=lead_row, payload=payload)

    # ── perfil_b2c / perfil_b2b / perfil_revenda ──
    if payload.intent in ("perfil_b2c", "perfil_b2b", "perfil_revenda"):
        target_stage_name = INTENT_TO_STAGE[payload.intent]
        stage_row = _resolve_stage_case_insensitive(
            supabase, tenant_id=tenant_id, funnel_id=funnel_id, target_stage_name=target_stage_name,
        )
        if not stage_row:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Etapa '{target_stage_name}' não encontrada no funil. Crie essa etapa no Kanban.",
            )

        client_id: str | None = None
        phone_raw = payload.phone or ""
        phone_digits = digits_only(phone_raw)
        if phone_digits:
            client_id = resolve_or_create_crm_client(
                supabase,
                tenant_id=tenant_id,
                sender_phone_raw=phone_raw,
                sender_name=payload.lead_name or "",
            )
            if client_id:
                _link_client_to_lead(supabase, lead_row=lead_row, client_id=client_id)

        if payload.lead_name and not lead_row.get("contact_name"):
            try:
                supabase.table("leads").update({"contact_name": payload.lead_name}).eq("id", lead_id).execute()
            except Exception:
                pass

        canonical = _move_lead_to_stage(
            supabase,
            lead_row=lead_row,
            stage_row=stage_row,
            funnel_id=funnel_id,
            tenant_id=tenant_id,
            intent=payload.intent,
            button_id=payload.button_id,
        )

        return N8nWebhookResponse(
            status="ok",
            lead_id=lead_id,
            client_id=client_id,
            stage=canonical,
            message=f"Lead movido para '{canonical}'. Client {'vinculado' if client_id else 'não vinculado (sem telefone)'}.",
            warnings=warnings,
        )

    # ── cart_update ──
    if payload.intent == "cart_update":
        products_json, w = _update_products_json(
            supabase, lead_row=lead_row, payload=payload, tenant_id=tenant_id,
        )
        warnings.extend(w)

        return N8nWebhookResponse(
            status="ok",
            lead_id=lead_id,
            stage=lead_row.get("stage"),
            message=f"products_json atualizado com {len(products_json)} itens." if payload.order_summary else "Nenhuma alteração (order_summary vazio).",
            warnings=warnings,
        )

    # ── pedido ──
    if payload.intent == "pedido":
        products_json, w = _update_products_json(
            supabase, lead_row=lead_row, payload=payload, tenant_id=tenant_id,
        )
        warnings.extend(w)

        client_id = str(lead_row.get("client_id") or "")
        client_row: dict | None = None
        if client_id:
            try:
                cr = supabase.table("crm_clients").select("id, display_name").eq("id", client_id).limit(1).execute()
                client_row = (cr.data or [None])[0]
            except Exception:
                pass
        elif payload.phone:
            resolved_cid = resolve_or_create_crm_client(
                supabase,
                tenant_id=tenant_id,
                sender_phone_raw=payload.phone,
                sender_name=payload.lead_name or "",
            )
            if resolved_cid:
                client_id = resolved_cid
                _link_client_to_lead(supabase, lead_row=lead_row, client_id=resolved_cid)
                try:
                    cr = supabase.table("crm_clients").select("id, display_name").eq("id", resolved_cid).limit(1).execute()
                    client_row = (cr.data or [None])[0]
                except Exception:
                    pass

        client_name = generate_client_name(lead_row, payload, client_row)
        product_summary = generate_product_summary(payload.order_summary or [])
        total = round(
            sum(float(line.get("line_total") or 0) for line in products_json),
            2,
        )
        if total <= 0:
            total = parse_brl_to_float(payload.total_value)

        # Idempotency: check for recent pending order on same lead
        order_id: str | None = None
        existing_order: dict | None = None
        try:
            eo = (
                supabase.table("orders")
                .select("id, created_at")
                .eq("lead_id", lead_id)
                .eq("tenant_id", tenant_id)
                .eq("payment_status", "pendente")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if eo.data:
                created = eo.data[0].get("created_at", "")
                if created:
                    created_str = str(created).replace("Z", "+00:00")
                    created_dt = datetime.fromisoformat(created_str)
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    age_minutes = (datetime.now(timezone.utc) - created_dt).total_seconds() / 60
                    if age_minutes < 60:
                        existing_order = eo.data[0]
        except Exception:
            pass

        order_payload = {
            "tenant_id": tenant_id,
            "lead_id": lead_id,
            "client_id": client_id or None,
            "client_name": client_name,
            "product_summary": product_summary,
            "products_json": products_json,
            "total": total,
            "subtotal": total,
            "discount_total": 0.0,
            "payment_status": "pendente",
            "payment_method": payload.payment_method,
            "stage": "Novo Pedido",
        }

        try:
            if existing_order:
                upd = (
                    supabase.table("orders")
                    .update(order_payload)
                    .eq("id", existing_order["id"])
                    .execute()
                )
                order_id = existing_order["id"]
            else:
                ins = supabase.table("orders").insert(order_payload).execute()
                if ins.data:
                    order_id = str(ins.data[0]["id"])
        except Exception as exc:
            logger.exception("n8n_order_create_failed", extra={"lead_id": lead_id, "error": str(exc)})
            warnings.append(f"Erro ao criar/atualizar order: {exc}")

        # Move lead to "Pedido Feito"
        target_stage_name = INTENT_TO_STAGE["pedido"]
        stage_row = _resolve_stage_case_insensitive(
            supabase, tenant_id=tenant_id, funnel_id=funnel_id, target_stage_name=target_stage_name,
        )
        canonical: str | None = None
        if stage_row:
            canonical = _move_lead_to_stage(
                supabase,
                lead_row=lead_row,
                stage_row=stage_row,
                funnel_id=funnel_id,
                tenant_id=tenant_id,
                intent=payload.intent,
                button_id=payload.button_id,
            )
        else:
            warnings.append(f"Etapa '{target_stage_name}' não encontrada no funil — lead não foi movido.")

        return N8nWebhookResponse(
            status="ok",
            lead_id=lead_id,
            client_id=client_id or None,
            stage=canonical,
            order_id=order_id,
            message=f"Pedido {'atualizado' if existing_order else 'criado'}. Lead movido para '{canonical or 'N/A'}'.",
            warnings=warnings,
        )

    # ── pagto_confirmado ──
    if payload.intent == "pagto_confirmado":
        order_id, already_paid = _confirm_order_payment(
            supabase,
            tenant_id=tenant_id,
            lead_id=lead_id,
            order_id=payload.order_id,
        )
        if not order_id:
            warnings.append("Nenhum pedido pendente encontrado para este lead — apenas a etapa será atualizada.")

        target_stage_name = INTENT_TO_STAGE["pagto_confirmado"]
        stage_row = _resolve_stage_case_insensitive(
            supabase, tenant_id=tenant_id, funnel_id=funnel_id, target_stage_name=target_stage_name,
        )
        canonical: str | None = None
        if stage_row:
            canonical = _move_lead_to_stage(
                supabase,
                lead_row=lead_row,
                stage_row=stage_row,
                funnel_id=funnel_id,
                tenant_id=tenant_id,
                intent=payload.intent,
                button_id=payload.button_id,
            )
        else:
            warnings.append(f"Etapa '{target_stage_name}' não encontrada no funil — lead não foi movido.")

        paid_msg = "já estava pago" if already_paid else "marcado como pago"
        return N8nWebhookResponse(
            status="ok",
            lead_id=lead_id,
            client_id=str(lead_row.get("client_id") or "") or None,
            stage=canonical,
            order_id=order_id,
            message=(
                f"Pagamento confirmado. Pedido {paid_msg if order_id else 'não localizado'}. "
                f"Lead movido para '{canonical or 'N/A'}'."
            ),
            warnings=warnings,
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Intent '{payload.intent}' não reconhecido.",
    )
