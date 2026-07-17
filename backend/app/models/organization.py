"""
Pydantic models — organizações e membros (Sprint 3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


class OrganizationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    menu_config: Optional[dict[str, bool]] = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.name is None and self.menu_config is None:
            raise ValueError("Informe name e/ou menu_config.")
        return self


class OrganizationResponse(BaseModel):
    id: str
    name: str
    menu_config: dict[str, bool] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MenuCatalogItem(BaseModel):
    key: str
    label: str
    route: str
    icon: str


class OrganizationMemberCreate(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: Literal["admin", "read_only"]
    assigned_funnel_id: Optional[str] = None

    @model_validator(mode="after")
    def funnel_rule(self):
        if self.role == "read_only":
            if not self.assigned_funnel_id:
                raise ValueError("assigned_funnel_id é obrigatório para read_only.")
        elif self.assigned_funnel_id is not None:
            raise ValueError("assigned_funnel_id deve ser omitido para administrador.")
        return self


class OrganizationMemberUpdate(BaseModel):
    role: Optional[Literal["admin", "read_only"]] = None
    assigned_funnel_id: Optional[str] = None

    @model_validator(mode="after")
    def funnel_rule(self):
        if self.role == "admin" and self.assigned_funnel_id is not None:
            raise ValueError("assigned_funnel_id deve ser omitido ao definir role admin.")
        return self


class OrganizationMemberResponse(BaseModel):
    id: str
    organization_id: str
    user_id: str
    role: str
    assigned_funnel_id: Optional[str] = None
    created_at: datetime


class OrganizationFunnelItem(BaseModel):
    """Funil atribuível na org (tenant = membro admin). Sprint 6 — console / dropdowns."""

    id: str
    tenant_id: str
    name: str
    created_at: datetime
    updated_at: datetime
