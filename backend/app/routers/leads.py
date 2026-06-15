"""
Leads Router — CRUD + Kanban Stage Management + Chat Mirror
Provides the data for the Funil de Vendas Kanban board and WhatsApp chat integration.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from supabase import Client as SupabaseClient
from typing import Optional
from pydantic import BaseModel, Field, ValidationError
from time import perf_counter
from datetime import datetime, timezone

from app.dependencies import get_supabase, get_current_user
from app.authz import EffectiveRole, get_effective_role, require_org_admin
from app.org_scope import funnel_ids_for_organization, list_funnels_for_organization
from app.models.lead import (
    LeadCreate,
    LeadUpdate,
    LeadMoveStage,
    LeadResponse,
    KanbanBoard,
    KanbanColumn,
    LeadPriority,
)
from app.models.chat_message import SendMessagePayload
from app.observability import get_logger, metrics
from app.services.uazapi_service import get_uazapi_service
from app.services.webhook_lead_context import get_uazapi_instance_token_for_tenant
from app.services.promotion_engine import apply_promotion_discount, round_money, select_best_promotion
from app.services.phone_normalize import digits_only as _digits_only
from app.services.lead_stock import (
    apply_stock_delta,
    compute_stock_delta,
    invert_delta,
    normalize_product_items,
)
from app.services.lead_phone_sync import fetch_display_phone_for_crm_client
from app.services.lead_board import (
    DESPACHADO_CANONICAL_CASEFOLD,
    DESPACHADO_TRUNCATED_PREFIX_MIN_LEN,
    apply_destination_mirror,
    build_pos_by_lead,
    fetch_stage_automation_for_source_stage,
    find_stage_row_by_casefold_name,
    insert_lead_activity,
    is_despachado_destination_name,
    merge_kanban_lead_rows,
    resolve_stage_name_for_board,
    upsert_pipeline_position,
)
from app.services.conversion_cohort import compute_inicial_cohort_snapshot
from app.services.lead_finalized_spawn import (
    fetch_pipeline_stages_for_funnel as _fetch_pipeline_stages_for_funnel,
    is_chat_mirror_closed_for_lead,
)
from app.org_scope import assert_funnel_assignable_to_org

router = APIRouter()
logger = get_logger("leads")


def _db_error_detail(exc: Exception) -> str:
    for attr in ("details", "message", "msg"):
        val = getattr(exc, attr, None)
        if isinstance(val, str) and val.strip():
            return val
    text = str(exc)
    return text or "Erro inesperado no banco."


def _is_missing_column_error(detail: str, column_name: str) -> bool:
    lowered = detail.lower()
    return "column" in lowered and column_name.lower() in lowered and ("does not exist" in lowered or "não existe" in lowered)


def _price_lead_products_with_promotions(
    *,
    supabase: SupabaseClient,
    tenant_id: str,
    products_json: list[dict] | None,
) -> tuple[float, list[dict]]:
    normalized_items = normalize_product_items(products_json)
    if not normalized_items:
        return 0.0, []

    product_ids = list({item["product_id"] for item in normalized_items})
    product_rows = (
        supabase.table("products")
        .select("id, name, price, category_id, is_active")
        .eq("tenant_id", tenant_id)
        .in_("id", product_ids)
        .execute()
    ).data or []
    products_map = {str(row["id"]): row for row in product_rows}
    missing_ids = [pid for pid in product_ids if pid not in products_map]
    if missing_ids:
        raise HTTPException(status_code=400, detail=f"Produtos não encontrados: {', '.join(missing_ids)}")

    subtotal = 0.0
    fallback_lines: list[dict] = []
    for item in normalized_items:
        product = products_map[item["product_id"]]
        quantity = int(item["quantity"])
        unit_price = float(product.get("price") or 0.0)
        line_subtotal = round_money(unit_price * quantity)
        subtotal += line_subtotal
        fallback_lines.append(
            {
                "id": str(product["id"]),
                "product_id": str(product["id"]),
                "name": product.get("name") or "",
                "price": unit_price,
                "quantity": quantity,
                "qty": quantity,
                "category_id": str(product.get("category_id")) if product.get("category_id") else None,
                "line_subtotal": line_subtotal,
                "line_discount": 0.0,
                "line_total": line_subtotal,
                "applied_promotion_name": None,
            }
        )
    subtotal = round_money(subtotal)

    # Compatibility safety: if promotions schema isn't available, keep subtotal.
    try:
        promotions_rows = (
            supabase.table("promotions")
            .select("id, name, discount_type, discount_value, category_id, starts_at, ends_at, priority, is_active, created_at")
            .eq("tenant_id", tenant_id)
            .execute()
        ).data or []
    except Exception:
        return subtotal, fallback_lines

    if not promotions_rows:
        return subtotal, fallback_lines

    promotion_ids = [row["id"] for row in promotions_rows]
    category_ids = list(
        {
            str(products_map[item["product_id"]].get("category_id"))
            for item in normalized_items
            if products_map[item["product_id"]].get("category_id")
        }
    )

    link_rows = []
    try:
        if promotion_ids and product_ids:
            link_rows = (
                supabase.table("promotion_products")
                .select("promotion_id, product_id")
                .eq("tenant_id", tenant_id)
                .in_("promotion_id", promotion_ids)
                .in_("product_id", product_ids)
                .execute()
            ).data or []
    except Exception:
        link_rows = []

    linked_by_product: dict[str, list[dict]] = {}
    linked_by_category: dict[str, list[dict]] = {}
    promo_by_id = {str(row["id"]): row for row in promotions_rows}
    for link in link_rows:
        promo = promo_by_id.get(str(link.get("promotion_id")))
        if not promo:
            continue
        enriched = {**promo, "link_type": "product", "product_id": str(link.get("product_id"))}
        linked_by_product.setdefault(str(link.get("product_id")), []).append(enriched)

    for promo in promotions_rows:
        category_id = promo.get("category_id")
        if category_id and str(category_id) in category_ids:
            linked_by_category.setdefault(str(category_id), []).append({**promo, "link_type": "category"})

    now_utc = datetime.now(timezone.utc)
    discount_total = 0.0
    resolved_lines: list[dict] = []
    for item in normalized_items:
        product = products_map[item["product_id"]]
        unit_price = float(product.get("price") or 0.0)
        quantity = int(item["quantity"])
        line_subtotal = round_money(unit_price * quantity)
        category_id = str(product.get("category_id")) if product.get("category_id") else None

        candidates = []
        candidates.extend(linked_by_product.get(str(product["id"]), []))
        if category_id:
            candidates.extend(linked_by_category.get(category_id, []))

        selected = select_best_promotion(
            product_id=str(product["id"]),
            category_id=category_id,
            candidate_promotions=candidates,
            now_utc=now_utc,
        )
        line_discount = round_money(apply_promotion_discount(line_subtotal, selected))
        line_total = round_money(max(line_subtotal - line_discount, 0.0))
        discount_total += line_discount
        resolved_lines.append(
            {
                "id": str(product["id"]),
                "product_id": str(product["id"]),
                "name": product.get("name") or "",
                "price": unit_price,
                "quantity": quantity,
                "qty": quantity,
                "category_id": category_id,
                "line_subtotal": line_subtotal,
                "line_discount": line_discount,
                "line_total": line_total,
                "applied_promotion_name": selected.get("name") if selected else None,
                "applied_promotion_id": str(selected.get("id")) if selected and selected.get("id") else None,
                "applied_discount_type": selected.get("discount_type") if selected else None,
                "applied_discount_value": float(selected.get("discount_value") or 0.0) if selected else None,
            }
        )

    discount_total = round_money(discount_total)
    total = round_money(max(subtotal - discount_total, 0.0))
    return total, resolved_lines


def _list_pipeline_stages_for_response(*, supabase: SupabaseClient, tenant_id: str) -> list[dict]:
    try:
        response = (
            supabase.table("pipeline_stages")
            .select("id, name, order_position, version, is_conversion")
            .eq("tenant_id", tenant_id)
            .order("order_position")
            .execute()
        )
        return response.data or []
    except Exception:
        response = (
            supabase.table("pipeline_stages")
            .select("id, name, order_position, version")
            .eq("tenant_id", tenant_id)
            .order("order_position")
            .execute()
        )
        return response.data or []


def _list_pipeline_stages_for_board_scope(
    *,
    supabase: SupabaseClient,
    data_tenant_id: str,
    funnel_id: str,
) -> list[dict]:
    return _fetch_pipeline_stages_for_funnel(
        supabase,
        data_tenant_id=data_tenant_id,
        funnel_id=funnel_id,
    )


class ReorderStageItem(BaseModel):
    id: str
    version: int = Field(..., ge=1)


class ReorderStagesPayload(BaseModel):
    items: list[ReorderStageItem] = Field(..., min_length=1)


class StageCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    is_conversion: bool = False


class StageRenamePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class StageDeletePayload(BaseModel):
    fallback_stage_id: str | None = None


class StageAutomationPayload(BaseModel):
    organization_id: str
    target_user_id: str
    target_funnel_id: str
    target_stage_id: str


class StageAutomationOut(BaseModel):
    id: str
    organization_id: str
    source_funnel_id: str
    source_stage_id: str
    target_user_id: str
    target_funnel_id: str
    target_stage_id: str
    created_at: datetime | None = None


class LeadActivityItem(BaseModel):
    id: str
    event_type: str
    from_stage_id: str | None = None
    to_stage_id: str | None = None
    actor_user_id: str | None = None
    occurred_at: datetime
    metadata: dict = Field(default_factory=dict)


def _default_funnel_id_for_tenant(supabase: SupabaseClient, tenant_id: str) -> str:
    """Preferência: funil nome 'Default'; senão o mais antigo por created_at."""
    res = (
        supabase.table("funnels")
        .select("id, name, created_at")
        .eq("tenant_id", tenant_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum funil cadastrado para este tenant. Crie um funil ou execute a migração de funil Default.",
        )
    for r in rows:
        if str(r.get("name") or "").strip().lower() == "default":
            return str(r["id"])
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return str(rows[0]["id"])


def _default_funnel_for_organization(supabase: SupabaseClient, org_id: str) -> tuple[str, str]:
    """Fallback do Kanban para admins da organização quando o tenant próprio não tem funis."""
    rows = list_funnels_for_organization(supabase, org_id)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nenhum funil cadastrado para esta organização. Crie um funil ou execute a migração de funil Default.",
        )
    for r in rows:
        if str(r.get("name") or "").strip().lower() == "default":
            return str(r["tenant_id"]), str(r["id"])
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    chosen = rows[0]
    return str(chosen["tenant_id"]), str(chosen["id"])


def _despachado_finalizado_sync_plan(
    supabase: SupabaseClient,
    *,
    data_tenant_id: str,
) -> tuple[str, list[dict], dict]:
    """
    Funil principal = mesmo critério do Kanban default (`_default_funnel_id_for_tenant`:
    preferência nome \"Default\", senão o funil mais antigo).
    """
    main_funnel_id = _default_funnel_id_for_tenant(supabase, data_tenant_id)
    main_stages = _fetch_pipeline_stages_for_funnel(
        supabase, data_tenant_id=data_tenant_id, funnel_id=main_funnel_id
    )
    fin = find_stage_row_by_casefold_name(main_stages, "finalizado")
    if not fin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                'O funil principal não possui uma etapa nomeada "Finalizado". '
                "Crie uma etapa com esse nome no funil principal (comparação sem diferenciar "
                "maiúsculas e ignorando espaços nas pontas) antes de mover cards para Despachado."
            ),
        )
    return main_funnel_id, main_stages, fin


def _pipeline_stage_id_for_lead_stage_text(stages: list[dict], stage_text: str) -> str | None:
    key = str(stage_text or "").strip().lower()
    if not key:
        return None
    for s in stages:
        if str(s.get("name", "")).strip().lower() == key:
            return str(s["id"])
    return None


def _sync_primary_lead_to_finalizado_after_despachado(
    supabase: SupabaseClient,
    *,
    lead_id: str,
    lead_row: dict,
    data_tenant_id: str,
    acting_user_id: str,
    main_funnel_id: str,
    main_stages: list[dict],
    finalized_row: dict,
) -> None:
    """Atualiza o lead primário no funil principal para a etapa Finalizado (Kanban admin)."""
    if str(lead_row.get("tenant_id") or "") != str(data_tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sincronização Despachado→Finalizado não aplicável a este lead.",
        )
    canonical_final = str(finalized_row["name"])
    final_id = str(finalized_row["id"])
    from_sid = _pipeline_stage_id_for_lead_stage_text(main_stages, str(lead_row.get("stage") or ""))

    upd = (
        supabase.table("leads")
        .update({"stage": canonical_final})
        .eq("id", lead_id)
        .eq("tenant_id", data_tenant_id)
        .execute()
    )
    if not upd.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
    upsert_pipeline_position(
        supabase,
        lead_id=lead_id,
        funnel_id=main_funnel_id,
        stage_id=final_id,
        board_owner_user_id=data_tenant_id,
    )
    insert_lead_activity(
        supabase,
        lead_id=lead_id,
        event_type="stage_move",
        actor_user_id=acting_user_id,
        from_stage_id=from_sid,
        to_stage_id=final_id,
        metadata={
            "funnel_id": main_funnel_id,
            "despachado_sync_to_finalizado": True,
        },
    )


def _resolve_kanban_scope(
    supabase: SupabaseClient,
    user_id: str,
    eff: EffectiveRole,
    funnel_id_query: Optional[str],
) -> tuple[str, str]:
    """Retorna (tenant_id dos dados no banco, funnel_id resolvido)."""
    uid = str(user_id)
    if eff.is_read_only:
        q_in = (funnel_id_query or "").strip()
        fid = eff.assigned_funnel_id
        if not fid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Funil não atribuído para usuário read_only.",
            )
        if q_in and q_in != str(fid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Não é permitido consultar outro funil (read_only).",
            )
        fres = (
            supabase.table("funnels")
            .select("id, tenant_id")
            .eq("id", fid)
            .limit(1)
            .execute()
        )
        rows = fres.data or []
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Funil atribuído inválido ou inexistente.",
            )
        data_tenant = str(rows[0]["tenant_id"])
        resolved = str(rows[0]["id"])
        if eff.org_member_organization_id:
            allowed = funnel_ids_for_organization(supabase, eff.org_member_organization_id)
            if resolved not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Funil não autorizado para a organização deste usuário.",
                )
        return data_tenant, resolved

    tenant_id = uid
    q = (funnel_id_query or "").strip()
    if q:
        fres = (
            supabase.table("funnels")
            .select("id, tenant_id")
            .eq("id", q)
            .limit(1)
            .execute()
        )
        rows = fres.data or []
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Funil não encontrado.")
        resolved_tenant_id = str(rows[0]["tenant_id"])
        if resolved_tenant_id == tenant_id:
            return tenant_id, str(rows[0]["id"])
        if eff.is_org_admin and eff.org_member_organization_id:
            allowed = funnel_ids_for_organization(supabase, eff.org_member_organization_id)
            if q in allowed:
                return resolved_tenant_id, str(rows[0]["id"])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Funil não pertence a este tenant.",
        )

    try:
        return tenant_id, _default_funnel_id_for_tenant(supabase, tenant_id)
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise
        if eff.is_org_admin and eff.org_member_organization_id:
            return _default_funnel_for_organization(supabase, eff.org_member_organization_id)
        raise


def _read_only_board_owner_ids_for_funnel(
    supabase: SupabaseClient,
    organization_id: str,
    funnel_id: str,
) -> list[str]:
    """Membros read_only com este funil atribuído (espelhos da automação usam esse board_owner)."""
    res = (
        supabase.table("organization_members")
        .select("user_id")
        .eq("organization_id", str(organization_id))
        .eq("role", "read_only")
        .eq("assigned_funnel_id", str(funnel_id))
        .execute()
    )
    return [str(r["user_id"]) for r in (res.data or []) if r.get("user_id")]


def _pipeline_board_owner_ids_for_scope(
    eff: EffectiveRole,
    acting_user_id: str,
    supabase: SupabaseClient,
    data_tenant_id: str,
    resolved_funnel_id: str,
) -> list[str]:
    """Mesma regra do GET /kanban: donos das positions neste funil para merge e movimentação."""
    if eff.is_read_only:
        return [str(acting_user_id)]
    if eff.is_org_admin and eff.org_member_organization_id:
        mirror_owners = _read_only_board_owner_ids_for_funnel(
            supabase, eff.org_member_organization_id, resolved_funnel_id
        )
        return mirror_owners if mirror_owners else [data_tenant_id]
    return [data_tenant_id]


def _fetch_leads_for_funnel(
    supabase: SupabaseClient,
    *,
    data_tenant_id: str,
    funnel_id: str,
) -> list[dict]:
    """Leads do funil; ignora filtros archived/deleted/funnel_id se coluna não existir no schema."""
    use_archived = True
    use_deleted = True
    use_funnel = True
    while True:
        try:
            query = (
                supabase.table("leads")
                .select("*")
                .eq("tenant_id", data_tenant_id)
            )
            if use_archived:
                query = query.eq("archived", False)
            if use_deleted:
                query = query.eq("deleted", False)
            if use_funnel:
                query = query.eq("funnel_id", funnel_id)
            response = query.order("created_at", desc=False).execute()
            return response.data or []
        except Exception as exc:
            detail = _db_error_detail(exc)
            if use_archived and _is_missing_column_error(detail, "archived"):
                use_archived = False
                continue
            if use_deleted and _is_missing_column_error(detail, "deleted"):
                use_deleted = False
                continue
            if use_funnel and _is_missing_column_error(detail, "funnel_id"):
                use_funnel = False
                continue
            raise


def _sanitize_optional_json_list_dicts(value) -> list[dict] | None:
    """Garante `list[dict]` para campos JSON do lead; evita 500 no Kanban com dados legados."""
    if value is None:
        return None
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, dict)]


def _sanitize_priority_for_response(raw) -> LeadPriority | None:
    if raw is None or raw == "":
        return None
    s = str(raw).strip().lower()
    if s in ("alta", "media", "baixa"):
        return LeadPriority(s)
    return None


def _sanitize_non_negative_float(raw, default: float = 0.0) -> float:
    try:
        v = float(raw)
        return v if v >= 0 else 0.0
    except Exception:
        return default


def _non_empty_field_str(raw, *, fallback: str) -> str:
    s = str(raw).strip() if raw is not None else ""
    return s if len(s) >= 1 else fallback


def _sanitize_notes_field(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw)
    return s[:1000] if len(s) > 1000 else s


def _coerce_datetime_required(raw, *, fallback: datetime) -> datetime:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            s = raw.strip().replace("Z", "+00:00")
            return datetime.fromisoformat(s)
        except Exception:
            return fallback
    return fallback


def _coerce_datetime_optional(raw) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            s = raw.strip().replace("Z", "+00:00")
            return datetime.fromisoformat(s)
        except Exception:
            return None
    return None


def _sanitize_lead_row_for_kanban(row: dict) -> dict:
    """Normaliza linha do Supabase antes de `LeadResponse` (prioridade, JSON, textos obrigatórios)."""
    now = datetime.now(timezone.utc)
    out = dict(row)
    out["id"] = str(out["id"]) if out.get("id") is not None else "unknown"
    out["tenant_id"] = str(out.get("tenant_id") or "")
    out["created_at"] = _coerce_datetime_required(out.get("created_at"), fallback=now)
    out["updated_at"] = _coerce_datetime_required(out.get("updated_at"), fallback=now)
    out["chat_cycle_closed_at"] = _coerce_datetime_optional(out.get("chat_cycle_closed_at"))
    for _fk in ("funnel_id", "inbox_id", "client_id"):
        if out.get(_fk) is not None:
            out[_fk] = str(out[_fk])
    out["company_name"] = _non_empty_field_str(out.get("company_name"), fallback="(sem empresa)")
    out["contact_name"] = _non_empty_field_str(out.get("contact_name"), fallback="(sem contato)")
    out["stage"] = str(out.get("stage") or "")
    out["priority"] = _sanitize_priority_for_response(out.get("priority"))
    out["value"] = _sanitize_non_negative_float(out.get("value"), 0.0)
    out["notes"] = _sanitize_notes_field(out.get("notes"))
    if "phone" in out and out["phone"] is not None:
        ps = str(out["phone"])
        out["phone"] = ps[:50] if len(ps) > 50 else ps
    if out.get("whatsapp_chat_id") is not None:
        out["whatsapp_chat_id"] = str(out["whatsapp_chat_id"])
    out["products_json"] = _sanitize_optional_json_list_dicts(out.get("products_json"))
    out["stock_reserved_json"] = _sanitize_optional_json_list_dicts(out.get("stock_reserved_json"))
    out["purchase_history_json"] = _sanitize_optional_json_list_dicts(out.get("purchase_history_json"))
    return out


def _fallback_lead_response_from_row(row: dict) -> LeadResponse:
    """Último recurso: card mínimo válido para não derrubar o board."""
    now = datetime.now(timezone.utc)
    lid = row.get("id")
    tid = row.get("tenant_id")
    wcid = row.get("whatsapp_chat_id")
    return LeadResponse(
        id=str(lid) if lid is not None else "unknown",
        tenant_id=str(tid) if tid is not None else "",
        created_at=_coerce_datetime_required(row.get("created_at"), fallback=now),
        updated_at=_coerce_datetime_required(row.get("updated_at"), fallback=now),
        funnel_id=str(row["funnel_id"]) if row.get("funnel_id") else None,
        inbox_id=str(row["inbox_id"]) if row.get("inbox_id") else None,
        client_id=str(row["client_id"]) if row.get("client_id") else None,
        chat_cycle_closed_at=_coerce_datetime_optional(row.get("chat_cycle_closed_at")),
        company_name="(dados inválidos — card sanitizado)",
        contact_name="(dados inválidos — card sanitizado)",
        phone=None,
        stage=str(row.get("stage") or ""),
        priority=None,
        value=0.0,
        notes=_sanitize_notes_field(row.get("notes")),
        whatsapp_chat_id=str(wcid) if wcid is not None else None,
        products_json=None,
        stock_reserved_json=None,
        purchase_history_json=None,
    )


def lead_row_to_response_safe(row: dict) -> LeadResponse:
    """
    Monta `LeadResponse` para o Kanban sem propagar ValidationError (dados legados / webhook).
    Prefere sanitizar e retornar o card; em falha residual, fallback mínimo + log.
    """
    lead_id = row.get("id")
    try:
        sanitized = _sanitize_lead_row_for_kanban(row)
        return LeadResponse(**sanitized)
    except ValidationError as exc:
        logger.warning(
            "kanban_lead_response_validation_failed",
            extra={"lead_id": str(lead_id) if lead_id is not None else None, "errors": exc.errors()},
        )
        try:
            return _fallback_lead_response_from_row(row)
        except ValidationError:
            logger.exception(
                "kanban_lead_response_fallback_failed",
                extra={"lead_id": str(lead_id) if lead_id is not None else None},
            )
            return LeadResponse(
                id=str(lead_id) if lead_id is not None else "unknown",
                tenant_id=str(row.get("tenant_id") or ""),
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                company_name="(erro ao carregar card)",
                contact_name="(erro ao carregar card)",
                stage="",
                value=0.0,
            )


@router.get("/kanban", response_model=KanbanBoard)
async def get_kanban_board(
    funnel_id: Optional[str] = Query(
        None,
        description="Funil do board; default = funil Default do tenant. read_only: deve ser o funil atribuído ou omitido; outro valor retorna 403.",
    ),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
):
    """Kanban por funil: colunas = estágios daquele funil; leads filtrados por funnel_id."""
    started = perf_counter()
    data_tenant_id, resolved_funnel_id = _resolve_kanban_scope(supabase, user.id, eff, funnel_id)

    stages_data = _fetch_pipeline_stages_for_funnel(
        supabase, data_tenant_id=data_tenant_id, funnel_id=resolved_funnel_id
    )

    if not stages_data:
        elapsed_ms = (perf_counter() - started) * 1000.0
        metrics.observe("kanban_board", elapsed_ms, ok=True)
        return KanbanBoard(
            columns=[],
            funnel_id=resolved_funnel_id,
            initial_stage_cohort_badge_count=None,
            initial_stage_id=None,
        )

    lead_rows_primary = _fetch_leads_for_funnel(supabase, data_tenant_id=data_tenant_id, funnel_id=resolved_funnel_id)
    pipeline_board_owner_ids = _pipeline_board_owner_ids_for_scope(
        eff, str(user.id), supabase, data_tenant_id, resolved_funnel_id
    )
    lead_rows = merge_kanban_lead_rows(
        supabase=supabase,
        primary_rows=lead_rows_primary,
        data_tenant_id=data_tenant_id,
        funnel_id=resolved_funnel_id,
        pipeline_board_owner_user_ids=pipeline_board_owner_ids,
    )
    pos_by_lead = build_pos_by_lead(
        supabase, funnel_id=resolved_funnel_id, pipeline_board_owner_user_ids=pipeline_board_owner_ids
    )

    leads_by_stage: dict[str, list] = {s["name"]: [] for s in stages_data}

    for row in lead_rows:
        col_name = resolve_stage_name_for_board(
            row,
            funnel_id=resolved_funnel_id,
            data_tenant_id=data_tenant_id,
            stages_data=stages_data,
            pos_by_lead=pos_by_lead,
        )
        if not col_name:
            col_name = stages_data[0]["name"] if stages_data else "Contato Inicial"
        if col_name not in leads_by_stage and stages_data:
            col_name = stages_data[0]["name"]
        if col_name in leads_by_stage:
            leads_by_stage[col_name].append(lead_row_to_response_safe(row))
        elif stages_data:
            leads_by_stage[stages_data[0]["name"]].append(lead_row_to_response_safe(row))

    columns = []
    for stage_info in stages_data:
        name = stage_info["name"]
        stage_leads = leads_by_stage[name]
        columns.append(
            KanbanColumn(
                stage=name,
                stage_id=stage_info.get("id"),
                stage_version=int(stage_info.get("version") or 1),
                stage_is_conversion=bool(stage_info.get("is_conversion", False)),
                label=name,
                count=len(stage_leads),
                total_value=sum(l.value for l in stage_leads),
                leads=stage_leads,
            )
        )

    cohort_snap = compute_inicial_cohort_snapshot(
        supabase, data_tenant_id=data_tenant_id, funnel_id=resolved_funnel_id
    )

    elapsed_ms = (perf_counter() - started) * 1000.0
    metrics.observe("kanban_board", elapsed_ms, ok=True)
    return KanbanBoard(
        columns=columns,
        funnel_id=resolved_funnel_id,
        initial_stage_cohort_badge_count=cohort_snap.inicial_cohort_count,
        initial_stage_id=cohort_snap.inicial_stage_id,
    )


@router.post("/stages/reorder", status_code=status.HTTP_200_OK)
async def reorder_stages(
    payload: ReorderStagesPayload,
    funnel_id: Optional[str] = Query(
        None,
        description="Funil do board que está sendo reordenado.",
    ),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    started = perf_counter()
    data_tenant_id, resolved_funnel_id = _resolve_kanban_scope(supabase, user.id, eff, funnel_id)
    ordered_ids = [item.id for item in payload.items]
    version_by_id = {item.id: item.version for item in payload.items}
    current_rows = _list_pipeline_stages_for_board_scope(
        supabase=supabase,
        data_tenant_id=data_tenant_id,
        funnel_id=resolved_funnel_id,
    )
    if not current_rows:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhuma etapa encontrada para reorder.")

    db_ids = [row["id"] for row in current_rows]
    if set(db_ids) != set(ordered_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload inválido: etapas ausentes, duplicadas ou de outro tenant.",
        )

    for stage in current_rows:
        expected_version = version_by_id.get(stage["id"])
        if expected_version is None:
            raise HTTPException(status_code=400, detail="Payload inválido: versão ausente.")
        if int(stage.get("version") or 1) != int(expected_version):
            metrics.observe("kanban_reorder", (perf_counter() - started) * 1000.0, ok=False)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflito de versão. Recarregue o Kanban.")

    previous_positions = {row["id"]: row["order_position"] for row in current_rows}
    previous_versions = {row["id"]: int(row.get("version") or 1) for row in current_rows}
    try:
        for idx, stage_id in enumerate(ordered_ids):
            update_res = (
                supabase.table("pipeline_stages")
                .update({"order_position": idx, "version": previous_versions[stage_id] + 1})
                .eq("id", stage_id)
                .eq("tenant_id", data_tenant_id)
                .eq("version", previous_versions[stage_id])
                .execute()
            )
            if not update_res.data:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conflito de versão. Recarregue o Kanban.")
    except HTTPException:
        # Best-effort rollback para manter consistência visual/banco em falha parcial.
        for stage_id, old_position in previous_positions.items():
            supabase.table("pipeline_stages").update(
                {"order_position": old_position, "version": previous_versions[stage_id]}
            ).eq("id", stage_id).eq("tenant_id", data_tenant_id).execute()
        metrics.observe("kanban_reorder", (perf_counter() - started) * 1000.0, ok=False)
        logger.warning("kanban_reorder_conflict_or_error", extra={"tenant_id": data_tenant_id, "error_count": 1})
        raise
    except Exception as exc:
        for stage_id, old_position in previous_positions.items():
            supabase.table("pipeline_stages").update(
                {"order_position": old_position, "version": previous_versions[stage_id]}
            ).eq("id", stage_id).eq("tenant_id", data_tenant_id).execute()
        metrics.observe("kanban_reorder", (perf_counter() - started) * 1000.0, ok=False)
        logger.exception("kanban_reorder_failed", extra={"tenant_id": data_tenant_id})
        raise HTTPException(status_code=500, detail=f"Erro ao persistir reorder: {str(exc)}")

    refreshed = _list_pipeline_stages_for_board_scope(
        supabase=supabase,
        data_tenant_id=data_tenant_id,
        funnel_id=resolved_funnel_id,
    )
    elapsed_ms = (perf_counter() - started) * 1000.0
    metrics.observe("kanban_reorder", elapsed_ms, ok=True)
    logger.info(
        "kanban_reorder_success",
        extra={"tenant_id": data_tenant_id, "result_count": len(ordered_ids), "elapsed_ms": round(elapsed_ms, 2)},
    )
    return {"stages": refreshed}


@router.post("/stages", status_code=status.HTTP_201_CREATED)
async def create_stage(
    payload: StageCreatePayload,
    funnel_id: Optional[str] = Query(
        None,
        description="Funil do board onde a etapa será criada.",
    ),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    tenant_id, resolved_funnel_id = _resolve_kanban_scope(supabase, user.id, eff, funnel_id)
    existing = _list_pipeline_stages_for_board_scope(
        supabase=supabase,
        data_tenant_id=tenant_id,
        funnel_id=resolved_funnel_id,
    )
    existing.sort(key=lambda row: int(row.get("order_position") or 0), reverse=True)
    next_order = int(existing[0]["order_position"]) + 1 if existing else 0
    insert_payload = {
        "tenant_id": tenant_id,
        "funnel_id": resolved_funnel_id,
        "name": payload.name.strip(),
        "order_position": next_order,
        "is_conversion": bool(payload.is_conversion),
    }
    try:
        response = supabase.table("pipeline_stages").insert(insert_payload).execute()
    except Exception as exc:
        detail = _db_error_detail(exc)
        if _is_missing_column_error(detail, "is_conversion"):
            logger.info("create_stage_fallback", extra={"reason": "is_conversion column missing", "tenant_id": tenant_id})
            try:
                response = (
                    supabase.table("pipeline_stages")
                    .insert(
                        {
                            "tenant_id": tenant_id,
                            "funnel_id": resolved_funnel_id,
                            "name": payload.name.strip(),
                            "order_position": next_order,
                        }
                    )
                    .execute()
                )
                if response.data and len(response.data) > 0:
                    response.data[0]["is_conversion"] = False
            except Exception as fallback_exc:
                logger.exception("create_stage_fallback_failed", extra={"tenant_id": tenant_id})
                raise HTTPException(
                    status_code=500,
                    detail="Erro ao criar etapa. Execute a migration 005_pipeline_stage_conversion_flag.sql no Supabase.",
                ) from fallback_exc
        else:
            logger.exception("create_stage_failed", extra={"tenant_id": tenant_id, "detail": detail})
            raise HTTPException(status_code=500, detail=f"Erro ao criar etapa: {detail}")
    rows = response.data or []
    if not rows:
        raise HTTPException(status_code=400, detail="Erro ao criar etapa.")
    return rows[0]


@router.patch("/stages/{stage_id}")
async def rename_stage(
    stage_id: str,
    payload: StageRenamePayload,
    funnel_id: Optional[str] = Query(
        None,
        description="Funil do board onde a etapa está localizada.",
    ),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    try:
        uuid.UUID(str(stage_id).strip())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ID de etapa inválido. Recarregue o Kanban — etapas só locais (demonstração) não podem ser renomeadas até existirem no banco.",
        )

    data_tenant_id, resolved_funnel_id = _resolve_kanban_scope(supabase, user.id, eff, funnel_id)
    stage_rows = _list_pipeline_stages_for_board_scope(
        supabase=supabase,
        data_tenant_id=data_tenant_id,
        funnel_id=resolved_funnel_id,
    )
    allowed_stage_ids = {str(row["id"]) for row in stage_rows}
    if stage_id not in allowed_stage_ids:
        raise HTTPException(status_code=404, detail="Etapa não encontrada.")

    target_row = next((r for r in stage_rows if str(r["id"]) == str(stage_id)), None)
    if not target_row:
        raise HTTPException(status_code=404, detail="Etapa não encontrada.")
    old_name = str(target_row.get("name") or "")
    new_name = payload.name.strip()
    if old_name == new_name:
        return {
            "id": stage_id,
            "name": new_name,
            "order_position": target_row.get("order_position", 0),
            "version": int(target_row.get("version") or 1),
        }

    # postgrest-py 2.x: .update().eq(...) não encadeia .select() (só SyncSelectRequestBuilder tem select/single).
    # PATCH com returning=representation (padrão) devolve a linha em response.data.
    try:
        response = (
            supabase.table("pipeline_stages")
            .update({"name": new_name})
            .eq("id", stage_id)
            .eq("tenant_id", data_tenant_id)
            .execute()
        )
    except Exception as exc:
        detail = _db_error_detail(exc)
        logger.exception("rename_stage_failed", extra={"stage_id": stage_id, "detail": detail})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST
            if "invalid input syntax for type uuid" in detail.lower() or "22P02" in detail
            else status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao renomear etapa: {detail}",
        ) from exc

    raw = response.data
    rows = raw if isinstance(raw, list) else ([raw] if raw else [])
    if not rows:
        raise HTTPException(status_code=404, detail="Etapa não encontrada.")

    # leads.stage armazena o nome da coluna — alinhar após renomear pipeline_stages
    try:
        supabase.table("leads").update({"stage": new_name}).eq("tenant_id", data_tenant_id).eq("funnel_id", resolved_funnel_id).eq(
            "stage", old_name
        ).execute()
    except Exception as exc:
        d = _db_error_detail(exc)
        if _is_missing_column_error(d, "funnel_id"):
            try:
                supabase.table("leads").update({"stage": new_name}).eq("tenant_id", data_tenant_id).eq("stage", old_name).execute()
            except Exception as exc2:
                logger.warning("rename_stage_leads_update_failed", extra={"detail": _db_error_detail(exc2)})
        else:
            logger.warning("rename_stage_leads_update_failed", extra={"detail": d})

    return rows[0]


@router.delete("/stages/{stage_id}")
async def delete_stage(
    stage_id: str,
    payload: StageDeletePayload,
    funnel_id: Optional[str] = Query(
        None,
        description="Funil do board onde a etapa será excluída.",
    ),
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    data_tenant_id, resolved_funnel_id = _resolve_kanban_scope(supabase, user.id, eff, funnel_id)
    stages = _list_pipeline_stages_for_board_scope(
        supabase=supabase,
        data_tenant_id=data_tenant_id,
        funnel_id=resolved_funnel_id,
    )
    target = next((s for s in stages if str(s["id"]) == str(stage_id)), None)
    if not target:
        raise HTTPException(status_code=404, detail="Etapa não encontrada.")
    if len(stages) <= 1:
        raise HTTPException(status_code=400, detail="É necessário manter pelo menos uma etapa.")

    fallback = None
    if payload.fallback_stage_id:
        fallback = next((s for s in stages if str(s["id"]) == str(payload.fallback_stage_id) and str(s["id"]) != str(stage_id)), None)
    if not fallback:
        fallback = next((s for s in stages if str(s["id"]) != str(stage_id)), None)
    if not fallback:
        raise HTTPException(status_code=400, detail="Etapa de fallback inválida.")

    # Move leads to fallback by both stage name and legacy id-in-stage field.
    try:
        supabase.table("leads").update({"stage": fallback["name"]}).eq("tenant_id", data_tenant_id).eq("funnel_id", resolved_funnel_id).in_("stage", [target["name"], target["id"]]).execute()
    except Exception as exc:
        detail = _db_error_detail(exc)
        if _is_missing_column_error(detail, "funnel_id"):
            supabase.table("leads").update({"stage": fallback["name"]}).eq("tenant_id", data_tenant_id).in_("stage", [target["name"], target["id"]]).execute()
        else:
            raise
    delete_result = supabase.table("pipeline_stages").delete().eq("id", stage_id).eq("tenant_id", data_tenant_id).execute()
    if not delete_result.data:
        raise HTTPException(status_code=400, detail="Erro ao excluir etapa.")

    refreshed = _list_pipeline_stages_for_board_scope(
        supabase=supabase,
        data_tenant_id=data_tenant_id,
        funnel_id=resolved_funnel_id,
    )
    return {"fallback_stage_id": fallback["id"], "stages": refreshed}


@router.get("/", response_model=list[LeadResponse])
async def list_leads(
    stage: Optional[str] = None,
    search: Optional[str] = Query(None, min_length=1),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """List leads with optional stage and search filters."""
    query = supabase.table("leads").select("*").eq("tenant_id", user.id).order("created_at", desc=True)

    if stage:
        query = query.eq("stage", stage)
    if search:
        query = query.or_(f"company_name.ilike.%{search}%,contact_name.ilike.%{search}%")

    response = query.execute()
    return [LeadResponse(**row) for row in response.data]


def _resolve_or_create_client_by_phone(
    supabase: SupabaseClient, tenant_id: str, phone: str | None, contact_name: str | None, company_name: str | None,
) -> str | None:
    """Search crm_clients by phone; create a minimal record if not found. Returns client_id or None."""
    if not phone:
        return None
    needle = _digits_only(phone)
    if len(needle) < 4:
        return None

    res = supabase.table("crm_clients").select("*").eq("tenant_id", tenant_id).execute()
    for r in res.data or []:
        phones_raw = r.get("phones")
        if not isinstance(phones_raw, list):
            continue
        for p in phones_raw:
            if _digits_only(str(p)) == needle:
                return str(r["id"])

    now = datetime.now(timezone.utc).isoformat()
    display = (contact_name or company_name or phone or "Novo cliente").strip()
    ins = supabase.table("crm_clients").insert({
        "tenant_id": tenant_id,
        "person_type": "PF",
        "display_name": display,
        "phones": [phone],
        "updated_at": now,
    }).execute()
    rows = ins.data or []
    return str(rows[0]["id"]) if rows else None


@router.post("/", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    user=Depends(get_current_user),
    eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Create a new lead/card."""
    data = payload.model_dump()
    funnel_id_opt = data.pop("funnel_id", None)
    explicit_client_id = data.pop("client_id", None)
    data_tenant_id = str(user.id)
    resolved_fid = ""
    previous_reserved: list[dict] = []
    rollback_needed = False
    applied_delta: dict[str, int] = {}

    try:
        data_tenant_id, resolved_fid = _resolve_kanban_scope(supabase, user.id, eff, funnel_id_opt)
        data["tenant_id"] = data_tenant_id
        next_reserved, applied_delta = compute_stock_delta(previous_reserved, data.get("products_json") or [])
        apply_stock_delta(supabase=supabase, tenant_id=data_tenant_id, delta=applied_delta)
        rollback_needed = True
        data["stock_reserved_json"] = next_reserved
        if "purchase_history_json" not in data or data["purchase_history_json"] is None:
            data["purchase_history_json"] = []
        priced_value, resolved_lines = _price_lead_products_with_promotions(
            supabase=supabase,
            tenant_id=data_tenant_id,
            products_json=data.get("products_json") or [],
        )
        data["value"] = priced_value
        data["products_json"] = resolved_lines
        data["funnel_id"] = resolved_fid

        if explicit_client_id:
            data["client_id"] = explicit_client_id
        elif data.get("phone"):
            resolved_cid = _resolve_or_create_client_by_phone(
                supabase,
                tenant_id=data_tenant_id,
                phone=data["phone"],
                contact_name=data.get("contact_name"),
                company_name=data.get("company_name"),
            )
            if resolved_cid:
                data["client_id"] = resolved_cid

        cid_sync = data.get("client_id")
        if cid_sync:
            synced_phone = fetch_display_phone_for_crm_client(
                supabase, tenant_id=data_tenant_id, client_id=str(cid_sync)
            )
            if synced_phone:
                data["phone"] = synced_phone

        response = supabase.table("leads").insert(data).execute()
    except Exception:
        if rollback_needed and applied_delta:
            try:
                apply_stock_delta(supabase=supabase, tenant_id=data_tenant_id, delta=invert_delta(applied_delta))
            except Exception:
                logger.exception("lead_create_stock_rollback_failed", extra={"tenant_id": data_tenant_id})
        raise

    if not response.data:
        if applied_delta:
            try:
                apply_stock_delta(supabase=supabase, tenant_id=user.id, delta=invert_delta(applied_delta))
            except Exception:
                logger.exception("lead_create_stock_rollback_failed", extra={"tenant_id": str(user.id)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Erro ao criar lead.")

    lead_row = response.data[0]
    lid = str(lead_row["id"])
    try:
        stages_f = _fetch_pipeline_stages_for_funnel(
            supabase, data_tenant_id=data_tenant_id, funnel_id=str(lead_row.get("funnel_id") or resolved_fid)
        )
        st_match = next(
            (
                s
                for s in stages_f
                if str(s.get("name", "")).strip().lower() == str(lead_row.get("stage", "")).strip().lower()
            ),
            None,
        )
        if st_match:
            upsert_pipeline_position(
                supabase,
                lead_id=lid,
                funnel_id=str(lead_row.get("funnel_id") or resolved_fid),
                stage_id=str(st_match["id"]),
                board_owner_user_id=data_tenant_id,
            )
            auto = fetch_stage_automation_for_source_stage(
                supabase,
                source_funnel_id=str(lead_row.get("funnel_id") or resolved_fid),
                source_stage_id=str(st_match["id"]),
            )
            if auto:
                apply_destination_mirror(supabase, lead_id=lid, automation=auto)
    except Exception:
        logger.exception("lead_create_automation_hook_failed", extra={"tenant_id": str(user.id), "lead_id": lid})

    return LeadResponse(**lead_row)


@router.patch("/{lead_id}", response_model=LeadResponse)
async def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
    _eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Update a lead's data."""
    update_data = payload.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhum campo para atualizar.")

    rollback_needed = False
    applied_delta: dict[str, int] = {}

    if "products_json" in update_data:
        current_lead = (
            supabase.table("leads")
            .select("id, products_json, stock_reserved_json")
            .eq("id", lead_id)
            .eq("tenant_id", user.id)
            .single()
            .execute()
        )
        if not current_lead.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
        previous_reserved = current_lead.data.get("stock_reserved_json") or current_lead.data.get("products_json") or []
        next_reserved, applied_delta = compute_stock_delta(previous_reserved, update_data.get("products_json") or [])
        apply_stock_delta(supabase=supabase, tenant_id=user.id, delta=applied_delta)
        rollback_needed = True
        update_data["stock_reserved_json"] = next_reserved
        priced_value, resolved_lines = _price_lead_products_with_promotions(
            supabase=supabase,
            tenant_id=user.id,
            products_json=update_data.get("products_json") or [],
        )
        update_data["value"] = priced_value
        update_data["products_json"] = resolved_lines

    try:
        response = supabase.table("leads") \
            .update(update_data) \
            .eq("id", lead_id) \
            .eq("tenant_id", user.id) \
            .execute()
    except Exception:
        if rollback_needed and applied_delta:
            try:
                apply_stock_delta(supabase=supabase, tenant_id=user.id, delta=invert_delta(applied_delta))
            except Exception:
                logger.exception("lead_update_stock_rollback_failed", extra={"tenant_id": str(user.id), "lead_id": lead_id})
        raise

    if not response.data:
        if rollback_needed and applied_delta:
            try:
                apply_stock_delta(supabase=supabase, tenant_id=user.id, delta=invert_delta(applied_delta))
            except Exception:
                logger.exception("lead_update_stock_rollback_failed", extra={"tenant_id": str(user.id), "lead_id": lead_id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")

    lead_data = response.data[0]

    # Com vínculo a crm_clients, o telefone exibido no card segue o cadastro (fonte de verdade).
    if lead_data.get("client_id"):
        want_phone = fetch_display_phone_for_crm_client(
            supabase,
            tenant_id=str(lead_data["tenant_id"]),
            client_id=str(lead_data["client_id"]),
        )
        if want_phone and _digits_only(want_phone) != _digits_only(lead_data.get("phone") or ""):
            r_phone = (
                supabase.table("leads")
                .update({"phone": want_phone})
                .eq("id", lead_id)
                .eq("tenant_id", str(lead_data["tenant_id"]))
                .execute()
            )
            if r_phone.data:
                lead_data = r_phone.data[0]

    # Sync with Uazapi if contact_name was updated and lead has whatsapp_chat_id
    if "contact_name" in update_data and lead_data.get("whatsapp_chat_id"):
        phone_number = lead_data["whatsapp_chat_id"].replace("@s.whatsapp.net", "").replace("@g.us", "")
        uazapi = get_uazapi_service()
        # Run in background to not block the request
        background_tasks.add_task(uazapi.update_contact, number=phone_number, name=lead_data["contact_name"])

    try:
        fid = str(lead_data.get("funnel_id") or "").strip()
        tid = str(lead_data.get("tenant_id") or "").strip()
        if fid and tid:
            stages_u = _fetch_pipeline_stages_for_funnel(supabase, data_tenant_id=tid, funnel_id=fid)
            stage_name = str(lead_data.get("stage") or "").strip()
            st_row = next(
                (s for s in stages_u if str(s.get("name", "")).strip().lower() == stage_name.lower()),
                None,
            )
            if st_row:
                auto_u = fetch_stage_automation_for_source_stage(
                    supabase,
                    source_funnel_id=fid,
                    source_stage_id=str(st_row["id"]),
                )
                if auto_u:
                    apply_destination_mirror(supabase, lead_id=str(lead_data["id"]), automation=auto_u)
    except Exception:
        logger.exception("lead_update_automation_hook_failed", extra={"lead_id": lead_id})

    return LeadResponse(**lead_data)


@router.get("/stages/{stage_id}/automation", response_model=Optional[StageAutomationOut])
async def get_stage_automation(
    stage_id: str,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    sres = (
        supabase.table("pipeline_stages")
        .select("id, tenant_id")
        .eq("id", stage_id)
        .limit(1)
        .execute()
    )
    rows = sres.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etapa não encontrada.")
    if str(rows[0]["tenant_id"]) != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a esta etapa.")
    ares = (
        supabase.table("stage_automations")
        .select("*")
        .eq("source_stage_id", stage_id)
        .limit(1)
        .execute()
    )
    if not ares.data:
        return None
    r = ares.data[0]
    return StageAutomationOut(
        id=str(r["id"]),
        organization_id=str(r["organization_id"]),
        source_funnel_id=str(r["source_funnel_id"]),
        source_stage_id=str(r["source_stage_id"]),
        target_user_id=str(r["target_user_id"]),
        target_funnel_id=str(r["target_funnel_id"]),
        target_stage_id=str(r["target_stage_id"]),
        created_at=r.get("created_at"),
    )


@router.put("/stages/{stage_id}/automation", response_model=StageAutomationOut)
async def upsert_stage_automation(
    stage_id: str,
    payload: StageAutomationPayload,
    user=Depends(get_current_user),
    _eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    sres = (
        supabase.table("pipeline_stages")
        .select("id, tenant_id, funnel_id")
        .eq("id", stage_id)
        .limit(1)
        .execute()
    )
    srows = sres.data or []
    if not srows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etapa não encontrada.")
    stage_row = srows[0]
    if str(stage_row["tenant_id"]) != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão nesta etapa.")
    try:
        assert_funnel_assignable_to_org(supabase, payload.organization_id, str(stage_row.get("funnel_id")))
        assert_funnel_assignable_to_org(supabase, payload.organization_id, payload.target_funnel_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    mem = (
        supabase.table("organization_members")
        .select("user_id, role, assigned_funnel_id")
        .eq("organization_id", payload.organization_id)
        .eq("user_id", payload.target_user_id)
        .limit(1)
        .execute()
    ).data or []
    if not mem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Usuário alvo não pertence à organização.")
    target_member = mem[0]
    target_role = str(target_member.get("role") or "")
    assigned_funnel_id = target_member.get("assigned_funnel_id")

    tf = (
        supabase.table("funnels")
        .select("id, tenant_id")
        .eq("id", payload.target_funnel_id)
        .limit(1)
        .execute()
    ).data or []
    if not tf:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Funil de destino não encontrado.")

    if target_role == "read_only":
        # Funis da org são criados no tenant do admin; read_only não é tenant_id do funil.
        if assigned_funnel_id and str(assigned_funnel_id) != str(payload.target_funnel_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Funil de destino deve ser o funil atribuído ao usuário read_only.",
            )
    else:
        if str(tf[0]["tenant_id"]) != str(payload.target_user_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Funil de destino não pertence ao usuário alvo.",
            )

    ts = (
        supabase.table("pipeline_stages")
        .select("id, funnel_id")
        .eq("id", payload.target_stage_id)
        .limit(1)
        .execute()
    ).data or []
    if not ts or str(ts[0]["funnel_id"]) != str(payload.target_funnel_id):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Etapa de destino inválida para o funil.")

    row_in = {
        "organization_id": payload.organization_id,
        "source_funnel_id": str(stage_row.get("funnel_id")),
        "source_stage_id": stage_id,
        "target_user_id": payload.target_user_id,
        "target_funnel_id": payload.target_funnel_id,
        "target_stage_id": payload.target_stage_id,
        "created_by": str(user.id),
    }
    supabase.table("stage_automations").delete().eq("source_stage_id", stage_id).execute()
    ins = supabase.table("stage_automations").insert(row_in).execute()
    out = (ins.data or [None])[0]
    if not out:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Não foi possível salvar automação.")
    r = out
    return StageAutomationOut(
        id=str(r["id"]),
        organization_id=str(r["organization_id"]),
        source_funnel_id=str(r["source_funnel_id"]),
        source_stage_id=str(r["source_stage_id"]),
        target_user_id=str(r["target_user_id"]),
        target_funnel_id=str(r["target_funnel_id"]),
        target_stage_id=str(r["target_stage_id"]),
        created_at=r.get("created_at"),
    )


@router.delete("/stages/{stage_id}/automation", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stage_automation(
    stage_id: str,
    user=Depends(get_current_user),
    _eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    sres = (
        supabase.table("pipeline_stages")
        .select("id, tenant_id")
        .eq("id", stage_id)
        .limit(1)
        .execute()
    )
    srows = sres.data or []
    if not srows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etapa não encontrada.")
    if str(srows[0]["tenant_id"]) != str(user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão nesta etapa.")
    supabase.table("stage_automations").delete().eq("source_stage_id", stage_id).execute()
    return None


@router.get("/{lead_id}/activity", response_model=list[LeadActivityItem])
async def list_lead_activity(
    lead_id: str,
    limit: int = Query(80, ge=1, le=200),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
):
    lead_chk = (
        supabase.table("leads")
        .select("id, tenant_id, funnel_id")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    ).data or []
    if not lead_chk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
    row0 = lead_chk[0]
    if str(row0["tenant_id"]) != str(user.id):
        allowed = False
        if eff.is_read_only and eff.assigned_funnel_id:
            if str(row0.get("funnel_id") or "") == str(eff.assigned_funnel_id):
                allowed = True
            else:
                pos = (
                    supabase.table("lead_pipeline_positions")
                    .select("id")
                    .eq("lead_id", lead_id)
                    .eq("funnel_id", str(eff.assigned_funnel_id))
                    .eq("board_owner_user_id", str(user.id))
                    .limit(1)
                    .execute()
                )
                if pos.data:
                    allowed = True
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a este lead.")
    ares = (
        supabase.table("lead_activity")
        .select("*")
        .eq("lead_id", lead_id)
        .order("occurred_at", desc=True)
        .limit(limit)
        .execute()
    )
    items: list[LeadActivityItem] = []
    for r in ares.data or []:
        items.append(
            LeadActivityItem(
                id=str(r["id"]),
                event_type=str(r["event_type"]),
                from_stage_id=str(r["from_stage_id"]) if r.get("from_stage_id") else None,
                to_stage_id=str(r["to_stage_id"]) if r.get("to_stage_id") else None,
                actor_user_id=str(r["actor_user_id"]) if r.get("actor_user_id") else None,
                occurred_at=r["occurred_at"],
                metadata=r.get("metadata") or {},
            )
        )
    return items


@router.patch("/{lead_id}/stage", response_model=LeadResponse)
async def move_lead_stage(
    lead_id: str,
    payload: LeadMoveStage,
    funnel_id: Optional[str] = Query(
        None,
        description="Funil do board (mesmo parâmetro do GET /kanban).",
    ),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
):
    """Move o card; atualiza leads.stage e/ou lead_pipeline_positions; auditoria + automação de etapa."""
    data_tenant_id, resolved_funnel_id = _resolve_kanban_scope(supabase, user.id, eff, funnel_id)

    stages = _fetch_pipeline_stages_for_funnel(
        supabase, data_tenant_id=data_tenant_id, funnel_id=resolved_funnel_id
    )
    if not stages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nenhuma etapa para este funil.")

    canonical_stage = payload.stage
    to_stage_row: dict | None = None
    if payload.stage_id:
        to_stage_row = next((s for s in stages if str(s.get("id")) == str(payload.stage_id)), None)
        if not to_stage_row:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Etapa inválida para este funil.")
        canonical_stage = str(to_stage_row["name"])
    else:
        target = payload.stage.strip().lower()
        to_stage_row = next(
            (s for s in stages if str(s.get("name", "")).strip().lower() == target),
            None,
        )
        if not to_stage_row:
            # UI pode truncar o rótulo; ainda assim deve casar com a etapa "Despachado" no funil.
            pt = payload.stage.strip().casefold()
            full_cf = DESPACHADO_CANONICAL_CASEFOLD
            if (
                len(pt) >= DESPACHADO_TRUNCATED_PREFIX_MIN_LEN
                and len(pt) < len(full_cf)
                and full_cf.startswith(pt)
            ):
                to_stage_row = next(
                    (s for s in stages if str(s.get("name", "")).strip().casefold() == full_cf),
                    None,
                )
        if not to_stage_row:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Etapa inválida para este funil.")
        canonical_stage = str(to_stage_row["name"])

    to_stage_id = str(to_stage_row["id"])

    despachado_finalizado_plan: tuple[str, list[dict], dict] | None = None
    if is_despachado_destination_name(canonical_stage):
        despachado_finalizado_plan = _despachado_finalizado_sync_plan(
            supabase, data_tenant_id=data_tenant_id
        )

    lead_res = supabase.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    lead_rows = lead_res.data or []
    if not lead_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
    lead_row = lead_rows[0]

    board_owner_scope = _pipeline_board_owner_ids_for_scope(
        eff, str(user.id), supabase, data_tenant_id, resolved_funnel_id
    )
    owners_for_query = [str(x).strip() for x in board_owner_scope if str(x).strip()]
    if not owners_for_query:
        pos_existing_rows: list[dict] = []
    elif len(owners_for_query) == 1:
        pos_existing = (
            supabase.table("lead_pipeline_positions")
            .select("id, stage_id, board_owner_user_id")
            .eq("lead_id", lead_id)
            .eq("funnel_id", resolved_funnel_id)
            .eq("board_owner_user_id", owners_for_query[0])
            .execute()
        )
        pos_existing_rows = pos_existing.data or []
    else:
        pos_existing = (
            supabase.table("lead_pipeline_positions")
            .select("id, stage_id, board_owner_user_id")
            .eq("lead_id", lead_id)
            .eq("funnel_id", resolved_funnel_id)
            .in_("board_owner_user_id", owners_for_query)
            .execute()
        )
        pos_existing_rows = pos_existing.data or []
    has_pos = bool(pos_existing_rows)
    is_owner = str(lead_row.get("tenant_id")) == str(data_tenant_id)
    is_primary = is_owner and str(lead_row.get("funnel_id") or "") == str(resolved_funnel_id)
    if not is_owner and not has_pos:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para mover este card neste funil.")

    from_stage_id: str | None = None
    if is_primary:
        prev_name = str(lead_row.get("stage") or "").strip()
        prev_row = next(
            (s for s in stages if str(s.get("name", "")).strip().lower() == prev_name.lower()),
            None,
        )
        if prev_row:
            from_stage_id = str(prev_row["id"])
    elif pos_existing_rows:
        from_stage_id = str(pos_existing_rows[0].get("stage_id"))

    if is_primary:
        upd = (
            supabase.table("leads")
            .update({"stage": canonical_stage})
            .eq("id", lead_id)
            .eq("tenant_id", data_tenant_id)
            .execute()
        )
        if not upd.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
        upsert_pipeline_position(
            supabase,
            lead_id=lead_id,
            funnel_id=resolved_funnel_id,
            stage_id=to_stage_id,
            board_owner_user_id=data_tenant_id,
        )
    else:
        if pos_existing_rows:
            owners_to_touch = list(
                dict.fromkeys(str(r["board_owner_user_id"]) for r in pos_existing_rows if r.get("board_owner_user_id"))
            )
        else:
            owners_to_touch = owners_for_query[:1] if owners_for_query else [str(data_tenant_id)]
        for pos_owner in owners_to_touch:
            upsert_pipeline_position(
                supabase,
                lead_id=lead_id,
                funnel_id=resolved_funnel_id,
                stage_id=to_stage_id,
                board_owner_user_id=str(pos_owner),
            )

    insert_lead_activity(
        supabase,
        lead_id=lead_id,
        event_type="stage_move",
        actor_user_id=str(user.id),
        from_stage_id=from_stage_id,
        to_stage_id=to_stage_id,
        metadata={"funnel_id": resolved_funnel_id, "primary": is_primary},
    )

    auto = fetch_stage_automation_for_source_stage(
        supabase,
        source_funnel_id=resolved_funnel_id,
        source_stage_id=to_stage_id,
    )
    if auto:
        apply_destination_mirror(supabase, lead_id=lead_id, automation=auto)

    if despachado_finalizado_plan:
        main_funnel_id, main_stages, finalized_row = despachado_finalizado_plan
        _sync_primary_lead_to_finalizado_after_despachado(
            supabase,
            lead_id=lead_id,
            lead_row=lead_row,
            data_tenant_id=data_tenant_id,
            acting_user_id=str(user.id),
            main_funnel_id=main_funnel_id,
            main_stages=main_stages,
            finalized_row=finalized_row,
        )

    refreshed = (
        supabase.table("leads")
        .select("*")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    ).data or []
    if not refreshed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
    return LeadResponse(**refreshed[0])


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead(
    lead_id: str,
    user=Depends(get_current_user),
    _eff: EffectiveRole = Depends(require_org_admin),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Delete a lead."""
    current = (
        supabase.table("leads")
        .select("id, products_json, stock_reserved_json")
        .eq("id", lead_id)
        .eq("tenant_id", user.id)
        .single()
        .execute()
    )
    if not current.data:
        return

    previous_reserved = current.data.get("stock_reserved_json") or current.data.get("products_json") or []
    _, release_delta = compute_stock_delta(previous_reserved, [])
    if release_delta:
        apply_stock_delta(supabase=supabase, tenant_id=user.id, delta=release_delta)
    supabase.table("leads").delete().eq("id", lead_id).eq("tenant_id", user.id).execute()


@router.get("/{lead_id}/messages")
async def get_lead_messages(
    lead_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """
    Get the full chat message history for a lead (WhatsApp chat mirror).
    Returns messages sorted chronologically for display in the chat panel.
    """
    # First get the lead to find its whatsapp_chat_id
    lead_response = supabase.table("leads") \
        .select("id, company_name, contact_name, whatsapp_chat_id, stage, chat_cycle_closed_at") \
        .eq("id", lead_id) \
        .eq("tenant_id", user.id) \
        .single() \
        .execute()

    if not lead_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")

    lead = lead_response.data
    if is_chat_mirror_closed_for_lead(lead):
        return {
            "lead_id": lead_id,
            "lead_name": f"{lead['contact_name']} - {lead['company_name']}",
            "whatsapp_chat_id": None,
            "messages": [],
            "total_messages": 0,
        }

    whatsapp_chat_id = lead.get("whatsapp_chat_id")

    # Get messages for this chat, ordered chronologically
    messages_response = supabase.table("chat_messages") \
        .select("*", count="exact") \
        .eq("whatsapp_chat_id", whatsapp_chat_id) \
        .eq("tenant_id", user.id) \
        .order("created_at", desc=False) \
        .range(offset, offset + limit - 1) \
        .execute()

    return {
        "lead_id": lead_id,
        "lead_name": f"{lead['contact_name']} - {lead['company_name']}",
        "whatsapp_chat_id": whatsapp_chat_id,
        "messages": messages_response.data or [],
        "total_messages": messages_response.count or 0,
    }


@router.get("/{lead_id}/chat-history")
async def get_lead_chat_history(
    lead_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """
    Get the full chat message history for a lead directly from Uazapi device.
    Returns messages fetched live from WhatsApp through the Uazapi integration.
    """
    lead_response = supabase.table("leads") \
        .select("id, company_name, contact_name, whatsapp_chat_id, inbox_id, stage, chat_cycle_closed_at") \
        .eq("id", lead_id) \
        .eq("tenant_id", user.id) \
        .single() \
        .execute()

    if not lead_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")

    lead = lead_response.data
    if is_chat_mirror_closed_for_lead(lead):
        return {
            "lead_id": lead_id,
            "lead_name": f"{lead['contact_name']} - {lead['company_name']}",
            "whatsapp_chat_id": None,
            "messages": [],
            "hasMore": False,
        }

    whatsapp_chat_id = lead.get("whatsapp_chat_id")

    instance_token = get_uazapi_instance_token_for_tenant(
        supabase,
        tenant_id=str(user.id),
        inbox_id=str(lead["inbox_id"]) if lead.get("inbox_id") else None,
    )

    if not instance_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum token Uazapi configurado. Configure uma caixa de entrada com token válido.",
        )

    uazapi = get_uazapi_service()
    try:
        uazapi_response = await uazapi.find_messages(
            chatid=whatsapp_chat_id,
            limit=limit,
            offset=offset,
            instance_token=instance_token,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao buscar histórico via Uazapi: {str(e)}",
        )

    return {
        "lead_id": lead_id,
        "lead_name": f"{lead['contact_name']} - {lead['company_name']}",
        "whatsapp_chat_id": whatsapp_chat_id,
        "messages": uazapi_response.get("messages", []),
        "returnedMessages": uazapi_response.get("returnedMessages", 0),
        "limit": uazapi_response.get("limit", limit),
        "offset": uazapi_response.get("offset", offset),
        "nextOffset": uazapi_response.get("nextOffset", None),
        "hasMore": uazapi_response.get("hasMore", False),
    }


@router.post("/{lead_id}/messages/send")
async def send_message_to_lead(
    lead_id: str,
    payload: SendMessagePayload,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """
    Send a WhatsApp message to a lead via Uazapi API.
    Supports text, image, video, document, and audio messages.
    The sent message is also saved in chat_messages for the chat mirror.
    """
    # Validate payload
    try:
        payload.validate_payload()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Get the lead's WhatsApp chat ID
    lead_response = supabase.table("leads") \
        .select("id, company_name, contact_name, whatsapp_chat_id, tenant_id, inbox_id, stage, chat_cycle_closed_at") \
        .eq("id", lead_id) \
        .eq("tenant_id", user.id) \
        .single() \
        .execute()

    if not lead_response.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")

    lead = lead_response.data
    if is_chat_mirror_closed_for_lead(lead):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este card está com o ciclo WhatsApp encerrado (finalizado). Use o novo lead na etapa inicial para conversar.",
        )

    whatsapp_chat_id = lead.get("whatsapp_chat_id")

    if not whatsapp_chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este lead não possui WhatsApp vinculado (whatsapp_chat_id).",
        )

    instance_token = get_uazapi_instance_token_for_tenant(
        supabase,
        tenant_id=str(lead.get("tenant_id") or user.id),
        inbox_id=str(lead["inbox_id"]) if lead.get("inbox_id") else None,
    )

    if not instance_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum token Uazapi configurado. Configure uma caixa de entrada com token válido.",
        )

    # Extract the phone number from the JID
    phone_number = whatsapp_chat_id.replace("@s.whatsapp.net", "").replace("@g.us", "")

    # Send the message via Uazapi
    uazapi = get_uazapi_service()
    uazapi_response = None

    try:
        if payload.file_url and payload.media_type:
            # Send media (optionally with caption/text)
            uazapi_response = await uazapi.send_media(
                number=phone_number,
                media_type=payload.media_type,
                file_url=payload.file_url,
                caption=payload.text or "",
                doc_name=payload.file_name,
                instance_token=instance_token,
            )
        else:
            # Send text only
            uazapi_response = await uazapi.send_text(
                number=phone_number,
                text=payload.text,
                instance_token=instance_token,
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao enviar mensagem via Uazapi: {str(e)}",
        )

    # Determine content type and text for saving
    content_type = payload.media_type or "text"
    content_text = payload.text or f"[{content_type.upper()}]"
    caption = payload.text if payload.file_url else None

    # Save the outgoing message to chat_messages
    message_record = {
        "whatsapp_chat_id": whatsapp_chat_id,
        "whatsapp_message_id": uazapi_response.get("messageid", "") if uazapi_response else "",
        "lead_id": lead_id,
        "tenant_id": lead.get("tenant_id"),
        "direction": "outgoing",
        "content_type": content_type,
        "content": content_text,
        "media_url": payload.file_url,
        "media_mimetype": None,
        "media_filename": payload.file_name,
        "caption": caption,
        "sender_name": "CRM Neurix",
        "sender_phone": "",
    }
    # Remove None values
    message_record = {k: v for k, v in message_record.items() if v is not None}

    try:
        saved = supabase.table("chat_messages").insert(message_record).execute()
    except Exception as e:
        # Message was sent but failed to save — log but don't error
        print(f"⚠️ Message sent but failed to save: {e}")
        saved = None

    return {
        "status": "sent",
        "message": "Mensagem enviada com sucesso.",
        "uazapi_response": uazapi_response,
        "saved_message": saved.data[0] if saved and saved.data else message_record,
    }


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: str,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
    eff: EffectiveRole = Depends(get_effective_role),
):
    """
    Retorna um lead se o usuário tiver acesso (tenant ou read_only no funil atribuído).
    Registrado por último para não sombrear rotas estáticas (`/kanban`, `/stages`, …).
    """
    lead_chk = (
        supabase.table("leads")
        .select("*")
        .eq("id", lead_id)
        .limit(1)
        .execute()
    ).data or []
    if not lead_chk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead não encontrado.")
    row0 = lead_chk[0]
    if str(row0["tenant_id"]) != str(user.id):
        allowed = False
        if eff.is_read_only and eff.assigned_funnel_id:
            if str(row0.get("funnel_id") or "") == str(eff.assigned_funnel_id):
                allowed = True
            else:
                pos = (
                    supabase.table("lead_pipeline_positions")
                    .select("id")
                    .eq("lead_id", lead_id)
                    .eq("funnel_id", str(eff.assigned_funnel_id))
                    .eq("board_owner_user_id", str(user.id))
                    .limit(1)
                    .execute()
                )
                if pos.data:
                    allowed = True
        if not allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem acesso a este lead.")
    return LeadResponse(**row0)
