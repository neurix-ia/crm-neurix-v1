"use client";

import { useEffect, useState } from "react";

import {
    getHqN8nExecutionError,
    type N8nExecutionErrorDetail,
    type N8nWorkflowErrorRow,
} from "@/lib/api";

type Props = {
    row: N8nWorkflowErrorRow;
    onClose: () => void;
};

export default function N8nExecutionErrorModal({ row, onClose }: Props) {
    const [detail, setDetail] = useState<N8nExecutionErrorDetail | null>(null);
    const [loading, setLoading] = useState(true);
    const [err, setErr] = useState<string | null>(null);

    useEffect(() => {
        const token = localStorage.getItem("access_token");
        if (!token || !row.last_execution_id) {
            setLoading(false);
            if (!row.last_execution_id) {
                setErr("Nenhuma execução com erro encontrada para este workflow no período.");
            }
            return;
        }
        let cancelled = false;
        (async () => {
            try {
                const data = await getHqN8nExecutionError(
                    row.instance_id,
                    row.last_execution_id,
                    row.workflow_id ?? undefined,
                    token
                );
                if (!cancelled) setDetail(data);
            } catch (e) {
                if (!cancelled) {
                    setErr(e instanceof Error ? e.message : "Erro ao carregar detalhe.");
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [row]);

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <button
                type="button"
                className="absolute inset-0 bg-black/40"
                aria-label="Fechar"
                onClick={onClose}
            />
            <div className="relative z-10 w-full max-w-2xl max-h-[90vh] overflow-y-auto glass-effect rounded-2xl border border-border-light dark:border-border-dark shadow-2xl p-6">
                <div className="flex items-start justify-between gap-4 mb-4">
                    <div>
                        <h3 className="text-lg font-bold font-display">Causa do erro</h3>
                        <p className="text-sm text-text-secondary-light mt-1">{row.workflow_name}</p>
                        <p className="text-xs text-text-secondary-light">
                            {row.instance_label}
                            {row.last_failed_at &&
                                ` · ${new Date(row.last_failed_at).toLocaleString("pt-BR")}`}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="p-1 rounded-lg hover:bg-black/5 dark:hover:bg-white/5"
                    >
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>

                {loading && <p className="text-sm text-text-secondary-light">Carregando…</p>}
                {err && (
                    <div className="rounded-xl border border-red-300 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 px-4 py-3 text-sm">
                        {err}
                    </div>
                )}

                {detail && (
                    <div className="space-y-4 text-sm">
                        {detail.node_name && (
                            <div>
                                <p className="text-xs font-semibold uppercase text-text-secondary-light">Nó</p>
                                <p className="font-mono text-sm mt-0.5">{detail.node_name}</p>
                            </div>
                        )}
                        <div>
                            <p className="text-xs font-semibold uppercase text-text-secondary-light">Mensagem</p>
                            <p className="mt-1 text-red-700 dark:text-red-300 whitespace-pre-wrap">{detail.message}</p>
                        </div>
                        {detail.description && (
                            <div>
                                <p className="text-xs font-semibold uppercase text-text-secondary-light">Descrição</p>
                                <p className="mt-1 whitespace-pre-wrap">{detail.description}</p>
                            </div>
                        )}
                        {detail.stack && (
                            <details className="rounded-xl border border-border-light dark:border-border-dark">
                                <summary className="cursor-pointer px-3 py-2 text-xs font-semibold uppercase text-text-secondary-light">
                                    Stack trace
                                </summary>
                                <pre className="p-3 text-xs overflow-x-auto whitespace-pre-wrap font-mono bg-black/5 dark:bg-white/5">
                                    {detail.stack}
                                </pre>
                            </details>
                        )}
                        <div className="flex flex-wrap gap-2 pt-2">
                            {detail.n8n_execution_url && (
                                <a
                                    href={detail.n8n_execution_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-primary text-sm font-medium hover:underline"
                                >
                                    Abrir no n8n
                                    <span className="material-symbols-outlined text-base">open_in_new</span>
                                </a>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}
