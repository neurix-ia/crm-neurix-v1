"use client";

import { useEffect, useState } from "react";
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

export default function ConversasPage() {
    const params = useParams();
    const weekKey = decodeURIComponent(String(params.week_key || ""));
    const [rows, setRows] = useState<Row[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");

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
                                {COLS.map((c) => (
                                    <th key={c.key} className={`text-left font-semibold px-3 py-2.5 whitespace-nowrap ${c.w || ""}`}>
                                        {c.label}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {rows.map((r, i) => (
                                <tr key={i} className="border-t border-border-light dark:border-border-dark align-top">
                                    {COLS.map((c) => {
                                        const val = r[c.key];
                                        const text = val === undefined || val === null ? "" : String(val);
                                        const cls =
                                            c.key === "sentimento" ? sentimentClass(text) : "";
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
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
