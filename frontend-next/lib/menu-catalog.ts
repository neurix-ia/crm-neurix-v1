/** Catálogo canônico do menu lateral (espelha backend/app/menu_catalog.py). */

export type MenuItemKey =
    | "dashboard"
    | "kanban"
    | "clientes"
    | "produtos"
    | "comunicados"
    | "vendi"
    | "relatorios"
    | "configuracoes";

export type MenuCatalogItem = {
    key: MenuItemKey;
    label: string;
    route: string;
    icon: string;
    section: "main" | "system";
};

export const MENU_CATALOG: MenuCatalogItem[] = [
    { key: "dashboard", label: "Painel", route: "/dashboard", icon: "dashboard", section: "main" },
    { key: "kanban", label: "Funil de Vendas", route: "/kanban", icon: "view_kanban", section: "main" },
    { key: "clientes", label: "Clientes", route: "/clientes", icon: "person_search", section: "main" },
    { key: "produtos", label: "Produtos", route: "/produtos", icon: "inventory_2", section: "main" },
    { key: "comunicados", label: "Comunicados", route: "/disparador", icon: "campaign", section: "main" },
    { key: "vendi", label: "Vendi", route: "/vendi", icon: "storefront", section: "main" },
    { key: "relatorios", label: "Relatórios", route: "/relatorios", icon: "summarize", section: "main" },
    { key: "configuracoes", label: "Configurações", route: "/configuracoes", icon: "settings", section: "system" },
];

export const DEFAULT_MENU_CONFIG: Record<MenuItemKey, boolean> = {
    dashboard: true,
    kanban: true,
    clientes: true,
    produtos: true,
    comunicados: false,
    vendi: false,
    relatorios: true,
    configuracoes: true,
};

export type MenuConfig = Record<string, boolean>;

export function resolveMenuConfig(raw?: MenuConfig | null): Record<MenuItemKey, boolean> {
    const resolved = { ...DEFAULT_MENU_CONFIG };
    if (!raw || typeof raw !== "object") return resolved;
    for (const item of MENU_CATALOG) {
        if (typeof raw[item.key] === "boolean") {
            resolved[item.key] = raw[item.key];
        }
    }
    return resolved;
}

export function firstEnabledRoute(menuConfig: MenuConfig): string {
    const resolved = resolveMenuConfig(menuConfig);
    for (const item of MENU_CATALOG) {
        if (resolved[item.key]) return item.route;
    }
    return "/dashboard";
}

export function routeToMenuKey(pathname: string): MenuItemKey | null {
    const path = (pathname.split("?")[0] || "/").replace(/\/$/, "") || "/";
    let best: MenuItemKey | null = null;
    let bestLen = -1;
    for (const item of MENU_CATALOG) {
        const route = item.route.replace(/\/$/, "") || "/";
        if (path === route || path.startsWith(route + "/")) {
            if (route.length > bestLen) {
                best = item.key;
                bestLen = route.length;
            }
        }
    }
    return best;
}

export function isMenuRouteEnabled(pathname: string, menuConfig: MenuConfig): boolean {
    const key = routeToMenuKey(pathname);
    if (!key) return true; // rotas fora do catálogo (ex. perfil) liberadas
    return Boolean(resolveMenuConfig(menuConfig)[key]);
}
