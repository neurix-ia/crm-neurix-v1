"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CrmClientForm } from "@/components/crm/CrmClientForm";
import {
    createCrmClient,
    deleteClient,
    getAuthMe,
    listClients,
    listClientLeads,
    listClientOrders,
    updateClient,
    type AuthMe,
    type ClientLeadDTO,
    type ClientOrderDTO,
    type CreateCrmClientBody,
    type CrmClientDTO,
    type PatchCrmClientBody,
} from "@/lib/api";
import { maskCpf, maskCnpj, maskCep } from "@/lib/crm-masks";

type Tab = "list" | "detail";

export default function ClientesPage() {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const [me, setMe] = useState<AuthMe | null>(null);
    const [rows, setRows] = useState<CrmClientDTO[]>([]);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [tab, setTab] = useState<Tab>("list");
    const [search, setSearch] = useState("");

    const [modalOpen, setModalOpen] = useState(false);
    const [modalMode, setModalMode] = useState<"create" | "edit">("create");
    const [editing, setEditing] = useState<CrmClientDTO | null>(null);
    const [formKey, setFormKey] = useState(0);
    const [submitting, setSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);

    const [selectedClient, setSelectedClient] = useState<CrmClientDTO | null>(null);
    const [clientLeads, setClientLeads] = useState<ClientLeadDTO[]>([]);
    const [clientOrders, setClientOrders] = useState<ClientOrderDTO[]>([]);
    const [detailLoading, setDetailLoading] = useState(false);

    useEffect(() => {
        if (!token) return;
        getAuthMe(token).then(setMe).catch(() => {});
    }, [token]);

    const loadClients = useCallback(async () => {
        if (!token) return;
        setLoading(true);
        setError(null);
        try {
            const data = await listClients(token);
            setRows(data);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao listar clientes.");
            setRows([]);
        } finally {
            setLoading(false);
        }
    }, [token]);

    useEffect(() => {
        void loadClients();
    }, [loadClients]);

    const filteredRows = useMemo(() => {
        if (!search.trim()) return rows;
        const q = search.toLowerCase();
        return rows.filter(
            (c) =>
                c.display_name.toLowerCase().includes(q) ||
                (c.contact_name || "").toLowerCase().includes(q) ||
                (c.cpf || "").includes(q) ||
                (c.cnpj || "").includes(q) ||
                (c.phones || []).some((p) => p.includes(q)) ||
                (c.city || "").toLowerCase().includes(q)
        );
    }, [rows, search]);

    const openCreate = () => {
        setModalMode("create");
        setEditing(null);
        setFormError(null);
        setFormKey((k) => k + 1);
        setModalOpen(true);
    };

    const openEdit = (row: CrmClientDTO) => {
        setModalMode("edit");
        setEditing(row);
        setFormError(null);
        setFormKey((k) => k + 1);
        setModalOpen(true);
    };

    const closeModal = () => {
        setModalOpen(false);
        setEditing(null);
        setFormError(null);
    };

    const handleFormSubmit = async (payload: CreateCrmClientBody | PatchCrmClientBody) => {
        if (!token) return;
        setSubmitting(true);
        setFormError(null);
        try {
            if (modalMode === "create") {
                await createCrmClient(payload as CreateCrmClientBody, token);
            } else if (editing) {
                await updateClient(editing.id, payload as PatchCrmClientBody, token);
            }
            closeModal();
            await loadClients();
        } catch (e) {
            setFormError(e instanceof Error ? e.message : "Erro ao salvar.");
        } finally {
            setSubmitting(false);
        }
    };

    const handleDelete = async (row: CrmClientDTO) => {
        if (!token) return;
        if (!window.confirm(`Excluir cliente "${row.display_name}"? Leads vinculados perderão o vínculo.`)) return;
        setError(null);
        try {
            await deleteClient(row.id, token);
            if (selectedClient?.id === row.id) {
                setSelectedClient(null);
                setTab("list");
            }
            await loadClients();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao excluir.");
        }
    };

    const openDetail = async (row: CrmClientDTO) => {
        if (!token) return;
        setSelectedClient(row);
        setTab("detail");
        setDetailLoading(true);
        try {
            const [leads, orders] = await Promise.all([
                listClientLeads(row.id, token),
                listClientOrders(row.id, token),
            ]);
            setClientLeads(leads);
            setClientOrders(orders);
        } catch {
            setClientLeads([]);
            setClientOrders([]);
        } finally {
            setDetailLoading(false);
        }
    };

    const formatCurrency = (v: number) =>
        new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);

    const formatDate = (s: string) => {
        try {
            return new Date(s).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" });
        } catch {
            return s;
        }
    };

    const inputCls =
        "w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3 text-sm focus:ring-1 focus:ring-primary focus:border-transparent";

    return (
        <div className="p-6 max-w-7xl mx-auto space-y-6">
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-bold font-display">Clientes</h1>
                    <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark mt-1">
                        Gerencie seus clientes, veja negócios e histórico de compras vinculados.
                    </p>
                </div>
                {tab === "list" && (
                    <button
                        onClick={openCreate}
                        className="h-10 px-5 rounded-xl bg-primary text-white text-sm font-semibold flex items-center gap-2 hover:opacity-90 transition-opacity"
                    >
                        <span className="material-symbols-outlined text-lg">person_add</span>
                        Novo cliente
                    </button>
                )}
                {tab === "detail" && (
                    <button
                        onClick={() => setTab("list")}
                        className="h-10 px-5 rounded-xl border border-border-light dark:border-border-dark text-sm font-medium flex items-center gap-2 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    >
                        <span className="material-symbols-outlined text-lg">arrow_back</span>
                        Voltar à lista
                    </button>
                )}
            </div>

            {error && (
                <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm px-4 py-3">
                    {error}
                </div>
            )}

            {/* === LIST TAB === */}
            {tab === "list" && (
                <>
                    {/* Search */}
                    <div className="flex gap-3 flex-wrap items-center">
                        <div className="relative flex-1 min-w-[200px] max-w-md">
                            <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-text-secondary-light text-lg">
                                search
                            </span>
                            <input
                                className={`${inputCls} pl-10`}
                                placeholder="Buscar por nome, CPF/CNPJ, telefone, cidade..."
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                            />
                        </div>
                        <span className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                            {filteredRows.length} cliente{filteredRows.length !== 1 ? "s" : ""}
                        </span>
                    </div>

                    {/* Stats Cards */}
                    {rows.length > 0 && (
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-4">
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Total</p>
                                <p className="text-2xl font-bold font-display">{rows.length}</p>
                            </div>
                            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-4">
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Pessoa Física</p>
                                <p className="text-2xl font-bold font-display">{rows.filter((c) => c.person_type === "PF").length}</p>
                            </div>
                            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-4">
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Pessoa Jurídica</p>
                                <p className="text-2xl font-bold font-display">{rows.filter((c) => c.person_type === "PJ").length}</p>
                            </div>
                            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-4">
                                <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">Com telefone</p>
                                <p className="text-2xl font-bold font-display">
                                    {rows.filter((c) => (c.phones || []).length > 0).length}
                                </p>
                            </div>
                        </div>
                    )}

                    {/* Table */}
                    {loading ? (
                        <div className="flex items-center justify-center py-12">
                            <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
                        </div>
                    ) : filteredRows.length === 0 ? (
                        <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-12 text-center">
                            <span className="material-symbols-outlined text-5xl text-text-secondary-light mb-3 block">
                                person_off
                            </span>
                            <p className="text-text-secondary-light dark:text-text-secondary-dark">
                                {search ? "Nenhum cliente encontrado para esta busca." : "Nenhum cliente cadastrado ainda."}
                            </p>
                            {!search && (
                                <button
                                    onClick={openCreate}
                                    className="mt-4 h-10 px-5 rounded-xl bg-primary text-white text-sm font-semibold"
                                >
                                    Cadastrar primeiro cliente
                                </button>
                            )}
                        </div>
                    ) : (
                        <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark overflow-x-auto">
                            <table className="w-full text-sm min-w-[800px]">
                                <thead className="bg-black/5 dark:bg-white/5 text-left">
                                    <tr>
                                        <th className="p-3 font-semibold">Tipo</th>
                                        <th className="p-3 font-semibold">Nome</th>
                                        <th className="p-3 font-semibold">CPF/CNPJ</th>
                                        <th className="p-3 font-semibold">Telefones</th>
                                        <th className="p-3 font-semibold">Cidade/UF</th>
                                        <th className="p-3 font-semibold">Cadastro</th>
                                        <th className="p-3 font-semibold text-right">Ações</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {filteredRows.map((c) => (
                                        <tr
                                            key={c.id}
                                            className="border-t border-border-light dark:border-border-dark hover:bg-slate-50/50 dark:hover:bg-slate-800/30 transition-colors cursor-pointer"
                                            onClick={() => void openDetail(c)}
                                        >
                                            <td className="p-3">
                                                <span
                                                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                                                        c.person_type === "PF"
                                                            ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                                            : "bg-rose-50 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300"
                                                    }`}
                                                >
                                                    <span className="material-symbols-outlined text-sm">
                                                        {c.person_type === "PF" ? "person" : "business"}
                                                    </span>
                                                    {c.person_type}
                                                </span>
                                            </td>
                                            <td className="p-3">
                                                <div className="font-medium">{c.display_name}</div>
                                                {c.contact_name && c.contact_name !== c.display_name && (
                                                    <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                                        {c.contact_name}
                                                    </div>
                                                )}
                                            </td>
                                            <td className="p-3 font-mono text-xs">
                                                {c.person_type === "PF"
                                                    ? c.cpf
                                                        ? maskCpf(c.cpf)
                                                        : "—"
                                                    : c.cnpj
                                                    ? maskCnpj(c.cnpj)
                                                    : "—"}
                                            </td>
                                            <td className="p-3 max-w-[200px] truncate" title={(c.phones || []).join(", ")}>
                                                {(c.phones || []).join(", ") || "—"}
                                            </td>
                                            <td className="p-3">
                                                {[c.city, c.state].filter(Boolean).join("/") || "—"}
                                            </td>
                                            <td className="p-3 text-xs text-text-secondary-light">
                                                {formatDate(c.created_at)}
                                            </td>
                                            <td className="p-3 text-right" onClick={(e) => e.stopPropagation()}>
                                                <div className="flex justify-end gap-2">
                                                    <button
                                                        type="button"
                                                        className="p-1.5 rounded-lg text-primary hover:bg-primary/10 transition-colors"
                                                        title="Editar"
                                                        onClick={() => openEdit(c)}
                                                    >
                                                        <span className="material-symbols-outlined text-lg">edit</span>
                                                    </button>
                                                    <button
                                                        type="button"
                                                        className="p-1.5 rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                                        title="Excluir"
                                                        onClick={() => void handleDelete(c)}
                                                    >
                                                        <span className="material-symbols-outlined text-lg">delete</span>
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}

            {/* === DETAIL TAB === */}
            {tab === "detail" && selectedClient && (
                <div className="space-y-6">
                    {/* Client Header Card */}
                    <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-6">
                        <div className="flex flex-wrap items-start justify-between gap-4">
                            <div className="flex items-center gap-4">
                                <div
                                    className={`h-14 w-14 rounded-2xl flex items-center justify-center text-white font-bold text-lg ${
                                        selectedClient.person_type === "PF"
                                            ? "bg-gradient-to-br from-blue-500 to-blue-600"
                                            : "bg-primary"
                                    }`}
                                >
                                    <span className="material-symbols-outlined text-2xl">
                                        {selectedClient.person_type === "PF" ? "person" : "business"}
                                    </span>
                                </div>
                                <div>
                                    <h2 className="text-xl font-bold font-display">{selectedClient.display_name}</h2>
                                    <div className="flex flex-wrap items-center gap-3 mt-1 text-sm text-text-secondary-light dark:text-text-secondary-dark">
                                        <span
                                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                                                selectedClient.person_type === "PF"
                                                    ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                                                    : "bg-rose-50 dark:bg-rose-900/30 text-rose-700 dark:text-rose-300"
                                            }`}
                                        >
                                            {selectedClient.person_type === "PF" ? "Pessoa Física" : "Pessoa Jurídica"}
                                        </span>
                                        {selectedClient.person_type === "PF" && selectedClient.cpf && (
                                            <span className="font-mono text-xs">CPF: {maskCpf(selectedClient.cpf)}</span>
                                        )}
                                        {selectedClient.person_type === "PJ" && selectedClient.cnpj && (
                                            <span className="font-mono text-xs">CNPJ: {maskCnpj(selectedClient.cnpj)}</span>
                                        )}
                                    </div>
                                </div>
                            </div>
                            <div className="flex gap-2">
                                <button
                                    onClick={() => openEdit(selectedClient)}
                                    className="h-9 px-4 rounded-xl border border-border-light dark:border-border-dark text-sm font-medium flex items-center gap-1.5 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-base">edit</span>
                                    Editar
                                </button>
                                <button
                                    onClick={() => void handleDelete(selectedClient)}
                                    className="h-9 px-4 rounded-xl border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 text-sm font-medium flex items-center gap-1.5 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-base">delete</span>
                                    Excluir
                                </button>
                            </div>
                        </div>

                        {/* Contact & Address Info */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
                            <div className="space-y-3">
                                <h3 className="text-sm font-semibold text-text-secondary-light dark:text-text-secondary-dark uppercase tracking-wider">
                                    Contato
                                </h3>
                                {selectedClient.contact_name && (
                                    <div className="flex items-center gap-2 text-sm">
                                        <span className="material-symbols-outlined text-lg text-text-secondary-light">badge</span>
                                        {selectedClient.contact_name}
                                    </div>
                                )}
                                {(selectedClient.phones || []).length > 0 && (
                                    <div className="flex items-start gap-2 text-sm">
                                        <span className="material-symbols-outlined text-lg text-text-secondary-light mt-0.5">phone</span>
                                        <div className="space-y-0.5">
                                            {selectedClient.phones.map((p, i) => (
                                                <div key={i}>{p}</div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                                {!(selectedClient.phones || []).length && (
                                    <p className="text-sm text-text-secondary-light italic">Sem telefone cadastrado</p>
                                )}
                            </div>
                            <div className="space-y-3">
                                <h3 className="text-sm font-semibold text-text-secondary-light dark:text-text-secondary-dark uppercase tracking-wider">
                                    Endereço
                                </h3>
                                {selectedClient.address_line1 ? (
                                    <div className="flex items-start gap-2 text-sm">
                                        <span className="material-symbols-outlined text-lg text-text-secondary-light mt-0.5">
                                            location_on
                                        </span>
                                        <div>
                                            <div>{selectedClient.address_line1}{selectedClient.address_line2 ? `, ${selectedClient.address_line2}` : ""}</div>
                                            {selectedClient.neighborhood && <div>{selectedClient.neighborhood}</div>}
                                            <div>
                                                {[selectedClient.city, selectedClient.state].filter(Boolean).join(" / ")}
                                                {selectedClient.postal_code ? ` — CEP ${maskCep(selectedClient.postal_code)}` : ""}
                                            </div>
                                            {selectedClient.complement && <div className="text-text-secondary-light">{selectedClient.complement}</div>}
                                            {(selectedClient.no_number || selectedClient.dead_end_street) && (
                                                <div className="flex gap-2 mt-1">
                                                    {selectedClient.no_number && (
                                                        <span className="text-xs bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 px-2 py-0.5 rounded-full">
                                                            Sem número
                                                        </span>
                                                    )}
                                                    {selectedClient.dead_end_street && (
                                                        <span className="text-xs bg-yellow-50 dark:bg-yellow-900/20 text-yellow-700 dark:text-yellow-300 px-2 py-0.5 rounded-full">
                                                            Rua sem saída
                                                        </span>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ) : (
                                    <p className="text-sm text-text-secondary-light italic">Endereço não informado</p>
                                )}
                            </div>
                        </div>
                    </div>

                    {detailLoading ? (
                        <div className="flex items-center justify-center py-8">
                            <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
                        </div>
                    ) : (
                        <>
                            {/* Linked Leads (Business Cards) */}
                            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-6">
                                <h3 className="text-lg font-bold font-display flex items-center gap-2 mb-4">
                                    <span className="material-symbols-outlined text-primary">view_kanban</span>
                                    Negócios vinculados
                                    <span className="text-sm font-normal text-text-secondary-light ml-1">
                                        ({clientLeads.length})
                                    </span>
                                </h3>
                                {clientLeads.length === 0 ? (
                                    <p className="text-sm text-text-secondary-light italic">
                                        Nenhum negócio vinculado a este cliente.
                                    </p>
                                ) : (
                                    <div className="space-y-2">
                                        {clientLeads.map((lead) => (
                                            <div
                                                key={lead.id}
                                                className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-black/[0.02] dark:bg-white/[0.03] border border-border-light/50 dark:border-border-dark/50"
                                            >
                                                <div className="flex items-center gap-3 min-w-0">
                                                    <span className="material-symbols-outlined text-lg text-text-secondary-light">
                                                        credit_card
                                                    </span>
                                                    <div className="min-w-0">
                                                        <div className="font-medium text-sm truncate">
                                                            {lead.company_name}
                                                        </div>
                                                        <div className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                                            {lead.contact_name} · {formatDate(lead.created_at)}
                                                        </div>
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-3 text-sm">
                                                    <span className="inline-flex px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 dark:bg-slate-800 text-text-secondary-light dark:text-text-secondary-dark">
                                                        {lead.stage}
                                                    </span>
                                                    <span className="font-semibold">{formatCurrency(lead.value)}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Purchase History (Orders) */}
                            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-6">
                                <h3 className="text-lg font-bold font-display flex items-center gap-2 mb-4">
                                    <span className="material-symbols-outlined text-primary">receipt_long</span>
                                    Histórico de compras
                                    <span className="text-sm font-normal text-text-secondary-light ml-1">
                                        ({clientOrders.length})
                                    </span>
                                </h3>
                                {clientOrders.length === 0 ? (
                                    <p className="text-sm text-text-secondary-light italic">
                                        Nenhum pedido encontrado para este cliente.
                                    </p>
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="w-full text-sm min-w-[600px]">
                                            <thead className="text-left text-xs text-text-secondary-light uppercase tracking-wider">
                                                <tr>
                                                    <th className="pb-2 pr-3">Data</th>
                                                    <th className="pb-2 pr-3">Resumo</th>
                                                    <th className="pb-2 pr-3">Total</th>
                                                    <th className="pb-2">Status</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {clientOrders.map((order) => (
                                                    <tr
                                                        key={order.id}
                                                        className="border-t border-border-light/50 dark:border-border-dark/50"
                                                    >
                                                        <td className="py-2.5 pr-3 text-xs text-text-secondary-light">
                                                            {formatDate(order.created_at)}
                                                        </td>
                                                        <td className="py-2.5 pr-3 truncate max-w-[250px]" title={order.product_summary}>
                                                            {order.product_summary || "—"}
                                                        </td>
                                                        <td className="py-2.5 pr-3 font-semibold">
                                                            {formatCurrency(order.total)}
                                                        </td>
                                                        <td className="py-2.5">
                                                            <span
                                                                className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${
                                                                    order.payment_status === "paid"
                                                                        ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-300"
                                                                        : order.payment_status === "pending"
                                                                        ? "bg-yellow-50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-300"
                                                                        : "bg-slate-100 dark:bg-slate-800 text-text-secondary-light"
                                                                }`}
                                                            >
                                                                {order.payment_status === "paid"
                                                                    ? "Pago"
                                                                    : order.payment_status === "pending"
                                                                    ? "Pendente"
                                                                    : order.payment_status}
                                                            </span>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}

                                {/* Total summary */}
                                {clientOrders.length > 0 && (
                                    <div className="mt-4 pt-4 border-t border-border-light dark:border-border-dark flex items-center justify-between">
                                        <span className="text-sm text-text-secondary-light">Total em pedidos</span>
                                        <span className="text-lg font-bold font-display">
                                            {formatCurrency(clientOrders.reduce((s, o) => s + (o.total || 0), 0))}
                                        </span>
                                    </div>
                                )}
                            </div>
                        </>
                    )}
                </div>
            )}

            {/* Modal */}
            {modalOpen && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
                    <div className="bg-background-light dark:bg-background-dark border border-border-light dark:border-border-dark rounded-2xl shadow-xl max-w-lg w-full max-h-[90vh] overflow-hidden p-6">
                        <h2 className="text-lg font-bold font-display mb-4">
                            {modalMode === "create" ? "Novo cliente" : "Editar cliente"}
                        </h2>
                        <CrmClientForm
                            key={formKey}
                            mode={modalMode}
                            tenantIdForCreate=""
                            initial={editing}
                            submitting={submitting}
                            serverError={formError}
                            onSubmit={handleFormSubmit}
                            onCancel={closeModal}
                        />
                    </div>
                </div>
            )}
        </div>
    );
}
