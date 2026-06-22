"use client";

import { Fragment, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { getWeeklyConversations } from "@/lib/api";

type Row = Record<string, unknown>;

const COLS: Array<{ key: string; label: string; w?: string }> = [
    { key: "data", label: "Data", w: "w-24" },
    { key: "nome", label: "Contato" },
    { key: "topico_principal", label: "Tópico" },
    { key: "intencao", label: "Intenção" },
    { key: "sentimento", label: "Sentimento" },
    { key: "resultado", label: "Resultado" },
    { key: "profissionalismo_agente", label: "Nota IA" },
    { key: "profissionalismo_humano", label: "Nota humano" },
    { key: "resumo", label: "Resumo" },
];

function sentimentClass(v: string): string {
    const s = (v || "").toLowerCase();
    if (s.includes("positiv")) return "text-emerald-600 dark:text-emerald-400";
    if (s.includes("negativ")) return "text-red-600 dark:text-red-400";
    return "text-text-secondary-light dark:text-text-secondary-dark";
}

type Msg = { ts: string; role: string; text: string };

function parseTranscript(t: string): Msg[] {
    if (!t) return [];
    const re = /\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(Lead|Agente|Humano)\s*:\s*/g;
    const out: Msg[] = [];
    let m: RegExpExecArray | null;
    let lastIndex = 0;
    let prev: { ts: string; role: string } | null = null;
    while ((m = re.exec(t)) !== null) {
        if (prev) out.push({ ...prev, text: t.slice(lastIndex, m.index).trim() });
        prev = { ts: m[1], role: m[2] };
        lastIndex = re.lastIndex;
    }
    if (prev) out.push({ ...prev, text: t.slice(lastIndex).trim() });
    return out;
}

function hora(ts: string): string {
    const m = ts.match(/\d{2}:\d{2}:\d{2}$/);
    return m ? m[0].slice(0, 5) : "";
}

function Bubble({ msg }: { msg: Msg }) {
    const isLead = msg.role === "Lead";
    const align = isLead ? "items-start" : "items-end";
    const bubble = isLead
        ? "bg-black/5 dark:bg-white/5"
        : msg.role === "Humano"
        ? "bg-emerald-50 dark:bg-emerald-900/20"
        : "bg-primary/10";
    const label =
        msg.role === "Humano"
            ? "text-emerald-700 dark:text-emerald-400"
            : msg.role === "Agente"
            ? "text-primary"
            : "text-text-secondary-light dark:text-text-secondary-dark";
    return (
        <div className={`flex flex-col gap-0.5 ${align}`}>
            <div className="flex items-center gap-2 text-[11px]">
                <span className={`font-semibold ${label}`}>{msg.role}</span>
                <span className="text-text-tertiary-light dark:text-text-tertiary-dark">{hora(msg.ts)}</span>
            </div>
            <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${bubble}`}>
                {msg.text}
            </div>
        </div>
    );
}

export default function ConversasPage() {
    const params = useParams();
    const weekKey = decodeURIComponent(String(params.week_key || ""));
    const [rows, setRows] = useState<Row[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [open, setOpen] = useState<number | null>(null);

    useEffect(() => {
        if (!weekKey) return;
        getWeeklyConversations(weekKey)
            .then((d) => setRows(d.conversations || []))
            .catch((e) => setError(e instanceof Error ? e.message : "Erro ao carregar conversas"))
            .finally(() => setLoading(false));
    }, [weekKey]);

    return (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 flex flex-col gap-5">
            <div className="flex items-center gap-3">
                <Link
                    href={`/relatorios?wk=${encodeURIComponent(weekKey)}`}
                    className="h-10 w-10 rounded-xl border border-border-light dark:border-border-dark flex items-center justify-center hover:bg-black/5 dark:hover:bg-white/5"
                    title="Voltar ao relatório"
                >
                    <span className="material-symbols-outlined text-[20px]">arrow_back</span>
                </Link>
                <div>
                    <h1 className="text-2xl font-extrabold tracking-tight">Conversas da semana</h1>
                    <p className="text-text-secondary-light dark:text-text-secondary-dark text-sm">
                        {weekKey} · somente leitura · {rows.length} conversa{rows.length === 1 ? "" : "s"}
                    </p>
                </div>
            </div>

            {error && (
                <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-xl border border-red-200 dark:border-red-800">
                    {error}
                </div>
            )}
            {loading && <div className="text-sm text-text-secondary-light dark:text-text-secondary-dark">Carregando…</div>}

            {!loading && !error && rows.length === 0 && (
                <div className="rounded-2xl border border-border-light dark:border-border-dark p-8 text-center text-text-secondary-light dark:text-text-secondary-dark">
                    Nenhuma conversa registrada nesta semana.
                </div>
            )}

            {!loading && rows.length > 0 && (
                <div className="overflow-x-auto rounded-2xl border border-border-light dark:border-border-dark">
                    <table className="min-w-full text-sm">
                        <thead className="bg-black/5 dark:bg-white/5">
                            <tr>
                                <th className="w-10 px-2 py-2.5"></th>
                                {COLS.map((c) => (
                                    <th key={c.key} className={`text-left font-semibold px-3 py-2.5 whitespace-nowrap ${c.w || ""}`}>
                                        {c.label}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((r, i) => {
                                const transcript = parseTranscript(String(r["transcrição"] ?? ""));
                                const isOpen = open === i;
                                return (
                                    <Fragment key={i}>
                                        <tr
                                            className="border-t border-border-light dark:border-border-dark align-top cursor-pointer hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
                                            onClick={() => setOpen(isOpen ? null : i)}
                                        >
                                            <td className="px-2 py-2.5 text-center">
                                                <span className="material-symbols-outlined text-[20px] text-text-secondary-light dark:text-text-secondary-dark">
                                                    {isOpen ? "expand_less" : "expand_more"}
                                                </span>
                                            </td>
                                            {COLS.map((c) => {
                                                const val = r[c.key];
                                                const text = val === undefined || val === null ? "" : String(val);
                                                const cls = c.key === "sentimento" ? sentimentClass(text) : "";
                                                const isWide = c.key === "resumo";
                                                return (
                                                    <td
                                                        key={c.key}
                                                        className={`px-3 py-2.5 ${cls} ${isWide ? "min-w-[280px] max-w-[420px]" : "whitespace-nowrap"}`}
                                                    >
                                                        {text}
                                                    </td>
                                                );
                                            })}
                                        </tr>
                                        {isOpen && (
                                            <tr className="bg-black/[0.02] dark:bg-white/[0.03]">
                                                <td colSpan={COLS.length + 1} className="px-4 py-4">
                                                    <div className="text-xs font-semibold text-text-secondary-light dark:text-text-secondary-dark mb-3 flex items-center gap-2">
                                                        <span className="material-symbols-outlined text-[18px]">forum</span>
                                                        Transcrição da conversa
                                                    </div>
                                                    {transcript.length > 0 ? (
                                                        <div className="flex flex-col gap-3 max-w-3xl">
                                                            {transcript.map((m, j) => (
                                                                <Bubble key={j} msg={m} />
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <div className="text-sm whitespace-pre-wrap text-text-secondary-light dark:text-text-secondary-dark">
                                                            {String(r["transcrição"] ?? "—")}
                                                        </div>
                                                    )}
                                                </td>
                                            </tr>
                                        )}
                                    </Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
