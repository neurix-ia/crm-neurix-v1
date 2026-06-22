"""
N8n Reports Router — /api/n8n/reports/*
Ingestion + WhatsApp notification for the weekly customer-service report feature.
Auth: API key via X-CRM-API-Key header (verify_n8n_api_key), no JWT.

Endpoints:
  - POST /reports/weekly                 — upsert weekly_reports (status=published)
  - POST /reports/agent-improvement      — upsert agent_improvement_reports
  - GET  /reports/pending-notifications  — published reports not yet notified
  - POST /reports/{report_id}/notify     — send WhatsApp + mark notified_at
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from supabase import Client as SupabaseClient

from app.config import Settings, get_settings
from app.dependencies import get_supabase, verify_n8n_api_key
from app.models.weekly_report import AgentReportIn, WeeklyReportIn
from app.observability import get_logger
from app.services.uazapi_service import get_uazapi_service
from app.services.report_hours import compute_horas_economizadas

router = APIRouter()
logger = get_logger("n8n_reports")


def _iso(dt: datetime) -> str:
    """Serialize a datetime to an ISO string for Supabase JSON payloads."""
    return dt.isoformat()


def _fetch_notify_whatsapp(supabase: SupabaseClient, tenant_id: str) -> str | None:
    """Return the tenant's configured WhatsApp notification number, or None."""
    try:
        res = (
            supabase.table("client_report_config")
            .select("notify_whatsapp")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    row = (res.data or [None])[0]
    if not row:
        return None
    value = str(row.get("notify_whatsapp") or "").strip()
    return value or None


def _fetch_agent_keys(supabase: SupabaseClient, tenant_id: str) -> list[str]:
    """agent_keys (workflow ids do n8n) configurados para o tenant."""
    try:
        res = (
            supabase.table("client_report_config")
            .select("agent_keys")
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows and isinstance(rows[0].get("agent_keys"), list):
            return [str(k) for k in rows[0]["agent_keys"] if k]
    except Exception:
        logger.warning("fetch_agent_keys_failed", extra={"tenant_id": tenant_id})
    return []


@router.post("/reports/weekly")
async def ingest_weekly_report(
    payload: WeeklyReportIn,
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    """Upsert a weekly report keyed by (tenant_id, week_key); publishes it."""
    row = {
        "tenant_id": payload.tenant_id,
        "week_key": payload.week_key,
        "week_start": _iso(payload.week_start),
        "week_end": _iso(payload.week_end),
        "metrics": payload.metrics.model_dump(),
        "problema_principal": payload.problema_principal,
        "solucao_recomendada": payload.solucao_recomendada,
        "acoes": [a.model_dump() for a in payload.acoes],
        "sheet_ref": payload.sheet_ref,
        "status": "published",
    }

    # Horas economizadas: o backend calcula a partir das execuções do n8n
    # (soma os agent_keys do tenant na janela). O valor enviado pelo n8n é ignorado.
    agent_keys = _fetch_agent_keys(supabase, payload.tenant_id)
    if agent_keys:
        try:
            horas = await compute_horas_economizadas(
                settings,
                agent_keys=agent_keys,
                week_start=payload.week_start,
                week_end=payload.week_end,
            )
            row["metrics"]["horas_economizadas"] = horas
        except Exception:
            logger.warning(
                "horas_economizadas_failed", extra={"tenant_id": payload.tenant_id}
            )

    try:
        supabase.table("weekly_reports").upsert(
            row, on_conflict="tenant_id,week_key"
        ).execute()
    except Exception as exc:
        logger.exception("weekly_report_upsert_failed", extra={"week_key": payload.week_key})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao salvar relatório semanal: {exc}",
        ) from exc

    return {"status": "ok", "week_key": payload.week_key}


@router.post("/reports/agent-improvement")
async def ingest_agent_report(
    payload: AgentReportIn,
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Upsert an agent-improvement report keyed by (agent_key, week_key)."""
    row = {
        "agent_key": payload.agent_key,
        "agent_name": payload.agent_name,
        "tenant_id": payload.tenant_id,
        "week_key": payload.week_key,
        "week_start": _iso(payload.week_start),
        "week_end": _iso(payload.week_end),
        "severidade": payload.severidade,
        "problema": payload.problema,
        "recomendacoes": payload.recomendacoes,
    }
    try:
        supabase.table("agent_improvement_reports").upsert(
            row, on_conflict="agent_key,week_key"
        ).execute()
    except Exception as exc:
        logger.exception("agent_report_upsert_failed", extra={"agent_key": payload.agent_key})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao salvar relatório de agente: {exc}",
        ) from exc

    return {"status": "ok"}


@router.get("/reports/pending-notifications")
async def pending_notifications(
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """List published weekly reports that have not been notified yet."""
    try:
        res = (
            supabase.table("weekly_reports")
            .select("id, tenant_id, week_key, status, notified_at")
            .eq("status", "published")
            .is_("notified_at", "null")
            .execute()
        )
    except Exception as exc:
        logger.exception("pending_notifications_query_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao consultar notificações pendentes: {exc}",
        ) from exc

    out: list[dict] = []
    for row in res.data or []:
        tenant_id = str(row["tenant_id"])
        out.append(
            {
                "id": str(row["id"]),
                "tenant_id": tenant_id,
                "week_key": row.get("week_key"),
                "notify_whatsapp": _fetch_notify_whatsapp(supabase, tenant_id),
            }
        )
    return out


def _build_notification_message(
    *, week_key: str, problema_principal: str, frontend_url: str
) -> str:
    deep_link = f"{frontend_url.rstrip('/')}/relatorios?wk={week_key}"
    return (
        "📊 Relatório semanal pronto!\n\n"
        f"Olá! Seu relatório de atendimento ({week_key}) já está disponível.\n"
        f"👉 {deep_link}\n\n"
        f"Resumo: {problema_principal}"
    )


@router.post("/reports/{report_id}/notify")
async def notify_report(
    report_id: str,
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    """Send the WhatsApp notification for a weekly report and mark notified_at."""
    try:
        res = (
            supabase.table("weekly_reports")
            .select("id, tenant_id, week_key, problema_principal, notified_at")
            .eq("id", report_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.exception("notify_report_lookup_failed", extra={"report_id": report_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao carregar relatório: {exc}",
        ) from exc

    report = (res.data or [None])[0]
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório semanal não encontrado.",
        )

    tenant_id = str(report["tenant_id"])
    notify_whatsapp = _fetch_notify_whatsapp(supabase, tenant_id)
    if not notify_whatsapp:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Tenant não possui notify_whatsapp configurado em client_report_config — "
                "não é possível notificar."
            ),
        )

    message = _build_notification_message(
        week_key=str(report.get("week_key") or ""),
        problema_principal=str(report.get("problema_principal") or ""),
        frontend_url=settings.PUBLIC_FRONTEND_URL,
    )

    uazapi = get_uazapi_service()
    try:
        await uazapi.send_text(
            number=notify_whatsapp,
            text=message,
            instance_token=settings.UAZAPI_INSTANCE_TOKEN or None,
        )
    except Exception as exc:
        logger.exception("notify_report_send_failed", extra={"report_id": report_id})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Falha ao enviar notificação WhatsApp: {exc}",
        ) from exc

    notified_at = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("weekly_reports").update({"notified_at": notified_at}).eq(
            "id", report_id
        ).execute()
    except Exception:
        logger.exception("notify_report_mark_failed", extra={"report_id": report_id})

    return {"status": "ok"}
