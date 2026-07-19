"use client";

import { useEffect, useMemo, useState } from "react";

import {
    ADMIN_AGENT_REPORT_CATALOG,
    findAdminAgentById,
    type AdminAgentReportEntry,
} from "@/lib/admin-agent-report-catalog";
import { listAgentReports, patchAgentReport, type AgentImprovementReport } from "@/lib/api";

const SEV_CLS: Record<string, string> = {
    alta: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    media: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    baixa: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
};
const NEXT_STATUS: Record<string, string> = { aberto: "revisado", revisado: "aplicado", aplicado: "aberto" };

function fmtRange(startIso: string, endIso: string): string {
    try {
        const s = new Date(startIso);
        const e = new Date(endIso);
        const f = (d: Date) => d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
        return `${f(s)} – ${f(e)}`;
    } catch {
        return "";
    }
}

export default function AgentesSaudePage() {
    const [rows, setRows] = useState<AgentImprovementReport[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [sev, setSev] = useState("");
    const [status, setStatus] = useState("");
    const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
    const [detail, setDetail] = useState<AgentImprovementReport | null>(null);

    const selectedAgent: AdminAgentReportEntry | undefined = useMemo(
        () => findAdminAgentById(selectedAgentId),
        [selectedAgentId]
    );

    const load = () => {
        setLoading(true);
        setError("");
        const opts: Parameters<typeof listAgentReports>[0] = {
            severidade: sev || undefined,
            status: status || undefined,
        };
        if (selectedAgent?.agentKeys.length === 1) {
            opts.agent_key = selectedAgent.agentKeys[0];
        } else if (selectedAgent && selectedAgent.agentKeys.length > 1) {
            opts.agent_keys = selectedAgent.agentKeys;
        }
        listAgentReports(opts)
            .then((data) => {
                setRows(data);
                setDetail((cur) => (cur && data.some((r) => r.id === cur.id) ? cur : null));
            })
            .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar"))
            .finally(() => setLoading(false));
    };
    useEffect(load, [sev, status, selectedAgentId, selectedAgent]);

    const cycle = async (r: AgentImprovementReport) => {
        const next = NEXT_STATUS[r.status] || "aberto";
        try {
            await patchAgentReport(r.id, next);
            setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, status: next } : x)));
            setDetail((cur) => (cur?.id === r.id ? { ...cur, status: next } : cur));
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao atualizar status");
        }
    };

    const emptyMessage = selectedAgent
        ? selectedAgent.hasWeeklyPipeline
            ? `Ainda sem relatório semanal para ${selectedAgent.label}.`
            : `Ainda sem relatório semanal para ${selectedAgent.label} (pipeline não ligado).`
        : "Nenhum relatório de agente.";

    return (
        <div className="flex flex-col gap-5">
            <div>
                <h1 className="text-2xl font-extrabold tracking-tight">Saúde dos agentes</h1>
                <p className="text-text-secondary-light dark:text-text-secondary-dark text-sm">
                    Relatórios semanais de melhoria — internos, não enviados ao cliente. Escolha um agente para filtrar.
                </p>
            </div>

            <div className="flex gap-2 flex-wrap">
                <button
                    type="button"
                    onClick={() => {
                        setSelectedAgentId(null);
                        setDetail(null);
                    }}
                    className={`h-9 px-3 rounded-xl text-sm font-semibold border transition-colors ${
                        selectedAgentId === null
                            ? "bg-primary text-white border-primary"
                            : "border-border-light dark:border-border-dark bg-white dark:bg-surface-dark hover:bg-black/5 dark:hover:bg-white/5"
                    }`}
                >
                    Todos
                </button>
                {ADMIN_AGENT_REPORT_CATALOG.map((a) => {
                    const active = selectedAgentId === a.id;
                    return (
                        <button
                            key={a.id}
                            type="button"
                            onClick={() => {
                                setSelectedAgentId(a.id);
                                setDetail(null);
                            }}
                            className={`h-9 px-3 rounded-xl text-sm font-semibold border transition-colors ${
                                active
                                    ? "bg-primary text-white border-primary"
                                    : "border-border-light dark:border-border-dark bg-white dark:bg-surface-dark hover:bg-black/5 dark:hover:bg-white/5"
                            }`}
                            title={a.hasWeeklyPipeline ? "Pipeline semanal ativo" : "Somente botão — sem pipeline ainda"}
                        >
                            {a.label}
                        </button>
                    );
                })}
            </div>

            <div className="flex gap-3 flex-wrap">
                <select
                    value={sev}
                    onChange={(e) => setSev(e.target.value)}
                    className="h-10 px-3 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-sm"
                >
                    <option value="">Toda severidade</option>
                    <option value="alta">Alta</option>
                    <option value="media">Média</option>
                    <option value="baixa">Baixa</option>
                </select>
                <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                    className="h-10 px-3 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-sm"
                >
                    <option value="">Todo status</option>
                    <option value="aberto">Aberto</option>
                    <option value="revisado">Revisado</option>
                    <option value="aplicado">Aplicado</option>
                </select>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-xl border border-red-200 dark:border-red-800">
                    {error}
                </div>
            )}

            {detail && (
                <div className="rounded-2xl border border-primary/40 bg-white dark:bg-surface-dark p-5 flex flex-col gap-3">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div>
                            <div className="text-xs uppercase tracking-wide text-text-secondary-light dark:text-text-secondary-dark mb-1">
                                Relatório
                            </div>
                            <h2 className="text-lg font-bold">{detail.agent_name}</h2>
                            <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                {detail.week_key}
                                {detail.week_start && detail.week_end
                                    ? ` · ${fmtRange(detail.week_start, detail.week_end)}`
                                    : ""}
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => setDetail(null)}
                            className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5"
                        >
                            Fechar
                        </button>
                    </div>
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${SEV_CLS[detail.severidade] || ""}`}>
                            {detail.severidade}
                        </span>
                        <button
                            type="button"
                            onClick={() => cycle(detail)}
                            className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5"
                        >
                            {detail.status} ›
                        </button>
                    </div>
                    <p className="text-sm leading-relaxed">{detail.problema}</p>
                    {detail.recomendacoes?.length > 0 && (
                        <div>
                            <div className="text-xs font-semibold mb-1">Recomendações</div>
                            <ul className="list-disc list-inside text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                {detail.recomendacoes.map((rec, i) => (
                                    <li key={i}>{rec}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                </div>
            )}

            {loading && <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Carregando…</div>}
            {!loading && rows.length === 0 && !error && (
                <div className="rounded-2xl border border-border-light dark:border-border-dark p-8 text-center text-text-secondary-light dark:text-text-secondary-dark">
                    {emptyMessage}
                </div>
            )}

            <div className="flex flex-col gap-3">
                {rows.map((r) => (
                    <div
                        key={r.id}
                        className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-5"
                    >
                        <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
                            <div className="flex items-center gap-2 flex-wrap">
                                <span className="font-bold">{r.agent_name}</span>
                                <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    {r.week_key}
                                </span>
                                <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${SEV_CLS[r.severidade] || ""}`}>
                                    {r.severidade}
                                </span>
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    type="button"
                                    onClick={() => setDetail(r)}
                                    className="text-xs font-semibold px-3 h-8 rounded-lg bg-primary text-white hover:opacity-90"
                                >
                                    Relatório
                                </button>
                                <button
                                    type="button"
                                    onClick={() => cycle(r)}
                                    className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5"
                                >
                                    {r.status} ›
                                </button>
                            </div>
                        </div>
                        <p className="text-sm leading-relaxed mb-2 line-clamp-2">{r.problema}</p>
                        {r.recomendacoes?.length > 0 && (
                            <ul className="list-disc list-inside text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                {r.recomendacoes.slice(0, 2).map((rec, i) => (
                                    <li key={i}>{rec}</li>
                                ))}
                            </ul>
                        )}
                    </div>
                ))}
            </div>
        </div>
    );
}
