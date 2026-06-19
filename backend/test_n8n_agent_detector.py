"""Testes do detector de agentes n8n."""

from __future__ import annotations

import unittest

from app.services.n8n_agent_detector import is_agent_workflow


class TestN8nAgentDetector(unittest.TestCase):
    def test_name_contains_agente(self):
        self.assertTrue(is_agent_workflow({"name": "Staging: Agente Villa Dora"}))

    def test_langchain_agent_node(self):
        wf = {
            "name": "My Flow",
            "nodes": [{"type": "@n8n/n8n-nodes-langchain.agent", "name": "AI Agent"}],
        }
        self.assertTrue(is_agent_workflow(wf))

    def test_regular_workflow(self):
        wf = {
            "name": "error-handler",
            "nodes": [{"type": "n8n-nodes-base.webhook", "name": "Webhook"}],
        }
        self.assertFalse(is_agent_workflow(wf))


if __name__ == "__main__":
    unittest.main()
