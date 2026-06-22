"use client";

import { useEffect, useState } from "react";

import { listAgentReports, patchAgentReport, type AgentImprovementReport } from "@/lib/api";

const SEV_CLS: Record<string, string> = {
    alta: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    media: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
    baixa: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
};
const NEXT_STATUS: Record<string, string> = { aberto: "revisado", revisado: "aplicado", aplicado: "aberto" };

export default function AgentesSaudePage() {
    const [rows, setRows] = useState<AgentImprovementReport[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [sev, setSev] = useState("");
    const [status, setStatus] = useState("");

    const load = () => {
        setLoading(true);
        listAgentReports({ severidade: sev || undefined, status: status || undefined })
            .then(setRows)
            .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar"))
            .finally(() => setLoading(false));
    };
    useEffect(load, [sev, status]);

    const cycle = async (r: AgentImprovementReport) => {
        const next = NEXT_STATUS[r.status] || "aberto";
        try {
            await patchAgentReport(r.id, next);
            setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, status: next } : x)));
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao atualizar status");
        }
    };

    return (
        <div className="flex flex-col gap-5">
            <div>
                <h1 className="text-2xl font-extrabold tracking-tight">Saúde dos agentes</h1>
                <p className="text-text-secondary-light dark:text-text-secondary-dark text-sm">
                    Relatórios semanais de melhoria — internos, não enviados ao cliente.
                </p>
            </div>

            <div className="flex gap-3 flex-wrap">
                <select value={sev} onChange={(e) => setSev(e.target.value)} className="h-10 px-3 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-sm">
                    <option value="">Toda severidade</option>
                    <option value="alta">Alta</option>
                    <option value="media">Média</option>
                    <option value="baixa">Baixa</option>
                </select>
                <select value={status} onChange={(e) => setStatus(e.target.value)} className="h-10 px-3 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark text-sm">
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
            {loading && <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Carregando…</div>}
            {!loading && rows.length === 0 && !error && (
                <div className="rounded-2xl border border-border-light dark:border-border-dark p-8 text-center text-text-secondary-light dark:text-text-secondary-dark">
                    Nenhum relatório de agente.
                </div>
            )}

            <div className="flex flex-col gap-3">
                {rows.map((r) => (
                    <div key={r.id} className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-5">
                        <div className="flex items-center justify-between gap-3 flex-wrap mb-2">
                            <div className="flex items-center gap-2">
                                <span className="font-bold">{r.agent_name}</span>
                                <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">{r.week_key}</span>
                                <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${SEV_CLS[r.severidade] || ""}`}>{r.severidade}</span>
                            </div>
                            <button onClick={() => cycle(r)} className="text-xs font-semibold px-3 h-8 rounded-lg border border-border-light dark:border-border-dark hover:bg-black/5 dark:hover:bg-white/5">
                                {r.status} ›
                            </button>
                        </div>
                        <p className="text-sm leading-relaxed mb-2">{r.problema}</p>
                        {r.recomendacoes?.length > 0 && (
                            <ul className="list-disc list-inside text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                {r.recomendacoes.map((rec, i) => (
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
