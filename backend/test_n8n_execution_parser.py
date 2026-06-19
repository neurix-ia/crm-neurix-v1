"""Testes parser de erro n8n."""

import unittest

from app.services.n8n_execution_parser import extract_execution_error


class TestN8nExecutionParser(unittest.TestCase):
    def test_extracts_top_level_error(self):
        payload = {
            "data": {
                "data": {
                    "resultData": {
                        "error": {
                            "message": "Node failed",
                            "stack": "Error: Node failed\n  at x",
                            "node": {"name": "HTTP Request"},
                        }
                    }
                }
            }
        }
        out = extract_execution_error(payload)
        self.assertEqual(out["node_name"], "HTTP Request")
        self.assertEqual(out["message"], "Node failed")
        self.assertIn("Node failed", out["stack"] or "")

    def test_fallback_last_node(self):
        payload = {
            "data": {
                "resultData": {
                    "lastNodeExecuted": "Code",
                    "runData": {
                        "Code": [{"error": {"message": "Syntax error"}}],
                    },
                }
            }
        }
        out = extract_execution_error(payload)
        self.assertEqual(out["node_name"], "Code")
        self.assertEqual(out["message"], "Syntax error")


if __name__ == "__main__":
    unittest.main()
