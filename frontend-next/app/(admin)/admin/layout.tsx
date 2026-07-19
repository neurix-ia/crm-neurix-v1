"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getAuthMe } from "@/lib/api";

const NAV = [
    { href: "/admin/core", label: "Neurix HQ" },
    { href: "/admin", label: "Início" },
    { href: "/admin/organizations", label: "Organizações" },
    { href: "/admin/users", label: "Usuários" },
    { href: "/admin/clientes", label: "Clientes" },
    { href: "/admin/products", label: "Produtos" },
    { href: "/admin/funnels", label: "Funis" },
    { href: "/admin/inboxes", label: "Configurações / Inboxes" },
    { href: "/admin/automacao-auditoria", label: "Automação / Auditoria" },
    { href: "/admin/agentes-saude", label: "Saúde dos Agentes" },
    { href: "/admin/help", label: "Ajuda" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
    const router = useRouter();
    const pathname = usePathname();
    const [gate, setGate] = useState<"loading" | "ok">("loading");

    useEffect(() => {
        const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
        if (!token) {
            router.replace("/login");
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const me = await getAuthMe(token);
                if (cancelled) return;
                if (!me.is_superadmin) {
                    router.replace("/dashboard");
                    return;
                }
                setGate("ok");
            } catch {
                if (!cancelled) router.replace("/dashboard");
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [router]);

    if (gate === "loading") {
        return (
            <div className="min-h-screen flex items-center justify-center bg-background-light dark:bg-background-dark text-text-main-light dark:text-text-main-dark">
                <p className="text-sm text-text-secondary-light">Carregando console…</p>
            </div>
        );
    }

    return (
        <div className="min-h-screen flex flex-col md:flex-row bg-background-light dark:bg-background-dark text-text-main-light dark:text-text-main-dark">
            <div className="absolute inset-0 z-0 bg-gradient-to-br from-rose-50 via-white to-slate-100 dark:from-gray-900 dark:via-gray-900 dark:to-slate-950" />
            <aside className="relative z-10 w-full md:w-64 shrink-0 border-b md:border-b-0 md:border-r border-border-light dark:border-border-dark glass-effect md:min-h-screen p-4 flex flex-col gap-4">
                <div className="flex items-center gap-2 px-2">
                    <span className="material-symbols-outlined text-primary text-2xl">admin_panel_settings</span>
                    <div>
                        <p className="font-display font-bold text-sm">Console Admin</p>
                        <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Neurix CRM</p>
                    </div>
                </div>
                <nav className="flex flex-col gap-1">
                    {NAV.map((item) => {
                        const active = pathname === item.href || (item.href !== "/admin" && pathname.startsWith(item.href));
                        return (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={`rounded-xl px-3 py-2 text-sm font-medium transition-colors ${
                                    active
                                        ? "bg-primary/15 text-primary"
                                        : "text-text-secondary-light hover:bg-black/5 dark:hover:bg-white/5"
                                }`}
                            >
                                {item.label}
                            </Link>
                        );
                    })}
                </nav>
                <div className="mt-auto pt-4 border-t border-border-light dark:border-border-dark">
                    <Link
                        href="/dashboard"
                        className="text-sm text-primary hover:underline flex items-center gap-1"
                    >
                        <span className="material-symbols-outlined text-lg">arrow_back</span>
                        Voltar ao app
                    </Link>
                </div>
            </aside>
            <main className="relative z-10 flex-1 overflow-y-auto p-4 md:p-8">{children}</main>
        </div>
    );
}
