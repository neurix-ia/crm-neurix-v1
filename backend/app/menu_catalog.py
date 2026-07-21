"""
Catálogo canônico do menu lateral do app do tenant.
Defaults e merge usados por organizations + /auth/me.
"""

from __future__ import annotations

from typing import Any

# Ordem fixa de exibição no sidebar.
MENU_CATALOG: list[dict[str, str]] = [
    {"key": "dashboard", "label": "Painel", "route": "/dashboard", "icon": "dashboard"},
    {"key": "kanban", "label": "Funil de Vendas", "route": "/kanban", "icon": "view_kanban"},
    {"key": "clientes", "label": "Clientes", "route": "/clientes", "icon": "person_search"},
    {"key": "produtos", "label": "Produtos", "route": "/produtos", "icon": "inventory_2"},
    {"key": "comunicados", "label": "Comunicados", "route": "/disparador", "icon": "campaign"},
    {"key": "vendi", "label": "Vendi", "route": "/vendi", "icon": "storefront"},
    {"key": "relatorios", "label": "Relatórios", "route": "/relatorios", "icon": "summarize"},
    {"key": "configuracoes", "label": "Configurações", "route": "/configuracoes", "icon": "settings"},
]

MENU_KEYS: frozenset[str] = frozenset(item["key"] for item in MENU_CATALOG)

# Tudo ON exceto Comunicados (comportamento legado do allowlist por e-mail).
DEFAULT_MENU_CONFIG: dict[str, bool] = {
    "dashboard": True,
    "kanban": True,
    "clientes": True,
    "produtos": True,
    "comunicados": False,
    "vendi": False,
    "relatorios": True,
    "configuracoes": True,
}


def resolve_menu_config(raw: Any) -> dict[str, bool]:
    """Merge stored JSONB with defaults; ignore unknown keys; coerce to bool."""
    resolved = dict(DEFAULT_MENU_CONFIG)
    if not isinstance(raw, dict):
        return resolved
    for key, value in raw.items():
        if key in MENU_KEYS:
            resolved[key] = bool(value)
    return resolved


def sanitize_menu_config_input(raw: Any) -> dict[str, bool]:
    """Validate PATCH body: only catalog keys, bool values. Raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("menu_config deve ser um objeto.")
    out: dict[str, bool] = {}
    for key, value in raw.items():
        if key not in MENU_KEYS:
            raise ValueError(f"Chave de menu inválida: {key}")
        if not isinstance(value, bool):
            raise ValueError(f"menu_config.{key} deve ser boolean.")
        out[key] = value
    return out


def first_enabled_route(menu_config: dict[str, bool]) -> str:
    """Primeira rota habilitada na ordem do catálogo (fallback /dashboard)."""
    for item in MENU_CATALOG:
        if menu_config.get(item["key"], False):
            return item["route"]
    return "/dashboard"


def route_to_menu_key(pathname: str) -> str | None:
    """Mapeia pathname (ex. /kanban/foo) para a key do catálogo, se houver."""
    path = pathname.split("?")[0].rstrip("/") or "/"
    best: str | None = None
    best_len = -1
    for item in MENU_CATALOG:
        route = item["route"].rstrip("/") or "/"
        if path == route or path.startswith(route + "/"):
            if len(route) > best_len:
                best = item["key"]
                best_len = len(route)
    return best
