"""
Modelos Pydantic — Vendi (vendas de rua / street_sales).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator

MatchStatus = Literal["match", "mismatch", "audio_only", "typed_only", "no_phone"]


class VendiSaleIngest(BaseModel):
    """Payload limpo enviado pelo n8n após STT/upload."""

    tenant_id: str = Field(..., min_length=1)
    seller_name: str = Field(..., min_length=1, max_length=200)
    seller_user_id: Optional[str] = None
    phone_typed: Optional[str] = None
    phone_from_audio: Optional[str] = None
    phone_final: Optional[str] = None
    match_status: Optional[MatchStatus] = None
    transcript: Optional[str] = None
    photo_url: Optional[str] = None
    audio_url: Optional[str] = None
    pao_italiano_qtd: int = Field(0, ge=0)
    pao_integral_qtd: int = Field(0, ge=0)
    sold_at: Optional[datetime] = None
    geolocation: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_display_name: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def require_product_or_phone(self) -> "VendiSaleIngest":
        if self.pao_italiano_qtd + self.pao_integral_qtd <= 0:
            raise ValueError("Informe ao menos 1 unidade de produto.")
        return self


class VendiSaleIngestResponse(BaseModel):
    status: str = "ok"
    sale_id: str
    client_id: Optional[str] = None
    phone_final: str
    match_status: MatchStatus
    message: str = "Venda registrada"


class StreetSaleRow(BaseModel):
    id: str
    tenant_id: str
    seller_name: str
    seller_user_id: Optional[str] = None
    client_id: Optional[str] = None
    order_id: Optional[str] = None
    phone_typed: Optional[str] = None
    phone_from_audio: Optional[str] = None
    phone_final: str
    match_status: MatchStatus
    transcript: Optional[str] = None
    photo_url: Optional[str] = None
    audio_url: Optional[str] = None
    pao_italiano_qtd: int = 0
    pao_integral_qtd: int = 0
    geolocation: Optional[dict[str, Any]] = None
    sold_at: datetime
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    client_display_name: Optional[str] = None

    @classmethod
    def from_row(cls, row: dict[str, Any], client_display_name: Optional[str] = None) -> "StreetSaleRow":
        return cls(
            id=str(row["id"]),
            tenant_id=str(row["tenant_id"]),
            seller_name=str(row.get("seller_name") or ""),
            seller_user_id=str(row["seller_user_id"]) if row.get("seller_user_id") else None,
            client_id=str(row["client_id"]) if row.get("client_id") else None,
            order_id=str(row["order_id"]) if row.get("order_id") else None,
            phone_typed=row.get("phone_typed"),
            phone_from_audio=row.get("phone_from_audio"),
            phone_final=str(row.get("phone_final") or ""),
            match_status=row.get("match_status") or "typed_only",
            transcript=row.get("transcript"),
            photo_url=row.get("photo_url"),
            audio_url=row.get("audio_url"),
            pao_italiano_qtd=int(row.get("pao_italiano_qtd") or 0),
            pao_integral_qtd=int(row.get("pao_integral_qtd") or 0),
            geolocation=row.get("geolocation") if isinstance(row.get("geolocation"), dict) else None,
            sold_at=row["sold_at"],
            created_at=row["created_at"],
            metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
            client_display_name=client_display_name,
        )


class VendiSalesAggregates(BaseModel):
    total_sales: int = 0
    pao_italiano_qtd: int = 0
    pao_integral_qtd: int = 0
    total_units: int = 0


class VendiSalesListResponse(BaseModel):
    sales: list[StreetSaleRow]
    aggregates: VendiSalesAggregates
    from_ts: Optional[datetime] = None
    to_ts: Optional[datetime] = None


class VendiActiveClient(BaseModel):
    client_id: str
    display_name: str
    phone: Optional[str] = None
    last_sale_at: datetime
    sales_count: int = 0
    total_units: int = 0
