"""Extrai causa de erro de payloads de execução n8n."""

from __future__ import annotations

from typing import Any, Optional


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_execution_error(payload: dict[str, Any]) -> dict[str, Optional[str]]:
    """Retorna node_name, message, description, stack (truncado)."""
    root = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    inner = _as_dict(root.get("data"))
    result_data = _as_dict(inner.get("resultData") or root.get("resultData"))

    err = _as_dict(result_data.get("error"))
    node = _as_dict(err.get("node"))
    node_name = node.get("name") if node else err.get("node")

    message = err.get("message") or err.get("description")
    description = err.get("description") if err.get("description") != message else None
    stack = err.get("stack")

    if not message:
        last_node = result_data.get("lastNodeExecuted")
        run_data = _as_dict(result_data.get("runData"))
        if last_node and last_node in run_data:
            node_runs = run_data[last_node]
            if isinstance(node_runs, list) and node_runs:
                last_run = node_runs[-1]
                if isinstance(last_run, dict):
                    run_err = _as_dict(last_run.get("error"))
                    message = run_err.get("message") or message
                    stack = stack or run_err.get("stack")
                    node_name = node_name or last_node

    if isinstance(stack, str) and len(stack) > 4000:
        stack = stack[:4000] + "\n… (truncado)"

    return {
        "node_name": str(node_name) if node_name else None,
        "message": str(message) if message else "Erro sem mensagem detalhada na execução.",
        "description": str(description) if description else None,
        "stack": stack if isinstance(stack, str) else None,
    }
