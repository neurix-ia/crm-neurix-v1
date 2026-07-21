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


class EvalSuggestionModel(BaseModel):
    """Uma sugestão de melhoria gerada por LLM a partir do resultado do eval."""

    severidade: str = "media"  # alta | media | baixa
    problema: str
    recomendacao: str = ""


class AgentEvalRunIn(BaseModel):
    """Payload for POST /reports/agent-eval — upserted into agent_eval_runs.

    `result` é o JSON integral devolvido pelo deep-eval em /result/{job_id}
    (chaves test_cases + summary). pass_rate/total/passed são denormalizados
    do summary para listagem barata sem carregar o JSONB.
    """

    agent_key: str
    agent_name: str
    job_id: str
    mode: str = "baseline"  # baseline | mangle
    pass_rate: float | None = None
    total: int = 0
    passed: int = 0
    result: dict = Field(default_factory=dict)
    suggestions: list[EvalSuggestionModel] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
