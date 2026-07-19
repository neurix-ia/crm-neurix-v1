"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useRef, useEffect } from "react";
import { supabase } from "@/lib/supabase";
import EditProfileModal from "@/components/EditProfileModal";
import { getAuthMe } from "@/lib/api";
import {
    DEFAULT_MENU_CONFIG,
    firstEnabledRoute,
    MENU_CATALOG,
    resolveMenuConfig,
    type MenuConfig,
} from "@/lib/menu-catalog";

type SidebarProps = {
    mobileOpen?: boolean;
    onMobileClose?: () => void;
};

export default function Sidebar({ mobileOpen = false, onMobileClose }: SidebarProps) {
    const pathname = usePathname();
    const router = useRouter();
    const [showProfile, setShowProfile] = useState(false);
    const [showEditProfileModal, setShowEditProfileModal] = useState(false);
    const profileRef = useRef<HTMLDivElement>(null);

    const [userName, setUserName] = useState("Carregando...");
    const [userEmail, setUserEmail] = useState("");
    const [userInitials, setUserInitials] = useState("--");
    const [isSuperadmin, setIsSuperadmin] = useState(false);
    const [menuConfig, setMenuConfig] = useState<MenuConfig>(DEFAULT_MENU_CONFIG);

    useEffect(() => {
        async function fetchUser() {
            const { data: { user } } = await supabase.auth.getUser();
            if (user) {
                setUserEmail(user.email || "");
                const { data: profile } = await supabase
                    .from("profiles")
                    .select("full_name")
                    .eq("id", user.id)
                    .single();

                if (profile?.full_name) {
                    setUserName(profile.full_name);
                    setUserInitials(profile.full_name.substring(0, 2).toUpperCase());
                } else if (user.email) {
                    setUserName(user.email.split("@")[0]);
                    setUserInitials(user.email.substring(0, 2).toUpperCase());
                }
            }
        }
        fetchUser();
    }, []);

    useEffect(() => {
        const token = localStorage.getItem("access_token");
        if (!token) return;
        getAuthMe(token)
            .then((me) => {
                setIsSuperadmin(Boolean(me.is_superadmin));
                setMenuConfig(resolveMenuConfig(me.menu_config));
            })
            .catch(() => {
                setIsSuperadmin(false);
                setMenuConfig(DEFAULT_MENU_CONFIG);
            });
    }, []);

    useEffect(() => {
        onMobileClose?.();
    }, [pathname, onMobileClose]);

    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
                setShowProfile(false);
            }
        }
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    const handleLogout = () => {
        onMobileClose?.();
        localStorage.removeItem("token");
        router.push("/login");
    };

    const panelTransform = mobileOpen ? "translate-x-0" : "max-md:-translate-x-full md:translate-x-0";

    const resolved = resolveMenuConfig(menuConfig);
    const mainItems = MENU_CATALOG.filter((item) => item.section === "main" && resolved[item.key]);
    const systemItems = MENU_CATALOG.filter((item) => item.section === "system" && resolved[item.key]);
    const homeHref = firstEnabledRoute(resolved);

    return (
        <aside
            id="dashboard-nav"
            className={`flex w-[280px] max-w-[min(280px,92vw)] flex-shrink-0 flex-col border-r border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark transition-[transform,colors] duration-200 ease-out md:static md:z-auto ${panelTransform} fixed inset-y-0 left-0 z-50 shadow-2xl md:shadow-none`}
        >
            <div className="flex h-16 shrink-0 items-center justify-between border-b border-border-light px-6 dark:border-border-dark">
                <Link
                    href={homeHref}
                    onClick={() => onMobileClose?.()}
                    className="flex min-w-0 items-center gap-2 transition-colors hover:bg-slate-50 dark:hover:bg-slate-800/30 -mx-2 px-2 py-1 rounded-lg"
                >
                    <span className="material-symbols-outlined text-primary text-3xl shrink-0">hexagon</span>
                    <span className="font-display font-bold text-xl tracking-tight text-text-main-light dark:text-text-main-dark truncate">
                        Neurix<span className="text-primary">CRM</span>
                    </span>
                </Link>
                <button
                    type="button"
                    onClick={() => onMobileClose?.()}
                    aria-label="Fechar menu"
                    className="md:hidden -mr-2 rounded-lg p-2 text-text-main-light hover:bg-slate-100 dark:text-text-main-dark dark:hover:bg-slate-800"
                >
                    <span className="material-symbols-outlined">close</span>
                </button>
            </div>

            <nav className="flex-1 overflow-y-auto py-6 px-3 space-y-1">
                {mainItems.map((item) => {
                    const isActive = pathname === item.route || pathname.startsWith(item.route + "/");
                    return (
                        <Link
                            key={item.key}
                            href={item.route}
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors ${
                                isActive
                                    ? "bg-primary-light dark:bg-primary/20 text-primary font-medium"
                                    : "text-text-secondary-light dark:text-text-secondary-dark hover:bg-slate-100 dark:hover:bg-slate-700/50 hover:text-primary"
                            }`}
                        >
                            <span className={`material-symbols-outlined ${isActive ? "filled" : ""}`}>
                                {item.icon}
                            </span>
                            <span className="text-sm">{item.label}</span>
                        </Link>
                    );
                })}

                {(systemItems.length > 0 || isSuperadmin) && (
                    <div className="pt-4 mt-4 border-t border-border-light dark:border-border-dark">
                        <span className="px-3 text-xs font-semibold text-text-secondary-light dark:text-text-secondary-dark uppercase tracking-wider">
                            Sistema
                        </span>
                    </div>
                )}

                {systemItems.map((item) => {
                    const isActive = pathname === item.route || pathname.startsWith(item.route + "/");
                    return (
                        <Link
                            key={item.key}
                            href={item.route}
                            className={`flex items-center gap-3 px-3 py-2.5 mt-2 rounded-xl transition-colors ${
                                isActive
                                    ? "bg-primary-light dark:bg-primary/20 text-primary font-medium"
                                    : "text-text-secondary-light dark:text-text-secondary-dark hover:bg-slate-100 dark:hover:bg-slate-700/50 hover:text-primary"
                            }`}
                        >
                            <span className={`material-symbols-outlined ${isActive ? "filled" : ""}`}>
                                {item.icon}
                            </span>
                            <span className="text-sm">{item.label}</span>
                        </Link>
                    );
                })}
                {isSuperadmin && (
                    <>
                        <Link
                            href="/admin/core"
                            className={`flex items-center gap-3 px-3 py-2.5 mt-2 rounded-xl transition-colors ${
                                pathname.startsWith("/admin/core")
                                    ? "bg-primary-light dark:bg-primary/20 text-primary font-medium"
                                    : "text-text-secondary-light dark:text-text-secondary-dark hover:bg-slate-100 dark:hover:bg-slate-700/50 hover:text-primary"
                            }`}
                        >
                            <span
                                className={`material-symbols-outlined ${
                                    pathname.startsWith("/admin/core") ? "filled" : ""
                                }`}
                            >
                                dashboard
                            </span>
                            <span className="text-sm">Neurix HQ</span>
                        </Link>
                        <Link
                            href="/admin"
                            className={`flex items-center gap-3 px-3 py-2.5 rounded-xl transition-colors ${
                                pathname.startsWith("/admin") && !pathname.startsWith("/admin/core")
                                    ? "bg-primary-light dark:bg-primary/20 text-primary font-medium"
                                    : "text-text-secondary-light dark:text-text-secondary-dark hover:bg-slate-100 dark:hover:bg-slate-700/50 hover:text-primary"
                            }`}
                        >
                            <span
                                className={`material-symbols-outlined ${
                                    pathname.startsWith("/admin") && !pathname.startsWith("/admin/core")
                                        ? "filled"
                                        : ""
                                }`}
                            >
                                admin_panel_settings
                            </span>
                            <span className="text-sm">Console Admin</span>
                        </Link>
                    </>
                )}
            </nav>

            <div className="p-4 border-t border-border-light dark:border-border-dark relative" ref={profileRef}>
                {showProfile && (
                    <div className="absolute bottom-full left-3 right-3 mb-2 bg-surface-light dark:bg-surface-dark rounded-xl shadow-2xl border border-border-light dark:border-border-dark p-4 z-50 animate-in fade-in slide-in-from-bottom-2 duration-200">
                        <div className="flex items-center gap-3 mb-4 pb-4 border-b border-border-light dark:border-border-dark">
                            <div className="h-12 w-12 rounded-full bg-primary flex items-center justify-center text-white font-bold text-lg uppercase">
                                {userInitials}
                            </div>
                            <div className="overflow-hidden">
                                <p className="font-semibold text-sm text-text-main-light dark:text-text-main-dark truncate">
                                    {userName}
                                </p>
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark truncate">
                                    {userEmail}
                                </p>
                            </div>
                        </div>
                        <div className="space-y-3 text-sm">
                            <div className="flex items-center gap-3 text-text-secondary-light dark:text-text-secondary-dark">
                                <span className="material-symbols-outlined text-lg">mail</span>
                                <span className="truncate">{userEmail}</span>
                            </div>
                            <div className="flex items-center gap-3 text-text-secondary-light dark:text-text-secondary-dark">
                                <span className="material-symbols-outlined text-lg">badge</span>
                                <span>Administrador</span>
                            </div>
                        </div>
                        <button
                            onClick={() => {
                                setShowProfile(false);
                                setShowEditProfileModal(true);
                            }}
                            className="mt-4 w-full text-xs text-primary hover:underline text-center font-medium"
                        >
                            Editar Perfil
                        </button>
                    </div>
                )}

                <div className="flex items-center gap-3">
                    <button
                        onClick={() => setShowProfile(!showProfile)}
                        className="h-9 w-9 shrink-0 rounded-full bg-primary flex items-center justify-center text-white font-bold text-sm hover:scale-105 transition-transform cursor-pointer uppercase"
                    >
                        {userInitials}
                    </button>
                    <button
                        onClick={() => setShowProfile(!showProfile)}
                        className="flex-1 min-w-0 text-left cursor-pointer"
                    >
                        <p className="text-sm font-medium text-text-main-light dark:text-text-main-dark truncate">
                            {userName}
                        </p>
                        <p className="text-[10px] text-text-secondary-light dark:text-text-secondary-dark truncate">
                            {userEmail}
                        </p>
                    </button>
                    <button
                        onClick={handleLogout}
                        title="Sair"
                        className="text-text-secondary-light dark:text-text-secondary-dark hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 p-1.5 rounded-lg transition-all"
                    >
                        <span className="material-symbols-outlined text-lg">logout</span>
                    </button>
                </div>
            </div>

            {showEditProfileModal && (
                <EditProfileModal onClose={() => setShowEditProfileModal(false)} />
            )}
        </aside>
    );
}
