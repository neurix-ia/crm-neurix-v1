"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import {
    downloadVendiExport,
    listVendiActiveClients,
    listVendiSales,
    type StreetSale,
    type VendiActiveClient,
    type VendiMatchStatus,
    type VendiPeriod,
    type VendiSalesAggregates,
} from "@/lib/api";

const MATCH_LABEL: Record<VendiMatchStatus, string> = {
    match: "Áudio = digitado",
    mismatch: "Divergência",
    audio_only: "Só áudio",
    typed_only: "Só digitado",
    no_phone: "Sem telefone",
};

function fmtTime(iso: string): string {
    try {
        return new Date(iso).toLocaleString("pt-BR", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return iso;
    }
}

function unitsOf(s: StreetSale): number {
    return (s.pao_italiano_qtd || 0) + (s.pao_integral_qtd || 0);
}

/** Poll only 07:00–19:00 America/Sao_Paulo, every 15 minutes. */
function shouldPollNow(): boolean {
    try {
        const parts = new Intl.DateTimeFormat("en-US", {
            timeZone: "America/Sao_Paulo",
            hour: "numeric",
            hour12: false,
        }).formatToParts(new Date());
        const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
        return hour >= 7 && hour < 19;
    } catch {
        const h = new Date().getHours();
        return h >= 7 && h < 19;
    }
}

function Kpi({ label, value, icon }: { label: string; value: string; icon: string }) {
    return (
        <div className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-5 flex flex-col gap-2">
            <div className="flex items-center gap-2 text-text-secondary-light dark:text-text-secondary-dark">
                <span className="material-symbols-outlined text-[20px] text-primary">{icon}</span>
                <span className="text-sm font-semibold">{label}</span>
            </div>
            <div className="text-3xl font-extrabold tracking-tight">{value}</div>
        </div>
    );
}

function Toast({ message, onClose }: { message: string; onClose: () => void }) {
    useEffect(() => {
        const t = setTimeout(onClose, 5000);
        return () => clearTimeout(t);
    }, [onClose]);
    return (
        <div className="fixed bottom-6 left-4 right-4 sm:left-auto sm:right-6 sm:max-w-md z-50 rounded-xl bg-emerald-600 text-white px-4 py-3 shadow-lg font-semibold text-sm">
            {message}
        </div>
    );
}

function SaleDetailModal({ sale, onClose }: { sale: StreetSale; onClose: () => void }) {
    return (
        <div className="fixed inset-0 z-40 flex items-end sm:items-center justify-center bg-black/50 p-0 sm:p-4" onClick={onClose}>
            <div
                className="bg-white dark:bg-surface-dark w-full sm:max-w-lg max-h-[90vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl p-5 flex flex-col gap-4"
                onClick={(e) => e.stopPropagation()}
            >
                <div className="flex items-start justify-between gap-3">
                    <div>
                        <h2 className="text-lg font-bold">Detalhe da venda</h2>
                        <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                            {fmtTime(sale.sold_at)} · {sale.seller_name}
                        </p>
                    </div>
                    <button type="button" onClick={onClose} className="text-text-secondary-light">
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>

                <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-xl border border-border-light dark:border-border-dark p-3">
                        <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Italiano</div>
                        <div className="text-xl font-bold">{sale.pao_italiano_qtd}</div>
                    </div>
                    <div className="rounded-xl border border-border-light dark:border-border-dark p-3">
                        <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Integral</div>
                        <div className="text-xl font-bold">{sale.pao_integral_qtd}</div>
                    </div>
                </div>

                <div className="rounded-xl border border-border-light dark:border-border-dark p-3 text-sm space-y-2">
                    <div className="font-semibold">Confronto de telefone</div>
                    <div className="flex justify-between gap-2">
                        <span className="text-text-secondary-light dark:text-text-secondary-dark">Digitado</span>
                        <span className="font-mono">{sale.phone_typed || "—"}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                        <span className="text-text-secondary-light dark:text-text-secondary-dark">Do áudio</span>
                        <span className="font-mono">{sale.phone_from_audio || "—"}</span>
                    </div>
                    <div className="flex justify-between gap-2">
                        <span className="text-text-secondary-light dark:text-text-secondary-dark">Final</span>
                        <span className="font-mono font-bold">{sale.phone_final}</span>
                    </div>
                    <div
                        className={`inline-flex text-xs font-semibold px-2 py-1 rounded-lg ${
                            sale.match_status === "mismatch"
                                ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200"
                                : sale.match_status === "match"
                                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
                                  : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200"
                        }`}
                    >
                        {MATCH_LABEL[sale.match_status] || sale.match_status}
                    </div>
                </div>

                {sale.transcript && (
                    <div className="rounded-xl border border-border-light dark:border-border-dark p-3 text-sm">
                        <div className="font-semibold mb-1">Transcrição</div>
                        <p className="whitespace-pre-wrap text-text-secondary-light dark:text-text-secondary-dark">
                            {sale.transcript}
                        </p>
                    </div>
                )}

                {sale.audio_url && (
                    <div>
                        <div className="text-sm font-semibold mb-1">Áudio</div>
                        <audio controls className="w-full" src={sale.audio_url} />
                    </div>
                )}

                {sale.photo_url && (
                    <div>
                        <div className="text-sm font-semibold mb-1">Foto da placa</div>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={sale.photo_url} alt="Placa" className="w-full rounded-xl border border-border-light dark:border-border-dark" />
                    </div>
                )}

                {sale.client_display_name && (
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                        Cliente: <span className="font-semibold text-text-main-light dark:text-text-main-dark">{sale.client_display_name}</span>
                    </p>
                )}
            </div>
        </div>
    );
}

export default function VendiAdminPage() {
    const [period, setPeriod] = useState<VendiPeriod>("day");
    const [sales, setSales] = useState<StreetSale[]>([]);
    const [aggs, setAggs] = useState<VendiSalesAggregates>({
        total_sales: 0,
        pao_italiano_qtd: 0,
        pao_integral_qtd: 0,
        total_units: 0,
    });
    const [clients, setClients] = useState<VendiActiveClient[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [toast, setToast] = useState<string | null>(null);
    const [selected, setSelected] = useState<StreetSale | null>(null);
    const [tab, setTab] = useState<"feed" | "clientes">("feed");
    const [exporting, setExporting] = useState(false);
    const knownIds = useRef<Set<string>>(new Set());
    const lastPollAt = useRef<string | null>(null);
    const bootstrapped = useRef(false);

    const loadPeriod = useCallback(async () => {
        setLoading(true);
        setError("");
        try {
            const data = await listVendiSales({ period, limit: 200 });
            setSales(data.sales);
            setAggs(data.aggregates);
            knownIds.current = new Set(data.sales.map((s) => s.id));
            if (data.sales[0]?.sold_at) {
                lastPollAt.current = data.sales[0].sold_at;
            } else {
                lastPollAt.current = new Date().toISOString();
            }
            bootstrapped.current = true;
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao carregar vendas");
        } finally {
            setLoading(false);
        }
    }, [period]);

    const loadClients = useCallback(async () => {
        try {
            const list = await listVendiActiveClients({ limit: 100 });
            setClients(list);
        } catch {
            /* silent */
        }
    }, []);

    useEffect(() => {
        void loadPeriod();
        void loadClients();
    }, [loadPeriod, loadClients]);

    const pollDelta = useCallback(async () => {
        if (!bootstrapped.current || !shouldPollNow()) return;
        const since = lastPollAt.current;
        if (!since) return;
        try {
            const data = await listVendiSales({ since, limit: 50 });
            if (!data.sales.length) return;
            const fresh = data.sales.filter((s) => !knownIds.current.has(s.id));
            if (!fresh.length) {
                lastPollAt.current = data.sales[0].sold_at;
                return;
            }
            for (const s of fresh) knownIds.current.add(s.id);
            lastPollAt.current = fresh[0].sold_at;
            setSales((prev) => {
                const merged = [...fresh, ...prev];
                const seen = new Set<string>();
                return merged.filter((s) => {
                    if (seen.has(s.id)) return false;
                    seen.add(s.id);
                    return true;
                });
            });
            // refresh aggregates for current period
            void listVendiSales({ period, limit: 200 }).then((full) => setAggs(full.aggregates));
            void loadClients();

            const top = fresh[0];
            setToast(
                `Nova venda — ${top.seller_name}, ${unitsOf(top)} pão(es) · ${top.phone_final}`
            );
        } catch {
            /* ignore poll errors */
        }
    }, [period, loadClients]);

    useEffect(() => {
        const id = setInterval(() => {
            void pollDelta();
        }, 15 * 60 * 1000);
        return () => clearInterval(id);
    }, [pollDelta]);

    const periodLabel = useMemo(() => {
        if (period === "week") return "Esta semana";
        if (period === "month") return "Este mês";
        return "Hoje";
    }, [period]);

    const handleExport = async () => {
        setExporting(true);
        try {
            await downloadVendiExport({ period });
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha no export");
        } finally {
            setExporting(false);
        }
    };

    return (
        <div className="flex flex-col gap-6 p-4 sm:p-6 max-w-5xl mx-auto w-full">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-extrabold tracking-tight">Vendi</h1>
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                        Acompanhamento de vendas de rua · {periodLabel}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Link
                        href="/vendi/nova"
                        className="inline-flex items-center gap-1.5 h-10 px-4 rounded-xl bg-primary text-white text-sm font-bold shadow-sm"
                    >
                        <span className="material-symbols-outlined text-[18px]">add</span>
                        Nova venda
                    </Link>
                    <button
                        type="button"
                        title="Atualizar agora — refresh imediato do período (qualquer horário)"
                        onClick={() => {
                            void loadPeriod();
                            void loadClients();
                        }}
                        className="inline-flex items-center gap-1.5 h-10 px-3 rounded-xl border border-border-light dark:border-border-dark text-sm font-semibold"
                    >
                        <span className="material-symbols-outlined text-[18px]">refresh</span>
                        Atualizar agora
                    </button>
                    <button
                        type="button"
                        disabled={exporting}
                        onClick={() => void handleExport()}
                        className="inline-flex items-center gap-1.5 h-10 px-3 rounded-xl border border-border-light dark:border-border-dark text-sm font-semibold disabled:opacity-50"
                    >
                        <span className="material-symbols-outlined text-[18px]">download</span>
                        Exportar CSV
                    </button>
                </div>
            </div>

            <div className="flex gap-2">
                {(["day", "week", "month"] as VendiPeriod[]).map((p) => (
                    <button
                        key={p}
                        type="button"
                        onClick={() => setPeriod(p)}
                        className={`h-9 px-4 rounded-full text-sm font-semibold ${
                            period === p
                                ? "bg-primary text-white"
                                : "bg-white dark:bg-surface-dark border border-border-light dark:border-border-dark"
                        }`}
                    >
                        {p === "day" ? "Dia" : p === "week" ? "Semana" : "Mês"}
                    </button>
                ))}
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <Kpi label="Vendas" value={String(aggs.total_sales)} icon="receipt_long" />
                <Kpi label="Pão Italiano" value={String(aggs.pao_italiano_qtd)} icon="bakery_dining" />
                <Kpi label="Pão Integral" value={String(aggs.pao_integral_qtd)} icon="eco" />
                <Kpi label="Total unidades" value={String(aggs.total_units)} icon="shopping_bag" />
            </div>

            <div className="flex gap-2 border-b border-border-light dark:border-border-dark">
                <button
                    type="button"
                    onClick={() => setTab("feed")}
                    className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px ${
                        tab === "feed" ? "border-primary text-primary" : "border-transparent text-text-secondary-light"
                    }`}
                >
                    Feed ao vivo
                </button>
                <button
                    type="button"
                    onClick={() => setTab("clientes")}
                    className={`px-4 py-2 text-sm font-semibold border-b-2 -mb-px ${
                        tab === "clientes" ? "border-primary text-primary" : "border-transparent text-text-secondary-light"
                    }`}
                >
                    Clientes ativos
                </button>
            </div>

            {error && (
                <div className="rounded-xl bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-200 text-sm px-4 py-3">
                    {error}
                </div>
            )}

            {tab === "feed" && (
                <div className="flex flex-col gap-2">
                    <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                        Atualização automática a cada 15 min entre 07h e 19h (Brasília). Fora disso (ou a qualquer hora), use Atualizar agora.
                    </p>
                    {loading && <p className="text-sm text-text-secondary-light">Carregando…</p>}
                    {!loading && sales.length === 0 && (
                        <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark py-8 text-center">
                            Nenhuma venda neste período.
                        </p>
                    )}
                    {sales.map((s) => (
                        <button
                            key={s.id}
                            type="button"
                            onClick={() => setSelected(s)}
                            className="text-left rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-4 hover:border-primary/40 transition-colors"
                        >
                            <div className="flex justify-between gap-3 items-start">
                                <div>
                                    <div className="font-bold">{s.seller_name}</div>
                                    <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                        {fmtTime(s.sold_at)} · {s.phone_final}
                                        {s.client_display_name ? ` · ${s.client_display_name}` : ""}
                                    </div>
                                </div>
                                <div className="text-right shrink-0">
                                    <div className="font-extrabold">{unitsOf(s)} un.</div>
                                    <div className="text-xs text-text-secondary-light">
                                        IT {s.pao_italiano_qtd} · IN {s.pao_integral_qtd}
                                    </div>
                                </div>
                            </div>
                            {s.match_status === "mismatch" && (
                                <div className="mt-2 text-xs font-semibold text-amber-700 dark:text-amber-300">
                                    Telefone divergente (áudio ≠ digitado)
                                </div>
                            )}
                        </button>
                    ))}
                </div>
            )}

            {tab === "clientes" && (
                <div className="flex flex-col gap-2">
                    {clients.length === 0 && (
                        <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark py-8 text-center">
                            Nenhum cliente ativo ainda.
                        </p>
                    )}
                    {clients.map((c) => (
                        <div
                            key={c.client_id}
                            className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-4 flex justify-between gap-3"
                        >
                            <div>
                                <div className="font-bold">{c.display_name}</div>
                                <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark font-mono">
                                    {c.phone || "—"}
                                </div>
                            </div>
                            <div className="text-right text-sm">
                                <div className="font-semibold">{c.sales_count} venda(s)</div>
                                <div className="text-text-secondary-light dark:text-text-secondary-dark">
                                    {c.total_units} un. · {fmtTime(c.last_sale_at)}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {selected && <SaleDetailModal sale={selected} onClose={() => setSelected(null)} />}
            {toast && <Toast message={toast} onClose={() => setToast(null)} />}
        </div>
    );
}
