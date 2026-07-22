"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { TenantOrgRequired } from "@/components/TenantOrgRequired";
import {
    connectWhatsappInstance,
    connectChatwoot,
    disconnectChatwoot,
    getChatwootStatus,
    createInbox,
    createMyFunnel,
    deleteInbox,
    disconnectWhatsappInstance,
    getAuthMe,
    getWhatsappStatus,
    initWhatsappInstance,
    listInboxes,
    listMyFunnels,
    listOrganizationFunnels,
    probeOrgAdmin,
    saveWhatsappToken,
    updateInbox,
    type FunnelListItem,
    type InboxDTO,
} from "@/lib/api";

function InboxConnectModal(props: {
    open: boolean;
    inbox: InboxDTO | null;
    onClose: () => void;
    token: string | undefined;
    onAfterChange: () => void;
}) {
    const { open, inbox, onClose, token, onAfterChange } = props;
    const inboxId = inbox?.id;
    const [tab, setTab] = useState<"qr" | "manual">("qr");
    const [qrCodeBase64, setQrCodeBase64] = useState("");
    const [manualToken, setManualToken] = useState("");
    const [instanceNameInput, setInstanceNameInput] = useState("crm_neurix");
    const [loading, setLoading] = useState(false);
    const [polling, setPolling] = useState(false);
    const [status, setStatus] = useState<string>("—");

    useEffect(() => {
        if (!open || !inboxId) return;
        setInstanceNameInput(`inbox_${inboxId.slice(0, 8)}`);
        setQrCodeBase64("");
        setManualToken("");
        setTab("qr");
        setPolling(false);
        (async () => {
            try {
                const res = await getWhatsappStatus(token, inboxId);
                setStatus(res.status);
            } catch {
                setStatus("desconhecido");
            }
        })();
    }, [open, inboxId, token]);

    useEffect(() => {
        let interval: ReturnType<typeof setInterval>;
        if (!open || !inboxId) return undefined;
        if (polling || status === "connecting" || status === "unknown") {
            interval = setInterval(async () => {
                try {
                    const res = await getWhatsappStatus(token, inboxId);
                    setStatus(res.status);
                    if (res.status === "open" || res.status === "connected") {
                        setPolling(false);
                        onAfterChange();
                    } else if (res.status === "disconnected") {
                        setPolling(false);
                    }
                } catch {
                    setPolling(false);
                }
            }, 3000);
        }
        return () => clearInterval(interval);
    }, [open, inboxId, token, polling, status, onAfterChange]);

    const isConnected = status === "open" || status === "connected";

    const applyQrResponse = (res: { data?: Record<string, unknown> }) => {
        const d = res.data ?? {};
        const inst = (d.instance as Record<string, unknown> | undefined) || {};
        const qrString =
            (d.base64 as string) || (d.qrcode as string) || (inst.qrcode as string);

        if (qrString) {
            setQrCodeBase64(qrString);
            setPolling(true);
            setStatus("connecting");
            return;
        }

        if (inst.state === "open" || inst.state === "connected") {
            setStatus("open");
            onAfterChange();
            return;
        }

        if (inst.state === "connecting" || d.state === "connecting") {
            setStatus("connecting");
            setPolling(true);
        }
    };

    const handleInit = async () => {
        if (!inboxId || !instanceNameInput.trim()) return;
        setLoading(true);
        try {
            await initWhatsappInstance(instanceNameInput.trim(), token, inboxId);
            const res = await getWhatsappStatus(token, inboxId);
            setStatus(res.status);
        } catch (e) {
            console.error(e);
            alert(e instanceof Error ? e.message : "Erro ao inicializar instância.");
        } finally {
            setLoading(false);
        }
    };

    const handleGenerateQr = async () => {
        if (!inboxId) return;
        setLoading(true);
        try {
            try {
                const res = await connectWhatsappInstance(token, inboxId);
                applyQrResponse(res as { data?: Record<string, unknown> });
            } catch (error: unknown) {
                const msg = error instanceof Error ? error.message : String(error || "");
                const needsInit = /nenhum token configurado|crie uma instância/i.test(msg);
                if (!needsInit) throw error;
                if (!instanceNameInput.trim()) {
                    throw new Error(
                        "Informe um nome de instância e clique em Criar instância antes de gerar o QR."
                    );
                }
                await initWhatsappInstance(instanceNameInput.trim(), token, inboxId);
                const res = await connectWhatsappInstance(token, inboxId);
                applyQrResponse(res as { data?: Record<string, unknown> });
            }
        } catch (error: unknown) {
            console.error(error);
            alert(error instanceof Error ? error.message : "Erro ao gerar QR Code");
        } finally {
            setLoading(false);
        }
    };

    const handleSaveToken = async () => {
        if (!inboxId || !manualToken.trim()) return;
        setLoading(true);
        try {
            await saveWhatsappToken(manualToken.trim(), token, inboxId);
            await getWhatsappStatus(token, inboxId).then((r) => setStatus(r.status));
            onAfterChange();
            onClose();
        } catch {
            alert("Erro ao salvar token");
        } finally {
            setLoading(false);
        }
    };

    const handleDisconnect = async () => {
        if (!inboxId || !confirm("Remover token Uazapi desta caixa?")) return;
        setLoading(true);
        try {
            await disconnectWhatsappInstance(token, inboxId);
            setQrCodeBase64("");
            setPolling(false);
            setStatus("disconnected");
            onAfterChange();
        } catch {
            alert("Erro ao desconectar");
        } finally {
            setLoading(false);
        }
    };

    if (!open || !inbox) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm" onClick={() => !loading && onClose()} />
            <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md flex flex-col max-h-[90vh]">
                <div className="p-6 border-b border-border-light dark:border-border-dark flex justify-between shrink-0">
                    <div>
                        <h3 className="text-lg font-bold font-display">Conexão Uazapi</h3>
                        <p className="text-xs text-text-secondary-light mt-1">{inbox.name}</p>
                    </div>
                    <button type="button" onClick={() => !loading && onClose()} disabled={loading}>
                        <span className="material-symbols-outlined text-text-secondary-light">close</span>
                    </button>
                </div>

                <div className="p-6 overflow-y-auto space-y-6">
                    <div className="flex rounded-lg bg-slate-100 dark:bg-slate-800 p-1">
                        <button
                            type="button"
                            className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${tab === "qr" ? "bg-white dark:bg-slate-700 shadow-sm text-primary" : "text-text-secondary-light"}`}
                            onClick={() => setTab("qr")}
                        >
                            QR Code
                        </button>
                        <button
                            type="button"
                            className={`flex-1 py-1.5 text-sm font-medium rounded-md transition-colors ${tab === "manual" ? "bg-white dark:bg-slate-700 shadow-sm text-primary" : "text-text-secondary-light"}`}
                            onClick={() => setTab("manual")}
                        >
                            Token (Leads Infinitos)
                        </button>
                    </div>

                    <div
                        className={`p-3 rounded-lg border flex items-center gap-3 ${isConnected ? "bg-green-50 border-green-200 text-green-700 dark:bg-green-900/20 dark:border-green-800 dark:text-green-400" : "bg-slate-50 border-slate-200 dark:bg-slate-800 dark:border-slate-700"}`}
                    >
                        <span className="material-symbols-outlined">{isConnected ? "check_circle" : "info"}</span>
                        <div className="text-sm">
                            <p className="font-semibold">
                                Status: {status === "open" ? "Conectado" : status}
                            </p>
                            <p className="text-xs opacity-80">
                                Cada caixa tem credenciais próprias (inbox_id no backend).
                            </p>
                        </div>
                    </div>

                    {tab === "qr" && (
                        <div className="flex flex-col items-center gap-4 text-center">
                            <div className="w-full p-4 rounded-xl border border-border-light dark:border-border-dark bg-slate-50 dark:bg-slate-800/50 space-y-3 text-left">
                                <p className="text-sm text-text-secondary-light">
                                    Crie a instância na Uazapi e depois gere o QR Code para parear o WhatsApp.
                                </p>
                                <div>
                                    <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">
                                        Nome da instância
                                    </label>
                                    <input
                                        type="text"
                                        value={instanceNameInput}
                                        onChange={(e) => setInstanceNameInput(e.target.value)}
                                        className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none"
                                    />
                                </div>
                                <button
                                    type="button"
                                    onClick={() => void handleInit()}
                                    disabled={loading || !instanceNameInput.trim()}
                                    className="w-full px-6 py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary-hover disabled:opacity-50"
                                >
                                    {loading ? "…" : "Criar instância"}
                                </button>
                            </div>

                            {qrCodeBase64 ? (
                                <div className="p-4 bg-white rounded-xl border-2 border-primary/20 shadow-inner">
                                    <img
                                        src={
                                            qrCodeBase64.startsWith("data:image")
                                                ? qrCodeBase64
                                                : `data:image/png;base64,${qrCodeBase64}`
                                        }
                                        alt="QR"
                                        className="w-48 h-48 object-contain"
                                    />
                                    {polling && (
                                        <p className="text-xs text-primary mt-3 animate-pulse">
                                            Aguardando leitura do QR…
                                        </p>
                                    )}
                                </div>
                            ) : (
                                <div className="w-48 h-48 bg-slate-100 dark:bg-slate-800 rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-600 flex items-center justify-center">
                                    <span className="material-symbols-outlined text-4xl text-slate-400">
                                        qr_code_scanner
                                    </span>
                                </div>
                            )}

                            <button
                                type="button"
                                onClick={() => void handleGenerateQr()}
                                disabled={loading}
                                className="px-6 py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary-hover disabled:opacity-50 flex items-center gap-2"
                            >
                                {loading ? (
                                    <span className="material-symbols-outlined animate-spin">refresh</span>
                                ) : (
                                    <span className="material-symbols-outlined">sync</span>
                                )}
                                Gerar QR Code
                            </button>
                        </div>
                    )}

                    {tab === "manual" && (
                        <div className="space-y-4">
                            <p className="text-sm text-text-secondary-light">
                                Cole o token da instância (Leads Infinitos, Uazapi ou nome da instância já
                                existente), conforme o fluxo que você já usa hoje.
                            </p>
                            <div>
                                <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">
                                    Token da instância
                                </label>
                                <input
                                    type="text"
                                    value={manualToken}
                                    onChange={(e) => setManualToken(e.target.value)}
                                    placeholder="Token ou identificador da instância"
                                    className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none"
                                />
                            </div>
                            <button
                                type="button"
                                onClick={() => void handleSaveToken()}
                                disabled={loading || !manualToken.trim()}
                                className="w-full py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary-hover disabled:opacity-50"
                            >
                                Salvar token
                            </button>
                        </div>
                    )}

                    <div className="pt-4 border-t border-border-light dark:border-border-dark">
                        <button
                            type="button"
                            onClick={() => void handleDisconnect()}
                            disabled={loading}
                            className="w-full py-2 px-4 rounded-lg border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 dark:border-red-900 dark:text-red-400 dark:bg-red-900/20 text-sm font-medium flex items-center justify-center gap-2"
                        >
                            <span className="material-symbols-outlined text-base">leak_remove</span>
                            Remover token desta caixa
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function ChatwootConnectModal(props: {
    open: boolean;
    inbox: InboxDTO | null;
    onClose: () => void;
    token: string | undefined;
    onAfterChange: () => void;
}) {
    const { open, inbox, onClose, token, onAfterChange } = props;
    const inboxId = inbox?.id;
    const [baseUrl, setBaseUrl] = useState("");
    const [accountId, setAccountId] = useState("");
    const [chatwootInboxId, setChatwootInboxId] = useState("");
    const [apiToken, setApiToken] = useState("");
    const [webhookSecret, setWebhookSecret] = useState("");
    const [loading, setLoading] = useState(false);
    const [status, setStatus] = useState<string>("—");
    const [statusMsg, setStatusMsg] = useState<string>("");

    useEffect(() => {
        if (!open || !inbox) return;
        const cfg = (inbox.chatwoot_settings ?? {}) as Record<string, unknown>;
        setBaseUrl(typeof cfg.base_url === "string" ? cfg.base_url : "");
        setAccountId(cfg.account_id != null ? String(cfg.account_id) : "");
        setChatwootInboxId(cfg.inbox_id != null ? String(cfg.inbox_id) : "");
        setApiToken("");
        setWebhookSecret(typeof cfg.webhook_secret === "string" ? cfg.webhook_secret : "");
        setStatus("—");
        setStatusMsg("");
        if (cfg.api_access_token && inboxId) {
            (async () => {
                try {
                    const res = await getChatwootStatus(inboxId, token);
                    setStatus(res.status);
                    if (res.message) setStatusMsg(res.message);
                } catch {
                    setStatus("desconhecido");
                }
            })();
        }
    }, [open, inbox, inboxId, token]);

    const isConnected = status === "connected";

    const handleConnect = async () => {
        if (!inboxId) return;
        if (!baseUrl.trim() || !accountId.trim() || !chatwootInboxId.trim() || !apiToken.trim()) {
            alert("Preencha URL base, account_id, inbox do Chatwoot e o token.");
            return;
        }
        setLoading(true);
        try {
            const res = await connectChatwoot(
                {
                    inbox_id: inboxId,
                    base_url: baseUrl.trim(),
                    account_id: accountId.trim(),
                    chatwoot_inbox_id: chatwootInboxId.trim(),
                    api_access_token: apiToken.trim(),
                    webhook_secret: webhookSecret.trim() || undefined,
                },
                token
            );
            setStatus(res.status);
            setStatusMsg("Etiquetas encontradas: " + (res.labels_count ?? 0));
            onAfterChange();
        } catch (e) {
            alert(e instanceof Error ? e.message : "Erro ao conectar no Chatwoot");
        } finally {
            setLoading(false);
        }
    };

    const handleDisconnect = async () => {
        if (!inboxId || !confirm("Remover credenciais Chatwoot desta caixa?")) return;
        setLoading(true);
        try {
            await disconnectChatwoot(inboxId, token);
            setStatus("disconnected");
            setApiToken("");
            onAfterChange();
        } catch {
            alert("Erro ao desconectar");
        } finally {
            setLoading(false);
        }
    };

    if (!open || !inbox) return null;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
            <div className="w-full max-w-md bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-border-light dark:border-border-dark overflow-hidden">
                <div className="p-5 border-b border-border-light dark:border-border-dark flex items-start justify-between">
                    <div>
                        <h3 className="font-semibold">WhatsApp Oficial (Chatwoot)</h3>
                        <p className="text-xs text-text-secondary-light mt-1">{inbox.name}</p>
                    </div>
                    <button type="button" onClick={onClose} className="text-text-secondary-light hover:text-primary">
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>

                <div className="p-5 space-y-4">
                    <p className="text-xs">
                        Status:{" "}
                        <span className={isConnected ? "text-green-600 font-medium" : "text-text-secondary-light"}>
                            {isConnected ? "conectado" : status}
                        </span>
                        {statusMsg ? <span className="text-text-secondary-light"> {"—"} {statusMsg}</span> : null}
                    </p>

                    <div>
                        <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">URL base do Chatwoot</label>
                        <input type="text" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://chatwoot.suaempresa.com" className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none" />
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">Account ID</label>
                            <input type="text" value={accountId} onChange={(e) => setAccountId(e.target.value)} placeholder="2" className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none" />
                        </div>
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">Inbox ID (Chatwoot)</label>
                            <input type="text" value={chatwootInboxId} onChange={(e) => setChatwootInboxId(e.target.value)} placeholder="65" className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none" />
                        </div>
                    </div>
                    <div>
                        <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">API Access Token</label>
                        <input type="password" value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="api_access_token" className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none" />
                    </div>
                    <div>
                        <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">Webhook Secret (HMAC, opcional)</label>
                        <input type="text" value={webhookSecret} onChange={(e) => setWebhookSecret(e.target.value)} placeholder="secret de assinatura do webhook" className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none" />
                    </div>

                    <button type="button" onClick={() => void handleConnect()} disabled={loading} className="w-full py-2.5 bg-primary text-white rounded-lg font-medium hover:bg-primary-hover disabled:opacity-50">
                        {loading ? "Validando…" : "Salvar e testar conexão"}
                    </button>

                    <div className="pt-4 border-t border-border-light dark:border-border-dark">
                        <button type="button" onClick={() => void handleDisconnect()} disabled={loading} className="w-full py-2 px-4 rounded-lg border border-red-200 text-red-600 bg-red-50 hover:bg-red-100 dark:border-red-900 dark:text-red-400 dark:bg-red-900/20 text-sm font-medium flex items-center justify-center gap-2">
                            <span className="material-symbols-outlined text-base">leak_remove</span>
                            Remover credenciais Chatwoot
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}

function ConfiguracoesContent() {
    const searchParams = useSearchParams();
    const fromAdmin = searchParams.get("from") === "admin";

    const [activeColor, setActiveColor] = useState("#E11D48");
    const [pendingColor, setPendingColor] = useState("#E11D48");
    const [showDashboardEdit, setShowDashboardEdit] = useState(false);
    const [showFunnelStats, setShowFunnelStats] = useState(false);
    const [showProductsPanel, setShowProductsPanel] = useState(false);
    const [aiEnabled, setAiEnabled] = useState(true);
    const [nfEnabled, setNfEnabled] = useState(false);
    const [systemPromptExtra, setSystemPromptExtra] = useState("");

    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") || undefined : undefined;

    const [funnels, setFunnels] = useState<FunnelListItem[]>([]);
    const [inboxes, setInboxes] = useState<InboxDTO[]>([]);
    const [inboxStatuses, setInboxStatuses] = useState<Record<string, string>>({});
    const [listLoading, setListLoading] = useState(true);
    const [listError, setListError] = useState<string | null>(null);
    const [canManage, setCanManage] = useState<boolean | null>(null);

    const [createOpen, setCreateOpen] = useState(false);
    const [createName, setCreateName] = useState("");
    const [createFunnelId, setCreateFunnelId] = useState("");
    const [createBusy, setCreateBusy] = useState(false);
    const [funnelModalOpen, setFunnelModalOpen] = useState(false);
    const [newFunnelName, setNewFunnelName] = useState("");
    const [funnelCreateBusy, setFunnelCreateBusy] = useState(false);
    const [currentUserId, setCurrentUserId] = useState<string | null>(null);

    const [editOpen, setEditOpen] = useState(false);
    const [editRow, setEditRow] = useState<InboxDTO | null>(null);
    const [editName, setEditName] = useState("");
    const [editFunnelId, setEditFunnelId] = useState("");
    const [editBusy, setEditBusy] = useState(false);

    const [connectInbox, setConnectInbox] = useState<InboxDTO | null>(null);
    const [connectChatwootInbox, setConnectChatwootInbox] = useState<InboxDTO | null>(null);

    const funnelById = useMemo(() => {
        const m = new Map<string, string>();
        funnels.forEach((f) => m.set(f.id, f.name));
        return m;
    }, [funnels]);

    const refreshAll = useCallback(async () => {
        if (!token) {
            setListLoading(false);
            return;
        }
        setListError(null);
        setListLoading(true);
        try {
            try {
                await probeOrgAdmin(token);
                setCanManage(true);
            } catch {
                setCanManage(false);
            }

            const me = await getAuthMe(token);
            setCurrentUserId(me.id);
            const orgId = me.organization_id?.trim() || null;

            const [myFl, orgFl, ib] = await Promise.all([
                listMyFunnels(token),
                orgId ? listOrganizationFunnels(orgId, token) : Promise.resolve([]),
                listInboxes(token),
            ]);

            const merged: FunnelListItem[] = [];
            const seen = new Set<string>();
            for (const f of orgFl.length > 0 ? orgFl : myFl) {
                if (!seen.has(f.id)) {
                    seen.add(f.id);
                    merged.push(f);
                }
            }
            for (const f of myFl) {
                if (!seen.has(f.id)) {
                    seen.add(f.id);
                    merged.push(f);
                }
            }
            setFunnels(merged);
            setInboxes(ib);

            const statusEntries = await Promise.all(
                ib.map(async (i) => {
                    try {
                        const r = await getWhatsappStatus(token, i.id);
                        return [i.id, r.status] as const;
                    } catch {
                        return [i.id, "erro"] as const;
                    }
                })
            );
            setInboxStatuses(Object.fromEntries(statusEntries));
        } catch (e) {
            setListError(e instanceof Error ? e.message : "Erro ao carregar caixas.");
        } finally {
            setListLoading(false);
        }
    }, [token]);

    useEffect(() => {
        void refreshAll();
    }, [refreshAll]);

    const onCreated = () => void refreshAll();

    const handleCreateFunnel = async () => {
        const name = newFunnelName.trim();
        if (!name || !token) return;
        setFunnelCreateBusy(true);
        try {
            await createMyFunnel({ name }, token);
            setFunnelModalOpen(false);
            setNewFunnelName("");
            await refreshAll();
        } catch (e) {
            alert(e instanceof Error ? e.message : "Erro ao criar funil.");
        } finally {
            setFunnelCreateBusy(false);
        }
    };

    const handleCreate = async () => {
        const name = createName.trim();
        if (!name) {
            alert("Informe o nome da caixa.");
            return;
        }
        if (!createFunnelId) {
            alert("Selecione um funil. Cada caixa deve estar vinculada a exatamente um funil.");
            return;
        }
        setCreateBusy(true);
        try {
            await createInbox({ name, funnel_id: createFunnelId }, token);
            setCreateOpen(false);
            setCreateName("");
            setCreateFunnelId("");
            await refreshAll();
        } catch (e) {
            alert(e instanceof Error ? e.message : "Erro ao criar caixa.");
        } finally {
            setCreateBusy(false);
        }
    };

    const handleEditSave = async () => {
        if (!editRow) return;
        const name = editName.trim();
        if (!name) {
            alert("Informe o nome.");
            return;
        }
        if (!editFunnelId) {
            alert("Selecione um funil.");
            return;
        }
        setEditBusy(true);
        try {
            await updateInbox(
                editRow.id,
                { name, funnel_id: editFunnelId },
                token
            );
            setEditOpen(false);
            setEditRow(null);
            await refreshAll();
        } catch (e) {
            alert(e instanceof Error ? e.message : "Erro ao atualizar.");
        } finally {
            setEditBusy(false);
        }
    };

    const handleDelete = async (row: InboxDTO) => {
        if (!confirm(`Excluir a caixa "${row.name}"? Isso remove o vínculo Uazapi desta caixa.`)) return;
        try {
            await deleteInbox(row.id, token);
            await refreshAll();
        } catch (e) {
            alert(e instanceof Error ? e.message : "Erro ao excluir.");
        }
    };

    const [dashMetrics, setDashMetrics] = useState({
        conversao: true,
        faturamento: true,
        contatos: true,
        pedidosRecentes: true,
        produtosMaisVendidos: false,
        msgPorDia: false,
    });

    const modules = [
        { icon: "dashboard", name: "Painel Principal", desc: "Visualização geral de métricas", action: () => setShowDashboardEdit(true) },
        { icon: "trending_up", name: "Funil de Vendas", desc: "Gestão de leads e oportunidades", action: () => setShowFunnelStats(true) },
        { icon: "inventory_2", name: "Produtos", desc: "Catálogo de produtos e insumos", action: () => setShowProductsPanel(true) },
    ];

    const colorOptions = [
        { value: "#E11D48", label: "Rosa" },
        { value: "#DC2626", label: "Vermelho" },
        { value: "#2563EB", label: "Azul Royal" },
        { value: "#D97706", label: "Dourado" },
        { value: "#0F766E", label: "Verde" },
    ];

    function applyColor() {
        setActiveColor(pendingColor);
        document.documentElement.style.setProperty("--color-primary", pendingColor);
    }

    return (
        <div className="p-8 overflow-y-auto h-full">
            <div className="max-w-[960px] mx-auto flex flex-col gap-8 pb-12">
                {fromAdmin && (
                    <div className="rounded-xl border border-primary/30 bg-primary/5 dark:bg-primary/10 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
                        <p className="text-sm text-text-secondary-light">
                            Você veio do <strong className="text-text-main-light dark:text-text-main-dark">Console Admin</strong>.
                        </p>
                        <Link
                            href="/admin"
                            className="inline-flex items-center gap-2 h-9 px-4 rounded-lg bg-primary text-white text-sm font-semibold hover:bg-primary-hover"
                        >
                            <span className="material-symbols-outlined text-[18px]">arrow_back</span>
                            Voltar ao Console Admin
                        </Link>
                    </div>
                )}

                <div className="flex flex-col gap-2">
                    <h1 className="text-3xl font-extrabold font-display tracking-tight">Configurações</h1>
                    <p className="text-text-secondary-light dark:text-text-secondary-dark text-base">
                        Gerencie seus módulos, integrações e preferências do sistema.
                    </p>
                </div>

                <div className="flex flex-col gap-4">
                    <div className="flex items-center justify-between">
                        <h2 className="text-lg font-bold">Gerenciar Módulos</h2>
                        <button type="button" className="text-primary text-sm font-medium hover:underline">
                            Restaurar padrões
                        </button>
                    </div>
                    <div className="bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-border-light dark:border-border-dark overflow-hidden">
                        {modules.map((mod, i) => (
                            <div
                                key={mod.name}
                                className={`flex items-center justify-between p-4 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors ${i < modules.length - 1 ? "border-b border-border-light dark:border-border-dark" : ""}`}
                            >
                                <div className="flex items-center gap-4">
                                    <div className="flex items-center justify-center rounded-lg bg-primary/10 text-primary shrink-0 w-10 h-10">
                                        <span className="material-symbols-outlined">{mod.icon}</span>
                                    </div>
                                    <div>
                                        <span className="font-medium text-sm">{mod.name}</span>
                                        <br />
                                        <span className="text-text-secondary-light text-xs">{mod.desc}</span>
                                    </div>
                                </div>
                                <button
                                    type="button"
                                    onClick={mod.action}
                                    className="p-2 rounded-full text-text-secondary-light hover:text-primary hover:bg-primary/10 transition-all"
                                >
                                    <span className="material-symbols-outlined text-[20px]">edit</span>
                                </button>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="flex flex-col gap-4">
                    <h2 className="text-lg font-bold">Customização Visual</h2>
                    <div className="bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-border-light dark:border-border-dark p-5">
                        <div className="flex items-center justify-between flex-wrap gap-4">
                            <div className="flex flex-col gap-1">
                                <span className="font-medium text-sm">Paleta de Cores</span>
                                <p className="text-text-secondary-light text-xs">Escolha a cor principal da interface</p>
                            </div>
                            <div className="flex items-center gap-4">
                                <div className="flex items-center gap-3 bg-slate-50 dark:bg-slate-800/50 p-2 rounded-full border border-border-light dark:border-border-dark">
                                    {colorOptions.map((c) => (
                                        <button
                                            key={c.value}
                                            type="button"
                                            onClick={() => setPendingColor(c.value)}
                                            className={`rounded-full transition-all hover:scale-110 ${pendingColor === c.value ? "w-8 h-8 ring-2 ring-offset-2 ring-primary" : "w-6 h-6"}`}
                                            style={{ backgroundColor: c.value }}
                                            title={c.label}
                                        />
                                    ))}
                                </div>
                                <button
                                    type="button"
                                    onClick={applyColor}
                                    disabled={pendingColor === activeColor}
                                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${pendingColor !== activeColor ? "bg-primary text-white hover:bg-primary-hover shadow-lg shadow-primary/30" : "bg-slate-100 dark:bg-slate-800 text-text-secondary-light cursor-not-allowed"}`}
                                >
                                    Aplicar
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="flex flex-col gap-4">
                    <h2 className="text-lg font-bold">Integrações</h2>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div className="bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-border-light dark:border-border-dark p-5 space-y-4 md:col-span-2">
                            <div className="flex flex-wrap items-start justify-between gap-4">
                                <div className="flex items-center gap-3">
                                    <div className="w-10 h-10 rounded-full bg-primary/15 text-primary flex items-center justify-center">
                                        <span className="material-symbols-outlined">inbox</span>
                                    </div>
                                    <div>
                                        <h3 className="font-semibold text-sm">Caixas de entrada (WhatsApp / Uazapi)</h3>
                                        <p className="text-xs text-text-secondary-light max-w-xl">
                                            Cada caixa tem nome, um funil vinculado (obrigatório) e credenciais Uazapi próprias.
                                            Várias caixas podem usar o mesmo funil — o Kanban mostrará a origem quando houver mais de uma caixa (S13).
                                        </p>
                                    </div>
                                </div>
                                {canManage && (
                                    <div className="flex flex-wrap gap-2 shrink-0">
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setNewFunnelName("");
                                                setFunnelModalOpen(true);
                                            }}
                                            className="h-10 px-4 rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark text-sm font-semibold hover:border-primary"
                                        >
                                            Novo funil
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setCreateName("");
                                                setCreateFunnelId(funnels[0]?.id ?? "");
                                                setCreateOpen(true);
                                            }}
                                            className="h-10 px-4 rounded-xl bg-primary text-white text-sm font-semibold hover:bg-primary-hover"
                                        >
                                            Nova caixa
                                        </button>
                                    </div>
                                )}
                            </div>

                            {canManage === false && (
                                <p className="text-sm text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
                                    Apenas administradores da organização podem criar ou editar caixas de entrada. Seu usuário está em modo restrito (ex.: somente leitura).
                                </p>
                            )}

                            {listError && (
                                <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm px-3 py-2">
                                    {listError}
                                </div>
                            )}

                            {listLoading && <p className="text-sm text-text-secondary-light">Carregando caixas…</p>}

                            {!listLoading && canManage !== false && funnels.length === 0 && (
                                <p className="text-sm text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg px-3 py-2">
                                    Nenhum funil disponível para esta conta ou organização. Crie um funil com <strong>Novo funil</strong> antes de abrir uma caixa.
                                </p>
                            )}

                            {!listLoading && canManage !== false && inboxes.length === 0 && (
                                <p className="text-sm text-text-secondary-light">
                                    Nenhuma caixa ainda. Clique em <strong>Nova caixa</strong>, escolha o funil e conecte o WhatsApp (QR ou token).
                                </p>
                            )}

                            {!listLoading && inboxes.length > 0 && (
                                <div className="space-y-3">
                                    {inboxes.map((row) => {
                                        const st = inboxStatuses[row.id] ?? "—";
                                        const ok = st === "open" || st === "connected";
                                        return (
                                            <div
                                                key={row.id}
                                                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border-light dark:border-border-dark bg-slate-50/80 dark:bg-slate-800/40 p-4"
                                            >
                                                <div className="min-w-0">
                                                    <p className="font-medium text-sm truncate">{row.name}</p>
                                                    <p className="text-xs text-text-secondary-light font-mono truncate">
                                                        Funil: {funnelById.get(row.funnel_id) ?? row.funnel_id}
                                                    </p>
                                                    <p className="text-xs mt-1">
                                                        Uazapi:{" "}
                                                        <span
                                                            className={
                                                                ok ? "text-green-600 font-medium" : "text-text-secondary-light"
                                                            }
                                                        >
                                                            {ok ? "conectado" : st}
                                                        </span>
                                                    </p>
                                                </div>
                                                <div className="flex flex-wrap gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={() => {
                                                            setConnectInbox(row);
                                                        }}
                                                        className="h-9 px-3 rounded-lg text-xs font-semibold bg-primary/10 text-primary hover:bg-primary/20"
                                                    >
                                                        Conectar
                                                    </button>
                                                    <button
                                                        type="button"
                                                        onClick={() => { setConnectChatwootInbox(row); }}
                                                        className="h-9 px-3 rounded-lg text-xs font-semibold bg-primary/10 text-primary hover:bg-primary/20"
                                                    >
                                                        API Oficial
                                                    </button>
                                                    {canManage && (
                                                        <>
                                                            <button
                                                                type="button"
                                                                onClick={() => {
                                                                    setEditRow(row);
                                                                    setEditName(row.name);
                                                                    setEditFunnelId(row.funnel_id);
                                                                    setEditOpen(true);
                                                                }}
                                                                className="h-9 px-3 rounded-lg text-xs font-semibold border border-border-light dark:border-border-dark hover:border-primary"
                                                            >
                                                                Editar
                                                            </button>
                                                            <button
                                                                type="button"
                                                                onClick={() => void handleDelete(row)}
                                                                className="h-9 px-3 rounded-lg text-xs font-semibold text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                                                            >
                                                                Excluir
                                                            </button>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}

                            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-border-light dark:border-border-dark">
                                <div className="flex items-center justify-between mb-3">
                                    <div>
                                        <span className="font-medium text-sm">Agente de IA</span>
                                        <p className="text-xs text-text-secondary-light mt-0.5">
                                            Ativar respostas automáticas com IA
                                        </p>
                                    </div>
                                    <label className="relative inline-flex items-center cursor-pointer">
                                        <input
                                            checked={aiEnabled}
                                            onChange={(e) => setAiEnabled(e.target.checked)}
                                            className="sr-only peer"
                                            type="checkbox"
                                        />
                                        <div className="w-11 h-6 bg-slate-200 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary" />
                                    </label>
                                </div>
                                {aiEnabled && (
                                    <div>
                                        <label className="text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1 block">
                                            Informações adicionais para o prompt
                                        </label>
                                        <textarea
                                            value={systemPromptExtra}
                                            onChange={(e) => setSystemPromptExtra(e.target.value)}
                                            className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm focus:ring-1 focus:ring-primary resize-none"
                                            rows={3}
                                            placeholder="Ex: Promoção de Natal: 20% de desconto…"
                                        />
                                    </div>
                                )}
                            </div>
                        </div>

                        <div className="bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-border-light dark:border-border-dark p-5 space-y-4">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-900/30 text-blue-600 flex items-center justify-center">
                                    <span className="material-symbols-outlined">receipt_long</span>
                                </div>
                                <div className="flex-1">
                                    <h3 className="font-semibold text-sm">Emissão de Nota Fiscal</h3>
                                    <p className="text-xs text-text-secondary-light">Integração com API de NF-e</p>
                                </div>
                            </div>
                            <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-border-light dark:border-border-dark">
                                <div className="flex items-center justify-between mb-3">
                                    <div>
                                        <span className="font-medium text-sm">Emissão Automática</span>
                                        <p className="text-xs text-text-secondary-light mt-0.5">
                                            Gerar NF-e ao confirmar pagamento
                                        </p>
                                    </div>
                                    <label className="relative inline-flex items-center cursor-pointer">
                                        <input
                                            checked={nfEnabled}
                                            onChange={(e) => setNfEnabled(e.target.checked)}
                                            className="sr-only peer"
                                            type="checkbox"
                                        />
                                        <div className="w-11 h-6 bg-slate-200 rounded-full peer dark:bg-slate-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-primary" />
                                    </label>
                                </div>
                                <button
                                    type="button"
                                    className="w-full px-3 py-2 border border-border-light dark:border-border-dark rounded-lg text-sm font-medium text-text-secondary-light hover:border-primary hover:text-primary transition-colors flex items-center justify-center gap-2"
                                >
                                    <span className="material-symbols-outlined text-base">network_check</span>
                                    Testar Conectividade
                                </button>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="mt-8 border-t border-border-light dark:border-border-dark pt-6 flex flex-col md:flex-row justify-between items-center text-xs text-text-secondary-light">
                    <p>© 2026 — Neurix IA</p>
                    <div className="flex gap-4 mt-2 md:mt-0">
                        <a className="hover:text-primary transition-colors" href="#">
                            Documentação
                        </a>
                        <a className="hover:text-primary transition-colors" href="#">
                            Suporte
                        </a>
                        <a className="hover:text-primary transition-colors" href="#">
                            Termos de Uso
                        </a>
                    </div>
                </div>
            </div>

            {showDashboardEdit && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
                        onClick={() => setShowDashboardEdit(false)}
                    />
                    <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md">
                        <div className="p-6 border-b border-border-light dark:border-border-dark flex justify-between">
                            <h3 className="text-lg font-bold font-display">Editar Painel Principal</h3>
                            <button type="button" onClick={() => setShowDashboardEdit(false)}>
                                <span className="material-symbols-outlined text-text-secondary-light">close</span>
                            </button>
                        </div>
                        <div className="p-6 space-y-3">
                            <p className="text-sm text-text-secondary-light mb-4">
                                Escolha quais métricas aparecem no dashboard:
                            </p>
                            {[
                                { key: "conversao", label: "Taxa de Conversão" },
                                { key: "faturamento", label: "Faturamento Mensal" },
                                { key: "contatos", label: "Novos Contatos" },
                                { key: "pedidosRecentes", label: "Últimos Pedidos" },
                                { key: "produtosMaisVendidos", label: "Produtos Mais Vendidos" },
                                { key: "msgPorDia", label: "Mensagens por Dia" },
                            ].map(({ key, label }) => (
                                <label
                                    key={key}
                                    className="flex items-center justify-between py-2 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 px-3 rounded-lg transition-colors"
                                >
                                    <span className="text-sm font-medium">{label}</span>
                                    <input
                                        type="checkbox"
                                        checked={dashMetrics[key as keyof typeof dashMetrics]}
                                        onChange={(e) =>
                                            setDashMetrics({ ...dashMetrics, [key]: e.target.checked })
                                        }
                                        className="w-4 h-4 text-primary rounded border-border-light focus:ring-primary"
                                    />
                                </label>
                            ))}
                        </div>
                        <div className="p-4 border-t border-border-light dark:border-border-dark">
                            <button
                                type="button"
                                onClick={() => setShowDashboardEdit(false)}
                                className="w-full py-2.5 bg-primary text-white rounded-xl font-medium hover:bg-primary-hover transition-all"
                            >
                                Salvar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {showFunnelStats && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
                        onClick={() => setShowFunnelStats(false)}
                    />
                    <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md">
                        <div className="p-6 border-b border-border-light dark:border-border-dark flex justify-between">
                            <h3 className="text-lg font-bold font-display">Funil de Vendas</h3>
                            <button type="button" onClick={() => setShowFunnelStats(false)}>
                                <span className="material-symbols-outlined text-text-secondary-light">close</span>
                            </button>
                        </div>
                        <div className="p-6">
                            <div className="grid grid-cols-2 gap-4">
                                <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-xl text-center">
                                    <p className="text-xs text-text-secondary-light uppercase font-medium">
                                        Conversas Iniciadas
                                    </p>
                                    <p className="text-2xl font-bold mt-1">127</p>
                                </div>
                                <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-xl text-center">
                                    <p className="text-xs text-text-secondary-light uppercase font-medium">
                                        Tempo Médio IA
                                    </p>
                                    <p className="text-2xl font-bold mt-1">2.3s</p>
                                </div>
                                <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-xl text-center">
                                    <p className="text-xs text-text-secondary-light uppercase font-medium">
                                        Novos Pedidos
                                    </p>
                                    <p className="text-2xl font-bold mt-1 text-green-600">34</p>
                                </div>
                                <div className="bg-slate-50 dark:bg-slate-800/50 p-4 rounded-xl text-center">
                                    <p className="text-xs text-text-secondary-light uppercase font-medium">
                                        Pagam. Confirmados
                                    </p>
                                    <p className="text-2xl font-bold mt-1 text-primary">28</p>
                                </div>
                            </div>
                            <div className="mt-5 p-4 bg-primary/5 rounded-xl border border-primary/20">
                                <div className="flex items-center justify-between">
                                    <span className="text-sm font-medium">Conversão Geral</span>
                                    <span className="text-xl font-bold text-primary">22.0%</span>
                                </div>
                                <div className="mt-2 h-2 bg-slate-100 dark:bg-slate-700 rounded-full">
                                    <div className="h-full bg-primary rounded-full" style={{ width: "22%" }} />
                                </div>
                            </div>
                        </div>
                        <div className="p-4 border-t border-border-light dark:border-border-dark">
                            <button
                                type="button"
                                onClick={() => setShowFunnelStats(false)}
                                className="w-full py-2.5 bg-primary text-white rounded-xl font-medium hover:bg-primary-hover transition-all"
                            >
                                Fechar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {showProductsPanel && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
                        onClick={() => setShowProductsPanel(false)}
                    />
                    <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md">
                        <div className="p-6 border-b border-border-light dark:border-border-dark flex justify-between">
                            <h3 className="text-lg font-bold font-display">Gerenciar Produtos</h3>
                            <button type="button" onClick={() => setShowProductsPanel(false)}>
                                <span className="material-symbols-outlined text-text-secondary-light">close</span>
                            </button>
                        </div>
                        <div className="p-6 space-y-4">
                            <a
                                href="/produtos"
                                className="block p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-border-light dark:border-border-dark hover:border-primary transition-colors group"
                            >
                                <div className="flex items-center gap-3">
                                    <span className="material-symbols-outlined text-primary text-xl">inventory_2</span>
                                    <div>
                                        <p className="font-medium text-sm group-hover:text-primary transition-colors">
                                            Catálogo de Produtos
                                        </p>
                                        <p className="text-xs text-text-secondary-light">
                                            Gerenciar produtos, preços e estoque
                                        </p>
                                    </div>
                                    <span className="material-symbols-outlined text-text-secondary-light ml-auto">
                                        arrow_forward
                                    </span>
                                </div>
                            </a>
                            <div className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-border-light dark:border-border-dark">
                                <div className="flex items-center gap-3 mb-3">
                                    <span className="material-symbols-outlined text-primary text-xl">category</span>
                                    <div>
                                        <p className="font-medium text-sm">Categorias</p>
                                        <p className="text-xs text-text-secondary-light">Gerenciar categorias de produtos</p>
                                    </div>
                                </div>
                                <div className="flex flex-wrap gap-2">
                                    {["Tradicional", "Diet / Zero", "Gourmet", "Sazonal"].map((c) => (
                                        <span
                                            key={c}
                                            className="px-3 py-1 bg-primary-light dark:bg-primary/20 text-primary text-xs font-medium rounded-full"
                                        >
                                            {c}
                                        </span>
                                    ))}
                                </div>
                            </div>
                            <div className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-border-light dark:border-border-dark">
                                <div className="flex items-center gap-3">
                                    <span className="material-symbols-outlined text-primary text-xl">local_shipping</span>
                                    <div>
                                        <p className="font-medium text-sm">Lotes</p>
                                        <p className="text-xs text-text-secondary-light">Gerenciar lotes de produção</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div className="p-4 border-t border-border-light dark:border-border-dark">
                            <button
                                type="button"
                                onClick={() => setShowProductsPanel(false)}
                                className="w-full py-2.5 bg-primary text-white rounded-xl font-medium hover:bg-primary-hover transition-all"
                            >
                                Fechar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {funnelModalOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
                        onClick={() => !funnelCreateBusy && setFunnelModalOpen(false)}
                    />
                    <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md p-6 space-y-4">
                        <h3 className="text-lg font-bold font-display">Novo funil</h3>
                        <p className="text-xs text-text-secondary-light">
                            O funil é criado na sua conta e pode ser usado em caixas e no Kanban. Administradores da
                            organização também enxergam funis de outros admins no seletor.
                        </p>
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase mb-1 block">
                                Nome
                            </label>
                            <input
                                value={newFunnelName}
                                onChange={(e) => setNewFunnelName(e.target.value)}
                                className="w-full px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-white dark:bg-slate-800 text-sm"
                                placeholder="Ex.: Vendas B2B"
                            />
                        </div>
                        <div className="flex gap-2 justify-end pt-2">
                            <button
                                type="button"
                                onClick={() => setFunnelModalOpen(false)}
                                className="h-10 px-4 rounded-lg border border-border-light dark:border-border-dark text-sm"
                                disabled={funnelCreateBusy}
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleCreateFunnel()}
                                disabled={funnelCreateBusy || !newFunnelName.trim()}
                                className="h-10 px-4 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-50"
                            >
                                {funnelCreateBusy ? "Criando…" : "Criar funil"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {createOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
                        onClick={() => !createBusy && setCreateOpen(false)}
                    />
                    <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md p-6 space-y-4">
                        <h3 className="text-lg font-bold font-display">Nova caixa de entrada</h3>
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase mb-1 block">
                                Nome
                            </label>
                            <input
                                value={createName}
                                onChange={(e) => setCreateName(e.target.value)}
                                className="w-full px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-white dark:bg-slate-800 text-sm"
                                placeholder="Ex.: WhatsApp Loja Principal"
                            />
                        </div>
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase mb-1 block">
                                Funil (obrigatório)
                            </label>
                            <select
                                value={createFunnelId}
                                onChange={(e) => setCreateFunnelId(e.target.value)}
                                className="w-full px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-white dark:bg-slate-800 text-sm"
                            >
                                <option value="">— Selecione —</option>
                                {funnels.map((f) => (
                                    <option key={f.id} value={f.id}>
                                        {f.name}
                                        {currentUserId && f.tenant_id === currentUserId ? " (sua conta)" : ""}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="flex gap-2 justify-end pt-2">
                            <button
                                type="button"
                                onClick={() => setCreateOpen(false)}
                                className="h-10 px-4 rounded-lg border border-border-light dark:border-border-dark text-sm"
                                disabled={createBusy}
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleCreate()}
                                disabled={createBusy}
                                className="h-10 px-4 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-50"
                            >
                                {createBusy ? "Salvando…" : "Criar"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {editOpen && editRow && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
                    <div
                        className="absolute inset-0 bg-slate-900/30 backdrop-blur-sm"
                        onClick={() => !editBusy && setEditOpen(false)}
                    />
                    <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md p-6 space-y-4">
                        <h3 className="text-lg font-bold font-display">Editar caixa</h3>
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase mb-1 block">
                                Nome
                            </label>
                            <input
                                value={editName}
                                onChange={(e) => setEditName(e.target.value)}
                                className="w-full px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-white dark:bg-slate-800 text-sm"
                            />
                        </div>
                        <div>
                            <label className="text-xs font-semibold text-text-secondary-light uppercase mb-1 block">
                                Funil
                            </label>
                            <select
                                value={editFunnelId}
                                onChange={(e) => setEditFunnelId(e.target.value)}
                                className="w-full px-3 py-2 rounded-lg border border-border-light dark:border-border-dark bg-white dark:bg-slate-800 text-sm"
                            >
                                {funnels.map((f) => (
                                    <option key={f.id} value={f.id}>
                                        {f.name}
                                        {currentUserId && f.tenant_id === currentUserId ? " (sua conta)" : ""}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="flex gap-2 justify-end pt-2">
                            <button
                                type="button"
                                onClick={() => setEditOpen(false)}
                                className="h-10 px-4 rounded-lg border border-border-light dark:border-border-dark text-sm"
                                disabled={editBusy}
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                onClick={() => void handleEditSave()}
                                disabled={editBusy}
                                className="h-10 px-4 rounded-lg bg-primary text-white text-sm font-semibold disabled:opacity-50"
                            >
                                {editBusy ? "Salvando…" : "Salvar"}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <InboxConnectModal
                open={!!connectInbox}
                inbox={connectInbox}
                onClose={() => setConnectInbox(null)}
                token={token}
                onAfterChange={onCreated}
            />

            <ChatwootConnectModal
                open={!!connectChatwootInbox}
                inbox={connectChatwootInbox}
                onClose={() => setConnectChatwootInbox(null)}
                token={token}
                onAfterChange={onCreated}
            />
        </div>
    );
}

export default function ConfiguracoesPage() {
    return (
        <Suspense
            fallback={
                <div className="p-8 text-text-secondary-light text-sm">Carregando configurações…</div>
            }
        >
            <TenantOrgRequired>
                <ConfiguracoesContent />
            </TenantOrgRequired>
        </Suspense>
    );
}
