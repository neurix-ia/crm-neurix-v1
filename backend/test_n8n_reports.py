"""
Weekly customer-service report — n8n ingestion + notification endpoints.

Run: cd backend && python -m pytest test_n8n_reports.py -v

Covers:
  1. POST /api/n8n/reports/weekly without X-CRM-API-Key  → 401
  2. POST /api/n8n/reports/weekly (valid)                 → 200 + upsert recorded (status=published)
  3. POST /api/n8n/reports/agent-improvement (valid)      → 200 + upsert recorded
  4. GET  /api/n8n/reports/pending-notifications          → rows from fake supabase
  5. POST /api/n8n/reports/{id}/notify                    → calls UAZAPI send + records notified_at
"""

import unittest
from unittest.mock import patch, AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.config import Settings, get_settings
from app.dependencies import get_supabase, verify_n8n_api_key

FAKE_API_KEY = "test-api-key-abc123"
FAKE_TENANT_ID = "tenant-uuid-0001"
FAKE_REPORT_ID = "report-uuid-0001"
FAKE_WEEK_KEY = "2026-W24"
FAKE_WHATSAPP = "5541999998888"


# ── Fake Supabase that records upserts and serves canned query results ──


class _FakeExec:
    def __init__(self, data=None):
        self.data = data if data is not None else []


class _FakeQuery:
    """Records the chained query and returns canned data on .execute()."""

    def __init__(self, table_name, recorder):
        self.table_name = table_name
        self.recorder = recorder
        self.filters = {}
        self._is_null = []

    # mutation
    def upsert(self, payload, on_conflict=None):
        self.recorder["upserts"].append(
            {"table": self.table_name, "payload": payload, "on_conflict": on_conflict}
        )
        return self

    def update(self, payload):
        self.recorder["updates"].append({"table": self.table_name, "payload": payload})
        return self

    # query builders (chainable no-ops that just record filters)
    def select(self, *args, **kwargs):
        return self

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def is_(self, col, val):
        self._is_null.append((col, val))
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        self._single = True
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        data = self.recorder["query_results"].get(self.table_name, [])
        # client_report_config lookups are keyed by tenant_id → return a single matching row
        if getattr(self, "_single", False):
            return _FakeExec(data=(data[0] if data else None))
        return _FakeExec(data=data)


class _FakeSupabase:
    def __init__(self):
        self.recorder = {
            "upserts": [],
            "updates": [],
            "query_results": {},
        }

    def set_query_result(self, table, rows):
        self.recorder["query_results"][table] = rows

    def table(self, name):
        return _FakeQuery(name, self.recorder)


WEEKLY_BODY = {
    "tenant_id": FAKE_TENANT_ID,
    "week_key": FAKE_WEEK_KEY,
    "week_start": "2026-06-08T00:00:00Z",
    "week_end": "2026-06-14T23:59:59Z",
    "metrics": {
        "total_conversas": 120,
        "nota_media_ia": 4.6,
        "nota_media_humano": 4.2,
        "tempo_resp_humano_min": 7.5,
        "tempo_resp_ia_seg": 3.2,
        "horas_economizadas": 18.0,
    },
    "problema_principal": "Demora no primeiro atendimento humano.",
    "solucao_recomendada": "Ativar resposta automática de boas-vindas.",
    "acoes": [{"acao": "Configurar saudação", "contexto": "fora do horário"}],
    "sheet_ref": {"spreadsheet_id": "abc", "row": 5},
}

AGENT_BODY = {
    "agent_key": "agent-ely",
    "agent_name": "Ely",
    "tenant_id": FAKE_TENANT_ID,
    "week_key": FAKE_WEEK_KEY,
    "week_start": "2026-06-08T00:00:00Z",
    "week_end": "2026-06-14T23:59:59Z",
    "severidade": "alta",
    "problema": "Respostas longas demais.",
    "recomendacoes": ["Encurtar prompt", "Adicionar exemplos"],
}


