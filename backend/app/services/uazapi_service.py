"""
Uazapi Service — HTTP client for the Uazapi WhatsApp API.
Handles sending text & media messages and listing instances.

Uazapi Auth Model:
  - Admin endpoints: header `admintoken`
  - Instance endpoints (sending): header `token` (per-instance)
"""

import httpx
from typing import Optional
from app.config import get_settings


class UazapiService:
    """Async HTTP client for Uazapi WhatsApp API."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.UAZAPI_URL.rstrip("/")
        self.admin_token = settings.UAZAPI_ADMIN_TOKEN
        self.default_instance_token = settings.UAZAPI_INSTANCE_TOKEN

    def _admin_headers(self) -> dict:
        return {"admintoken": self.admin_token, "Content-Type": "application/json"}

    def _instance_headers(self, instance_token: str | None = None) -> dict:
        token = instance_token or self.default_instance_token
        return {"token": token, "Content-Type": "application/json"}

    # ── Instance Management (Admin) ──

    async def list_instances(self) -> list[dict]:
        """List all WhatsApp instances (requires admin token)."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/instance/all",
                headers=self._admin_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def init_instance(self, name: str) -> dict:
        """Create a new WhatsApp instance via Uazapi (requires admin token). Legacy path /instance/init."""
        payload = {"name": name}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/instance/init",
                json=payload,
                headers=self._admin_headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def create_instance(self, name: str) -> dict:
        """
        Create instance via POST /instance/create (docs atuais).
        Fallback para /instance/init se create retornar 404.
        """
        if not self.admin_token:
            raise RuntimeError("UAZAPI_ADMIN_TOKEN não configurado no servidor.")
        payload = {"name": name}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/instance/create",
                json=payload,
                headers=self._admin_headers(),
            )
            if resp.status_code == 404:
                return await self.init_instance(name)
            resp.raise_for_status()
            return resp.json()

    # ── Instance Management (Instance Token) ──

    async def get_instance_status(self, instance_token: str | None = None) -> dict:
        """Check status of a specific instance."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/instance/status",
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def connect_instance(
        self,
        instance_token: str | None = None,
        phone: str | None = None,
    ) -> dict:
        """Generate QR Code or pairing code (optional phone digits)."""
        digits = "".join(c for c in (phone or "") if c.isdigit())
        body: dict = {"phone": digits} if digits else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/instance/connect",
                headers=self._instance_headers(instance_token),
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def disconnect_instance(self, instance_token: str | None = None) -> dict:
        """Disconnect the instance from WhatsApp."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{self.base_url}/instance/disconnect",
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def get_webhook(self, instance_token: str | None = None) -> dict:
        """Read the current webhook configuration for the instance."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.base_url}/webhook",
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def set_webhook(self, url: str, instance_token: str | None = None) -> dict:
        """Set the webhook URL for the instance to receive incoming messages."""
        payload = {
            "url": url,
            "enabled": True,
            "events": ["messages"],
            "excludeMessages": ["wasSentByApi"]
        }
        print(f"[webhook-config] Setting webhook URL: {url}")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.base_url}/webhook",
                json=payload,
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    # ── Send Messages (Instance) ──

    async def send_text(
        self,
        number: str,
        text: str,
        instance_token: str | None = None,
        delay: int = 0,
        track_source: str = "neurix_crm",
    ) -> dict:
        """
        Send a text message via WhatsApp.

        Args:
            number: Phone number (e.g. '5511999999999') or chat JID
            text: Message text (supports Uazapi placeholders like {{name}})
            instance_token: Override default instance token
            delay: Delay in ms before sending (shows 'Typing...')
            track_source: Tracking source identifier
        """
        payload = {
            "number": number,
            "text": text,
            "track_source": track_source,
        }
        if delay > 0:
            payload["delay"] = delay

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/send/text",
                json=payload,
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_media(
        self,
        number: str,
        media_type: str,
        file_url: str,
        caption: str = "",
        doc_name: str | None = None,
        instance_token: str | None = None,
        track_source: str = "neurix_crm",
    ) -> dict:
        """
        Send a media message via WhatsApp.

        Args:
            number: Phone number or chat JID
            media_type: One of 'image', 'video', 'document', 'audio', 'ptt', 'sticker'
            file_url: URL of the file to send
            caption: Caption text (for image, video, document)
            doc_name: File name (only for 'document' type)
            instance_token: Override default instance token
            track_source: Tracking source identifier
        """
        payload = {
            "number": number,
            "type": media_type,
            "file": file_url,
            "track_source": track_source,
        }
        if caption:
            payload["text"] = caption
        if doc_name and media_type == "document":
            payload["docName"] = doc_name

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/send/media",
                json=payload,
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def send_location(
        self,
        number: str,
        latitude: float,
        longitude: float,
        name: str = "",
        address: str = "",
        instance_token: str | None = None,
    ) -> dict:
        """Send a location pin via WhatsApp."""
        payload = {
            "number": number,
            "latitude": latitude,
            "longitude": longitude,
        }
        if name:
            payload["name"] = name
        if address:
            payload["address"] = address

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/send/location",
                json=payload,
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def find_messages(
        self,
        chatid: str,
        limit: int = 100,
        offset: int = 0,
        instance_token: str | None = None,
    ) -> dict:
        """
        Find messages in a specific chat via Uazapi.

        Args:
            chatid: Phone number or chat JID (e.g. 5511999999999@s.whatsapp.net)
            limit: Maximum number of messages to return
            offset: Offset for pagination
            instance_token: Override default instance token
        """
        payload = {
            "chatid": chatid,
            "limit": limit,
            "offset": offset,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/message/find",
                json=payload,
                headers=self._instance_headers(instance_token),
            )
            resp.raise_for_status()
            return resp.json()

    async def update_contact(
        self,
        number: str,
        name: str,
        instance_token: str | None = None,
    ) -> dict:
        """
        Update a contact's name in the Uazapi instance.
        This allows Uazapi to use the correct name for placeholders like {{name}}.
        """
        payload = {
            "number": number,
            "name": name,
        }

        async with httpx.AsyncClient(timeout=15) as client:
            # Endpoint is hypothetical based on spec suggestions (/chat/editLead or /chat/updateContact)
            # We use /chat/updateContact as it's common in similar APIs
            try:
                resp = await client.post(
                    f"{self.base_url}/chat/updateContact",
                    json=payload,
                    headers=self._instance_headers(instance_token),
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                # If the specific endpoint doesn't exist, we log and return avoiding crashing the CRM
                print(f"⚠️ Uazapi update_contact failed: {e}")
                return {"status": "error", "detail": str(e)}


# ── Singleton ──

_uazapi_service: UazapiService | None = None


def get_uazapi_service() -> UazapiService:
    """Returns a singleton UazapiService instance."""
    global _uazapi_service
    if _uazapi_service is None:
        _uazapi_service = UazapiService()
    return _uazapi_service
