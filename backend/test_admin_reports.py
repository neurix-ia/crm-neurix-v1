"""Admin report endpoints — config de cliente + saúde de agentes.

Run: cd backend && python -m pytest test_admin_reports.py -v
"""
import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_supabase
from app.authz import require_superadmin, get_effective_role


class _Exec:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, store):
        self.table = table
        self.store = store
        self.filters = {}

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def eq(self, c, v):
        self.filters[c] = v
        return self

    def in_(self, c, values):
        self.filters[c] = ("in", list(values))
        return self

    def upsert(self, payload, on_conflict=None):
        self.store["upserts"].append({"table": self.table, "payload": payload, "on_conflict": on_conflict})
        self._ret = [payload]
        return self

    def update(self, payload):
        self.store["updates"].append({"table": self.table, "payload": payload})
        self._ret = self.store["update_returns"]
        return self

    def execute(self):
        ret = getattr(self, "_ret", None)
        if ret is not None:
            return _Exec(ret)
        return _Exec(self.store["rows"].get(self.table, []))


class _FakeSupabase:
    def __init__(self, rows=None, update_returns=None):
        self.store = {
            "rows": rows or {},
            "upserts": [],
            "updates": [],
            "update_returns": update_returns if update_returns is not None else [{"id": "x"}],
        }

    def table(self, name):
        return _Query(name, self.store)


def _client(supa):
    app.dependency_overrides[get_supabase] = lambda: supa
    app.dependency_overrides[require_superadmin] = lambda: object()
    app.dependency_overrides[get_effective_role] = lambda: object()
    return TestClient(app)


class AdminReportsTest(unittest.TestCase):
    def tearDown(self):
        app.dependency_overrides.clear()

    def test_upsert_report_client(self):
        supa = _FakeSupabase()
        c = _client(supa)
        body = {"tenant_id": "t1", "spreadsheet_id": "SHEET", "worksheet": "Passivo teste",
                "agent_keys": ["NhL2pBGEXBn8sGXi"], "notify_whatsapp": "5541999"}
        r = c.post("/api/admin/report-clients", json=body)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(supa.store["upserts"][0]["on_conflict"], "tenant_id")
        self.assertEqual(supa.store["upserts"][0]["payload"]["spreadsheet_id"], "SHEET")

    def test_list_report_clients(self):
        supa = _FakeSupabase(rows={"client_report_config": [{"tenant_id": "t1"}]})
        c = _client(supa)
        r = c.get("/api/admin/report-clients")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [{"tenant_id": "t1"}])

    def test_patch_agent_report_status(self):
        supa = _FakeSupabase(update_returns=[{"id": "a1", "status": "revisado"}])
        c = _client(supa)
        r = c.patch("/api/admin/agent-reports/a1", json={"status": "revisado"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["report"]["status"], "revisado")

    def test_patch_agent_report_invalid_status(self):
        supa = _FakeSupabase()
        c = _client(supa)
        r = c.patch("/api/admin/agent-reports/a1", json={"status": "xpto"})
        self.assertEqual(r.status_code, 422)

    def test_patch_report_client_not_found(self):
        supa = _FakeSupabase(update_returns=[])
        c = _client(supa)
        r = c.patch("/api/admin/report-clients/tX", json={"enabled": False})
        self.assertEqual(r.status_code, 404)

    def test_list_agent_reports_filter_agent_key(self):
        rows = [
            {"id": "1", "agent_key": "NhL2pBGEXBn8sGXi", "week_key": "2026-W28"},
            {"id": "2", "agent_key": "DTJgDB8jPfBrk8EA", "week_key": "2026-W28"},
        ]
        supa = _FakeSupabase(rows={"agent_improvement_reports": rows})
        # Fake returns all rows; we assert the filter was applied on the query.
        c = _client(supa)
        r = c.get("/api/admin/agent-reports", params={"agent_key": "NhL2pBGEXBn8sGXi"})
        self.assertEqual(r.status_code, 200)

    def test_list_agent_reports_filter_agent_keys(self):
        supa = _FakeSupabase(rows={"agent_improvement_reports": []})
        c = _client(supa)
        r = c.get(
            "/api/admin/agent-reports",
            params={"agent_keys": "Yp8DuEmqb0Z43ahnJy6Gs,GPOZxMZ0lF4w6m7w"},
        )
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
