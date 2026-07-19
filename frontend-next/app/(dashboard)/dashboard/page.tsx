"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { setSupabaseSession } from "@/lib/supabase";
import {
    listOrders,
    archiveOrder,
    deleteOrder,
    globalSearch,
    getLeadById,
    getOrder,
    getProduct,
    getAuthMe,
    getDashboardKpis,
    type DashboardKpisDTO,
} from "@/lib/api";
import { tenantNeedsOrganization } from "@/lib/org-context";
import NewOrderModal from "@/components/NewOrderModal";
import WhatsAppChat from "@/components/WhatsAppChat";

// Types for search and detail cards
interface SearchResult {
    id: string;
    name: string;
    type: "lead" | "order" | "product";
}

interface LeadDetail {
    id: string;
    contact_name: string;
    company_name: string;
    phone: string;
    stage: string;
    priority: string;
    value: number;
    notes: string;
    delivery_address: string;
    created_at: string;
}

interface OrderDetail {
    id: string;
    client_name: string;
    client_company: string;
    product_summary: string;
    total: number;
    payment_status: string;
    stage: string;
    notes: string;
    subtotal?: number;
    discount_total?: number;
    applied_promotions_json?: Array<{
        product_name?: string;
        promotion_name?: string;
        line_discount?: number;
    }>;
    created_at: string;
    lead_id?: string;
    tenant_id?: string;
}

interface ProductDetail {
    id: string;
    name: string;
    description: string;
    price: number;
    weight_grams: number;
    category: string;
    status: string;
    is_active: boolean;
    image_url: string;
    created_at: string;
}

// Detail Card Components
function LeadCard({ lead, onClose }: { lead: LeadDetail; onClose: () => void }) {
    const fmt = (v: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-slate-900/30 dark:bg-slate-900/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md max-h-[85vh] overflow-y-auto">
                <div className="p-6 border-b border-border-light dark:border-border-dark flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg">
                            <span className="material-symbols-outlined text-blue-600 dark:text-blue-400">person</span>
                        </div>
                        <div>
                            <h3 className="text-lg font-bold font-display">{lead.contact_name}</h3>
                            {lead.company_name && <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">{lead.company_name}</p>}
                        </div>
                    </div>
                    <button onClick={onClose} className="text-text-secondary-light hover:text-text-main-light transition-colors">
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>
                <div className="p-6 space-y-4">
                    {lead.stage && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Etapa:</span>
                            <span className="bg-primary-light dark:bg-primary/20 text-primary text-xs font-medium px-2 py-0.5 rounded-full">{lead.stage}</span>
                        </div>
                    )}
                    {lead.priority && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Prioridade:</span>
                            <span className="text-sm">{lead.priority}</span>
                        </div>
                    )}
                    {lead.value > 0 && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Valor:</span>
                            <span className="text-sm font-bold text-green-600">{fmt(lead.value)}</span>
                        </div>
                    )}
                    {lead.phone && (
                        <div className="flex items-center gap-2">
                            <span className="material-symbols-outlined text-text-secondary-light text-base">phone</span>
                            <span className="text-sm">{lead.phone}</span>
                        </div>
                    )}
                    {lead.delivery_address && (
                        <div className="flex items-center gap-2">
                            <span className="material-symbols-outlined text-text-secondary-light text-base">location_on</span>
                            <span className="text-sm">{lead.delivery_address}</span>
                        </div>
                    )}
                    {lead.notes && (
                        <div>
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Notas:</span>
                            <p className="text-sm mt-1 text-text-secondary-light dark:text-text-secondary-dark">{lead.notes}</p>
                        </div>
                    )}
                    <div className="text-xs text-text-secondary-light pt-2 border-t border-border-light dark:border-border-dark">
                        Criado em: {new Date(lead.created_at).toLocaleDateString("pt-BR")}
                    </div>
                </div>
            </div>
        </div>
    );
}

