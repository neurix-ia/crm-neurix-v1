"""
Pydantic models for the weekly customer-service report feature.

Ingested by n8n via /api/n8n/reports/* endpoints. Mirrors the columns
defined in migrations/017_weekly_reports.sql.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class MetricsModel(BaseModel):
    """Aggregated weekly metrics (stored as JSONB in weekly_reports.metrics)."""

    total_conversas: int
    nota_media_ia: float
    nota_media_humano: float
    tempo_resp_humano_min: float
    tempo_resp_ia_seg: float
    horas_economizadas: float


class AcaoModel(BaseModel):
    """A single recommended action item."""

    acao: str
    contexto: str = ""


class WeeklyReportIn(BaseModel):
    """Payload for POST /reports/weekly — upserted into weekly_reports."""

    tenant_id: str
    week_key: str
    week_start: datetime
    week_end: datetime
    metrics: MetricsModel
    problema_principal: str
    solucao_recomendada: str
    acoes: list[AcaoModel] = Field(default_factory=list)
    sheet_ref: dict = Field(default_factory=dict)


class AgentReportIn(BaseModel):
    """Payload for POST /reports/agent-improvement — upserted into agent_improvement_reports."""

    agent_key: str
    agent_name: str
    tenant_id: str | None = None
    week_key: str
    week_start: datetime
    week_end: datetime
    severidade: str = "media"
    problema: str
    recomendacoes: list[str] = Field(default_factory=list)
