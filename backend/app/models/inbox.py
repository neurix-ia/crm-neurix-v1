"""
Pydantic models — caixas de entrada (inboxes) / Uazapi (Sprint 7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

InboxProvider = Literal["uazapi", "chatwoot"]


class InboxCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    funnel_id: str = Field(..., min_length=1, description="UUID do funil — exatamente um por caixa.")
    provider: InboxProvider = Field("uazapi", description="Canal da caixa: uazapi ou chatwoot.")
    uazapi_settings: dict[str, Any] = Field(default_factory=dict)
    chatwoot_settings: dict[str, Any] = Field(default_factory=dict)


class InboxUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    funnel_id: Optional[str] = Field(None, min_length=1)
    provider: Optional[InboxProvider] = None
    uazapi_settings: Optional[dict[str, Any]] = None
    chatwoot_settings: Optional[dict[str, Any]] = None


class InboxResponse(BaseModel):
    id: str
    tenant_id: str
    funnel_id: str
    name: str
    provider: InboxProvider = "uazapi"
    uazapi_settings: dict[str, Any]
    chatwoot_settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


def parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value is None:
        raise ValueError("Timestamp ausente.")
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def inbox_response_from_row(row: dict[str, Any]) -> InboxResponse:
    us = row.get("uazapi_settings")
    if us is None:
        us = {}
    cw = row.get("chatwoot_settings")
    if cw is None:
        cw = {}
    provider = row.get("provider") or "uazapi"
    return InboxResponse(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        funnel_id=str(row["funnel_id"]),
        name=row["name"],
        provider=provider,
        uazapi_settings=us,
        chatwoot_settings=cw,
        created_at=parse_ts(row.get("created_at")),
        updated_at=parse_ts(row.get("updated_at")),
    )
