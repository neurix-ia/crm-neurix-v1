"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
    api,
    listProducts,
    listLeads,
    createLead,
} from "@/lib/api";

interface Lead {
    id: string;
    contact_name: string;
    company_name: string;
    phone: string;
}

interface Product {
    id: string;
    name: string;
    price: number;
}

interface CatalogItem {
    id: string;
    type: "product" | "promotion" | "category";
    label: string;
    subtitle: string;
    category_id?: string;
    product_id?: string;
    promotion_id?: string;
    price?: number;
    discount_type?: "percent" | "fixed";
    discount_value?: number;
    is_active: boolean;
}

interface SelectedProduct {
    id: string;
    name: string;
    price: number;
    qty: number;
}

interface NewOrderModalProps {
    onClose: () => void;
    onCreated?: () => void;
}

export default function NewOrderModal({ onClose, onCreated }: NewOrderModalProps) {
    const [clientQuery, setClientQuery] = useState("");
    const [clientResults, setClientResults] = useState<Lead[]>([]);
    const [clientLoading, setClientLoading] = useState(false);
    const [selectedClient, setSelectedClient] = useState<Lead | null>(null);
    const [showClientDropdown, setShowClientDropdown] = useState(false);
    const [showNewClientForm, setShowNewClientForm] = useState(false);
    const [newClientName, setNewClientName] = useState("");
    const [newClientCompany, setNewClientCompany] = useState("");
    const [newClientPhone, setNewClientPhone] = useState("");
    const [creatingClient, setCreatingClient] = useState(false);
    const clientTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const [availableProducts, setAvailableProducts] = useState<Product[]>([]);
    const [selectedProducts, setSelectedProducts] = useState<SelectedProduct[]>([]);
    const [showProductDropdown, setShowProductDropdown] = useState(false);
    const [productsLoading, setProductsLoading] = useState(false);
    const [catalogQuery, setCatalogQuery] = useState("");
    const [catalogResults, setCatalogResults] = useState<CatalogItem[]>([]);
    const [catalogLoading, setCatalogLoading] = useState(false);
    const [selectedCatalogHints, setSelectedCatalogHints] = useState<CatalogItem[]>([]);
    const catalogTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const [notes, setNotes] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        loadProducts();
    }, []);

    useEffect(() => {
        return () => {
            if (clientTimerRef.current) clearTimeout(clientTimerRef.current);
            if (catalogTimerRef.current) clearTimeout(catalogTimerRef.current);
        };
    }, []);

    async function loadProducts() {
        setProductsLoading(true);
        try {
            const token = localStorage.getItem("access_token") || undefined;
            const rows = await listProducts({ active_only: true }, token);
            setAvailableProducts(
                rows.map((r) => ({
                    id: r.id,
                    name: r.name,
                    price: Number(r.price) || 0,
                }))
            );
        } catch (err) {
            console.error("Error loading products:", err);
        } finally {
            setProductsLoading(false);
        }
    }

    const searchCatalog = useCallback(async (query: string) => {
        if (query.trim().length < 2) {
            setCatalogResults([]);
            setCatalogLoading(false);
            return;
        }
        setCatalogLoading(true);
        try {
            const token = localStorage.getItem("access_token") || undefined;
            const data = await api<{ items: CatalogItem[] }>(
                `/api/catalog/search?q=${encodeURIComponent(query.trim())}&types=product,promotion,category&limit=20&offset=0`,
                { method: "GET", token }
            );
            setCatalogResults(data.items || []);
        } catch (err) {
            console.error("Catalog search error:", err);
            setCatalogResults([]);
        } finally {
            setCatalogLoading(false);
        }
    }, []);

    const handleCatalogQueryChange = (value: string) => {
        setCatalogQuery(value);
        if (catalogTimerRef.current) clearTimeout(catalogTimerRef.current);
        catalogTimerRef.current = setTimeout(() => searchCatalog(value), 250);
    };

    const handleSelectCatalogItem = (item: CatalogItem) => {
        if (item.type === "product") {
            const productId = item.product_id || item.id;
            const available = availableProducts.find((p) => p.id === productId);
            const prod = available || { id: productId, name: item.label, price: item.price || 0 };
            handleAddProduct(prod);
        } else {
            if (!selectedCatalogHints.some((h) => h.id === item.id && h.type === item.type)) {
                setSelectedCatalogHints((prev) => [...prev, item]);
            }
        }
        setCatalogQuery("");
        setCatalogResults([]);
    };

    const searchClients = useCallback(async (query: string) => {
        if (query.trim().length < 2) {
            setClientResults([]);
            setClientLoading(false);
            return;
        }
        setClientLoading(true);
        try {
            const token = localStorage.getItem("access_token") || undefined;
            const data = await listLeads({ search: query.trim() }, token);
            setClientResults(
                (data || []).slice(0, 5).map((row) => ({
                    id: row.id,
                    contact_name: row.contact_name,
                    company_name: row.company_name || "",
                    phone: row.phone || "",
                }))
            );
        } catch (err) {
            console.error("Client search error:", err);
            setClientResults([]);
        } finally {
            setClientLoading(false);
        }
    }, []);

    const handleClientQueryChange = (value: string) => {
        setClientQuery(value);
        setShowClientDropdown(value.length > 0);
        setSelectedClient(null);
        if (clientTimerRef.current) clearTimeout(clientTimerRef.current);
        clientTimerRef.current = setTimeout(() => searchClients(value), 300);
    };

    const handleSelectClient = (lead: Lead) => {
        setSelectedClient(lead);
        setClientQuery(lead.contact_name);
        setShowClientDropdown(false);
        setShowNewClientForm(false);
    };

    const handleCreateClient = async () => {
        if (!newClientName.trim()) return;
        setCreatingClient(true);
        setError("");
        try {
            const token = localStorage.getItem("access_token") || undefined;
            const data = await createLead(
                {
                    company_name: newClientCompany.trim() || "—",
                    contact_name: newClientName.trim(),
                    phone: newClientPhone.trim() || null,
                    priority: "media",
                    value: 0,
                },
                token
            );
            setSelectedClient({
                id: data.id,
                contact_name: data.contact_name,
                company_name: data.company_name || "",
                phone: data.phone || "",
            });
            setClientQuery(data.contact_name);
            setShowNewClientForm(false);
            setNewClientName("");
            setNewClientCompany("");
            setNewClientPhone("");
        } catch (err) {
            console.error("Create client error:", err);
            setError(
                "Erro ao criar cliente: " + (err instanceof Error ? err.message : "erro desconhecido")
            );
        } finally {
            setCreatingClient(false);
        }
    };

    const handleAddProduct = (product: Product) => {
        const existing = selectedProducts.find((p) => p.id === product.id);
        if (existing) {
            setSelectedProducts((prev) =>
                prev.map((p) => (p.id === product.id ? { ...p, qty: p.qty + 1 } : p))
            );
        } else {
            setSelectedProducts((prev) => [...prev, { ...product, qty: 1 }]);
        }
        setShowProductDropdown(false);
    };

    const handleRemoveProduct = (productId: string) => {
        setSelectedProducts((prev) => prev.filter((p) => p.id !== productId));
    };

    const handleProductQtyChange = (productId: string, qty: number) => {
        if (qty < 1) return;
        setSelectedProducts((prev) => prev.map((p) => (p.id === productId ? { ...p, qty } : p)));
    };

    const total = selectedProducts.reduce((sum, p) => sum + p.price * p.qty, 0);
    const fmt = (v: number) =>
        new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);

    const handleCreateOrder = async () => {
        setError("");
        if (!selectedClient) {
            setError("Selecione ou crie um cliente");
            return;
        }
        if (selectedProducts.length === 0) {
            setError("Adicione pelo menos um produto");
            return;
        }
        setSubmitting(true);
        try {
            const productsJson = selectedProducts.map((p) => ({
                id: p.id,
                name: p.name,
                price: p.price,
                qty: p.qty,
            }));
            const productSummary = selectedProducts.map((p) => `${p.name} (x${p.qty})`).join(", ");
            const hintNotes = selectedCatalogHints.length
                ? selectedCatalogHints.map((h) => `${h.type}: ${h.label}`).join(" | ")
                : "";
            const composedNotes = [notes.trim(), hintNotes].filter(Boolean).join("\n");
            const token = localStorage.getItem("access_token") || undefined;
            await api("/api/orders/", {
                method: "POST",
                token,
                body: JSON.stringify({
                    lead_id: selectedClient.id,
                    client_name: selectedClient.contact_name,
                    client_company: selectedClient.company_name || null,
                    products_json: productsJson,
                    product_summary: productSummary,
                    total,
                    stage: "Novo Pedido Manual",
                    payment_status: "pendente",
                    notes: composedNotes || null,
                }),
            });
            onCreated?.();
            onClose();
        } catch (err) {
            console.error("Create order error:", err);
            setError(`Erro ao criar pedido: ${err instanceof Error ? err.message : "erro desconhecido"}`);
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-slate-900/30 dark:bg-slate-900/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-lg max-h-[90vh] overflow-y-auto">
                <div className="p-6 border-b border-border-light dark:border-border-dark flex items-center justify-between">
                    <h3 className="text-lg font-bold font-display">Novo Pedido</h3>
                    <button onClick={onClose} className="text-text-secondary-light hover:text-text-main-light transition-colors">
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>

                <div className="p-6 space-y-5">
                    {error && (
                        <div className="bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm px-4 py-3 rounded-xl border border-red-200 dark:border-red-800">
                            {error}
                        </div>
                    )}

                    <div>
                        <label className="block text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1.5">
                            Cliente
                        </label>

                        {selectedClient ? (
                            <div className="flex items-center justify-between p-3 bg-blue-50 dark:bg-blue-900/20 rounded-xl border border-blue-200 dark:border-blue-800">
                                <div className="flex items-center gap-2">
                                    <span className="material-symbols-outlined text-blue-500 text-base">person</span>
                                    <div>
                                        <p className="text-sm font-medium">{selectedClient.contact_name}</p>
                                        {selectedClient.company_name && (
                                            <p className="text-xs text-text-secondary-light">{selectedClient.company_name}</p>
                                        )}
                                    </div>
                                </div>
                                <button
                                    onClick={() => {
                                        setSelectedClient(null);
                                        setClientQuery("");
                                    }}
                                    className="text-text-secondary-light hover:text-red-500 transition-colors"
                                >
                                    <span className="material-symbols-outlined text-base">close</span>
                                </button>
                            </div>
                        ) : !showNewClientForm ? (
                            <div className="relative">
                                <input
                                    value={clientQuery}
                                    onChange={(e) => handleClientQueryChange(e.target.value)}
                                    onFocus={() => clientQuery.length > 0 && setShowClientDropdown(true)}
                                    onBlur={() => setTimeout(() => setShowClientDropdown(false), 200)}
                                    className="w-full px-4 py-2.5 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-xl text-sm focus:ring-2 focus:ring-primary focus:border-transparent pl-10"
                                    placeholder="Buscar cliente existente..."
                                    type="text"
                                />
                                <span className="material-symbols-outlined absolute left-3 top-2.5 text-text-secondary-light text-lg">
                                    search
                                </span>

                                {showClientDropdown && (
                                    <div className="absolute top-full left-0 right-0 mt-1 bg-surface-light dark:bg-surface-dark rounded-xl shadow-2xl border border-border-light dark:border-border-dark z-50 overflow-hidden">
                                        <div className="p-2">
                                            {clientLoading && (
                                                <p className="px-3 py-2 text-xs text-text-secondary-light text-center">
                                                    Buscando...
                                                </p>
                                            )}
                                            {!clientLoading && clientResults.length === 0 && clientQuery.length >= 2 && (
                                                <p className="px-3 py-2 text-xs text-text-secondary-light text-center">
                                                    Nenhum cliente encontrado
                                                </p>
                                            )}
                                            {!clientLoading && clientQuery.length < 2 && (
                                                <p className="px-3 py-2 text-xs text-text-secondary-light text-center">
                                                    Digite ao menos 2 caracteres...
                                                </p>
                                            )}
                                            {clientResults.map((lead) => (
                                                <button
                                                    key={lead.id}
                                                    onMouseDown={() => handleSelectClient(lead)}
                                                    className="w-full px-3 py-2 text-sm text-left hover:bg-primary/5 rounded-lg flex items-center gap-2"
                                                >
                                                    <span className="material-symbols-outlined text-base text-blue-500">
                                                        person
                                                    </span>
                                                    <div>
                                                        <p>{lead.contact_name}</p>
                                                        {lead.company_name && (
                                                            <p className="text-xs text-text-secondary-light">{lead.company_name}</p>
                                                        )}
                                                    </div>
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <button
                                    onClick={() => {
                                        setShowNewClientForm(true);
                                        setShowClientDropdown(false);
                                    }}
                                    className="mt-2 text-xs text-primary hover:underline flex items-center gap-1"
                                >
                                    <span className="material-symbols-outlined text-sm">add</span>
                                    Criar novo cliente
                                </button>
                            </div>
                        ) : (
                            <div className="space-y-3 p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-border-light dark:border-border-dark">
                                <div className="flex items-center justify-between mb-1">
                                    <p className="text-xs font-semibold text-primary uppercase tracking-wider">Novo Cliente</p>
                                    <button
                                        onClick={() => setShowNewClientForm(false)}
                                        className="text-xs text-text-secondary-light hover:text-text-main-light"
                                    >
                                        Cancelar
                                    </button>
                                </div>
                                <input
                                    value={newClientName}
                                    onChange={(e) => setNewClientName(e.target.value)}
                                    className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm"
                                    placeholder="Nome do cliente *"
                                />
                                <input
                                    value={newClientCompany}
                                    onChange={(e) => setNewClientCompany(e.target.value)}
                                    className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm"
                                    placeholder="Empresa (opcional)"
                                />
                                <input
                                    value={newClientPhone}
                                    onChange={(e) => setNewClientPhone(e.target.value)}
                                    className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm"
                                    placeholder="Telefone (opcional)"
                                />
                                <button
                                    onClick={handleCreateClient}
                                    disabled={!newClientName.trim() || creatingClient}
                                    className="w-full px-3 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-primary-hover disabled:opacity-50 transition-colors"
                                >
                                    {creatingClient ? "Criando..." : "Salvar Cliente"}
                                </button>
                            </div>
                        )}
                    </div>

                    <div>
                        <label className="block text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1.5">
                            Produtos
                        </label>
                        <div className="mb-2">
                            <input
                                value={catalogQuery}
                                onChange={(e) => handleCatalogQueryChange(e.target.value)}
                                className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-lg text-sm"
                                placeholder="Buscar produto, promoção ou categoria..."
                            />
                            {(catalogLoading || catalogResults.length > 0) && (
                                <div className="mt-1 border border-border-light dark:border-border-dark rounded-lg bg-surface-light dark:bg-surface-dark max-h-40 overflow-y-auto">
                                    {catalogLoading && (
                                        <p className="px-3 py-2 text-xs text-text-secondary-light">Buscando...</p>
                                    )}
                                    {!catalogLoading &&
                                        catalogResults.map((item) => (
                                            <button
                                                key={`${item.type}-${item.id}`}
                                                type="button"
                                                onClick={() => handleSelectCatalogItem(item)}
                                                className="w-full text-left px-3 py-2 text-sm hover:bg-primary/5 flex items-center justify-between"
                                            >
                                                <span>{item.label}</span>
                                                <span className="text-[10px] uppercase text-text-secondary-light">
                                                    {item.type}
                                                </span>
                                            </button>
                                        ))}
                                </div>
                            )}
                            {selectedCatalogHints.length > 0 && (
                                <div className="mt-2 flex flex-wrap gap-1">
                                    {selectedCatalogHints.map((hint) => (
                                        <span
                                            key={`${hint.type}-${hint.id}`}
                                            className="text-[10px] px-2 py-1 rounded bg-blue-50 text-blue-700 border border-blue-200"
                                        >
                                            {hint.type}: {hint.label}
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                        <div className="border border-border-light dark:border-border-dark rounded-xl overflow-hidden">
                            {selectedProducts.length === 0 ? (
                                <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50">
                                    <span className="text-sm text-text-secondary-light">Nenhum produto adicionado</span>
                                    <div className="relative">
                                        <button
                                            onClick={() => setShowProductDropdown(!showProductDropdown)}
                                            className="text-primary text-sm font-medium hover:underline flex items-center gap-1"
                                        >
                                            <span className="material-symbols-outlined text-sm">add</span>
                                            Adicionar
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <div>
                                    {selectedProducts.map((p) => (
                                        <div
                                            key={p.id}
                                            className="flex items-center justify-between p-3 border-b border-border-light dark:border-border-dark last:border-b-0"
                                        >
                                            <div className="flex-1 min-w-0">
                                                <p className="text-sm font-medium truncate">{p.name}</p>
                                                <p className="text-xs text-text-secondary-light">{fmt(p.price)} /un</p>
                                            </div>
                                            <div className="flex items-center gap-2 ml-3">
                                                <button
                                                    onClick={() => handleProductQtyChange(p.id, p.qty - 1)}
                                                    className="w-6 h-6 flex items-center justify-center rounded bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 text-xs font-bold"
                                                >
                                                    −
                                                </button>
                                                <span className="text-sm font-medium w-6 text-center">{p.qty}</span>
                                                <button
                                                    onClick={() => handleProductQtyChange(p.id, p.qty + 1)}
                                                    className="w-6 h-6 flex items-center justify-center rounded bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 text-xs font-bold"
                                                >
                                                    +
                                                </button>
                                                <span className="text-sm font-medium w-20 text-right">{fmt(p.price * p.qty)}</span>
                                                <button
                                                    onClick={() => handleRemoveProduct(p.id)}
                                                    className="text-red-400 hover:text-red-600 ml-1"
                                                >
                                                    <span className="material-symbols-outlined text-base">delete</span>
                                                </button>
                                            </div>
                                        </div>
                                    ))}
                                    <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50">
                                        <div className="relative">
                                            <button
                                                onClick={() => setShowProductDropdown(!showProductDropdown)}
                                                className="text-primary text-sm font-medium hover:underline flex items-center gap-1"
                                            >
                                                <span className="material-symbols-outlined text-sm">add</span>
                                                Adicionar mais
                                            </button>
                                        </div>
                                        <div className="text-right">
                                            <p className="text-xs text-text-secondary-light uppercase">Total</p>
                                            <p className="text-lg font-bold text-green-600">{fmt(total)}</p>
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>

                        {showProductDropdown && (
                            <div className="mt-1 bg-surface-light dark:bg-surface-dark rounded-xl shadow-2xl border border-border-light dark:border-border-dark z-50 overflow-hidden max-h-48 overflow-y-auto">
                                <div className="p-2">
                                    {productsLoading && (
                                        <p className="px-3 py-2 text-xs text-text-secondary-light text-center">Carregando...</p>
                                    )}
                                    {!productsLoading && availableProducts.length === 0 && (
                                        <p className="px-3 py-2 text-xs text-text-secondary-light text-center">
                                            Nenhum produto cadastrado
                                        </p>
                                    )}
                                    {availableProducts.map((product) => (
                                        <button
                                            key={product.id}
                                            onClick={() => handleAddProduct(product)}
                                            className="w-full px-3 py-2 text-sm text-left hover:bg-primary/5 rounded-lg flex items-center justify-between"
                                        >
                                            <div className="flex items-center gap-2">
                                                <span className="material-symbols-outlined text-base text-primary">
                                                    inventory_2
                                                </span>
                                                {product.name}
                                            </div>
                                            <span className="text-xs text-text-secondary-light">{fmt(product.price)}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>

                    <div>
                        <label className="block text-xs font-semibold text-text-secondary-light uppercase tracking-wider mb-1.5">
                            Observações
                        </label>
                        <textarea
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            className="w-full px-4 py-2.5 bg-white dark:bg-slate-800 border border-border-light dark:border-border-dark rounded-xl text-sm focus:ring-2 focus:ring-primary focus:border-transparent resize-none"
                            placeholder="Notas sobre o pedido..."
                            rows={3}
                        />
                    </div>
                </div>

                <div className="p-6 border-t border-border-light dark:border-border-dark flex gap-3">
                    <button
                        onClick={onClose}
                        className="flex-1 px-4 py-2.5 border border-border-light dark:border-border-dark rounded-xl text-sm font-medium hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                    >
                        Cancelar
                    </button>
                    <button
                        onClick={handleCreateOrder}
                        disabled={submitting || !selectedClient || selectedProducts.length === 0}
                        className="flex-1 px-4 py-2.5 bg-primary text-white rounded-xl text-sm font-medium hover:bg-primary-hover shadow-lg shadow-primary/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {submitting ? "Criando..." : `Criar Pedido${total > 0 ? ` • ${fmt(total)}` : ""}`}
                    </button>
                </div>
            </div>
        </div>
    );
}
