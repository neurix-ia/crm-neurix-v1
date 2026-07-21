"use client";

import { useEffect, useMemo, useState } from "react";

import { ADMIN_AGENT_REPORT_CATALOG, findAdminAgentById } from "@/lib/admin-agent-report-catalog";
import {
    getAgentEval,
    listAgentEvals,
    type AgentEvalMetric,
    type AgentEvalRun,
    type AgentEvalTestCase,
} from "@/lib/api";

const SEV_CLS: Record<string, string> = {
    alta: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    media: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    baixa: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
};

const MODE_CLS: Record<string, string> = {
    baseline: "bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400",
    mangle: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
};

function fmtDate(iso: string | null): string {
    if (!iso) return "—";
    try {
        return new Date(iso).toLocaleString("pt-BR", {
            day: "2-digit",
            month: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        });
    } catch {
        return "—";
    }
}

function pct(v: number | null | undefined): string {
    return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function scoreCls(m: AgentEvalMetric): string {
    if (m.score === null) return "";
    return m.success
        ? "text-emerald-600 dark:text-emerald-400"
        : "text-red-600 dark:text-red-400 font-bold";
}

/** Sparkline de pass rate (runs em ordem cronológica). */
function TrendChart({ runs }: { runs: AgentEvalRun[] }) {
    const points = [...runs]
        .reverse()
        .filter((r) => r.pass_rate !== null)
        .slice(-20);
    if (points.length < 2) return null;
    const w = 320;
    const h = 64;
    const step = w / (points.length - 1);
    const path = points
        .map((r, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - (r.pass_rate as number) * h).toFixed(1)}`)
        .join(" ");
    return (
        <div className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-4">
            <div className="text-xs font-semibold mb-2 text-text-secondary-light dark:text-text-secondary-dark">
                Tendência de pass rate (últimos {points.length} runs)
            </div>
            <svg viewBox={`0 0 ${w} ${h + 8}`} className="w-full max-w-md" aria-hidden>
                <line x1="0" y1={h / 2} x2={w} y2={h / 2} className="stroke-black/10 dark:stroke-white/10" strokeDasharray="4 4" />
                <path d={path} fill="none" strokeWidth="2" className="stroke-primary" />
                {points.map((r, i) => (
                    <circle
                        key={r.id}
                        cx={i * step}
                        cy={h - (r.pass_rate as number) * h}
                        r="3"
                        className={r.mode === "mangle" ? "fill-purple-500" : "fill-primary"}
                    />
                ))}
            </svg>
        </div>
    );
}

function CaseRow({ tc }: { tc: AgentEvalTestCase }) {
    const [open, setOpen] = useState(false);
    return (
        <div className="border-b border-border-light dark:border-border-dark last:border-b-0">
            <button
                type="button"
                onClick={() => setOpen(!open)}
                className="w-full flex items-center justify-between gap-2 py-2 text-left hover:bg-black/5 dark:hover:bg-white/5 px-2 rounded-lg"
            >
                <span className="flex items-center gap-2 min-w-0">
                    <span className={`shrink-0 w-2 h-2 rounded-full ${tc.passed ? "bg-emerald-500" : "bg-red-500"}`} />
                    <span className="text-sm font-medium truncate">{tc.name || "(sem nome)"}</span>
                </span>
                <span className="flex items-center gap-3 shrink-0">
                    {tc.metrics.map((m) => (
                        <span key={m.name} className={`text-xs tabular-nums ${scoreCls(m)}`} title={m.name}>
                            {m.score === null ? "—" : m.score.toFixed(2)}
                        </span>
                    ))}
                    <span className="material-symbols-outlined text-base text-text-secondary-light">
                        {open ? "expand_less" : "expand_more"}
                    </span>
                </span>
            </button>
            {open && (
                <div className="px-2 pb-3 flex flex-col gap-2">
                    {tc.metrics.map((m) => (
                        <div key={m.name} className="text-xs">
                            <span className={`font-semibold ${scoreCls(m)}`}>
                                {m.name}: {m.score === null ? "—" : m.score.toFixed(2)}
                            </span>{" "}
                            <span className="text-text-secondary-light dark:text-text-secondary-dark">{m.reason || ""}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export default function AgentesEvalsPage() {
    const [rows, setRows] = useState<AgentEvalRun[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [mode, setMode] = useState("");
    const [detail, setDetail] = useState<AgentEvalRun | null>(null);
    const [compare, setCompare] = useState<AgentEvalRun | null>(null);

    const selectedAgent = useMemo(() => findAdminAgentById(selectedAgentId), [selectedAgentId]);

    const load = () => {
        setLoading(true);
        setError("");
        const opts: Parameters<typeof listAgentEvals>[0] = { mode: mode || undefined };
        if (selectedAgent?.agentKeys.length === 1) opts.agent_key = selectedAgent.agentKeys[0];
        else if (selectedAgent && selectedAgent.agentKeys.length > 1) opts.agent_keys = selectedAgent.agentKeys;
        listAgentEvals(opts)
            .then(setRows)
            .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar"))
            .finally(() => setLoading(false));
    };
    useEffect(load, [selectedAgentId, selectedAgent, mode]);

    const openRun = async (r: AgentEvalRun, slot: "detail" | "compare") => {
        try {
            const full = await getAgentEval(r.id);
            if (slot === "detail") setDetail(full);
            else setCompare(full);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao carregar run");
        }
    };

    const caseNames = useMemo(() => {
        const names = new Set<string>();
        detail?.result?.test_cases?.forEach((tc) => names.add(tc.name || ""));
        compare?.result?.test_cases?.forEach((tc) => names.add(tc.name || ""));
        return [...names];
    }, [detail, compare]);

    return (
        <div className="relative z-10 max-w-5xl mx-auto flex flex-col gap-5">
            <div>
                <h1 className="text-2xl font-extrabold tracking-tight">Evals dos agentes</h1>
                <p className="text-text-secondary-light dark:text-text-secondary-dark text-sm">
                    Histórico das baterias DeepEval por agente — pass rate, métricas por cenário e sugestões de melhoria.
                </p>
            </div>

            <div className="flex gap-2 flex-wrap">
                <button
                    type="button"
                    onClick={() => setSelectedAgentId(null)}
                    className={`h-9 px-3 rounded-xl text-sm font-semibold border transition-colors ${
                        selectedAgentId === null
                            ? "bg-primary text-white border-primary"
                            : "border-border-light dark:border-border-dark bg-white dark:bg-surface-dark hover:bg-black/5 dark:hover:bg-white/5"
                    }`}
                >
                    Todos
                </button>
                {ADMIN_AGENT_REPORT_CATALOG.map((a) => (
                    <button
                        key={a.id}
                        type="button"
                        onClick={() => setSelectedAgentId(a.id)}
                        className={`h-9 px-3 rounded-xl text-sm font-semibold border transition-colors ${
                            selectedAgentId === a.id
                                ? "bg-primary text-white border-primary"
                                : "border-border-light dark:border-border-dark bg-white dark:bg-surface-dark hover:bg-black/5 dark:hover:bg-white/5"
                        }`}
                    >
                        {a.label}
                    </button>
                ))}
                <select
                    value={mode}
                    onChange={(e) => setMode(e.target.value)}
                    className="h-9 px-3 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-sm"
                >
                    <option value="">Baseline + mangle</option>
                    <option value="baseline">Só baseline</option>
                    <option value="mangle">Só mangle</option>
                </select>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-xl border border-red-200 dark:border-red-800">
                    {error}
                </div>
            )}

            <TrendChart runs={rows} />

            {detail && (
                <div className="rounded-2xl border border-primary/40 bg-white dark:bg-surface-dark p-5 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div>
                            <div className="text-xs uppercase tracking-wide text-text-secondary-light dark:text-text-secondary-dark mb-1">
                                Run {compare ? "· comparando" : ""}
                            </div>
                            <h2 className="text-lg font-bold">
                                {detail.agent_name}{" "}
                                <span className={`text-xs px-2 py-0.5 rounded-full font-semibold align-middle ${MODE_CLS[detail.mode] || ""}`}>
                                    {detail.mode}
                                </span>
                            </h2>
                            <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                {fmtDate(detail.created_at)} · pass rate {pct(detail.pass_rate)} ({detail.passed}/{detail.total})
                            </p>
                        </div>
                        <div className="flex gap-2">
                            {compare && (
                                <button
                                    type="button"
                                    onClick={() => setCompare(null)}
                                    className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5"
                                >
                                    Tirar comparação
                                </button>
                            )}
                            <button
                                type="button"
                                onClick={() => {
                                    setDetail(null);
                                    setCompare(null);
                                }}
                                className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5"
                            >
                                Fechar
                            </button>
                        </div>
                    </div>

                    {compare ? (
                        <div className="overflow-x-auto">
                            <table className="w-full text-sm">
                                <thead>
                                    <tr className="text-left text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                        <th className="py-1 pr-3">Cenário</th>
                                        <th className="py-1 pr-3">
                                            {detail.mode} · {fmtDate(detail.created_at)}
                                        </th>
                                        <th className="py-1">
                                            {compare.mode} · {fmtDate(compare.created_at)}
                                        </th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {caseNames.map((name) => {
                                        const a = detail.result?.test_cases?.find((t) => (t.name || "") === name);
                                        const b = compare.result?.test_cases?.find((t) => (t.name || "") === name);
                                        const cell = (tc?: AgentEvalTestCase) =>
                                            tc ? (
                                                <span className={tc.passed ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400 font-bold"}>
                                                    {tc.passed ? "pass" : "fail"}{" "}
                                                    <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark tabular-nums">
                                                        ({tc.metrics.map((m) => (m.score === null ? "—" : m.score.toFixed(2))).join(" · ")})
                                                    </span>
                                                </span>
                                            ) : (
                                                "—"
                                            );
                                        return (
                                            <tr key={name} className="border-t border-border-light dark:border-border-dark">
                                                <td className="py-1.5 pr-3 font-medium">{name || "(sem nome)"}</td>
                                                <td className="py-1.5 pr-3">{cell(a)}</td>
                                                <td className="py-1.5">{cell(b)}</td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div>
                            {detail.result?.test_cases?.length ? (
                                <div className="flex flex-col">
                                    {detail.result.test_cases.map((tc, i) => (
                                        <CaseRow key={tc.name || i} tc={tc} />
                                    ))}
                                </div>
                            ) : (
                                <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Run sem test_cases.</p>
                            )}
                        </div>
                    )}

                    {detail.suggestions?.length > 0 && !compare && (
                        <div>
                            <div className="text-xs font-semibold mb-1">Sugestões de melhoria</div>
                            <ul className="flex flex-col gap-1.5 text-sm">
                                {detail.suggestions.map((s, i) => (
                                    <li key={i} className="flex items-start gap-2">
                                        <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-semibold ${SEV_CLS[s.severidade] || ""}`}>
                                            {s.severidade}
                                        </span>
                                        <span>
                                            <strong>{s.problema}</strong>
                                            {s.recomendacao ? ` — ${s.recomendacao}` : ""}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}

            {loading && <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Carregando…</div>}
            {!loading && rows.length === 0 && !error && (
                <div className="rounded-2xl border border-border-light dark:border-border-dark p-8 text-center text-text-secondary-light dark:text-text-secondary-dark">
                    Ainda sem runs de eval{selectedAgent ? ` para ${selectedAgent.label}` : ""}. Dispare a bateria pelo workflow
                    de eval no n8n.
                </div>
            )}

            <div className="flex flex-col gap-3">
                {rows.map((r) => (
                    <div
                        key={r.id}
                        className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-5"
                    >
                        <div className="flex items-center justify-between gap-3 flex-wrap">
                            <div className="flex items-center gap-2 flex-wrap min-w-0">
                                <span className="font-bold">{r.agent_name}</span>
                                <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${MODE_CLS[r.mode] || ""}`}>
                                    {r.mode}
                                </span>
                                <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    {fmtDate(r.created_at)}
                                </span>
                                <span
                                    className={`text-sm font-bold tabular-nums ${
                                        (r.pass_rate ?? 0) >= 0.8
                                            ? "text-emerald-600 dark:text-emerald-400"
                                            : (r.pass_rate ?? 0) >= 0.5
                                              ? "text-amber-600 dark:text-amber-400"
                                              : "text-red-600 dark:text-red-400"
                                    }`}
                                >
                                    {pct(r.pass_rate)}
                                </span>
                                <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    {r.passed}/{r.total} cenários
                                </span>
                                {r.suggestions?.length > 0 && (
                                    <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                        · {r.suggestions.length} sugestões
                                    </span>
                                )}
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={() => openRun(r, "detail")}
                                    className="text-xs font-semibold px-3 h-8 rounded-lg bg-primary text-white hover:opacity-90"
                                >
                                    Detalhes
                                </button>
                                {detail && detail.id !== r.id && (
                                    <button
                                        type="button"
                                        onClick={() => openRun(r, "compare")}
                                        className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5"
                                    >
                                        Comparar
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
