"""Testes Neurix HQ — agregação n8n."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from app.models.hq import N8nInstanceMetrics
from app.services.hq_n8n_service import (
    _consolidate_metrics,
    _metric_value,
    _parse_instance_metrics,
    _unwrap_workflow,
    _workflow_project_id,
    period_to_dates,
)
from app.services.n8n_instance_client import N8nInstanceConfig


class TestHqN8nAggregation(unittest.TestCase):
    def test_period_to_dates_7d(self):
        end = __import__("datetime").datetime(2026, 6, 19, 12, 0, 0, tzinfo=__import__("datetime").timezone.utc)
        start, end_out = period_to_dates("7d", now=end)
        self.assertEqual((end - start).days, 7)
        self.assertEqual(end_out, end)

    def test_unwrap_workflow_nested(self):
        wf = _unwrap_workflow({"data": {"id": "1", "name": "Dorinha"}})
        self.assertEqual(wf["name"], "Dorinha")

    def test_unwrap_workflow_key(self):
        wf = _unwrap_workflow({"workflow": {"id": "2", "name": "Agente X"}})
        self.assertEqual(wf["name"], "Agente X")

    def test_match_folder_by_name(self):
        from app.services.hq_n8n_service import _match_folder_for_workflow

        folders = [{"id": "f1", "name": "Villa Dora", "project": {"id": "p1"}}]
        wf = {"id": "w1", "name": "Prod: Agente Villa Dora"}
        fid, name = _match_folder_for_workflow(wf, folders, {"f1": folders[0]})
        self.assertEqual(fid, "f1")
        self.assertEqual(name, "Villa Dora")

    def test_workflow_project_id_from_shared(self):
        wf = {"shared": [{"projectId": "proj-1"}]}
        self.assertEqual(_workflow_project_id(wf), "proj-1")

    def test_folder_name_from_parent_folder_object(self):
        from app.services.hq_n8n_service import _folder_name_for_workflow

        wf = {"parentFolder": {"id": "f1", "name": "Villa Dora"}}
        fid, name = _folder_name_for_workflow(wf, {})
        self.assertEqual(fid, "f1")
        self.assertEqual(name, "Villa Dora")

    def test_normalize_workflow_tags(self):
        from app.services.hq_n8n_service import _normalize_workflow_tags

        wf = {"tags": [{"name": "prod"}, {"name": "staging"}]}
        self.assertEqual(_normalize_workflow_tags(wf), ["prod", "staging"])

    def test_metric_value_nested(self):
        payload = {"total": {"value": 100, "unit": "count", "deviation": 10}}
        self.assertEqual(_metric_value(payload, "total"), 100.0)

    def test_parse_instance_metrics(self):
        cfg = N8nInstanceConfig(id="neurix", label="Neurix", base_url="https://x", api_key="k")
        summary = {
            "total": {"value": 1000},
            "failed": {"value": 10},
            "failureRate": {"value": 0.01},
            "timeSaved": {"value": 120},
            "averageRunTime": {"value": 4.5},
        }
        m = _parse_instance_metrics(cfg, summary)
        self.assertEqual(m.total_executions, 1000)
        self.assertEqual(m.failed_executions, 10)
        self.assertEqual(m.failure_rate, 1.0)
        self.assertEqual(m.time_saved_minutes, 120)

    def test_consolidate_metrics_weighted_avg(self):
        instances = [
            N8nInstanceMetrics(
                id="a",
                label="A",
                total_executions=100,
                failed_executions=5,
                failure_rate=5.0,
                time_saved_minutes=60,
                average_run_time_seconds=2.0,
            ),
            N8nInstanceMetrics(
                id="b",
                label="B",
                total_executions=300,
                failed_executions=3,
                failure_rate=1.0,
                time_saved_minutes=180,
                average_run_time_seconds=6.0,
            ),
        ]
        c = _consolidate_metrics(instances)
        self.assertEqual(c.total_executions, 400)
        self.assertEqual(c.failed_executions, 8)
        self.assertEqual(c.failure_rate, 2.0)
        self.assertAlmostEqual(c.average_run_time_seconds, 5.0)


class TestHqN8nServiceAsync(unittest.IsolatedAsyncioTestCase):
    async def test_overview_empty_instances(self):
        from app.config import Settings
        from app.services.hq_n8n_service import HqN8nService

        settings = Settings(N8N_INSTANCES="")
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        svc = HqN8nService(settings, redis)
        result = await svc.get_overview("7d")
        self.assertEqual(result.instances, [])
        self.assertEqual(result.consolidated.status, "error")

    @patch("app.services.hq_n8n_service._fetch_instance_overview")
    async def test_overview_aggregates(self, mock_fetch):
        from app.config import Settings
        from app.services.hq_n8n_service import HqN8nService

        mock_fetch.side_effect = [
            N8nInstanceMetrics(id="neurix", label="Neurix", total_executions=100, failed_executions=2),
            N8nInstanceMetrics(id="wbtech", label="WB", total_executions=50, failed_executions=1),
        ]
        settings = Settings(
            N8N_INSTANCES='[{"id":"neurix","label":"Neurix","base_url":"https://a","api_key":"k1"},{"id":"wbtech","label":"WB","base_url":"https://b","api_key":"k2"}]'
        )
        redis = AsyncMock()
        redis.get = AsyncMock(return_value=None)
        redis.set = AsyncMock()

        svc = HqN8nService(settings, redis)
        result = await svc.get_overview("7d")
        self.assertEqual(result.consolidated.total_executions, 150)
        self.assertEqual(result.consolidated.failed_executions, 3)


if __name__ == "__main__":
    unittest.main()