function OrderCard({ order, onClose }: { order: OrderDetail; onClose: () => void }) {
    const fmt = (v: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);
    const statusColors: Record<string, string> = {
        pago: "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400",
        pendente: "bg-yellow-100 dark:bg-yellow-500/20 text-yellow-700 dark:text-yellow-400",
        cancelado: "bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400",
    };
    const statusClass = statusColors[(order.payment_status || "").toLowerCase()] || "bg-slate-100 text-slate-600";

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-slate-900/30 dark:bg-slate-900/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md max-h-[85vh] overflow-y-auto">
                <div className="p-6 border-b border-border-light dark:border-border-dark flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-orange-100 dark:bg-orange-900/30 rounded-lg">
                            <span className="material-symbols-outlined text-orange-600 dark:text-orange-400">receipt_long</span>
                        </div>
                        <div>
                            <h3 className="text-lg font-bold font-display">{order.client_name}</h3>
                            {order.client_company && <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">{order.client_company}</p>}
                        </div>
                    </div>
                    <button onClick={onClose} className="text-text-secondary-light hover:text-text-main-light transition-colors">
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>
                <div className="p-6 space-y-4">
                    {order.product_summary && (
                        <div>
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Produtos:</span>
                            <p className="text-sm mt-1">{order.product_summary}</p>
                        </div>
                    )}
                    <div className="flex items-center justify-between">
                        <div>
                            {typeof order.subtotal === "number" && (
                                <p className="text-xs text-text-secondary-light">Subtotal: {fmt(order.subtotal)}</p>
                            )}
                            {typeof order.discount_total === "number" && order.discount_total > 0 && (
                                <p className="text-xs text-emerald-600">Desconto: -{fmt(order.discount_total)}</p>
                            )}
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Total:</span>
                            <p className="text-xl font-bold text-green-600 mt-0.5">{fmt(order.total || 0)}</p>
                        </div>
                        <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${statusClass}`}>
                            {order.payment_status || "—"}
                        </span>
                    </div>
                    {order.stage && (
                        <div className="flex items-center gap-2">
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Etapa:</span>
                            <span className="bg-primary-light dark:bg-primary/20 text-primary text-xs font-medium px-2 py-0.5 rounded-full">{order.stage}</span>
                        </div>
                    )}
                    {order.notes && (
                        <div>
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Notas:</span>
                            <p className="text-sm mt-1 text-text-secondary-light dark:text-text-secondary-dark">{order.notes}</p>
                        </div>
                    )}
                    {(order.applied_promotions_json || []).length > 0 && (
                        <div>
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Promoções aplicadas:</span>
                            <div className="mt-1 space-y-1">
                                {order.applied_promotions_json!.map((promo, idx) => (
                                    <p key={idx} className="text-xs text-text-secondary-light dark:text-text-secondary-dark">
                                        {(promo.product_name || "Item")} - {(promo.promotion_name || "Promoção")} ({fmt(Number(promo.line_discount || 0))})
                                    </p>
                                ))}
                            </div>
                        </div>
                    )}
                    <div className="text-xs text-text-secondary-light pt-2 border-t border-border-light dark:border-border-dark">
                        Criado em: {new Date(order.created_at).toLocaleDateString("pt-BR")}
                    </div>
                </div>
            </div>
        </div>
    );
}

function ProductCard({ product, onClose }: { product: ProductDetail; onClose: () => void }) {
    const fmt = (v: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-slate-900/30 dark:bg-slate-900/60 backdrop-blur-sm" onClick={onClose} />
            <div className="relative bg-surface-light dark:bg-surface-dark rounded-2xl shadow-2xl border border-border-light dark:border-border-dark w-full max-w-md max-h-[85vh] overflow-y-auto">
                <div className="p-6 border-b border-border-light dark:border-border-dark flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-primary-light dark:bg-primary/20 rounded-lg">
                            <span className="material-symbols-outlined text-primary">inventory_2</span>
                        </div>
                        <div>
                            <h3 className="text-lg font-bold font-display">{product.name}</h3>
                            {product.category && <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark">{product.category}</p>}
                        </div>
                    </div>
                    <button onClick={onClose} className="text-text-secondary-light hover:text-text-main-light transition-colors">
                        <span className="material-symbols-outlined">close</span>
                    </button>
                </div>
                <div className="p-6 space-y-4">
                    {product.image_url && (
                        <div className="rounded-xl overflow-hidden border border-border-light dark:border-border-dark">
                            <img src={product.image_url} alt={product.name} className="w-full h-48 object-cover" />
                        </div>
                    )}
                    {product.description && (
                        <p className="text-sm text-text-secondary-light dark:text-text-secondary-dark">{product.description}</p>
                    )}
                    <div className="flex items-center justify-between">
                        <div>
                            <span className="text-xs font-semibold text-text-secondary-light uppercase">Preço:</span>
                            <p className="text-xl font-bold text-green-600 mt-0.5">{fmt(product.price || 0)}</p>
                        </div>
                        {product.weight_grams > 0 && (
                            <div className="text-right">
                                <span className="text-xs font-semibold text-text-secondary-light uppercase">Peso:</span>
                                <p className="text-sm font-medium mt-0.5">{product.weight_grams}g</p>
                            </div>
                        )}
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-text-secondary-light uppercase">Status:</span>
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${product.is_active ? "bg-green-100 dark:bg-green-500/20 text-green-700 dark:text-green-400" : "bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-400"}`}>
                            {product.is_active ? "Ativo" : "Inativo"}
                        </span>
                    </div>
                    <div className="text-xs text-text-secondary-light pt-2 border-t border-border-light dark:border-border-dark">
                        Criado em: {new Date(product.created_at).toLocaleDateString("pt-BR")}
                    </div>
                </div>
            </div>
        </div>
    );
}

