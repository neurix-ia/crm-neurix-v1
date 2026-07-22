import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.services.dispatch_service import cancel_n8n_execution, resolve_dispatch_n8n_client
from app.services.n8n_instance_client import N8nInstanceClient, N8nInstanceConfig


class TestN8nStopDelete(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = N8nInstanceConfig(
            id="wb", label="WB", base_url="https://n8n.example", api_key="k"
        )
        self.client = N8nInstanceClient(self.cfg, verify_ssl=True)

    async def test_stop_execution_posts(self):
        with patch.object(self.client, "_request_json", new_callable=AsyncMock) as m:
            m.return_value = {"id": "99", "status": "canceled"}
            out = await self.client.stop_execution("99")
            m.assert_awaited_once_with("POST", "/api/v1/executions/99/stop")
            self.assertEqual(out["id"], "99")

    async def test_delete_execution_deletes(self):
        with patch.object(self.client, "_request_json", new_callable=AsyncMock) as m:
            m.return_value = {"id": "99"}
            out = await self.client.delete_execution("99")
            m.assert_awaited_once_with("DELETE", "/api/v1/executions/99")
            self.assertEqual(out["id"], "99")


class TestResolveDispatchClient(unittest.TestCase):
    def test_resolve_by_instance_id(self):
        settings = Settings(
            N8N_DISPATCH_INSTANCE_ID="wb",
            N8N_INSTANCES='[{"id":"wb","label":"WB","base_url":"https://n8n.example","api_key":"k"}]',
        )
        client = resolve_dispatch_n8n_client(settings)
        self.assertIsNotNone(client)
        self.assertEqual(client.config.id, "wb")

    def test_resolve_by_webhook_host(self):
        settings = Settings(
            N8N_DISPATCH_INSTANCE_ID="",
            N8N_DISPATCH_WEBHOOK_URL="https://n8n.example/webhook/x",
            N8N_INSTANCES='[{"id":"wb","label":"WB","base_url":"https://n8n.example","api_key":"k"}]',
        )
        client = resolve_dispatch_n8n_client(settings)
        self.assertIsNotNone(client)
        self.assertEqual(client.config.id, "wb")

    def test_resolve_no_match_returns_none(self):
        settings = Settings(
            N8N_DISPATCH_INSTANCE_ID="other",
            N8N_DISPATCH_WEBHOOK_URL="https://unknown.example/webhook/x",
            N8N_INSTANCES='[{"id":"wb","label":"WB","base_url":"https://n8n.example","api_key":"k"}]',
        )
        client = resolve_dispatch_n8n_client(settings)
        self.assertIsNone(client)


class TestCancelN8nExecution(unittest.IsolatedAsyncioTestCase):
    async def test_stop_then_delete(self):
        mock_client = MagicMock()
        mock_client.stop_execution = AsyncMock(return_value={})
        mock_client.delete_execution = AsyncMock(return_value={})
        with patch(
            "app.services.dispatch_service.resolve_dispatch_n8n_client",
            return_value=mock_client,
        ):
            out = await cancel_n8n_execution("42")
        self.assertTrue(out["n8n_stopped"])
        self.assertTrue(out["n8n_deleted"])
        self.assertIsNone(out["n8n_error"])

    async def test_no_client(self):
        with patch(
            "app.services.dispatch_service.resolve_dispatch_n8n_client",
            return_value=None,
        ):
            out = await cancel_n8n_execution("42")
        self.assertFalse(out["n8n_stopped"])
        self.assertFalse(out["n8n_deleted"])
        self.assertIn("N8N", out["n8n_error"] or "")


if __name__ == "__main__":
    unittest.main()
