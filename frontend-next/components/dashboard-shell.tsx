"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import Sidebar from "@/components/sidebar";
import { getAuthMe } from "@/lib/api";
import {
    DEFAULT_MENU_CONFIG,
    firstEnabledRoute,
    isMenuRouteEnabled,
    resolveMenuConfig,
    type MenuConfig,
} from "@/lib/menu-catalog";

export default function DashboardShell({ children }: { children: React.ReactNode }) {
    const [mobileOpen, setMobileOpen] = useState(false);
    const pathname = usePathname();
    const router = useRouter();
    const [menuConfig, setMenuConfig] = useState<MenuConfig | null>(null);

    const closeMobile = useCallback(() => setMobileOpen(false), []);

    useEffect(() => {
        if (!mobileOpen) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") closeMobile();
        };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [mobileOpen, closeMobile]);

    useEffect(() => {
        if (mobileOpen) {
            document.body.style.overflow = "hidden";
        } else {
            document.body.style.overflow = "";
        }
        return () => {
            document.body.style.overflow = "";
        };
    }, [mobileOpen]);

    useEffect(() => {
        const mq = window.matchMedia("(min-width: 768px)");
        const onChange = () => {
            if (mq.matches) setMobileOpen(false);
        };
        mq.addEventListener("change", onChange);
        onChange();
        return () => mq.removeEventListener("change", onChange);
    }, []);

    useEffect(() => {
        const token = localStorage.getItem("access_token");
        if (!token) {
            setMenuConfig(DEFAULT_MENU_CONFIG);
            return;
        }
        getAuthMe(token)
            .then((me) => setMenuConfig(resolveMenuConfig(me.menu_config)))
            .catch(() => setMenuConfig(DEFAULT_MENU_CONFIG));
    }, []);

    useEffect(() => {
        if (!menuConfig) return;
        if (isMenuRouteEnabled(pathname, menuConfig)) return;
        const target = firstEnabledRoute(menuConfig);
        if (target !== pathname) {
            router.replace(target);
        }
    }, [menuConfig, pathname, router]);

    return (
        <div className="flex h-screen overflow-hidden bg-background-light dark:bg-background-dark text-text-main-light dark:text-text-main-dark">
            {mobileOpen && (
                <button
                    type="button"
                    aria-label="Fechar menu"
                    className="fixed inset-0 z-40 bg-black/50 md:hidden"
                    onClick={closeMobile}
                />
            )}
            <Sidebar mobileOpen={mobileOpen} onMobileClose={closeMobile} />
            <div className="flex flex-1 min-h-0 min-w-0 flex-col">
                <header className="sticky top-0 z-30 flex shrink-0 items-center justify-between border-b border-border-light dark:border-border-dark bg-surface-light px-4 py-3 dark:bg-surface-dark md:hidden">
                    <div className="flex items-center gap-2">
                        <span className="material-symbols-outlined text-2xl text-primary">hexagon</span>
                        <span className="font-display text-lg font-bold">Neurix</span>
                    </div>
                    <button
                        type="button"
                        onClick={() => setMobileOpen(true)}
                        aria-expanded={mobileOpen}
                        aria-controls="dashboard-nav"
                        aria-label="Abrir menu"
                        className="-mr-2 rounded-lg p-2 text-text-main-light transition-colors hover:bg-slate-100 dark:text-text-main-dark dark:hover:bg-slate-800"
                    >
                        <span className="material-symbols-outlined">menu</span>
                    </button>
                </header>
                <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>
            </div>
        </div>
    );
}