export default function DashboardPage() {
    const router = useRouter();
    const [showNewOrder, setShowNewOrder] = useState(false);
    const [searchQuery, setSearchQuery] = useState("");
    const [showSearch, setShowSearch] = useState(false);
    const [openMenu, setOpenMenu] = useState<number | null>(null);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState<number | null>(null);
    const [chatConfig, setChatConfig] = useState<{ leadId: string; leadName: string } | null>(null);
    const menuRef = useRef<HTMLDivElement>(null);

    // Search state
    const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Detail card state
    const [selectedLead, setSelectedLead] = useState<LeadDetail | null>(null);
    const [selectedOrder, setSelectedOrder] = useState<OrderDetail | null>(null);
    const [selectedProduct, setSelectedProduct] = useState<ProductDetail | null>(null);

    // Set Supabase auth session on mount
    const [recentOrders, setRecentOrders] = useState<OrderDetail[]>([]);
    const [ordersLoading, setOrdersLoading] = useState(true);
    const [showOrgHint, setShowOrgHint] = useState(false);
    const [kpis, setKpis] = useState<DashboardKpisDTO | null>(null);
    const [kpisLoading, setKpisLoading] = useState(true);

    useEffect(() => {
        setSupabaseSession();
        loadRecentOrders();
        loadKpis();
    }, []);

    useEffect(() => {
        const token = localStorage.getItem("access_token");
        if (!token) return;
        getAuthMe(token)
            .then((me) => setShowOrgHint(tenantNeedsOrganization(me)))
            .catch(() => setShowOrgHint(false));
    }, []);

    async function loadRecentOrders() {
        setOrdersLoading(true);
        try {
            const token = localStorage.getItem("access_token") || undefined;
            if (!token) return;
            const data = await listOrders(5, token);
            setRecentOrders(data as OrderDetail[]);
        } catch (err) {
            console.error("Error loading orders:", err);
        } finally {
            setOrdersLoading(false);
        }
    }

    async function loadKpis() {
        setKpisLoading(true);
        try {
            const token = localStorage.getItem("access_token") || undefined;
            if (!token) return;
            const data = await getDashboardKpis(token);
            setKpis(data);
        } catch (err) {
            console.error("Error loading KPIs:", err);
            setKpis(null);
        } finally {
            setKpisLoading(false);
        }
    }

    const handleArchiveOrder = async (order: OrderDetail) => {
        try {
            const token = localStorage.getItem("access_token") || undefined;
            await archiveOrder(order.id, token);
            setOpenMenu(null);
            loadRecentOrders();
        } catch (err) {
            console.error("Archive error:", err);
            alert(
                "Erro ao arquivar pedido: " +
                    (err instanceof Error ? err.message : "verifique se a migração orders_archived foi aplicada no Supabase.")
            );
        }
    };

    const handleDeleteOrder = async (order: OrderDetail) => {
        try {
            const token = localStorage.getItem("access_token") || undefined;
            await deleteOrder(order.id, token);
            setRecentOrders((prev) => prev.filter((o) => o.id !== order.id));
            setShowDeleteConfirm(null);
            loadRecentOrders();
        } catch (err) {
            console.error("Delete error:", err);
            alert("Erro ao excluir pedido: " + (err instanceof Error ? err.message : ""));
        }
    };

    const handleOpenChat = async (order: OrderDetail) => {
        if (!order.lead_id) {
            alert("Este pedido não possui um Lead associado.");
            return;
        }
        setChatConfig({ leadId: order.lead_id, leadName: order.client_name });
    };

    useEffect(() => {
        function handleClick(e: MouseEvent) {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
                setOpenMenu(null);
            }
        }
        document.addEventListener("mousedown", handleClick);
        return () => document.removeEventListener("mousedown", handleClick);
    }, []);

    // Debounced search function
    const performSearch = useCallback(async (query: string) => {
        if (query.trim().length < 2) {
            setSearchResults([]);
            setSearchLoading(false);
            return;
        }

        setSearchLoading(true);
        try {
            const token = localStorage.getItem("access_token") || undefined;
            const res = await globalSearch(query.trim(), token);
            setSearchResults((res.results || []) as SearchResult[]);
        } catch (err) {
            console.error("Search error:", err);
            setSearchResults([]);
        } finally {
            setSearchLoading(false);
        }
    }, []);

    // Handle search input change with debounce
    const handleSearchChange = (value: string) => {
        setSearchQuery(value);
        setShowSearch(value.length > 0);

        if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
        searchTimerRef.current = setTimeout(() => performSearch(value), 300);
    };

    // Handle clicking a search result — fetch detail and open card
    const handleSelectResult = async (result: SearchResult) => {
        setShowSearch(false);
        setSearchQuery("");

        try {
            const token = localStorage.getItem("access_token") || undefined;
            if (result.type === "lead") {
                const data = await getLeadById(result.id, token);
                setSelectedLead({
                    id: data.id,
                    contact_name: data.contact_name,
                    company_name: data.company_name,
                    phone: data.phone || "",
                    stage: data.stage,
                    priority: data.priority || "",
                    value: Number(data.value) || 0,
                    notes: data.notes || "",
                    delivery_address: data.delivery_address || "",
                    created_at: data.created_at,
                });
            } else if (result.type === "order") {
                const data = await getOrder(result.id, token);
                setSelectedOrder({
                    id: data.id,
                    client_name: data.client_name,
                    client_company: data.client_company || "",
                    product_summary: data.product_summary,
                    total: data.total,
                    payment_status: data.payment_status,
                    stage: data.stage || "",
                    notes: data.notes || "",
                    subtotal: data.subtotal,
                    discount_total: data.discount_total,
                    applied_promotions_json: (data.applied_promotions_json || []) as OrderDetail["applied_promotions_json"],
                    created_at: data.created_at,
                    lead_id: data.lead_id || undefined,
                    tenant_id: data.tenant_id,
                });
            } else if (result.type === "product") {
                const data = await getProduct(result.id, token);
                setSelectedProduct({
                    id: data.id,
                    name: data.name,
                    description: data.description || "",
                    price: data.price,
                    weight_grams: typeof data.weight_grams === "number" ? data.weight_grams : 0,
                    category: data.category || "",
                    status: data.status || "",
                    is_active: data.is_active,
                    image_url: data.image_url || "",
                    created_at: data.created_at,
                });
            }
        } catch (err) {
            console.error("Error fetching detail:", err);
        }
    };

    // Group search results by type
    const leadResults = searchResults.filter(r => r.type === "lead");
    const orderResults = searchResults.filter(r => r.type === "order");
    const productResults = searchResults.filter(r => r.type === "product");

    const fmtPctChange = (v: number) => {
        if (v > 0) return { text: `+${v.toFixed(1)}%`, up: true as const };
        if (v < 0) return { text: `${v.toFixed(1)}%`, up: false as const };
        return { text: "0.0%", up: false as const };
    };

    const fmt = (v: number) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v);

    const nc = kpis?.new_contacts ?? kpis?.message_volume ?? 0;
    const conv = kpis?.conversion_rate ?? 0;
    const rev = kpis?.monthly_revenue ?? 0;
    const convCh = fmtPctChange(kpis?.conversion_change ?? 0);
    const revCh = fmtPctChange(kpis?.revenue_change ?? 0);
    const ncCh = fmtPctChange(kpis?.new_contacts_change ?? kpis?.message_change ?? 0);

    const stats = [
        {
            icon: "insights",
            label: "Taxa de Conversão",
            value: kpisLoading ? "…" : `${conv.toFixed(1)}%`,
            change: convCh.text,
            up: convCh.up,
            bar: `${Math.min(100, conv)}%`,
        },
        {
            icon: "attach_money",
            label: "Faturamento Mensal",
            value: kpisLoading ? "…" : fmt(rev),
            change: revCh.text,
            up: revCh.up,
            bar: `${Math.min(100, rev > 0 ? (rev / 100000) * 100 : 0)}%`,
        },
        {
            icon: "group_add",
            label: "Novos Contatos",
            value: kpisLoading ? "…" : nc.toLocaleString("pt-BR"),
            change: ncCh.text,
            up: ncCh.up,
            bar: `${Math.min(100, nc > 0 ? (nc / 100) * 100 : 0)}%`,
        },
    ];

    // Helpers for rendering orders
    const getStatusConfig = (status: string) => {
        const s = (status || "").toLowerCase();
        if (s === "pago") return { bg: "bg-green-100 dark:bg-green-500/20", text: "text-green-700 dark:text-green-400", dot: "bg-green-500" };
        if (s === "cancelado") return { bg: "bg-red-100 dark:bg-red-500/20", text: "text-red-700 dark:text-red-400", dot: "bg-red-500" };
        return { bg: "bg-yellow-100 dark:bg-yellow-500/20", text: "text-yellow-700 dark:text-yellow-400", dot: "bg-yellow-500" };
    };

    const getInitialsInfo = (name: string) => {
        const initials = String(name || "C").substring(0, 2).toUpperCase();
        let hash = 0;
        for (let i = 0; i < initials.length; i++) hash += initials.charCodeAt(i);
        const colors = [
            { bg: "bg-orange-100 dark:bg-orange-900/30", text: "text-orange-600 dark:text-orange-400" },
            { bg: "bg-blue-100 dark:bg-blue-900/30", text: "text-blue-600 dark:text-blue-400" },
            { bg: "bg-primary-light dark:bg-primary/20", text: "text-primary" },
            { bg: "bg-pink-100 dark:bg-pink-900/30", text: "text-pink-600 dark:text-pink-400" },
            { bg: "bg-green-100 dark:bg-green-900/30", text: "text-green-600 dark:text-green-400" },
        ];
        return { initials, ...colors[hash % colors.length] };
    };

    return (
        <div className="p-6 lg:p-10 max-w-7xl mx-auto space-y-8">
            {showOrgHint && (
                <div
                    role="status"
                    className="rounded-xl border border-amber-200 dark:border-amber-800/60 bg-amber-50 dark:bg-amber-950/40 px-4 py-3 text-sm text-amber-900 dark:text-amber-100 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2"
                >
                    <span className="flex items-start gap-2">
                        <span className="material-symbols-outlined text-amber-600 dark:text-amber-400 text-xl shrink-0">info</span>
                        <span>
                            Sua conta ainda não está vinculada a uma organização. Recursos como funil, produtos e
                            configurações podem ficar indisponíveis até um administrador adicioná-lo à equipe.
                        </span>
                    </span>
                    <button
                        type="button"
                        onClick={() => setShowOrgHint(false)}
                        className="shrink-0 text-amber-800 dark:text-amber-200 underline text-xs font-medium"
                    >
                        Dispensar
                    </button>
                </div>
            )}
            {/* Detail Card Modals */}
            {selectedLead && <LeadCard lead={selectedLead} onClose={() => setSelectedLead(null)} />}
            {selectedOrder && <OrderCard order={selectedOrder} onClose={() => setSelectedOrder(null)} />}
            {selectedProduct && <ProductCard product={selectedProduct} onClose={() => setSelectedProduct(null)} />}
            {chatConfig && <WhatsAppChat leadId={chatConfig.leadId} leadName={chatConfig.leadName} onClose={() => setChatConfig(null)} />}

            {/* Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <h1 className="text-2xl font-display font-bold">Painel de Controle</h1>
                    <p className="text-text-secondary-light dark:text-text-secondary-dark mt-1">
                        Bem-vindo de volta!
                    </p>
                </div>
                <div className="flex items-center gap-3">
                    <div className="relative">
                        <input
                            value={searchQuery}
                            onChange={(e) => handleSearchChange(e.target.value)}
                            onFocus={() => searchQuery.length > 0 && setShowSearch(true)}
                            onBlur={() => setTimeout(() => setShowSearch(false), 200)}
                            className="pl-10 pr-4 py-2 rounded-xl border border-border-light dark:border-border-dark bg-surface-light dark:bg-surface-dark text-sm focus:ring-primary focus:border-primary w-full sm:w-64 shadow-sm"
                            placeholder="Buscar clientes, pedidos, produtos..."
                            type="text"
                        />
                        <span className="material-symbols-outlined absolute left-3 top-2.5 text-text-secondary-light text-lg">
                            search
                        </span>
                        {/* Search dropdown */}
                        {showSearch && (
                            <div className="absolute top-full left-0 right-0 mt-1 bg-surface-light dark:bg-surface-dark rounded-xl shadow-2xl border border-border-light dark:border-border-dark z-50 overflow-hidden">
                                <div className="p-2">
                                    {searchLoading && (
                                        <p className="px-3 py-2 text-xs text-text-secondary-light text-center">Buscando...</p>
                                    )}
                                    {!searchLoading && searchResults.length === 0 && searchQuery.length >= 2 && (
                                        <p className="px-3 py-2 text-xs text-text-secondary-light text-center">Nenhum resultado encontrado</p>
                                    )}
                                    {!searchLoading && searchQuery.length < 2 && (
                                        <p className="px-3 py-2 text-xs text-text-secondary-light text-center">Digite ao menos 2 caracteres...</p>
                                    )}
                                    {leadResults.length > 0 && (
                                        <>
                                            <p className="px-3 py-1 text-[10px] font-semibold text-text-secondary-light uppercase tracking-wider">Clientes</p>
                                            {leadResults.map((r) => (
                                                <button key={r.id} onMouseDown={() => handleSelectResult(r)} className="w-full px-3 py-2 text-sm text-left hover:bg-primary/5 rounded-lg flex items-center gap-2">
                                                    <span className="material-symbols-outlined text-base text-blue-500">person</span>
                                                    {r.name}
                                                </button>
                                            ))}
                                        </>
                                    )}
                                    {orderResults.length > 0 && (
                                        <>
                                            <p className="px-3 py-1 mt-1 text-[10px] font-semibold text-text-secondary-light uppercase tracking-wider">Pedidos</p>
                                            {orderResults.map((r) => (
                                                <button key={r.id} onMouseDown={() => handleSelectResult(r)} className="w-full px-3 py-2 text-sm text-left hover:bg-primary/5 rounded-lg flex items-center gap-2">
                                                    <span className="material-symbols-outlined text-base text-orange-500">receipt_long</span>
                                                    {r.name}
                                                </button>
                                            ))}
                                        </>
                                    )}
                                    {productResults.length > 0 && (
                                        <>
                                            <p className="px-3 py-1 mt-1 text-[10px] font-semibold text-text-secondary-light uppercase tracking-wider">Produtos</p>
                                            {productResults.map((r) => (
                                                <button key={r.id} onMouseDown={() => handleSelectResult(r)} className="w-full px-3 py-2 text-sm text-left hover:bg-primary/5 rounded-lg flex items-center gap-2">
                                                    <span className="material-symbols-outlined text-base text-primary">inventory_2</span>
                                                    {r.name}
                                                </button>
                                            ))}
                                        </>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                    <button
                        onClick={() => setShowNewOrder(true)}
                        className="bg-primary hover:bg-primary-hover text-white px-4 py-2 rounded-xl shadow-lg shadow-primary/30 flex items-center gap-2 transition-all text-sm font-medium"
                    >
                        <span className="material-symbols-outlined text-sm">add</span>
                        Novo Pedido
                    </button>
                </div>
            </div>

            {/* Stats Cards — hover-up animation */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {stats.map((stat) => (
                    <div
                        key={stat.label}
                        className="bg-surface-light dark:bg-surface-dark p-6 rounded-2xl shadow-sm border border-border-light/50 dark:border-border-dark relative overflow-hidden group hover:-translate-y-1 hover:shadow-lg transition-all duration-300"
                    >
                        <div className="absolute right-0 top-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
                            <span className="material-symbols-outlined text-8xl text-primary">trending_up</span>
                        </div>
                        <div className="flex items-center justify-between mb-4">
                            <div className="p-2 bg-primary-light dark:bg-primary/10 rounded-lg text-primary">
                                <span className="material-symbols-outlined text-xl">{stat.icon}</span>
                            </div>
                            <span
                                className={`${stat.up ? "text-green-500 bg-green-50 dark:bg-green-500/10" : "text-slate-400 bg-slate-50 dark:bg-slate-700/30"} px-2 py-1 rounded text-xs font-semibold flex items-center gap-1`}
                            >
                                {stat.change}
                                <span className="material-symbols-outlined text-xs">{stat.up ? "arrow_upward" : "remove"}</span>
                            </span>
                        </div>
                        <h3 className="text-text-secondary-light dark:text-text-secondary-dark text-sm font-medium uppercase tracking-wide">
                            {stat.label}
                        </h3>
                        <p className="text-3xl font-display font-bold mt-1">{stat.value}</p>
                        <div className="mt-4 h-1.5 w-full bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                            <div className="h-full bg-primary rounded-full" style={{ width: stat.bar }} />
                        </div>
                    </div>
                ))}
            </div>

            {/* Orders Table */}
            <div className="bg-surface-light dark:bg-surface-dark rounded-2xl shadow-sm border border-border-light dark:border-border-dark overflow-hidden">
                <div className="p-6 border-b border-border-light dark:border-border-dark flex items-center justify-between">
                    <h2 className="text-lg font-display font-semibold">Últimos Pedidos</h2>
                    <button onClick={() => router.push("/pedidos")} className="text-sm text-primary font-medium hover:text-primary-hover flex items-center gap-1">
                        Ver todos <span className="material-symbols-outlined text-sm">arrow_forward</span>
                    </button>
                </div>
                <div className="overflow-x-auto">
                    <table className="w-full text-left text-sm">
                        <thead className="bg-slate-50 dark:bg-slate-800/50 text-text-secondary-light dark:text-text-secondary-dark uppercase tracking-wider text-xs font-semibold">
                            <tr>
                                <th className="px-6 py-4">Cliente</th>
                                <th className="px-6 py-4">Produto</th>
                                <th className="px-6 py-4">Status Pagamento</th>
                                <th className="px-6 py-4">Total</th>
                                <th className="px-6 py-4 text-right">Ação</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border-light dark:divide-border-dark">
                            {ordersLoading ? (
                                <tr><td colSpan={5} className="px-6 py-8 text-center text-sm text-text-secondary-light">Carregando pedidos...</td></tr>
                            ) : recentOrders.length === 0 ? (
                                <tr><td colSpan={5} className="px-6 py-8 text-center text-sm text-text-secondary-light">Nenhum pedido recente.</td></tr>
                            ) : recentOrders.map((order, i) => {
                                const initialsInfo = getInitialsInfo(order.client_name);
                                const statusConfig = getStatusConfig(order.payment_status);
                                return (
                                    <tr key={order.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors group">
                                        <td className="px-6 py-4 font-medium flex items-center gap-3">
                                            <div className={`h-8 w-8 rounded-full ${initialsInfo.bg} ${initialsInfo.text} flex items-center justify-center text-xs font-bold shrink-0`}>
                                                {initialsInfo.initials}
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <p className="truncate text-text-main-light dark:text-text-main-dark">{order.client_name}</p>
                                                {order.client_company && <p className="text-xs text-text-secondary-light dark:text-text-secondary-dark font-normal truncate">{order.client_company}</p>}
                                            </div>
                                        </td>
                                        <td className="px-6 py-4 text-text-secondary-light dark:text-text-secondary-dark">
                                            <div className="line-clamp-2 max-w-xs" title={order.product_summary}>{order.product_summary || "—"}</div>
                                        </td>
                                        <td className="px-6 py-4">
                                            <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium uppercase tracking-wider ${statusConfig.bg} ${statusConfig.text}`}>
                                                <span className={`w-1.5 h-1.5 rounded-full ${statusConfig.dot}`} />
                                                {order.payment_status || "Pendente"}
                                            </span>
                                        </td>
                                        <td className="px-6 py-4 font-medium whitespace-nowrap">{fmt(order.total || 0)}</td>
                                        <td className="px-6 py-4 text-right relative">
                                            <div ref={openMenu === i ? menuRef : null}>
                                                <button
                                                    onClick={() => handleOpenChat(order)}
                                                    className="text-green-600 hover:text-green-700 dark:text-green-400 bg-green-50 dark:bg-green-500/10 p-2 rounded-lg transition-colors"
                                                    title="Conversar no WhatsApp"
                                                >
                                                    <span className="material-symbols-outlined text-lg">chat</span>
                                                </button>
                                                <button
                                                    onClick={() => setOpenMenu(openMenu === i ? null : i)}
                                                    className="text-text-secondary-light hover:text-primary dark:text-text-secondary-dark p-2 ml-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-lg transition-colors"
                                                >
                                                    <span className="material-symbols-outlined text-lg">more_vert</span>
                                                </button>
                                                {/* Dropdown menu */}
                                                {openMenu === i && (
                                                    <div
                                                        onMouseDown={(e) => e.stopPropagation()}
                                                        className="absolute right-0 top-full mt-1 w-48 bg-surface-light dark:bg-surface-dark rounded-xl shadow-2xl border border-border-light dark:border-border-dark z-50 py-1 text-left"
                                                    >
                                                        <button
                                                            onClick={() => { setSelectedOrder(order); setOpenMenu(null); }}
                                                            className="w-full px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center gap-2 text-text-main-light dark:text-text-main-dark"
                                                        >
                                                            <span className="material-symbols-outlined text-base">visibility</span>
                                                            Visualizar Pedido
                                                        </button>
                                                        <button
                                                            onClick={async () => {
                                                                console.log("Clicou em arquivar:", order.id);
                                                                await handleArchiveOrder(order);
                                                            }}
                                                            className="w-full px-4 py-2.5 text-sm hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center gap-2 text-text-main-light dark:text-text-main-dark"
                                                        >
                                                            <span className="material-symbols-outlined text-base">archive</span>
                                                            Arquivar
                                                        </button>
                                                        <div className="h-px bg-border-light dark:bg-border-dark mx-2 my-1" />
                                                        {showDeleteConfirm === i ? (
                                                            <div className="px-4 py-2">
                                                                <p className="text-xs text-red-600 mb-2">Confirmar exclusão?</p>
                                                                <div className="flex gap-2">
                                                                    <button
                                                                        onClick={async () => {
                                                                            console.log("Clicou em excluir confirmação:", order.id);
                                                                            await handleDeleteOrder(order);
                                                                        }}
                                                                        className="flex-1 px-2 py-1 text-xs bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                                                                    >
                                                                        Excluir
                                                                    </button>
                                                                    <button
                                                                        onClick={() => setShowDeleteConfirm(null)}
                                                                        className="flex-1 px-2 py-1 text-xs border border-border-light dark:border-border-dark rounded-lg hover:bg-slate-50 transition-colors"
                                                                    >
                                                                        Cancelar
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        ) : (
                                                            <button
                                                                onClick={() => {
                                                                    console.log("Clicou para abrir confirmação excluir");
                                                                    setShowDeleteConfirm(i);
                                                                }}
                                                                className="w-full px-4 py-2.5 text-sm hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center gap-2 text-red-600 dark:text-red-400 transition-colors"
                                                            >
                                                                <span className="material-symbols-outlined text-base">delete</span>
                                                                Excluir Pedido
                                                            </button>
                                                        )}
                                                    </div>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            {/* Footer */}
            <div className="mt-8 pt-6 border-t border-border-light dark:border-border-dark flex justify-between items-center text-xs text-text-secondary-light dark:text-text-secondary-dark">
                <p>© 2026 — Neurix IA</p>
                <div className="flex gap-4">
                    <a className="hover:text-primary" href="#">Suporte</a>
                    <a className="hover:text-primary" href="#">Termos</a>
                </div>
            </div>

            {/* New Order Modal */}
            {showNewOrder && (
                <NewOrderModal onClose={() => setShowNewOrder(false)} />
            )}
        </div>
    );
}
