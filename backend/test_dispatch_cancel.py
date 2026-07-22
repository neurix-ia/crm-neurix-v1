import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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


if __name__ == "__main__":
    unittest.main()
