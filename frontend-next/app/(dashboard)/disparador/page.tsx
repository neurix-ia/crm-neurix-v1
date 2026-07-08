"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    apiFetch,
    createDispatchCampaign,
    getDispatchCampaign,
    listDispatchMembers,
    type DispatchCampaignDetail,
    type DispatchMember,
} from "@/lib/api";

export default function DisparadorPage() {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const fileRef = useRef<HTMLInputElement>(null);

    const [members, setMembers] = useState<DispatchMember[]>([]);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [message, setMessage] = useState("");
    const [loading, setLoading] = useState(true);
    const [importing, setImporting] = useState(false);
    const [dispatching, setDispatching] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [importInfo, setImportInfo] = useState<string | null>(null);
    const [campaign, setCampaign] = useState<DispatchCampaignDetail | null>(null);
    const [minDelay, setMinDelay] = useState(3);
    const [maxDelay, setMaxDelay] = useState(5);

    const loadMembers = useCallback(async () => {
        if (!token) return;
        setLoading(true);
        setError(null);
        try {
            const data = await listDispatchMembers(token);
            setMembers(data);
            setSelected(new Set(data.map((m) => m.id)));
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao carregar membros.");
            setMembers([]);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        void loadMembers();
    }, [loadMembers]);

    const allSelected = members.length > 0 && selected.size === members.length;

    const toggleAll = () => {
        if (allSelected) {
            setSelected(new Set());
        } else {
            setSelected(new Set(members.map((m) => m.id)));
        }
    };

    const toggleOne = (id: string) => {
        setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const handleImport = async (file: File | null) => {
        if (!file || !token) return;
        setImporting(true);
        setError(null);
        setImportInfo(null);
        try {
            const form = new FormData();
            form.append("file", file);
            const res = await apiFetch("/api/dispatch/members/import", {
                method: "POST",
                token,
                body: form,
            });
            if (!res.ok) {
                const raw = await res.text();
                throw new Error(raw || "Falha no import.");
            }
            const data = (await res.json()) as {
                imported: number;
                invalid: { line: number; reason: string }[];
            };
            setImportInfo(
                `Importados: ${data.imported}. Inválidos: ${data.invalid?.length ?? 0}.`
            );
            await loadMembers();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro no import CSV.");
        } finally {
            setImporting(false);
            if (fileRef.current) fileRef.current.value = "";
        }
    };

    const pollCampaign = useCallback(
        async (campaignId: string) => {
            if (!token) return;
            const detail = await getDispatchCampaign(campaignId, token);
            setCampaign(detail);
            if (detail.status === "running") {
                setTimeout(() => void pollCampaign(campaignId), 2000);
            }
        },
        [token]
    );

    const handleDispatch = async () => {
        if (!token) return;
        if (!message.trim()) {
            setError("Informe a mensagem.");
            return;
        }
        if (selected.size === 0) {
            setError("Selecione ao menos um membro.");
            return;
        }
        setDispatching(true);
        setError(null);
        try {
            const created = await createDispatchCampaign(
                {
                    message: message.trim(),
                    member_ids: Array.from(selected),
                    min_delay: minDelay,
                    max_delay: maxDelay,
                },
                token
            );
            await pollCampaign(created.id);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao disparar.");
        } finally {
            setDispatching(false);
        }
    };

    const progress = useMemo(() => {
        if (!campaign) return 0;
        if (!campaign.total) return 0;
        return Math.round(((campaign.sent + campaign.failed) / campaign.total) * 100);
    }, [campaign]);

    return (
        <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
            <div>
                <h1 className="text-2xl font-bold text-text-main-light dark:text-text-main-dark">
                    Disparador WhatsApp
                </h1>
                <p className="mt-1 text-sm text-text-secondary-light dark:text-text-secondary-dark">
                    Importe membros via CSV, selecione destinatários e dispare mensagens com intervalo
                    aleatório.
                </p>
            </div>

            {error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                    {error}
                </div>
            )}
            {importInfo && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                    {importInfo}
                </div>
            )}

            <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark">
                <h2 className="mb-3 font-semibold">Mensagem</h2>
                <textarea
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    rows={4}
                    placeholder="Olá {{nome}}, temos novidades para você!"
                    className="w-full rounded-lg border border-border-light bg-white px-3 py-2 text-sm dark:border-border-dark dark:bg-slate-900"
                />
                <p className="mt-2 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                    Use {"{{nome}}"} para personalizar com o nome do membro.
                </p>
                <div className="mt-4 flex flex-wrap gap-4">
                    <label className="text-sm">
                        Delay mín (s)
                        <input
                            type="number"
                            min={1}
                            max={300}
                            value={minDelay}
                            onChange={(e) => setMinDelay(Number(e.target.value))}
                            className="ml-2 w-20 rounded border border-border-light px-2 py-1 dark:border-border-dark dark:bg-slate-900"
                        />
                    </label>
                    <label className="text-sm">
                        Delay máx (s)
                        <input
                            type="number"
                            min={1}
                            max={600}
                            value={maxDelay}
                            onChange={(e) => setMaxDelay(Number(e.target.value))}
                            className="ml-2 w-20 rounded border border-border-light px-2 py-1 dark:border-border-dark dark:bg-slate-900"
                        />
                    </label>
                </div>
            </section>

            <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <h2 className="font-semibold">Membros</h2>
                    <div className="flex gap-2">
                        <input
                            ref={fileRef}
                            type="file"
                            accept=".csv,text/csv"
                            className="hidden"
                            onChange={(e) => void handleImport(e.target.files?.[0] ?? null)}
                        />
                        <button
                            type="button"
                            onClick={() => fileRef.current?.click()}
                            disabled={importing}
                            className="rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-slate-50 dark:border-border-dark dark:hover:bg-slate-800"
                        >
                            {importing ? "Importando..." : "Importar CSV"}
                        </button>
                        <button
                            type="button"
                            onClick={() => void handleDispatch()}
                            disabled={dispatching || loading || members.length === 0}
                            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                        >
                            {dispatching ? "Disparando..." : "Disparar"}
                        </button>
                    </div>
                </div>

                <p className="mb-3 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                    CSV: colunas <code>nome,telefone</code>
                </p>

                {loading ? (
                    <p className="text-sm text-text-secondary-light">Carregando...</p>
                ) : members.length === 0 ? (
                    <p className="text-sm text-text-secondary-light">Nenhum membro. Importe um CSV.</p>
                ) : (
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-border-light text-left dark:border-border-dark">
                                    <th className="py-2 pr-3">
                                        <input
                                            type="checkbox"
                                            checked={allSelected}
                                            onChange={toggleAll}
                                            aria-label="Selecionar todos"
                                        />
                                    </th>
                                    <th className="py-2">Nome</th>
                                    <th className="py-2">Telefone</th>
                                </tr>
                            </thead>
                            <tbody>
                                {members.map((m) => (
                                    <tr
                                        key={m.id}
                                        className="border-b border-border-light/60 dark:border-border-dark/60"
                                    >
                                        <td className="py-2 pr-3">
                                            <input
                                                type="checkbox"
                                                checked={selected.has(m.id)}
                                                onChange={() => toggleOne(m.id)}
                                                aria-label={`Selecionar ${m.name}`}
                                            />
                                        </td>
                                        <td className="py-2">{m.name}</td>
                                        <td className="py-2 font-mono text-xs">{m.phone_e164}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>

            {campaign && (
                <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark">
                    <h2 className="mb-3 font-semibold">Progresso da campanha</h2>
                    <div className="mb-2 flex justify-between text-sm">
                        <span>Status: {campaign.status}</span>
                        <span>
                            {campaign.sent + campaign.failed}/{campaign.total}
                        </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                        <div
                            className="h-full bg-primary transition-all"
                            style={{ width: `${progress}%` }}
                        />
                    </div>
                    <ul className="mt-4 max-h-48 space-y-1 overflow-y-auto text-xs">
                        {campaign.targets.map((t) => (
                            <li key={t.id} className="flex justify-between gap-2">
                                <span>{t.name}</span>
                                <span
                                    className={
                                        t.status === "sent"
                                            ? "text-emerald-600"
                                            : t.status === "failed"
                                              ? "text-red-600"
                                              : "text-slate-500"
                                    }
                                >
                                    {t.status}
                                </span>
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </div>
    );
}
