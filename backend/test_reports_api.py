"""
Weekly report — client-facing read endpoints + week_bounds_from_key.

Run: cd backend && python -m pytest test_reports_api.py -v
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_current_user, get_supabase, get_redis_optional
from app.authz import get_effective_role
from app.services.sheets_reader import week_bounds_from_key

FAKE_TENANT = "tenant-uuid-0001"
OTHER_TENANT = "tenant-uuid-9999"
WK = "2026-W25"


class _User:
    id = "user-uuid-0001"


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

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        self.store["last_filters"] = dict(self.filters)
        rows = self.store["rows"].get(self.table, [])
        # respeita isolamento por tenant_id quando filtrado
        if "tenant_id" in self.filters:
            rows = [r for r in rows if r.get("tenant_id") == self.filters["tenant_id"]]
        if "week_key" in self.filters:
            rows = [r for r in rows if r.get("week_key") == self.filters["week_key"]]
        return _Exec(rows)


class _FakeSupabase:
    def __init__(self, rows):
        self.store = {"rows": rows, "last_filters": {}}

    def table(self, name):
        return _Query(name, self.store)


def _make_client(weekly_rows):
    supa = _FakeSupabase({"weekly_reports": weekly_rows})
    app.dependency_overrides[get_current_user] = lambda: _User()
    app.dependency_overrides[get_supabase] = lambda: supa
    app.dependency_overrides[get_effective_role] = lambda: object()
    app.dependency_overrides[get_redis_optional] = lambda: None
    return TestClient(app), supa


def _teardown():
    app.dependency_overrides.clear()


SAMPLE = [
    {"tenant_id": FAKE_TENANT, "week_key": "2026-W25", "week_start": "2026-06-15T00:00:00",
     "week_end": "2026-06-21T23:59:59", "status": "published", "problema_principal": "Repetição de perguntas",
     "metrics": {"total_conversas": 3}, "solucao_recomendada": "Usar contexto", "acoes": []},
    {"tenant_id": OTHER_TENANT, "week_key": "2026-W25", "week_start": "2026-06-15T00:00:00",
     "week_end": "2026-06-21T23:59:59", "status": "published", "problema_principal": "OUTRO TENANT",
     "metrics": {}, "solucao_recomendada": "x", "acoes": []},
]


class WeekBoundsTest(unittest.TestCase):
    def test_iso_week_bounds(self):
        start, end = week_bounds_from_key("2026-W25")
        self.assertEqual(start.date().isoformat(), "2026-06-15")  # segunda
        self.assertEqual(end.date().isoformat(), "2026-06-21")    # domingo
        self.assertEqual(start.isoweekday(), 1)
        self.assertEqual(end.isoweekday(), 7)
        self.assertIsNotNone(start.tzinfo)
        self.assertEqual((start.hour, end.hour, end.minute, end.second), (0, 23, 59, 59))


class ReportsApiTest(unittest.TestCase):
    def tearDown(self):
        _teardown()

    @patch("app.routers.reports._resolve_kanban_scope", return_value=(FAKE_TENANT, "f1"))
    def test_list_weekly_only_own_tenant(self, _m):
        client, supa = _make_client(SAMPLE)
        r = client.get("/api/reports/weekly")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["problema_principal"], "Repetição de perguntas")
        self.assertEqual(supa.store["last_filters"].get("tenant_id"), FAKE_TENANT)

    @patch("app.routers.reports._resolve_kanban_scope", return_value=(FAKE_TENANT, "f1"))
    def test_get_weekly_found(self, _m):
        client, _ = _make_client(SAMPLE)
        r = client.get(f"/api/reports/weekly/{WK}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["week_key"], WK)

    @patch("app.routers.reports._resolve_kanban_scope", return_value=(FAKE_TENANT, "f1"))
    def test_get_weekly_not_found(self, _m):
        client, _ = _make_client(SAMPLE)
        r = client.get("/api/reports/weekly/2099-W01")
        self.assertEqual(r.status_code, 404)

    @patch("app.routers.reports.read_week_rows")
    @patch("app.routers.reports._resolve_kanban_scope", return_value=(FAKE_TENANT, "f1"))
    def test_conversations_calls_reader(self, _scope, mock_reader):
        async def _fake_reader(supabase, redis, *, tenant_id, week_start, week_end):
            self.assertEqual(tenant_id, FAKE_TENANT)
            self.assertEqual(week_start.date().isoformat(), "2026-06-15")
            self.assertEqual(week_end.date().isoformat(), "2026-06-21")
            return [{"id_conversa": "x", "transcrição": "[2026-06-16 10:00:00] Lead: oi"}]
        mock_reader.side_effect = _fake_reader
        client, _ = _make_client(SAMPLE)
        r = client.get(f"/api/reports/weekly/{WK}/conversations")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["week_key"], WK)


if __name__ == "__main__":
    unittest.main()
