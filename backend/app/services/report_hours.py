"""Cálculo de "horas economizadas" por agente, a partir das execuções do n8n.

Reaproveita o cliente/instâncias do Neurix HQ (parse_n8n_instances + list_executions).
Soma as execuções com status=success de TODOS os workflows do agente (agent_keys)
dentro da janela da semana, e multiplica por um tempo fixo por execução (2 min).

Mantido fora do workflow n8n de propósito: pagina corretamente (o node do n8n
ficava limitado a 250 sem paginar) e centraliza a API key do n8n no backend.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings
from app.observability import get_logger
from app.services.hq_n8n_service import _parse_iso_dt, parse_n8n_instances
from app.services.n8n_instance_client import N8nInstanceClient

logger = get_logger("report_hours")

MINUTES_PER_EXECUTION = 2
_MAX_PAGES = 40  # 40 x 100 = até 4000 execuções/agente/instância


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def count_success_executions(
    settings: Settings,
    *,
    agent_keys: list[str],
    week_start: datetime,
    week_end: datetime,
) -> int:
    """Conta execuções success dos agent_keys na janela [week_start, week_end]."""
    instances = parse_n8n_instances(settings)
    if not instances or not agent_keys:
        return 0
    start = _aware(week_start)
    end = _aware(week_end)
    verify_ssl = getattr(settings, "N8N_SSL_VERIFY", True)
    total = 0

    for cfg in instances:
        client = N8nInstanceClient(cfg, verify_ssl=verify_ssl)
        for wid in agent_keys:
            cursor: str | None = None
            for _ in range(_MAX_PAGES):
                try:
                    payload = await client.list_executions(
                        workflow_id=str(wid), status="success", limit=100, cursor=cursor
                    )
                except Exception as exc:
                    logger.warning(
                        "list_executions falhou instance=%s wf=%s: %s", cfg.id, wid, exc
                    )
                    break
                items = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(items, list) or not items:
                    break
                stop = False
                for ex in items:
                    st = _parse_iso_dt(ex.get("startedAt"))
                    if st is None:
                        continue
                    if st < start:
                        # resultados vêm do mais recente p/ o mais antigo → pode parar
                        stop = True
                        continue
                    if st > end:
                        continue
                    total += 1
                if stop:
                    break
                cursor = payload.get("nextCursor") if isinstance(payload, dict) else None
                if not cursor:
                    break
    return total


async def compute_horas_economizadas(
    settings: Settings,
    *,
    agent_keys: list[str],
    week_start: datetime,
    week_end: datetime,
) -> float:
    """Horas economizadas = nº de execuções success na janela × 2 min / 60."""
    count = await count_success_executions(
        settings, agent_keys=agent_keys, week_start=week_start, week_end=week_end
    )
    return round(count * MINUTES_PER_EXECUTION / 60.0, 2)
