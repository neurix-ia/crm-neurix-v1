"use client";

import { useCallback, useEffect, useState } from "react";

import {
    getHqN8nOverview,
    getHqN8nWorkflowErrors,
    getHqSummary,
    refreshHqN8nCache,
    type HqLevel,
    type HqPeriod,
    type N8nOverviewResponse,
    type N8nWorkflowErrorRow,
    type N8nWorkflowErrorsResponse,
    type HqSummaryResponse,
} from "@/lib/api";
import N8nExecutionErrorModal from "@/components/admin/N8nExecutionErrorModal";

const PERIODS: { value: HqPeriod; label: string }[] = [
    { value: "24h", label: "24h" },
    { value: "7d", label: "7 dias" },
    { value: "30d", label: "30 dias" },
];

function levelDot(level: HqLevel) {
    const map: Record<HqLevel, string> = {
        green: "bg-emerald-500",
        yellow: "bg-amber-500",
        red: "bg-red-500",
        gray: "bg-slate-400",
    };
    return map[level] || map.gray;
}

function levelBorder(level: HqLevel) {
    const map: Record<HqLevel, string> = {
        green: "border-emerald-500/30",
        yellow: "border-amber-500/40",
        red: "border-red-500/40",
        gray: "border-slate-400/30",
    };
    return map[level] || map.gray;
}

function formatNumber(n: number) {
    return n.toLocaleString("pt-BR");
}

function formatTimeSaved(minutes: number) {
    if (minutes >= 60) {
        return `${(minutes / 60).toFixed(0)}h`;
    }
    return `${Math.round(minutes)} min`;
}

function deviationBadge(dev: number | null | undefined, unit: "%" | "s" = "%") {
    if (dev == null || Number.isNaN(dev)) return null;
    const sign = dev > 0 ? "+" : "";
    const color = dev > 0 ? "text-emerald-600" : dev < 0 ? "text-red-600" : "text-text-secondary-light";
    return (
        <span className={`text-xs font-medium ${color}`}>
            {sign}
            {unit === "%" ? (dev * 100).toFixed(1) : dev.toFixed(2)}
            {unit}
        </span>
    );
}

function KpiCard({
    label,
    value,
    sub,
    deviation,
    devUnit = "%",
}: {
    label: string;
    value: string;
    sub?: string;
    deviation?: number | null;
    devUnit?: "%" | "s";
}) {
    return (
        <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-4 shadow-lg shadow-primary/5">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary-light">{label}</p>
            <p className="text-2xl font-bold font-display mt-1">{value}</p>
            <div className="flex items-center gap-2 mt-1">
                {sub && <p className="text-xs text-text-secondary-light">{sub}</p>}
                {deviationBadge(deviation, devUnit)}
            </div>
        </div>
    );
}

