"""Leitura sob demanda da planilha de conversas (Google Sheets) + cache Redis.

Mantém as transcrições no Google (fonte bruta) — o CRM só lê a janela da semana
quando o cliente abre "ver detalhes". As credenciais são uma service account
(env GOOGLE_SA_JSON), nunca expostas ao frontend. gspread/google-auth são
importados de forma preguiçosa para não pesar no boot nem nos testes.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def week_bounds_from_key(week_key: str, tz: str = "America/Sao_Paulo") -> tuple[datetime, datetime]:
    """ISO week key 'YYYY-Www' -> (segunda 00:00:00, domingo 23:59:59) tz-aware."""
    zone = ZoneInfo(tz)
    monday = datetime.strptime(f"{week_key}-1", "%G-W%V-%u").replace(tzinfo=zone)
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = (week_start + timedelta(days=6)).replace(hour=23, minute=59, second=59, microsecond=0)
    return week_start, week_end


def _read_sheet_sync(sa_json: str, spreadsheet_id: str, worksheet: str) -> list[dict]:
    """Leitura síncrona via gspread (rodada em executor)."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=_SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(spreadsheet_id).worksheet(worksheet)
    return ws.get_all_records()


def _in_window(value, week_start: datetime, week_end: datetime) -> bool:
    try:
        d = datetime.strptime(str(value).strip(), "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return False
    return week_start.date() <= d <= week_end.date()


async def read_week_rows(supabase, redis, *, tenant_id: str, week_start: datetime, week_end: datetime) -> list[dict]:
    """Linhas da planilha do tenant dentro da janela [week_start, week_end]."""
    cfg_res = (
        supabase.table("client_report_config")
        .select("*")
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    cfg_rows = getattr(cfg_res, "data", None) or []
    if not cfg_rows:
        return []
    cfg = cfg_rows[0]
    if not cfg.get("enabled", True):
        return []

    cache_key = f"report:conv:{tenant_id}:{week_start.strftime('%Y%m%d')}"
    if redis is not None:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)

    settings = get_settings()
    if not settings.GOOGLE_SA_JSON:
        return []

    spreadsheet_id = cfg["spreadsheet_id"]
    worksheet = cfg.get("worksheet", "Conversas")
    loop = asyncio.get_event_loop()
    all_rows = await loop.run_in_executor(
        None, _read_sheet_sync, settings.GOOGLE_SA_JSON, spreadsheet_id, worksheet
    )

    date_col = cfg.get("date_column", "data")
    filtered = [r for r in all_rows if _in_window(r.get(date_col, ""), week_start, week_end)]

    if redis is not None:
        await redis.set(cache_key, json.dumps(filtered, ensure_ascii=False), ex=3600)
    return filtered
