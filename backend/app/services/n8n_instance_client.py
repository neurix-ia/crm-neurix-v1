"""Cliente HTTP para instâncias n8n (Public API v1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx

N8N_REQUEST_TIMEOUT = 30.0


@dataclass(frozen=True)
class N8nInstanceConfig:
    id: str
    label: str
    base_url: str
    api_key: str


class N8nInstanceClient:
    def __init__(self, config: N8nInstanceConfig) -> None:
        self.config = config
        self._base = config.base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "X-N8N-API-KEY": self.config.api_key,
            "Accept": "application/json",
        }

    async def get_insights_summary(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> dict[str, Any]:
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        return await self._get_json("/api/v1/insights/summary", params=params)

    async def get_insights_by_workflow(
        self,
        start_date: datetime,
        end_date: datetime,
        *,
        sort_by: str = "failed:desc",
        take: int = 50,
        skip: int = 0,
    ) -> dict[str, Any]:
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
            "sortBy": sort_by,
            "take": str(take),
            "skip": str(skip),
        }
        return await self._get_json("/api/v1/insights/by-workflow", params=params)

    async def _get_json(self, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=N8N_REQUEST_TIMEOUT) as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError(f"Resposta inesperada de {url}")
            return data