export default function NeurixHqPage() {
    const [period, setPeriod] = useState<HqPeriod>("7d");
    const [summary, setSummary] = useState<HqSummaryResponse | null>(null);
    const [overview, setOverview] = useState<N8nOverviewResponse | null>(null);
    const [errors, setErrors] = useState<N8nWorkflowErrorsResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [err, setErr] = useState<string | null>(null);
    const [selectedRow, setSelectedRow] = useState<N8nWorkflowErrorRow | null>(null);

    const load = useCallback(
        async (forceRefresh = false) => {
            const token = localStorage.getItem("access_token");
            if (!token) return;
            setErr(null);
            if (forceRefresh) setRefreshing(true);
            else setLoading(true);
            try {
                const [s, o, e] = await Promise.all([
                    getHqSummary(period, token),
                    getHqN8nOverview(period, forceRefresh, token),
                    getHqN8nWorkflowErrors(period, 20, forceRefresh, token),
                ]);
                setSummary(s);
                setOverview(o);
                setErrors(e);
            } catch (e) {
                setErr(e instanceof Error ? e.message : "Erro ao carregar Neurix HQ.");
            } finally {
                setLoading(false);
                setRefreshing(false);
            }
        },
        [period]
    );

    useEffect(() => {
        load();
    }, [load]);

    const handleRefresh = async () => {
        const token = localStorage.getItem("access_token");
        if (!token) return;
        try {
            await refreshHqN8nCache(token);
        } catch {
            /* cache invalidation is best-effort */
        }
        await load(true);
    };

    const c = overview?.consolidated;
    const devs = c?.metrics_raw?.deviations;

    return (
        <div className="max-w-6xl space-y-8">
            <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-bold font-display">Neurix HQ</h1>
                    <p className="text-text-secondary-light dark:text-text-secondary-dark text-sm mt-1">
                        Visão operacional da empresa — saúde de automações, comercial e mais.
                    </p>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <div className="flex rounded-xl border border-border-light dark:border-border-dark overflow-hidden">
                        {PERIODS.map((p) => (
                            <button
                                key={p.value}
                                type="button"
                                onClick={() => setPeriod(p.value)}
                                className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                                    period === p.value
                                        ? "bg-primary text-white"
                                        : "hover:bg-black/5 dark:hover:bg-white/5"
                                }`}
                            >
                                {p.label}
                            </button>
                        ))}
                    </div>
                    <button
                        type="button"
                        onClick={handleRefresh}
                        disabled={refreshing}
                        className="px-3 py-1.5 text-sm font-medium rounded-xl border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5 disabled:opacity-50"
                    >
                        {refreshing ? "Atualizando…" : "Atualizar"}
                    </button>
                </div>
            </div>

            {err && (
                <div className="rounded-xl border border-red-300 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 px-4 py-3 text-sm">
                    {err}
                </div>
            )}

            {/* Semáforo */}
            <section>
                <h2 className="text-sm font-semibold uppercase tracking-wide text-text-secondary-light mb-3">
                    Status geral
                </h2>
                {loading && !summary ? (
                    <p className="text-sm text-text-secondary-light">Carregando…</p>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                        {(summary?.modules ?? []).map((mod) => (
                            <div
                                key={mod.id}
                                className={`glass-effect rounded-2xl border-2 p-4 ${levelBorder(mod.level)} ${
                                    !mod.enabled ? "opacity-60" : ""
                                }`}
                            >
                                <div className="flex items-center gap-2 mb-2">
                                    <span className={`w-2.5 h-2.5 rounded-full ${levelDot(mod.level)}`} />
                                    <span className="font-semibold text-sm">{mod.label}</span>
                                </div>
                                <p className="text-xs text-text-secondary-light leading-relaxed">{mod.summary}</p>
                                {mod.alerts.length > 0 && (
                                    <ul className="mt-2 space-y-1">
                                        {mod.alerts.slice(0, 2).map((a, i) => (
                                            <li key={i} className="text-xs text-red-600 dark:text-red-400 truncate">
                                                {a.message}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </section>

            {/* KPIs Automação */}
            <section>
                <h2 className="text-lg font-bold font-display mb-1">Automação (n8n)</h2>
                <p className="text-xs text-text-secondary-light mb-4">
                    Consolidado neurix + wbtech
                    {overview?.cached && " · dados em cache"}
                    {overview?.generated_at && (
                        <> · {new Date(overview.generated_at).toLocaleString("pt-BR")}</>
                    )}
                </p>

                {loading && !overview ? (
                    <p className="text-sm text-text-secondary-light">Carregando métricas…</p>
                ) : c ? (
                    <>
                        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
                            <KpiCard
                                label="Execuções prod."
                                value={formatNumber(c.total_executions)}
                                deviation={devs?.total ?? null}
                            />
                            <KpiCard
                                label="Falhas prod."
                                value={formatNumber(c.failed_executions)}
                                deviation={devs?.failed ?? null}
                            />
                            <KpiCard
                                label="Taxa de falha"
                                value={`${c.failure_rate}%`}
                                deviation={devs?.failureRate ?? null}
                            />
                            <KpiCard
                                label="Tempo economizado"
                                value={formatTimeSaved(c.time_saved_minutes)}
                                deviation={devs?.timeSaved ?? null}
                            />
                            <KpiCard
                                label="Run time (méd.)"
                                value={`${c.average_run_time_seconds.toFixed(2)}s`}
                                deviation={devs?.averageRunTime ?? null}
                                devUnit="s"
                            />
                        </div>

                        {overview.instances.length > 0 && (
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-8">
                                {overview.instances.map((inst) => (
                                    <div
                                        key={inst.id}
                                        className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-4"
                                    >
                                        <div className="flex items-center justify-between mb-2">
                                            <span className="font-semibold text-sm">{inst.label}</span>
                                            <span
                                                className={`text-xs px-2 py-0.5 rounded-full ${
                                                    inst.status === "ok"
                                                        ? "bg-emerald-500/15 text-emerald-700"
                                                        : "bg-red-500/15 text-red-700"
                                                }`}
                                            >
                                                {inst.status === "ok" ? "online" : "erro"}
                                            </span>
                                        </div>
                                        {inst.status === "error" ? (
                                            <p className="text-xs text-red-600 dark:text-red-400">{inst.error_message}</p>
                                        ) : (
                                            <p className="text-xs text-text-secondary-light">
                                                {formatNumber(inst.total_executions)} exec. · {inst.failed_executions}{" "}
                                                falhas · {inst.failure_rate}%
                                            </p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}
                    </>
                ) : null}
            </section>

            {/* Ranking erros */}
            <section>
                <h2 className="text-lg font-bold font-display mb-3">Workflows com mais falhas</h2>
                {loading && !errors ? (
                    <p className="text-sm text-text-secondary-light">Carregando ranking…</p>
                ) : errors && errors.rows.length === 0 ? (
                    <p className="text-sm text-text-secondary-light">
                        Nenhuma falha no período — ou configure N8N_INSTANCES no backend.
                    </p>
                ) : (
                    <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark overflow-hidden">
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="border-b border-border-light dark:border-border-dark text-left text-xs uppercase tracking-wide text-text-secondary-light">
                                        <th className="px-4 py-3">#</th>
                                        <th className="px-4 py-3">Workflow</th>
                                        <th className="px-4 py-3">Pasta (cliente)</th>
                                        <th className="px-4 py-3">Instância</th>
                                        <th className="px-4 py-3 text-right">Falhas</th>
                                        <th className="px-4 py-3">Última falha</th>
                                        <th className="px-4 py-3 text-right">Run méd.</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {errors?.rows.map((row, idx) => (
                                        <tr
                                            key={`${row.instance_id}-${row.workflow_id ?? idx}`}
                                            onClick={() => setSelectedRow(row)}
                                            className="border-b border-border-light/50 dark:border-border-dark/50 hover:bg-primary/5 cursor-pointer"
                                        >
                                            <td className="px-4 py-3 text-text-secondary-light">{idx + 1}</td>
                                            <td className="px-4 py-3 font-medium">{row.workflow_name}</td>
                                            <td className="px-4 py-3 text-text-secondary-light">
                                                {row.project_name || "—"}
                                            </td>
                                            <td className="px-4 py-3">
                                                <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">
                                                    {row.instance_label}
                                                </span>
                                            </td>
                                            <td className="px-4 py-3 text-right font-semibold text-red-600 dark:text-red-400">
                                                {row.failed_executions}
                                            </td>
                                            <td className="px-4 py-3 text-xs text-text-secondary-light">
                                                {row.last_failed_at
                                                    ? new Date(row.last_failed_at).toLocaleString("pt-BR")
                                                    : "—"}
                                            </td>
                                            <td className="px-4 py-3 text-right text-text-secondary-light">
                                                {row.average_run_time_seconds.toFixed(2)}s
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}
                <p className="text-xs text-text-secondary-light mt-2">
                    Clique em uma linha para ver a causa do erro.
                </p>
            </section>

            {selectedRow && (
                <N8nExecutionErrorModal row={selectedRow} onClose={() => setSelectedRow(null)} />
            )}
        </div>
    );
}