class _AuthedTestBase(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.fake_sb = _FakeSupabase()
        app.dependency_overrides[get_supabase] = lambda: self.fake_sb
        app.dependency_overrides[verify_n8n_api_key] = lambda: {"source": "n8n"}

    def tearDown(self):
        app.dependency_overrides.clear()


class TestAuthGuard(unittest.TestCase):
    """Test 1: real verify_n8n_api_key runs → missing header → 401."""

    def setUp(self):
        self.client = TestClient(app)
        self.fake_sb = _FakeSupabase()
        # Only override supabase; let the REAL verify_n8n_api_key run.
        # Override get_settings so N8N_API_KEY is configured → missing header → 401.
        app.dependency_overrides[get_supabase] = lambda: self.fake_sb
        app.dependency_overrides[get_settings] = lambda: Settings(
            N8N_API_KEY=FAKE_API_KEY, SUPABASE_URL="http://fake", SUPABASE_ANON_KEY="k"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_weekly_without_api_key_returns_401(self):
        resp = self.client.post("/api/n8n/reports/weekly", json=WEEKLY_BODY)
        self.assertEqual(resp.status_code, 401)


class TestWeeklyUpsert(_AuthedTestBase):
    """Test 2: valid weekly upsert → 200, status=published recorded."""

    def test_weekly_upsert_recorded(self):
        resp = self.client.post("/api/n8n/reports/weekly", json=WEEKLY_BODY)
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["week_key"], FAKE_WEEK_KEY)

        upserts = self.fake_sb.recorder["upserts"]
        self.assertEqual(len(upserts), 1)
        rec = upserts[0]
        self.assertEqual(rec["table"], "weekly_reports")
        self.assertEqual(rec["on_conflict"], "tenant_id,week_key")
        self.assertEqual(rec["payload"]["status"], "published")
        self.assertEqual(rec["payload"]["tenant_id"], FAKE_TENANT_ID)
        self.assertEqual(rec["payload"]["week_key"], FAKE_WEEK_KEY)


class TestWeeklyHorasOverride(_AuthedTestBase):
    """Backend recalcula horas_economizadas a partir dos agent_keys (ignora o valor do n8n)."""

    def test_horas_overridden_from_agent_keys(self):
        self.fake_sb.set_query_result(
            "client_report_config", [{"agent_keys": ["wfA", "wfB"]}]
        )
        with patch(
            "app.routers.n8n_reports.compute_horas_economizadas",
            new=AsyncMock(return_value=31.5),
        ) as mocked:
            resp = self.client.post("/api/n8n/reports/weekly", json=WEEKLY_BODY)
        self.assertEqual(resp.status_code, 200, resp.text)
        mocked.assert_awaited_once()
        # agent_keys passados corretamente
        self.assertEqual(mocked.await_args.kwargs["agent_keys"], ["wfA", "wfB"])
        rec = self.fake_sb.recorder["upserts"][0]
        self.assertEqual(rec["payload"]["metrics"]["horas_economizadas"], 31.5)


class TestAgentUpsert(_AuthedTestBase):
    """Test 3: valid agent-improvement upsert → 200."""

    def test_agent_upsert_recorded(self):
        resp = self.client.post("/api/n8n/reports/agent-improvement", json=AGENT_BODY)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "ok")

        upserts = self.fake_sb.recorder["upserts"]
        self.assertEqual(len(upserts), 1)
        rec = upserts[0]
        self.assertEqual(rec["table"], "agent_improvement_reports")
        self.assertEqual(rec["on_conflict"], "agent_key,week_key")
        self.assertEqual(rec["payload"]["agent_key"], "agent-ely")


class TestPendingNotifications(_AuthedTestBase):
    """Test 4: pending-notifications returns rows joined with notify_whatsapp."""

    def test_pending_notifications(self):
        self.fake_sb.set_query_result(
            "weekly_reports",
            [
                {
                    "id": FAKE_REPORT_ID,
                    "tenant_id": FAKE_TENANT_ID,
                    "week_key": FAKE_WEEK_KEY,
                    "status": "published",
                    "notified_at": None,
                }
            ],
        )
        self.fake_sb.set_query_result(
            "client_report_config",
            [{"tenant_id": FAKE_TENANT_ID, "notify_whatsapp": FAKE_WHATSAPP}],
        )

        resp = self.client.get("/api/n8n/reports/pending-notifications")
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], FAKE_REPORT_ID)
        self.assertEqual(rows[0]["tenant_id"], FAKE_TENANT_ID)
        self.assertEqual(rows[0]["week_key"], FAKE_WEEK_KEY)
        self.assertEqual(rows[0]["notify_whatsapp"], FAKE_WHATSAPP)


class TestNotify(_AuthedTestBase):
    """Test 5: notify sends WhatsApp via UAZAPI and records notified_at."""

    def test_notify_sends_and_marks(self):
        self.fake_sb.set_query_result(
            "weekly_reports",
            [
                {
                    "id": FAKE_REPORT_ID,
                    "tenant_id": FAKE_TENANT_ID,
                    "week_key": FAKE_WEEK_KEY,
                    "problema_principal": "Demora no primeiro atendimento humano.",
                    "status": "published",
                    "notified_at": None,
                }
            ],
        )
        self.fake_sb.set_query_result(
            "client_report_config",
            [{"tenant_id": FAKE_TENANT_ID, "notify_whatsapp": FAKE_WHATSAPP}],
        )

        sent = {}

        async def fake_send_text(self, number, text, instance_token=None, **kwargs):
            sent["number"] = number
            sent["text"] = text
            return {"status": "ok"}

        with patch(
            "app.services.uazapi_service.UazapiService.send_text", new=fake_send_text
        ):
            resp = self.client.post(f"/api/n8n/reports/{FAKE_REPORT_ID}/notify")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "ok")

        # WhatsApp send happened with the deep link
        self.assertEqual(sent["number"], FAKE_WHATSAPP)
        self.assertIn("/relatorios?wk=", sent["text"])
        self.assertIn(FAKE_WEEK_KEY, sent["text"])

        # notified_at recorded
        updates = self.fake_sb.recorder["updates"]
        self.assertTrue(any("notified_at" in u["payload"] for u in updates))

    def test_notify_without_whatsapp_returns_422(self):
        self.fake_sb.set_query_result(
            "weekly_reports",
            [
                {
                    "id": FAKE_REPORT_ID,
                    "tenant_id": FAKE_TENANT_ID,
                    "week_key": FAKE_WEEK_KEY,
                    "problema_principal": "x",
                    "status": "published",
                    "notified_at": None,
                }
            ],
        )
        self.fake_sb.set_query_result("client_report_config", [])  # no config

        resp = self.client.post(f"/api/n8n/reports/{FAKE_REPORT_ID}/notify")
        self.assertEqual(resp.status_code, 422, resp.text)


if __name__ == "__main__":
    unittest.main()
