"""Cliente HTTP para instâncias n8n (Public API v1)."""

from __future__ import annotations

import json
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
    def __init__(self, config: N8nInstanceConfig, *, verify_ssl: bool = True) -> None:
        self.config = config
        self._base = config.base_url.rstrip("/")
        self._verify_ssl = verify_ssl

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

    async def list_executions(
        self,
        *,
        workflow_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"limit": str(min(limit, 250))}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return await self._get_json("/api/v1/executions", params=params)

    async def get_execution(self, execution_id: str, *, include_data: bool = False) -> dict[str, Any]:
        params = {"includeData": "true" if include_data else "false"}
        return await self._get_json(f"/api/v1/executions/{execution_id}", params=params)

    async def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/workflows/{workflow_id}")

    async def get_folder(self, project_id: str, folder_id: str) -> dict[str, Any]:
        return await self._get_json(f"/api/v1/projects/{project_id}/folders/{folder_id}")

    async def list_workflows(
        self,
        *,
        active: Optional[bool] = None,
        project_id: Optional[str] = None,
        limit: int = 250,
        cursor: Optional[str] = None,
        exclude_pinned_data: bool = True,
        include_folders: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"limit": str(min(limit, 250))}
        if active is not None:
            params["active"] = "true" if active else "false"
        if project_id:
            params["projectId"] = project_id
        if cursor:
            params["cursor"] = cursor
        if exclude_pinned_data:
            params["excludePinnedData"] = "true"
        if include_folders:
            params["includeFolders"] = "true"
        return await self._get_json("/api/v1/workflows", params=params)

    async def list_projects(self, *, limit: int = 100, cursor: Optional[str] = None) -> dict[str, Any]:
        params: dict[str, str] = {"limit": str(min(limit, 250))}
        if cursor:
            params["cursor"] = cursor
        return await self._get_json("/api/v1/projects", params=params)

    async def list_folders(
        self,
        project_id: str,
        *,
        take: int = 100,
        skip: int = 0,
        select_fields: Optional[list[str]] = None,
        parent_folder_id: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"take": str(take), "skip": str(skip)}
        if select_fields:
            params["select"] = json.dumps(select_fields)
        if parent_folder_id is not None:
            params["filter"] = json.dumps({"parentFolderId": parent_folder_id})
        return await self._get_json(f"/api/v1/projects/{project_id}/folders", params=params)

    async def _get_json(self, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
        url = f"{self._base}{path}"
        async with httpx.AsyncClient(timeout=N8N_REQUEST_TIMEOUT, verify=self._verify_ssl) as client:
            response = await client.get(url, headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError(f"Resposta inesperada de {url}")
            return data
