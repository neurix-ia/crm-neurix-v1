"""Neurix HQ — DTOs para command center (superadmin)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

HqLevel = Literal["green", "yellow", "red", "gray"]
HqPeriod = Literal["24h", "7d", "30d"]


class HqAlert(BaseModel):
    level: HqLevel
    message: str
    module: str
    link: Optional[str] = None


class HqModuleStatus(BaseModel):
    id: str
    label: str
    level: HqLevel
    summary: str
    alerts: list[HqAlert] = Field(default_factory=list)
    enabled: bool = True


class HqSummaryResponse(BaseModel):
    modules: list[HqModuleStatus]
    generated_at: datetime
    cached: bool = False


class HqMetricValue(BaseModel):
    value: float
    unit: str = "count"
    deviation: Optional[float] = None


class N8nInstanceMetrics(BaseModel):
    id: str
    label: str
    status: Literal["ok", "error"] = "ok"
    error_message: Optional[str] = None
    total_executions: int = 0
    failed_executions: int = 0
    failure_rate: float = 0.0
    time_saved_minutes: float = 0.0
    average_run_time_seconds: float = 0.0
    metrics_raw: Optional[dict] = None


class N8nOverviewResponse(BaseModel):
    period: HqPeriod
    start_date: datetime
    end_date: datetime
    instances: list[N8nInstanceMetrics]
    consolidated: N8nInstanceMetrics
    cached: bool = False
    generated_at: datetime


class N8nWorkflowErrorRow(BaseModel):
    instance_id: str
    instance_label: str
    workflow_id: Optional[str]
    workflow_name: str
    project_name: Optional[str] = None
    total_executions: int = 0
    failed_executions: int = 0
    failure_rate: float = 0.0
    average_run_time_seconds: float = 0.0
    last_execution_id: Optional[str] = None
    last_failed_at: Optional[datetime] = None


class N8nExecutionErrorDetail(BaseModel):
    instance_id: str
    instance_label: str
    instance_base_url: str
    workflow_id: Optional[str]
    workflow_name: Optional[str]
    execution_id: str
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    node_name: Optional[str] = None
    message: str
    description: Optional[str] = None
    stack: Optional[str] = None
    n8n_execution_url: Optional[str] = None


class N8nWorkflowErrorsResponse(BaseModel):
    period: HqPeriod
    rows: list[N8nWorkflowErrorRow]
    cached: bool = False
    generated_at: datetime
