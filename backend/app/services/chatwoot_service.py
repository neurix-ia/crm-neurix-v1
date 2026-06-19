"""
Chatwoot Service — HTTP client para a Application API do Chatwoot.

Credenciais são por-inbox (inboxes.chatwoot_settings):
  base_url, account_id, inbox_id (id do inbox no Chatwoot), api_access_token.

Auth: header `api_access_token`. Base de rotas: {base_url}/api/v1/accounts/{account_id}.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx


class ChatwootConfigError(ValueError):
    """chatwoot_settings incompleto/ausente."""


class ChatwootService:
    def __init__(self, base_url: str, account_id: str, api_access_token: str):
        self.base_url = str(base_url or "").rstrip("/")
        self.account_id = str(account_id or "").strip()
        self.api_access_token = str(api_access_token or "").strip()
        if not (self.base_url and self.account_id and self.api_access_token):
            raise ChatwootConfigError("Chatwoot: base_url, account_id e api_access_token são obrigatórios.")

    @classmethod
    def from_settings(cls, settings: dict[str, Any] | None) -> "ChatwootService":
        s = settings or {}
        return cls(
            base_url=s.get("base_url", ""),
            account_id=s.get("account_id", ""),
            api_access_token=s.get("api_access_token", ""),
        )

    def _headers(self) -> dict:
        return {"api_access_token": self.api_access_token, "Content-Type": "application/json"}

    def _account_url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/accounts/{self.account_id}{path}"

    # ── Conexão / validação ──

    async def verify(self) -> list[dict]:
        """Valida credenciais listando as etiquetas da conta. Levanta em falha."""
        return await self.list_labels()

    async def list_labels(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(self._account_url("/labels"), headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            # Chatwoot retorna {"payload": [...]} ou lista direta dependendo da versão.
            if isinstance(data, dict):
                return data.get("payload", []) or []
            return data or []

    # ── Conversa ──

    async def get_conversation(self, conversation_id: str | int) -> dict:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                self._account_url(f"/conversations/{conversation_id}"),
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def set_conversation_labels(self, conversation_id: str | int, labels: list[str]) -> dict:
        """Substitui o conjunto de etiquetas da conversa (CRM → Chatwoot, troca atômica)."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                self._account_url(f"/conversations/{conversation_id}/labels"),
                json={"labels": labels},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    # ── Envio ──

    async def send_text(self, conversation_id: str | int, content: str) -> dict:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                self._account_url(f"/conversations/{conversation_id}/messages"),
                json={"content": content, "message_type": "outgoing"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_attachment(
        self,
        conversation_id: str | int,
        file_bytes: bytes,
        filename: str,
        mimetype: str,
        content: Optional[str] = None,
    ) -> dict:
        """Envia mídia via multipart (attachments[])."""
        data = {"message_type": "outgoing"}
        if content:
            data["content"] = content
        files = {"attachments[]": (filename, file_bytes, mimetype)}
        headers = {"api_access_token": self.api_access_token}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self._account_url(f"/conversations/{conversation_id}/messages"),
                data=data,
                files=files,
                headers=headers,
            )
            resp.raise_for_status()
            return resp.json()
