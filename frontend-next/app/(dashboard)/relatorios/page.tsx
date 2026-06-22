"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import {
    listWeeklyReports,
    getWeeklyReport,
    type WeeklyReport,
    type WeeklyReportListItem,
} from "@/lib/api";

function fmtNum(v: number | undefined, digits = 1): string {
    if (v === undefined || v === null || Number.isNaN(v)) return "—";
    return v.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

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

function Box({ icon, label, value, hint }: { icon: string; label: string; value: string; hint?: string }) {
    return (
        <div className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-5 flex flex-col gap-2">
            <div className="flex items-center gap-2 text-text-secondary-light dark:text-text-secondary-dark">
                <span className="material-symbols-outlined text-[20px] text-primary">{icon}</span>
                <span className="text-sm font-semibold">{label}</span>
            </div>
            <div className="text-3xl font-extrabold tracking-tight">{value}</div>
            {hint && <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark">{hint}</div>}
        </div>
    );
}

function RelatoriosInner() {
    const router = useRouter();
    const params = useSearchParams();
    const wkParam = params.get("wk") || undefined;

    const [weeks, setWeeks] = useState<WeeklyReportListItem[]>([]);
    const [selected, setSelected] = useState<string | undefined>(wkParam);
    const [report, setReport] = useState<WeeklyReport | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

    useEffect(() => {
        (async () => {
            try {
                const list = await listWeeklyReports();
                setWeeks(list);
                setSelected((cur) => cur || list[0]?.week_key);
                if (list.length === 0) setLoading(false);
            } catch (e) {
                setError(e instanceof Error ? e.message : "Erro ao carregar relatórios");
                setLoading(false);
            }
        })();
    }, []);

    useEffect(() => {
        if (!selected) return;
        setLoading(true);
        setError("");
        getWeeklyReport(selected)
            .then((r) => setReport(r))
            .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar a semana"))
            .finally(() => setLoading(false));
    }, [selected]);

    const idx = useMemo(() => weeks.findIndex((w) => w.week_key === selected), [weeks, selected]);
    const go = useCallback(
        (delta: number) => {
            const next = weeks[idx + delta];
            if (next) {
                setSelected(next.week_key);
                router.replace(`/relatorios?wk=${encodeURIComponent(next.week_key)}`);
            }
        },
        [weeks, idx, router]
    );

    const m = report?.metrics || {};

    return (
        <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-6">
            {/* Header + navegador de semanas */}
            <div className="flex items-center justify-between gap-4 flex-wrap">
                <div>
                    <h1 className="text-2xl font-extrabold tracking-tight">Relatório semanal</h1>
                    <p className="text-text-secondary-light dark:text-text-secondary-dark text-sm">
                        Atendimento da semana — dados para decisões.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => go(1)}
                        disabled={idx < 0 || idx >= weeks.length - 1}
                        className="h-10 w-10 rounded-xl border border-border-light dark:border-border-dark flex items-center justify-center disabled:opacity-40 hover:bg-black/5 dark:hover:bg-white/5"
                        title="Semana anterior"
                    >
                        <span className="material-symbols-outlined text-[20px]">chevron_left</span>
                    </button>
                    <div className="px-4 h-10 rounded-xl border border-border-light dark:border-border-dark flex items-center text-sm font-semibold min-w-[140px] justify-center">
                        {report ? `${report.week_key} · ${fmtRange(report.week_start, report.week_end)}` : selected || "—"}
                    </div>
                    <button
                        onClick={() => go(-1)}
                        disabled={idx <= 0}
                        className="h-10 w-10 rounded-xl border border-border-light dark:border-border-dark flex items-center justify-center disabled:opacity-40 hover:bg-black/5 dark:hover:bg-white/5"
                        title="Próxima semana"
                    >
                        <span className="material-symbols-outlined text-[20px]">chevron_right</span>
                    </button>
                </div>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-xl border border-red-200 dark:border-red-800">
                    {error}
                </div>
            )}

            {!error && weeks.length === 0 && !loading && (
                <div className="rounded-2xl border border-border-light dark:border-border-dark p-8 text-center text-text-secondary-light dark:text-text-secondary-dark">
                    Nenhum relatório disponível ainda. O primeiro é gerado na segunda-feira.
                </div>
            )}

            {loading && (
                <div className="text-text-secondary-light dark:text-text-secondary-dark text-sm">Carregando…</div>
            )}

            {report && !loading && (
                <>
                    {/* Boxes */}
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                        <Box icon="forum" label="Conversas" value={fmtNum(m.total_conversas, 0)} />
                        <Box icon="bolt" label="Resp. IA (méd.)" value={`${fmtNum(m.tempo_resp_ia_seg, 1)} s`} />
                        <Box icon="support_agent" label="Resp. humano (méd.)" value={`${fmtNum(m.tempo_resp_humano_min, 1)} min`} />
                        <Box icon="schedule" label="Horas economizadas" value={`${fmtNum(m.horas_economizadas, 1)} h`} />
                        <Box icon="smart_toy" label="Nota média IA" value={`${fmtNum(m.nota_media_ia, 1)} / 5`} />
                        <Box icon="person" label="Nota média humano" value={`${fmtNum(m.nota_media_humano, 1)} / 5`} />
                    </div>

                    {/* Problema + Solução */}
                    <div className="grid md:grid-cols-2 gap-4">
                        <div className="rounded-2xl border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-5">
                            <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400 mb-2">
                                <span className="material-symbols-outlined text-[20px]">warning</span>
                                <span className="font-bold">Problema principal</span>
                            </div>
                            <p className="text-sm leading-relaxed">{report.problema_principal}</p>
                        </div>
                        <div className="rounded-2xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50 dark:bg-emerald-900/10 p-5">
                            <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 mb-2">
                                <span className="material-symbols-outlined text-[20px]">lightbulb</span>
                                <span className="font-bold">Solução recomendada</span>
                            </div>
                            <p className="text-sm leading-relaxed">{report.solucao_recomendada}</p>
                        </div>
                    </div>

                    {/* Ações */}
                    {report.acoes?.length > 0 && (
                        <div className="rounded-2xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark p-5">
                            <div className="font-bold mb-3 flex items-center gap-2">
                                <span className="material-symbols-outlined text-[20px] text-primary">checklist</span>
                                Ação da semana
                            </div>
                            <ul className="flex flex-col gap-3">
                                {report.acoes.map((a, i) => (
                                    <li key={i} className="flex gap-3">
                                        <span className="material-symbols-outlined text-primary text-[20px] mt-0.5">arrow_right</span>
                                        <div>
                                            <div className="font-semibold text-sm">{a.acao}</div>
                                            {a.contexto && (
                                                <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark mt-0.5">
                                                    {a.contexto}
                                                </div>
                                            )}
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Ver detalhes */}
                    <div>
                        <Link
                            href={`/relatorios/${encodeURIComponent(report.week_key)}/conversas`}
                            className="inline-flex items-center gap-2 h-11 px-5 rounded-xl bg-primary hover:bg-primary-hover text-white font-bold shadow-lg shadow-primary/30"
                        >
                            <span className="material-symbols-outlined text-[20px]">table_rows</span>
                            Ver detalhes das conversas
                        </Link>
                    </div>
                </>
            )}
        </div>
    );
}

export default function RelatoriosPage() {
    return (
        <Suspense fallback={<div className="p-8 text-sm text-text-secondary-light">Carregando…</div>}>
            <RelatoriosInner />
        </Suspense>
    );
}
