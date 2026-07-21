"""
N8n Vendi ingest — POST /api/n8n/vendi
Auth: X-CRM-API-Key (verify_n8n_api_key).

Recebe payload já processado pelo workflow (STT, Storage URLs, telefone canônico).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client as SupabaseClient

from app.dependencies import get_supabase, verify_n8n_api_key
from app.models.vendi import MatchStatus, VendiSaleIngest, VendiSaleIngestResponse
from app.observability import get_logger
from app.services.phone_normalize import digits_only
from app.services.webhook_lead_context import resolve_or_create_crm_client

router = APIRouter()
logger = get_logger("n8n_vendi")


def _resolve_match_and_phone(payload: VendiSaleIngest) -> tuple[str, MatchStatus]:
    typed = digits_only(payload.phone_typed or "")
    from_audio = digits_only(payload.phone_from_audio or "")
    explicit = digits_only(payload.phone_final or "")

    if explicit:
        phone_final = explicit
    elif from_audio:
        phone_final = from_audio
    elif typed:
        phone_final = typed
    else:
        phone_final = ""

    if payload.match_status:
        match_status: MatchStatus = payload.match_status
    elif typed and from_audio:
        match_status = "match" if typed == from_audio else "mismatch"
    elif from_audio and not typed:
        match_status = "audio_only"
    elif typed and not from_audio:
        match_status = "typed_only"
    else:
        match_status = "no_phone"

    if not phone_final and match_status != "no_phone":
        match_status = "no_phone"

    return phone_final, match_status


@router.post("/vendi", response_model=VendiSaleIngestResponse)
async def ingest_vendi_sale(
    payload: VendiSaleIngest,
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Persiste venda de rua + upsert de cliente ativo por phone_final."""
    phone_final, match_status = _resolve_match_and_phone(payload)

    if not phone_final:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="phone_final obrigatório (via digitado, áudio ou explícito).",
        )

    client_id: Optional[str] = None
    display = (payload.client_display_name or "").strip() or phone_final
    try:
        client_id = resolve_or_create_crm_client(
            supabase,
            tenant_id=payload.tenant_id,
            sender_phone_raw=phone_final,
            sender_name=display,
        )
    except Exception as exc:
        logger.warning(
            "vendi_client_upsert_failed",
            extra={"tenant_id": payload.tenant_id, "error": str(exc)},
        )

    sold_at = payload.sold_at or datetime.now(timezone.utc)
    if sold_at.tzinfo is None:
        sold_at = sold_at.replace(tzinfo=timezone.utc)

    row = {
        "tenant_id": payload.tenant_id,
        "seller_name": payload.seller_name.strip()[:200],
        "seller_user_id": payload.seller_user_id or None,
        "client_id": client_id,
        "phone_typed": digits_only(payload.phone_typed or "") or None,
        "phone_from_audio": digits_only(payload.phone_from_audio or "") or None,
        "phone_final": phone_final,
        "match_status": match_status,
        "transcript": payload.transcript,
        "photo_url": payload.photo_url,
        "audio_url": payload.audio_url,
        "pao_italiano_qtd": payload.pao_italiano_qtd,
        "pao_integral_qtd": payload.pao_integral_qtd,
        "geolocation": payload.geolocation,
        "sold_at": sold_at.isoformat(),
        "metadata": payload.metadata or {},
    }

    try:
        res = supabase.table("street_sales").insert(row).execute()
    except Exception as exc:
        logger.error("vendi_insert_failed", extra={"error": str(exc)})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao gravar venda: {exc}",
        ) from exc

    data = (res.data or [None])[0]
    if not data:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Insert street_sales sem retorno.",
        )

    sale_id = str(data["id"])
    logger.info(
        "vendi_sale_ingested",
        extra={
            "sale_id": sale_id,
            "tenant_id": payload.tenant_id,
            "match_status": match_status,
            "client_id": client_id,
        },
    )

    return VendiSaleIngestResponse(
        sale_id=sale_id,
        client_id=client_id,
        phone_final=phone_final,
        match_status=match_status,
    )
