"""Detecta workflows que são agentes (IA / WhatsApp) no n8n."""

from __future__ import annotations

import re
from typing import Any

_AGENT_NODE_MARKERS = (
    "langchain.agent",
    ".agent",
    "openaiassistant",
    "toolsagent",
)

_AGENT_NAME_RE = re.compile(r"agente", re.IGNORECASE)


def is_agent_workflow(workflow: dict[str, Any]) -> bool:
    """True se o workflow parece ser um agente ativo de atendimento/automação."""
    name = str(workflow.get("name") or "")
    if _AGENT_NAME_RE.search(name):
        return True

    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or "").lower()
        if any(marker in node_type for marker in _AGENT_NODE_MARKERS):
            return True

    return False
