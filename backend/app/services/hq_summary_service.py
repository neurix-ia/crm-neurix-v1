"""Agregador semáforo Neurix HQ."""

from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.config import Settings
from app.models.hq import HqAlert, HqLevel, HqModuleStatus, HqPeriod, HqSummaryResponse
from app.services.hq_n8n_service import HqN8nService, parse_n8n_instances


def _automation_level(overview_failed: int, failure_rate: float, instances_ok: int, instances_total: int) -> HqLevel:
    if instances_total == 0:
        return "gray"
    if instances_ok == 0:
        return "red"
    if failure_rate >= 5 or overview_failed >= 50:
        return "red"
    if failure_rate >= 1 or overview_failed >= 5:
        return "yellow"
    return "green"


class HqSummaryService:
    def __init__(self, settings: Settings, redis: aioredis.Redis | None = None) -> None:
        self.settings = settings
        self.redis = redis
        self.n8n = HqN8nService(settings, redis)

    async def get_summary(self, period: HqPeriod = "7d") -> HqSummaryResponse:
        now = datetime.now(timezone.utc)
        instances = parse_n8n_instances(self.settings)
        modules: list[HqModuleStatus] = []

        if not instances:
            modules.append(
                HqModuleStatus(
                    id="automation",
                    label="Automação",
                    level="gray",
                    summary="Configure N8N_INSTANCES no backend",
                    alerts=[
                        HqAlert(
                            level="gray",
                            message="N8N_INSTANCES não configurado — adicione credenciais das instâncias n8n.",
                            module="automation",
                        )
                    ],
                )
            )
        else:
            overview = await self.n8n.get_overview(period)
            errors = await self.n8n.get_workflow_errors(period, limit=5)
            c = overview.consolidated
            ok_count = sum(1 for i in overview.instances if i.status == "ok")
            level = _automation_level(c.failed_executions, c.failure_rate, ok_count, len(overview.instances))

            alerts: list[HqAlert] = []
            for inst in overview.instances:
                if inst.status == "error":
                    alerts.append(
                        HqAlert(
                            level="red",
                            message=f"{inst.label}: {inst.error_message or 'indisponível'}",
                            module="automation",
                        )
                    )
            for row in errors.rows[:3]:
                alerts.append(
                    HqAlert(
                        level="red" if row.failed_executions >= 10 else "yellow",
                        message=f"{row.workflow_name} ({row.instance_label}): {row.failed_executions} falha(s)",
                        module="automation",
                    )
                )

            summary_text = (
                f"{c.total_executions:,} exec. · {c.failed_executions} falhas · {c.failure_rate}% taxa"
                if c.total_executions
                else "Sem execuções no período"
            )
            modules.append(
                HqModuleStatus(
                    id="automation",
                    label="Automação",
                    level=level,
                    summary=summary_text,
                    alerts=alerts,
                )
            )

        modules.extend(
            [
                HqModuleStatus(
                    id="commercial",
                    label="Comercial",
                    level="gray",
                    summary="Em breve",
                    enabled=False,
                ),
                HqModuleStatus(
                    id="finance",
                    label="Financeiro",
                    level="gray",
                    summary="Em breve",
                    enabled=False,
                ),
                HqModuleStatus(
                    id="tasks",
                    label="Tarefas",
                    level="gray",
                    summary="Em breve (Linear)",
                    enabled=False,
                ),
            ]
        )

        return HqSummaryResponse(modules=modules, generated_at=now)
