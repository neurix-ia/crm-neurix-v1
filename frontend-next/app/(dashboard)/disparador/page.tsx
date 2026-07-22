"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    apiFetch,
    connectWhatsappInstance,
    cancelDispatchCampaign,
    createDispatchCampaign,
    deleteDispatchMember,
    deleteDispatchMembers,
    disconnectWhatsappInstance,
    ensureDispatchWhatsappInstance,
    getDispatchCampaign,
    getWhatsappStatus,
    listDispatchCampaigns,
    listDispatchMembers,
    type DispatchCampaign,
    type DispatchCampaignDetail,
    type DispatchMember,
} from "@/lib/api";

function formatCampaignDate(iso?: string | null) {
    if (!iso) return "—";
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

export default function DisparadorPage() {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const fileRef = useRef<HTMLInputElement>(null);

    const [members, setMembers] = useState<DispatchMember[]>([]);
    const [selected, setSelected] = useState<Set<string>>(new Set());
    const [message, setMessage] = useState("");
    const [loading, setLoading] = useState(true);
    const [importing, setImporting] = useState(false);
    const [dispatching, setDispatching] = useState(false);
    const [cancelling, setCancelling] = useState(false);
    const [deleting, setDeleting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [importInfo, setImportInfo] = useState<string | null>(null);
    const [campaign, setCampaign] = useState<DispatchCampaignDetail | null>(null);
    const [recentCampaigns, setRecentCampaigns] = useState<DispatchCampaign[]>([]);
    const [confirmOpen, setConfirmOpen] = useState(false);
    /** Delay entre envios, em minutos (enviado à API como segundos). */
    const [minDelayMin, setMinDelayMin] = useState(3);
    const [maxDelayMin, setMaxDelayMin] = useState(9);
    const [whatsappStatus, setWhatsappStatus] = useState<string>("—");
    const [whatsappConfigured, setWhatsappConfigured] = useState(false);
    const [pairPhone, setPairPhone] = useState("");
    const [qrCode, setQrCode] = useState<string | null>(null);
    const [pairingCode, setPairingCode] = useState<string | null>(null);
    const [connectingWa, setConnectingWa] = useState(false);
    const [forceExpandWa, setForceExpandWa] = useState(false);

    const loadWhatsappStatus = useCallback(async () => {
        if (!token) return;
        try {
            const res = await getWhatsappStatus(token);
            setWhatsappStatus(res.status);
            const noToken = (res.message || "").toLowerCase().includes("nenhum token");
            setWhatsappConfigured(!noToken);
            if (res.status === "open" || res.status === "connected") {
                setQrCode(null);
                setPairingCode(null);
                setForceExpandWa(false);
            }
        } catch {
            setWhatsappStatus("desconhecido");
            setWhatsappConfigured(false);
        }
    }, [token]);

    const loadCampaigns = useCallback(async (): Promise<DispatchCampaign[]> => {
        if (!token) return [];
        try {
            const list = await listDispatchCampaigns(10, token);
            setRecentCampaigns(list);
            return list;
        } catch {
            setRecentCampaigns([]);
            return [];
        }
    }, [token]);

    const handleConnectWhatsapp = async () => {
        if (!token) return;
        setConnectingWa(true);
        setError(null);
        setQrCode(null);
        setPairingCode(null);
        try {
            const runConnect = async () => {
                await ensureDispatchWhatsappInstance(token);
                const phoneDigits = pairPhone.replace(/\D/g, "");
                return connectWhatsappInstance(
                    token,
                    undefined,
                    phoneDigits ? { phone: phoneDigits } : {}
                );
            };

            let res;
            try {
                res = await runConnect();
            } catch (firstErr) {
                const msg = firstErr instanceof Error ? firstErr.message : String(firstErr);
                // Token órfão limpo no backend — 2º clique automático
                if (/401|inválido|apagada|Unauthorized/i.test(msg)) {
                    res = await runConnect();
                } else {
                    throw firstErr;
                }
            }

            setWhatsappConfigured(true);
            if (res.mode === "already_connected") {
                setWhatsappStatus(res.status || "connected");
                setForceExpandWa(false);
            } else if (res.mode === "pairing" && res.pairingCode) {
                setPairingCode(res.pairingCode);
                setWhatsappStatus(res.status || "connecting");
            } else if (res.mode === "qrcode" && res.qrcode) {
                setQrCode(res.qrcode);
                setWhatsappStatus(res.status || "connecting");
            }
            await loadWhatsappStatus();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao conectar WhatsApp.");
        } finally {
            setConnectingWa(false);
        }
    };

    const handleDisconnectWhatsapp = async () => {
        if (!token) return;
        if (!confirm("Desconectar WhatsApp deste tenant?")) return;
        setConnectingWa(true);
        setError(null);
        try {
            await disconnectWhatsappInstance(token);
            setQrCode(null);
            setPairingCode(null);
            setForceExpandWa(true);
            await loadWhatsappStatus();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao desconectar.");
        } finally {
            setConnectingWa(false);
        }
    };

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

    const pollCampaign = useCallback(
        async (campaignId: string) => {
            if (!token) return;
            const detail = await getDispatchCampaign(campaignId, token);
            setCampaign(detail);
            if (detail.status === "running") {
                setTimeout(() => void pollCampaign(campaignId), 2000);
            } else {
                void loadCampaigns();
            }
        },
        [token, loadCampaigns]
    );

    const handleCancelCampaign = async () => {
        if (!token || !campaign || campaign.status !== "running") return;
        if (!window.confirm("Cancelar o envio desta campanha?")) return;
        setCancelling(true);
        setError(null);
        try {
            const res = await cancelDispatchCampaign(campaign.id, token);
            setCampaign({ ...campaign, ...res, targets: campaign.targets });
            await loadCampaigns();
            if (res.n8n_error) {
                setError(
                    res.n8n_deleted
                        ? null
                        : `Campanha cancelada. Aviso n8n: ${res.n8n_error}`
                );
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao cancelar campanha.");
        } finally {
            setCancelling(false);
        }
    };

    useEffect(() => {
        void loadMembers();
        void loadWhatsappStatus();
        void (async () => {
            const list = await loadCampaigns();
            const running = list.find((c) => c.status === "running");
            if (running) {
                void pollCampaign(running.id);
            }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [loadMembers, loadWhatsappStatus, loadCampaigns]);

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

    const previewName = useMemo(() => {
        const firstSelected = members.find((m) => selected.has(m.id));
        return firstSelected?.name || members[0]?.name || "nome";
    }, [members, selected]);

    const messagePreview = useMemo(() => {
        const raw = message.trim() || "Olá {{nome}}, temos novidades para você!";
        return raw.replace(/\{\{\s*nome\s*\}\}/gi, previewName);
    }, [message, previewName]);

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

    const handleClearList = async () => {
        if (!token || members.length === 0) return;
        if (!confirm(`Excluir toda a lista (${members.length} membros)? Esta ação não pode ser desfeita.`)) {
            return;
        }
        setDeleting(true);
        setError(null);
        try {
            await deleteDispatchMembers({ all: true }, token);
            setImportInfo("Lista excluída.");
            await loadMembers();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao excluir lista.");
        } finally {
            setDeleting(false);
        }
    };

    const handleDeleteSelected = async () => {
        if (!token || selected.size === 0) return;
        if (selected.size === members.length) {
            await handleClearList();
            return;
        }
        if (!confirm(`Excluir ${selected.size} membro(s) selecionado(s)?`)) return;
        setDeleting(true);
        setError(null);
        try {
            await deleteDispatchMembers({ member_ids: Array.from(selected) }, token);
            setImportInfo(`${selected.size} membro(s) excluído(s).`);
            await loadMembers();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao excluir selecionados.");
        } finally {
            setDeleting(false);
        }
    };

    const handleDeleteOne = async (m: DispatchMember) => {
        if (!token) return;
        if (!confirm(`Excluir ${m.name}?`)) return;
        setDeleting(true);
        setError(null);
        try {
            await deleteDispatchMember(m.id, token);
            await loadMembers();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao excluir membro.");
        } finally {
            setDeleting(false);
        }
    };

    const openConfirmDispatch = () => {
        setError(null);
        if (!message.trim()) {
            setError("Informe a mensagem.");
            return;
        }
        if (selected.size === 0) {
            setError("Selecione ao menos um membro.");
            return;
        }
        if (minDelayMin < 1 || maxDelayMin < 1 || minDelayMin > maxDelayMin) {
            setError("Delay inválido: mínimo e máximo devem ser em minutos, com mín ≤ máx.");
            return;
        }
        setConfirmOpen(true);
    };

    const handleDispatch = async () => {
        if (!token) return;
        setConfirmOpen(false);
        setDispatching(true);
        setError(null);
        try {
            const created = await createDispatchCampaign(
                {
                    message: message.trim(),
                    member_ids: Array.from(selected),
                    min_delay: Math.round(minDelayMin * 60),
                    max_delay: Math.round(maxDelayMin * 60),
                },
                token
            );
            await loadCampaigns();
            await pollCampaign(created.id);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao disparar.");
        } finally {
            setDispatching(false);
        }
    };

    const openCampaignDetail = async (c: DispatchCampaign) => {
        if (!token) return;
        setError(null);
        try {
            if (c.status === "running") {
                await pollCampaign(c.id);
            } else {
                const detail = await getDispatchCampaign(c.id, token);
                setCampaign(detail);
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao carregar campanha.");
        }
    };

    const whatsappStatusLabel = useMemo(() => {
        if (whatsappStatus === "open" || whatsappStatus === "connected") return "Conectado";
        if (whatsappStatus === "connecting") return "Conectando…";
        if (whatsappStatus === "disconnected") return "Desconectado";
        if (whatsappStatus === "hibernated") return "Hibernado";
        return whatsappStatus;
    }, [whatsappStatus]);

    const isWhatsappConnected =
        whatsappStatus === "open" || whatsappStatus === "connected";
    const showWhatsappCompact = isWhatsappConnected && !forceExpandWa;

    const progress = useMemo(() => {
        if (!campaign) return 0;
        if (!campaign.total) return 0;
        return Math.round(((campaign.sent + campaign.failed) / campaign.total) * 100);
    }, [campaign]);

    const messageSnippet = message.trim().length > 120 ? `${message.trim().slice(0, 120)}…` : message.trim();

    return (
        <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-8">
            <div>
                <h1 className="text-2xl font-bold text-text-main-light dark:text-text-main-dark">
                    Comunicados
                </h1>
                <p className="mt-1 text-sm text-text-secondary-light dark:text-text-secondary-dark">
                    Importe membros via CSV, selecione destinatários e dispare mensagens WhatsApp com
                    intervalo aleatório.
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
                {showWhatsappCompact ? (
                    <div className="flex flex-wrap items-center justify-between gap-3">
                        <div className="flex items-center gap-3">
                            <span className="material-symbols-outlined text-primary text-2xl">smartphone</span>
                            <div>
                                <h2 className="font-semibold">WhatsApp</h2>
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    Pronto para disparos
                                </p>
                            </div>
                            <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                                {whatsappStatusLabel}
                            </span>
                        </div>
                        <div className="flex flex-wrap gap-2">
                            <button
                                type="button"
                                onClick={() => void loadWhatsappStatus()}
                                className="rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-slate-50 dark:border-border-dark dark:hover:bg-slate-800"
                            >
                                Atualizar status
                            </button>
                            <button
                                type="button"
                                onClick={() => {
                                    setForceExpandWa(true);
                                    setQrCode(null);
                                    setPairingCode(null);
                                }}
                                className="rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-slate-50 dark:border-border-dark dark:hover:bg-slate-800"
                            >
                                Reconectar
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleDisconnectWhatsapp()}
                                disabled={connectingWa}
                                className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40 disabled:opacity-50"
                            >
                                Desconectar
                            </button>
                        </div>
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <div>
                                <h2 className="font-semibold">Conectar WhatsApp</h2>
                                <p className="mt-0.5 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    QR Code ou código de pareamento (com telefone). A instância é criada
                                    automaticamente se ainda não existir.
                                </p>
                            </div>
                            <span
                                className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                                    isWhatsappConnected
                                        ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                                        : whatsappConfigured
                                          ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                                          : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                                }`}
                            >
                                {whatsappConfigured ? whatsappStatusLabel : "Não configurado"}
                            </span>
                        </div>

                        <label className="block text-sm">
                            Telefone (código de pareamento)
                            <input
                                type="tel"
                                value={pairPhone}
                                onChange={(e) => setPairPhone(e.target.value)}
                                placeholder="5511999999999"
                                className="mt-1 w-full rounded-lg border border-border-light bg-white px-3 py-2 text-sm dark:border-border-dark dark:bg-slate-900"
                            />
                            <span className="mt-1 block text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                Formato internacional, só dígitos. Com telefone, gera o código de pareamento;
                                vazio, gera QR Code.
                            </span>
                        </label>

                        <div className="flex flex-wrap gap-2">
                            <button
                                type="button"
                                onClick={() => void handleConnectWhatsapp()}
                                disabled={connectingWa}
                                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                            >
                                <span className="material-symbols-outlined text-lg">
                                    {connectingWa ? "progress_activity" : "qr_code_scanner"}
                                </span>
                                {connectingWa ? "Conectando…" : "Conectar"}
                            </button>
                            <button
                                type="button"
                                onClick={() => void loadWhatsappStatus()}
                                className="rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-slate-50 dark:border-border-dark dark:hover:bg-slate-800"
                            >
                                Atualizar status
                            </button>
                            {isWhatsappConnected && (
                                <button
                                    type="button"
                                    onClick={() => setForceExpandWa(false)}
                                    className="rounded-lg border border-border-light px-3 py-2 text-sm hover:bg-slate-50 dark:border-border-dark dark:hover:bg-slate-800"
                                >
                                    Recolher
                                </button>
                            )}
                        </div>

                        {pairingCode && (
                            <div className="rounded-xl border border-primary/20 bg-primary/5 px-4 py-6 text-center">
                                <p className="text-xs font-semibold uppercase tracking-wide text-text-secondary-light">
                                    Código de pareamento
                                </p>
                                <p className="mt-2 font-mono text-3xl font-bold tracking-widest text-primary">
                                    {pairingCode}
                                </p>
                                <p className="mt-2 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    No WhatsApp: Aparelhos conectados → Conectar com número de telefone
                                </p>
                            </div>
                        )}

                        {qrCode && !pairingCode && (
                            <div className="flex flex-col items-center gap-2">
                                <div className="rounded-xl border-2 border-primary/20 bg-white p-4 shadow-inner">
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                        src={
                                            qrCode.startsWith("data:image")
                                                ? qrCode
                                                : `data:image/png;base64,${qrCode}`
                                        }
                                        alt="QR Code WhatsApp"
                                        className="h-48 w-48 object-contain"
                                    />
                                </div>
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                    Escaneie o QR no WhatsApp. Depois use Atualizar status.
                                </p>
                            </div>
                        )}
                    </div>
                )}
            </section>

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
                <div className="mt-3 rounded-lg border border-border-light/80 bg-slate-50 px-3 py-2 dark:border-border-dark dark:bg-slate-900/50">
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-text-secondary-light dark:text-text-secondary-dark">
                        Preview
                    </p>
                    <p className="mt-1 text-sm text-text-main-light dark:text-text-main-dark whitespace-pre-wrap">
                        {messagePreview}
                    </p>
                </div>
                <div className="mt-4 flex flex-wrap gap-4">
                    <label className="text-sm">
                        Delay mín (min)
                        <input
                            type="number"
                            min={1}
                            max={60}
                            value={minDelayMin}
                            onChange={(e) => setMinDelayMin(Number(e.target.value))}
                            className="ml-2 w-20 rounded border border-border-light px-2 py-1 dark:border-border-dark dark:bg-slate-900"
                        />
                    </label>
                    <label className="text-sm">
                        Delay máx (min)
                        <input
                            type="number"
                            min={1}
                            max={120}
                            value={maxDelayMin}
                            onChange={(e) => setMaxDelayMin(Number(e.target.value))}
                            className="ml-2 w-20 rounded border border-border-light px-2 py-1 dark:border-border-dark dark:bg-slate-900"
                        />
                    </label>
                </div>
                <p className="mt-2 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                    Intervalo aleatório entre mensagens (padrão 3–9 minutos).
                </p>
            </section>

            <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark">
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                    <div>
                        <h2 className="font-semibold">Membros</h2>
                        {!loading && members.length > 0 && (
                            <p className="mt-0.5 text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                {selected.size} de {members.length} selecionados
                            </p>
                        )}
                    </div>
                    <div className="flex flex-wrap gap-2">
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
                        {members.length > 0 && (
                            <button
                                type="button"
                                onClick={() => void handleClearList()}
                                disabled={deleting}
                                className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40 disabled:opacity-50"
                            >
                                Excluir lista
                            </button>
                        )}
                        {selected.size > 0 && selected.size < members.length && (
                            <button
                                type="button"
                                onClick={() => void handleDeleteSelected()}
                                disabled={deleting}
                                className="rounded-lg border border-red-300 px-3 py-2 text-sm text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40 disabled:opacity-50"
                            >
                                Excluir selecionados
                            </button>
                        )}
                        <button
                            type="button"
                            onClick={openConfirmDispatch}
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
                                    <th className="py-2 w-16">Ação</th>
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
                                        <td className="py-2">
                                            <button
                                                type="button"
                                                onClick={() => void handleDeleteOne(m)}
                                                disabled={deleting}
                                                className="text-xs text-red-600 hover:underline disabled:opacity-50"
                                                aria-label={`Excluir ${m.name}`}
                                            >
                                                Excluir
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>

            {campaign && (
                <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark">
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                        <h2 className="font-semibold">Progresso da campanha</h2>
                        {campaign.status === "running" && (
                            <button
                                type="button"
                                onClick={() => void handleCancelCampaign()}
                                disabled={cancelling}
                                className="rounded-lg border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40"
                            >
                                {cancelling ? "Cancelando…" : "Cancelar envio"}
                            </button>
                        )}
                    </div>
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

            {recentCampaigns.length > 0 && (
                <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark">
                    <h2 className="mb-3 font-semibold">Campanhas recentes</h2>
                    <ul className="divide-y divide-border-light dark:divide-border-dark">
                        {recentCampaigns.map((c) => (
                            <li key={c.id}>
                                <button
                                    type="button"
                                    onClick={() => void openCampaignDetail(c)}
                                    className="flex w-full flex-wrap items-center justify-between gap-2 py-3 text-left text-sm hover:bg-slate-50 dark:hover:bg-slate-800/40 -mx-1 px-1 rounded-lg"
                                >
                                    <div className="min-w-0 flex-1">
                                        <p className="truncate font-medium">
                                            {c.message.length > 80 ? `${c.message.slice(0, 80)}…` : c.message}
                                        </p>
                                        <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                            {formatCampaignDate(c.created_at)} · {c.sent}/{c.total} enviados
                                            {c.failed > 0 ? ` · ${c.failed} falhas` : ""}
                                        </p>
                                    </div>
                                    <span
                                        className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${
                                            c.status === "cancelled"
                                                ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
                                                : c.status === "running"
                                                  ? "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300"
                                                  : c.status === "completed" || c.status === "done"
                                                    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                                                    : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
                                        }`}
                                    >
                                        {c.status}
                                    </span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {confirmOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
                    <div className="w-full max-w-md space-y-4 rounded-2xl border border-border-light bg-surface-light p-6 shadow-xl dark:border-border-dark dark:bg-surface-dark">
                        <h3 className="text-lg font-bold">Confirmar disparo</h3>
                        <ul className="space-y-2 text-sm text-text-secondary-light dark:text-text-secondary-dark">
                            <li>
                                <strong className="text-text-main-light dark:text-text-main-dark">
                                    {selected.size}
                                </strong>{" "}
                                destinatário{selected.size === 1 ? "" : "s"}
                            </li>
                            <li>
                                Intervalo:{" "}
                                <strong className="text-text-main-light dark:text-text-main-dark">
                                    {minDelayMin}–{maxDelayMin} min
                                </strong>
                            </li>
                            <li className="rounded-lg bg-slate-50 p-2 text-text-main-light dark:bg-slate-900/50 dark:text-text-main-dark">
                                {messageSnippet || "(sem mensagem)"}
                            </li>
                        </ul>
                        <div className="flex justify-end gap-2 pt-2">
                            <button
                                type="button"
                                onClick={() => setConfirmOpen(false)}
                                className="h-10 rounded-xl border border-border-light px-4 text-sm dark:border-border-dark"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleDispatch()}
                                disabled={dispatching}
                                className="h-10 rounded-xl bg-primary px-4 text-sm font-semibold text-white disabled:opacity-50"
                            >
                                Confirmar e disparar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
