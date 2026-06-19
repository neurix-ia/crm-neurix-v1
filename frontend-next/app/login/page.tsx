"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { getApiUrl, getAuthMe } from "@/lib/api";
import { persistAuthSession } from "@/lib/supabase";

export default function LoginPage() {
    const router = useRouter();
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    /** Após login bem-sucedido: superadmin escolhe destino (S5-UI-2). */
    const [postLoginChoice, setPostLoginChoice] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        setLoading(true);

        try {
            const res = await fetch(getApiUrl("/api/auth/login"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email, password }),
            });

            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || "Credenciais inválidas");
            }

            const data = await res.json();
            await persistAuthSession(data.access_token, data.refresh_token || "");

            try {
                const me = await getAuthMe(data.access_token);
                if (me.is_superadmin) {
                    setPostLoginChoice(true);
                    return;
                }
            } catch {
                /* fallback: app normal */
            }
            router.push("/dashboard");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Erro ao fazer login");
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="bg-background-light dark:bg-background-dark min-h-screen flex flex-col relative overflow-hidden text-text-main-light dark:text-text-main-dark font-display">
            {/* Background */}
            <div className="absolute inset-0 z-0 bg-gradient-to-br from-purple-50 via-white to-purple-100 dark:from-gray-900 dark:via-gray-900 dark:to-[#2a1b3d]" />
            <div className="absolute inset-0 z-0 bg-pattern" />
            <div className="absolute top-[-10%] right-[-5%] w-[500px] h-[500px] rounded-full bg-primary/5 blur-[100px] pointer-events-none" />
            <div className="absolute bottom-[-10%] left-[-10%] w-[600px] h-[600px] rounded-full bg-primary/10 blur-[120px] pointer-events-none" />

            {/* Content */}
            <div className="flex h-full grow flex-col relative z-10 justify-center items-center py-10 px-4 sm:px-6 lg:px-8">
                <div className="w-full max-w-[440px] flex flex-col gap-6">
                    {/* Header */}
                    <div className="text-center mb-2">
                        <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-6 text-primary shadow-lg shadow-primary/10">
                            <span className="material-symbols-outlined text-4xl">hexagon</span>
                        </div>
                        <h1 className="text-3xl font-extrabold tracking-tight mb-2">
                            Neurix CRM
                        </h1>
                        <p className="text-text-secondary-light dark:text-text-secondary-dark text-base">
                            Faça login para gerenciar sua produção
                        </p>
                    </div>

                    {/* Login Card */}
                    <div className="glass-effect rounded-2xl shadow-lg shadow-primary/5 border border-primary-light/50 p-8 sm:p-10 w-full">
                        {postLoginChoice ? (
                            <div className="flex flex-col gap-4 text-center">
                                <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                    Conta superadmin detectada. Onde deseja ir?
                                </p>
                                <button
                                    type="button"
                                    onClick={() => router.push("/admin/core")}
                                    className="w-full h-12 bg-primary hover:bg-primary-hover text-white font-bold rounded-xl shadow-lg shadow-primary/30 flex items-center justify-center gap-2"
                                >
                                    <span className="material-symbols-outlined text-[20px]">dashboard</span>
                                    Neurix HQ
                                </button>
                                <button
                                    type="button"
                                    onClick={() => router.push("/admin")}
                                    className="w-full h-12 border border-border-light dark:border-border-dark font-bold rounded-xl hover:bg-black/5 dark:hover:bg-white/5 flex items-center justify-center gap-2"
                                >
                                    <span className="material-symbols-outlined text-[20px]">admin_panel_settings</span>
                                    Console Admin
                                </button>
                                <button
                                    type="button"
                                    onClick={() => router.push("/dashboard")}
                                    className="w-full h-12 border border-border-light dark:border-border-dark font-bold rounded-xl hover:bg-black/5 dark:hover:bg-white/5"
                                >
                                    Ir para o app
                                </button>
                            </div>
                        ) : (
                        <form onSubmit={handleSubmit} className="flex flex-col gap-5">
                            {error && (
                                <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-xl border border-red-200 dark:border-red-800">
                                    {error}
                                </div>
                            )}

                            {/* Email */}
                            <div className="flex flex-col gap-2">
                                <label
                                    htmlFor="email"
                                    className="text-sm font-semibold text-text-secondary-light dark:text-text-secondary-dark ml-1"
                                >
                                    Email Corporativo
                                </label>
                                <div className="relative group">
                                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-text-secondary-light group-focus-within:text-primary transition-colors">
                                        <span className="material-symbols-outlined text-[20px]">
                                            mail
                                        </span>
                                    </div>
                                    <input
                                        id="email"
                                        type="email"
                                        autoComplete="email"
                                        value={email}
                                        onChange={(e) => setEmail(e.target.value)}
                                        placeholder="nome@neurix.com"
                                        className="w-full h-12 pl-11 pr-4 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-text-main-light dark:text-text-main-dark placeholder:text-text-secondary-light focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all duration-200"
                                        required
                                    />
                                </div>
                            </div>

                            {/* Password */}
                            <div className="flex flex-col gap-2">
                                <div className="flex justify-between items-center ml-1">
                                    <label
                                        htmlFor="password"
                                        className="text-sm font-semibold text-text-secondary-light dark:text-text-secondary-dark"
                                    >
                                        Senha
                                    </label>
                                    <a
                                        href="#"
                                        className="text-sm font-medium text-primary hover:text-primary-dark transition-colors"
                                    >
                                        Esqueceu a senha?
                                    </a>
                                </div>
                                <div className="relative group">
                                    <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-text-secondary-light group-focus-within:text-primary transition-colors">
                                        <span className="material-symbols-outlined text-[20px]">
                                            lock
                                        </span>
                                    </div>
                                    <input
                                        id="password"
                                        type="password"
                                        value={password}
                                        onChange={(e) => setPassword(e.target.value)}
                                        placeholder="••••••••"
                                        className="w-full h-12 pl-11 pr-4 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-text-main-light dark:text-text-main-dark placeholder:text-text-secondary-light focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all duration-200"
                                        required
                                    />
                                </div>
                            </div>

                            {/* Submit */}
                            <button
                                type="submit"
                                disabled={loading}
                                className="mt-2 w-full h-12 bg-primary hover:bg-primary-hover disabled:opacity-60 text-white font-bold rounded-xl shadow-lg shadow-primary/30 hover:shadow-primary/40 active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2 group"
                            >
                                <span>{loading ? "Entrando..." : "Entrar na Plataforma"}</span>
                                {!loading && (
                                    <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform text-[20px]">
                                        arrow_forward
                                    </span>
                                )}
                            </button>
                        </form>
                        )}

                        {!postLoginChoice && (
                            <>
                        {/* Divider */}
                        <div className="relative my-8">
                            <div className="absolute inset-0 flex items-center">
                                <div className="w-full border-t border-border-light dark:border-border-dark" />
                            </div>
                            <div className="relative flex justify-center text-xs uppercase tracking-wider">
                                <span className="bg-white dark:bg-surface-dark px-3 text-text-secondary-light">
                                    Acesso Seguro
                                </span>
                            </div>
                        </div>

                        {/* Footer Links */}
                        <div className="flex items-center justify-center gap-6 text-sm text-text-secondary-light">
                            <a
                                href="#"
                                className="hover:text-primary transition-colors flex items-center gap-1"
                            >
                                <span className="material-symbols-outlined text-[18px]">
                                    help
                                </span>
                                Ajuda
                            </a>
                            <a
                                href="#"
                                className="hover:text-primary transition-colors flex items-center gap-1"
                            >
                                <span className="material-symbols-outlined text-[18px]">
                                    privacy_tip
                                </span>
                                Privacidade
                            </a>
                        </div>
                            </>
                        )}
                    </div>

                    {/* Bottom */}
                    <div className="text-center space-y-2">
                        <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark font-medium">
                            Neurix CRM v1.0 • Sua fábrica de geleias conectada
                        </p>
                        <div className="flex justify-center gap-2">
                            <div className="h-1 w-1 rounded-full bg-primary/40" />
                            <div className="h-1 w-1 rounded-full bg-primary/40" />
                            <div className="h-1 w-1 rounded-full bg-primary/40" />
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
