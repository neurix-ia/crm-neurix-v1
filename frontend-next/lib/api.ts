import { clearAuthSession, persistAuthSession } from "@/lib/supabase";

/**
 * Normaliza `NEXT_PUBLIC_API_URL`:
 * - http→https na página HTTPS (evita Mixed Content)
 * - remove path `/api` só (erro comum: `https://host/api` — as rotas já usam `/api/...`)
 * Preferido: `https://crm.wbtech.dev` (sem `/api` no final).
 */
function normalizeConfiguredApiUrl(raw: string): string {
    const trimmed = raw.trim();
    try {
        const u = new URL(trimmed);
        if (typeof window !== "undefined" && window.location.protocol === "https:" && u.protocol === "http:") {
            u.protocol = "https:";
        }
        const p = u.pathname.replace(/\/$/, "") || "";
        if (p === "/api") {
            u.pathname = "";
        }
        return u.toString().replace(/\/$/, "");
    } catch {
        return trimmed.replace(/\/api\/?$/i, "").replace(/\/$/, "");
    }
}

/** Origem da API (scheme + host + porta), sem `/api` final. */
export function getApiBase(): string {
    return normalizeConfiguredApiUrl(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000");
}

/** Mesmo site que o front: path relativo herda HTTPS. Localhost com porta da API ≠ porta do Next usa URL absoluta. */
function shouldUseRelativeApiPath(apiBase: string): boolean {
    if (typeof window === "undefined") return false;
    try {
        const u = new URL(apiBase);
        if (u.hostname !== window.location.hostname) return false;
        const local =
            u.hostname === "localhost" ||
            u.hostname === "127.0.0.1" ||
            u.hostname === "::1" ||
            u.hostname === "[::1]";
        if (local) {
            return u.port === window.location.port;
        }
        return true;
    } catch {
        return false;
    }
}

/** Nunca devolver `http://` em página HTTPS (evita Mixed Content no fallback). */
function upgradeHttpToHttpsIfSecurePage(absoluteUrl: string): string {
    if (typeof window === "undefined") return absoluteUrl;
    if (window.location.protocol !== "https:") return absoluteUrl;
    try {
        const u = new URL(absoluteUrl);
        if (u.protocol === "http:") {
            u.protocol = "https:";
            return u.href;
        }
    } catch {
        /* ignore */
    }
    return absoluteUrl;
}

/**
 * URL final para fetch. Mesmo hostname (produção) → path relativo.
 * Se precisar de URL absoluta, força https em página https.
 */
export function getApiUrl(path: string): string {
    const pathNorm = path.startsWith("/") ? path : `/${path}`;
    if (typeof window !== "undefined") {
        try {
            const base = getApiBase();
            if (shouldUseRelativeApiPath(base)) {
                return pathNorm;
            }
        } catch {
            /* fallback abaixo */
        }
    }
    const base = getApiBase().replace(/\/$/, "");
    return upgradeHttpToHttpsIfSecurePage(base + pathNorm);
}

interface ApiOptions extends RequestInit {
    token?: string;
}

let refreshInFlight: Promise<string | null> | null = null;

function resolveRequestUrl(endpoint: string): string {
    if (/^https?:\/\//i.test(endpoint)) {
        if (typeof window !== "undefined" && window.location.protocol === "https:" && /^http:\/\//i.test(endpoint)) {
            try {
                const u = new URL(endpoint);
                if (u.protocol === "http:") {
                    const httpsUrl = endpoint.replace(/^http:\/\//i, "https://");
                    const u2 = new URL(httpsUrl);
                    if (u2.origin === window.location.origin) {
                        return u2.pathname + u2.search + u2.hash;
                    }
                    return httpsUrl;
                }
            } catch {
                return endpoint.replace(/^http:\/\//i, "https://");
            }
        }
        return endpoint;
    }
    return getApiUrl(endpoint);
}

function buildHeaders(customHeaders: HeadersInit | undefined, token?: string, body?: BodyInit | null): Headers {
    const headers = new Headers(customHeaders);
    if (!(body instanceof FormData) && !headers.has("Content-Type")) {
        headers.set("Content-Type", "application/json");
    }
    if (token) {
        headers.set("Authorization", `Bearer ${token}`);
    }
    return headers;
}

function getStoredAccessToken(): string | undefined {
    if (typeof window === "undefined") {
        return undefined;
    }
    return localStorage.getItem("access_token") || undefined;
}

async function redirectToLogin() {
    if (typeof window === "undefined") {
        return;
    }
    await clearAuthSession();
    window.location.href = "/login";
}

async function refreshAccessToken(): Promise<string | null> {
    if (typeof window === "undefined") {
        return null;
    }
    const refreshToken = localStorage.getItem("refresh_token");
    if (!refreshToken) {
        return null;
    }
    if (!refreshInFlight) {
        refreshInFlight = (async () => {
            const res = await fetch(resolveRequestUrl("/api/auth/refresh"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ refresh_token: refreshToken }),
            });
            if (!res.ok) {
                return null;
            }
            const data = (await res.json()) as { access_token?: string; refresh_token?: string | null };
            if (!data.access_token) {
                return null;
            }
            await persistAuthSession(data.access_token, data.refresh_token ?? refreshToken);
            return data.access_token;
        })()
            .catch(() => null)
            .finally(() => {
                refreshInFlight = null;
            });
    }
    return refreshInFlight;
}

export async function apiFetch(
    endpoint: string,
    options: ApiOptions = {},
    allowRetry = true
): Promise<Response> {
    const { token, headers: customHeaders, body, ...rest } = options;
    const authToken = token || getStoredAccessToken();
    const headers = buildHeaders(customHeaders, authToken, body);
    const res = await fetch(resolveRequestUrl(endpoint), {
        headers,
        body,
        ...rest,
    });

    if (res.status === 401 && allowRetry && typeof window !== "undefined") {
        const refreshedToken = await refreshAccessToken();
        if (refreshedToken) {
            return apiFetch(endpoint, { ...options, token: refreshedToken }, false);
        }
        await redirectToLogin();
    }

    return res;
}

export async function api<T = unknown>(
    endpoint: string,
    options: ApiOptions = {}
): Promise<T> {
    const res = await apiFetch(endpoint, options);

    if (!res.ok) {
        const raw = await res.text().catch(() => "");
        let detail: string = res.statusText;
        if (raw) {
            try {
                const parsed = JSON.parse(raw) as {
                    detail?: unknown;
                    message?: string;
                };
                const d = parsed.detail ?? parsed.message;
                if (Array.isArray(d)) {
                    detail = d
                        .map((item: unknown) =>
                            typeof item === "object" && item !== null && "msg" in item
                                ? String((item as { msg: string }).msg)
                                : JSON.stringify(item)
                        )
                        .join("; ");
                } else if (typeof d === "string") {
                    detail = d;
                } else if (d !== undefined) {
                    detail = JSON.stringify(d);
                } else {
                    detail = raw;
                }
            } catch {
                detail = raw;
            }
        }
        throw new Error(detail || `API Error ${res.status}`);
    }
    if (res.status === 204) {
        return undefined as T;
    }
    const raw = await res.text();
    if (!raw) {
        return undefined as T;
    }
    return JSON.parse(raw) as T;
}

// Convenience methods
export const apiGet = <T = unknown>(endpoint: string, token?: string) =>
    api<T>(endpoint, { method: "GET", token });

export const apiPost = <T = unknown>(endpoint: string, body: unknown, token?: string) =>
    api<T>(endpoint, { method: "POST", body: JSON.stringify(body), token });

export const apiPut = <T = unknown>(endpoint: string, body: unknown, token?: string) =>
    api<T>(endpoint, { method: "PUT", body: JSON.stringify(body), token });

export const apiDelete = <T = unknown>(endpoint: string, token?: string) =>
    api<T>(endpoint, { method: "DELETE", token });

export const apiPatch = <T = unknown>(endpoint: string, body: unknown, token?: string) =>
    api<T>(endpoint, { method: "PATCH", body: JSON.stringify(body), token });

// ── Pedidos, leads, produtos, busca (Sprint 14 — AC11: mutações via API) ──

export type OrderDTO = {
    id: string;
    tenant_id: string;
    lead_id?: string | null;
    client_name: string;
    client_company?: string | null;
    product_summary: string;
    products_json: unknown[];
    applied_promotions_json?: unknown[];
    subtotal?: number;
    discount_total?: number;
    total: number;
    stage?: string | null;
    notes?: string | null;
    payment_status: string;
    created_at: string;
};

export const listOrders = (limit = 20, token?: string) =>
    apiGet<OrderDTO[]>(`/api/orders/?limit=${limit}`, token);

export type DashboardKpisDTO = {
    conversion_rate: number;
    conversion_change: number;
    monthly_revenue: number;
    revenue_change: number;
    new_contacts: number;
    new_contacts_change?: number;
    message_volume: number;
    message_change: number;
};

export const getDashboardKpis = (token?: string) =>
    apiGet<DashboardKpisDTO>("/api/dashboard/kpis", token);

export const getOrder = (orderId: string, token?: string) =>
    apiGet<OrderDTO>(`/api/orders/${encodeURIComponent(orderId)}`, token);

export const deleteOrder = (orderId: string, token?: string) =>
    apiDelete<void>(`/api/orders/${encodeURIComponent(orderId)}`, token);

export const archiveOrder = (orderId: string, token?: string) =>
    apiPost<void>(`/api/orders/${encodeURIComponent(orderId)}/archive`, {}, token);

export type GlobalSearchItem = {
    id: string;
    name: string;
    type: "lead" | "order" | "product";
};

export const globalSearch = (q: string, token?: string) =>
    apiGet<{ results: GlobalSearchItem[] }>(
        `/api/dashboard/search?${new URLSearchParams({ q: q.trim() }).toString()}`,
        token
    );

export type LeadDTO = {
    id: string;
    tenant_id: string;
    contact_name: string;
    company_name: string;
    phone?: string | null;
    stage: string;
    priority?: string | null;
    value: number;
    notes?: string | null;
    delivery_address?: string | null;
    created_at: string;
};

export const getLeadById = (leadId: string, token?: string) =>
    apiGet<LeadDTO>(`/api/leads/${encodeURIComponent(leadId)}`, token);

export const listLeads = (opts?: { search?: string }, token?: string) => {
    const p = new URLSearchParams();
    if (opts?.search) p.set("search", opts.search);
    const qs = p.toString();
    return apiGet<LeadDTO[]>(`/api/leads${qs ? `?${qs}` : ""}`, token);
};

export const createLead = (body: Record<string, unknown>, token?: string) =>
    apiPost<LeadDTO>("/api/leads/", body, token);

export type ProductDTO = {
    id: string;
    name: string;
    description?: string | null;
    price: number;
    weight?: string | null;
    weight_grams?: number;
    category?: string | null;
    status?: string | null;
    is_active: boolean;
    image_url?: string | null;
    created_at: string;
};

export const listProducts = (opts?: { active_only?: boolean; search?: string }, token?: string) => {
    const p = new URLSearchParams();
    if (opts?.active_only) p.set("active_only", "true");
    if (opts?.search) p.set("search", opts.search);
    const qs = p.toString();
    return apiGet<ProductDTO[]>(`/api/products${qs ? `?${qs}` : ""}`, token);
};

export const getProduct = (productId: string, token?: string) =>
    apiGet<ProductDTO>(`/api/products/${encodeURIComponent(productId)}`, token);

// ── Auth / RBAC (Sprint 5 — Console Admin) ──

export type AuthMe = {
    id: string;
    email: string;
    full_name?: string | null;
    role?: string | null;
    avatar_url?: string | null;
    is_superadmin: boolean;
    organization_id?: string | null;
    /** Sprint 13 — Kanban / RBAC */
    is_read_only?: boolean;
    assigned_funnel_id?: string | null;
    is_org_admin?: boolean;
};

export const getAuthMe = (token?: string) => apiGet<AuthMe>("/api/auth/me", token);

// ── Neurix HQ (superadmin) ──

export type HqLevel = "green" | "yellow" | "red" | "gray";
export type HqPeriod = "24h" | "7d" | "30d";

export type HqAlert = {
    level: HqLevel;
    message: string;
    module: string;
    link?: string | null;
};

export type HqModuleStatus = {
    id: string;
    label: string;
    level: HqLevel;
    summary: string;
    alerts: HqAlert[];
    enabled: boolean;
};

export type HqSummaryResponse = {
    modules: HqModuleStatus[];
    generated_at: string;
    cached: boolean;
};

export type N8nInstanceMetrics = {
    id: string;
    label: string;
    status: "ok" | "error";
    error_message?: string | null;
    total_executions: number;
    failed_executions: number;
    failure_rate: number;
    time_saved_minutes: number;
    average_run_time_seconds: number;
    metrics_raw?: { deviations?: Record<string, number | null> } | null;
};

export type N8nOverviewResponse = {
    period: HqPeriod;
    start_date: string;
    end_date: string;
    instances: N8nInstanceMetrics[];
    consolidated: N8nInstanceMetrics;
    cached: boolean;
    generated_at: string;
};

export type N8nWorkflowErrorRow = {
    instance_id: string;
    instance_label: string;
    workflow_id?: string | null;
    workflow_name: string;
    project_name?: string | null;
    total_executions: number;
    failed_executions: number;
    failure_rate: number;
    average_run_time_seconds: number;
    last_execution_id?: string | null;
    last_failed_at?: string | null;
};

export type N8nExecutionErrorDetail = {
    instance_id: string;
    instance_label: string;
    instance_base_url: string;
    workflow_id?: string | null;
    workflow_name?: string | null;
    execution_id: string;
    status?: string | null;
    started_at?: string | null;
    stopped_at?: string | null;
    node_name?: string | null;
    message: string;
    description?: string | null;
    stack?: string | null;
    n8n_execution_url?: string | null;
};

export type N8nWorkflowErrorsResponse = {
    period: HqPeriod;
    rows: N8nWorkflowErrorRow[];
    cached: boolean;
    generated_at: string;
};

export const getHqSummary = (period: HqPeriod = "7d", token?: string) =>
    apiGet<HqSummaryResponse>(`/api/admin/hq/summary?period=${period}`, token);

export const getHqN8nOverview = (period: HqPeriod = "7d", refresh = false, token?: string) => {
    const p = new URLSearchParams({ period });
    if (refresh) p.set("refresh", "true");
    return apiGet<N8nOverviewResponse>(`/api/admin/hq/n8n/overview?${p}`, token);
};

export const getHqN8nWorkflowErrors = (
    period: HqPeriod = "7d",
    limit = 20,
    refresh = false,
    token?: string
) => {
    const p = new URLSearchParams({ period, limit: String(limit) });
    if (refresh) p.set("refresh", "true");
    return apiGet<N8nWorkflowErrorsResponse>(`/api/admin/hq/n8n/workflows/errors?${p}`, token);
};

export const refreshHqN8nCache = (token?: string) =>
    apiPost<{ ok: boolean; keys_deleted: number }>("/api/admin/hq/n8n/refresh", {}, token);

export const getHqN8nExecutionError = (
    instanceId: string,
    executionId: string,
    workflowId?: string,
    token?: string
) => {
    const p = new URLSearchParams();
    if (workflowId) p.set("workflow_id", workflowId);
    const qs = p.toString();
    return apiGet<N8nExecutionErrorDetail>(
        `/api/admin/hq/n8n/executions/${encodeURIComponent(instanceId)}/${encodeURIComponent(executionId)}${qs ? `?${qs}` : ""}`,
        token
    );
};

// ── Organizações ──

export type OrganizationDTO = {
    id: string;
    name: string;
    created_at: string;
    updated_at: string;
};

export type OrganizationMemberDTO = {
    id: string;
    organization_id: string;
    user_id: string;
    role: "admin" | "read_only";
    assigned_funnel_id?: string | null;
    created_at: string;
};

export const getOrganizations = (token?: string) =>
    apiGet<OrganizationDTO[]>("/api/organizations/", token);

export const createOrganization = (body: { name: string }, token?: string) =>
    apiPost<OrganizationDTO>("/api/organizations/", body, token);

export const updateOrganization = (orgId: string, body: { name: string }, token?: string) =>
    apiPatch<OrganizationDTO>(`/api/organizations/${orgId}`, body, token);

export const deleteOrganization = (orgId: string, token?: string) =>
    apiDelete<void>(`/api/organizations/${orgId}`, token);

export const getOrganization = (orgId: string, token?: string) =>
    apiGet<OrganizationDTO>(`/api/organizations/${orgId}`, token);

export const listOrgMembers = (orgId: string, token?: string) =>
    apiGet<OrganizationMemberDTO[]>(`/api/organizations/${orgId}/members`, token);

export type AddOrgMemberBody = {
    user_id: string;
    role: "admin" | "read_only";
    assigned_funnel_id?: string | null;
};

export const addOrgMember = (orgId: string, body: AddOrgMemberBody, token?: string) =>
    apiPost<OrganizationMemberDTO>(`/api/organizations/${orgId}/members`, body, token);

export type PatchOrgMemberBody = {
    role?: "admin" | "read_only";
    assigned_funnel_id?: string | null;
};

export const updateOrgMember = (
    orgId: string,
    memberUserId: string,
    body: PatchOrgMemberBody,
    token?: string
) =>
    apiPatch<OrganizationMemberDTO>(
        `/api/organizations/${orgId}/members/${memberUserId}`,
        body,
        token
    );

export const removeOrgMember = (orgId: string, memberUserId: string, token?: string) =>
    apiDelete<void>(`/api/organizations/${orgId}/members/${memberUserId}`, token);

/** Funis atribuíveis na org (admins da org) — Sprint 6 */
export type OrganizationFunnelItem = {
    id: string;
    tenant_id: string;
    name: string;
    created_at: string;
    updated_at: string;
};

export const listOrganizationFunnels = (orgId: string, token?: string) =>
    apiGet<OrganizationFunnelItem[]>(`/api/organizations/${orgId}/funnels`, token);

/** Console Admin — superadmin apenas */
export const getAdminProducts = (tenantId: string, token?: string) =>
    apiGet<
        Array<{
            id: string;
            name: string;
            price: number;
            stock_quantity?: number;
            is_active?: boolean;
            category?: string | null;
        }>
    >(`/api/admin/products?${new URLSearchParams({ tenant_id: tenantId }).toString()}`, token);

export const getAdminFunnels = (tenantId: string, token?: string) =>
    apiGet<OrganizationFunnelItem[]>(
        `/api/admin/funnels?${new URLSearchParams({ tenant_id: tenantId }).toString()}`,
        token
    );

// ── Usuários (Auth Admin API via backend) ──

export type CreateUserBody = {
    organization_id: string;
    email: string;
    password: string;
    full_name: string;
    company_name?: string | null;
    phones: string[];
    role: "admin" | "read_only";
    assigned_funnel_id?: string | null;
};

export type OrganizationUserResponse = {
    id: string;
    email?: string | null;
    full_name?: string | null;
    company_name?: string | null;
    phones: string[];
    organization_id: string;
    role: string;
    assigned_funnel_id?: string | null;
    created_at: string;
};

export const createUser = (body: CreateUserBody, token?: string) =>
    apiPost<OrganizationUserResponse>("/api/users/", body, token);

export type UserDetailResponse = {
    id: string;
    email?: string | null;
    full_name?: string | null;
    company_name?: string | null;
    phones: string[];
    memberships: { organization_id: string; role: string; assigned_funnel_id?: string | null }[];
};

export const getUser = (userId: string, token?: string) =>
    apiGet<UserDetailResponse>(`/api/users/${userId}`, token);

export type PatchUserBody = {
    full_name?: string;
    company_name?: string | null;
    phones?: string[];
    role?: "admin" | "read_only";
    assigned_funnel_id?: string | null;
};

export const patchUser = (userId: string, organizationId: string, body: PatchUserBody, token?: string) => {
    const q = new URLSearchParams({ organization_id: organizationId });
    return apiPatch<{ organization_id: string; role: string; assigned_funnel_id?: string | null }>(
        `/api/users/${userId}?${q.toString()}`,
        body,
        token
    );
};

// ── Funis do tenant (lista para Configurações / inboxes) — Sprint 8 ──

export type FunnelListItem = {
    id: string;
    tenant_id: string;
    name: string;
    created_at: string;
    updated_at: string;
};

export const listMyFunnels = (token?: string) => apiGet<FunnelListItem[]>("/api/funnels/", token);

export const createMyFunnel = (body: { name: string }, token?: string) =>
    apiPost<FunnelListItem>("/api/funnels/", body, token);

/** 200 se usuário pode gerenciar inboxes (org admin); 403 caso contrário (ex.: read_only). */
export const probeOrgAdmin = (token?: string) =>
    apiGet<{ ok: boolean; scope: string }>("/api/auth/rbac/org-admin", token);

// ── Caixas de entrada (inboxes) — Sprint 7 ──

export type InboxDTO = {
    id: string;
    tenant_id: string;
    funnel_id: string;
    name: string;
    provider?: "uazapi" | "chatwoot";
    uazapi_settings: Record<string, unknown>;
    chatwoot_settings?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
};

export type CreateInboxBody = {
    name: string;
    funnel_id: string;
    provider?: "uazapi" | "chatwoot";
    uazapi_settings?: Record<string, unknown>;
    chatwoot_settings?: Record<string, unknown>;
};

export type UpdateInboxBody = {
    name?: string;
    funnel_id?: string;
    provider?: "uazapi" | "chatwoot";
    uazapi_settings?: Record<string, unknown>;
    chatwoot_settings?: Record<string, unknown>;
};

/** Lista inboxes do tenant; superadmin pode passar tenantId (query tenant_id). */
export const listInboxes = (token?: string, tenantId?: string) => {
    const q = tenantId ? `?${new URLSearchParams({ tenant_id: tenantId }).toString()}` : "";
    return apiGet<InboxDTO[]>(`/api/inboxes/${q}`, token);
};

export const getInbox = (inboxId: string, token?: string) =>
    apiGet<InboxDTO>(`/api/inboxes/${inboxId}`, token);

export const createInbox = (body: CreateInboxBody, token?: string) =>
    apiPost<InboxDTO>("/api/inboxes/", body, token);

export const updateInbox = (inboxId: string, body: UpdateInboxBody, token?: string) =>
    apiPatch<InboxDTO>(`/api/inboxes/${inboxId}`, body, token);

export const deleteInbox = (inboxId: string, token?: string) =>
    apiDelete<void>(`/api/inboxes/${inboxId}`, token);

/** Console Admin — somente superadmin */
export const listAdminInboxes = (tenantId: string, token?: string) =>
    apiGet<InboxDTO[]>(
        `/api/admin/inboxes?${new URLSearchParams({ tenant_id: tenantId }).toString()}`,
        token
    );

// ── Chatwoot (WhatsApp Oficial) ──

export type ChatwootConnectBody = {
    inbox_id: string;
    base_url: string;
    account_id: string;
    chatwoot_inbox_id: string;
    api_access_token: string;
    webhook_secret?: string;
    phone_number_id?: string;
};

export type ChatwootStatus = {
    status: string;
    message?: string;
    labels_count?: number;
    account_id?: string;
};

export const connectChatwoot = (body: ChatwootConnectBody, token?: string) =>
    apiPost<{ status: string; labels_count: number }>("/api/chatwoot/connect", body, token);

export const getChatwootStatus = (inboxId: string, token?: string) =>
    apiGet<ChatwootStatus>(
        `/api/chatwoot/status?${new URLSearchParams({ inbox_id: inboxId }).toString()}`,
        token
    );

export const disconnectChatwoot = (inboxId: string, token?: string) =>
    apiDelete<{ status: string }>(
        `/api/chatwoot/disconnect?${new URLSearchParams({ inbox_id: inboxId }).toString()}`,
        token
    );

// ── Clientes CRM (Sprint 10) ──

export type CrmClientDTO = {
    id: string;
    tenant_id: string;
    person_type: "PF" | "PJ";
    cpf?: string | null;
    cnpj?: string | null;
    display_name: string;
    contact_name?: string | null;
    phones: string[];
    address_line1?: string | null;
    address_line2?: string | null;
    neighborhood?: string | null;
    postal_code?: string | null;
    city?: string | null;
    state?: string | null;
    complement?: string | null;
    no_number?: boolean | null;
    dead_end_street?: boolean | null;
    created_at: string;
    updated_at: string;
};

export type CreateCrmClientBody = {
    person_type: "PF" | "PJ";
    display_name: string;
    contact_name?: string | null;
    phones: string[];
    cpf?: string | null;
    cnpj?: string | null;
    tenant_id?: string | null;
    address_line1?: string | null;
    address_line2?: string | null;
    neighborhood?: string | null;
    postal_code?: string | null;
    city?: string | null;
    state?: string | null;
    complement?: string | null;
    no_number?: boolean | null;
    dead_end_street?: boolean | null;
};

export type PatchCrmClientBody = Partial<Omit<CreateCrmClientBody, "tenant_id">>;

/** Superadmin: `tenant_id` obrigatório. Demais usuários: omitir (usa JWT). */
export const listClients = (token: string, tenantId?: string) => {
    const q = tenantId ? `?${new URLSearchParams({ tenant_id: tenantId }).toString()}` : "";
    return apiGet<CrmClientDTO[]>(`/api/clients/${q}`, token);
};

export const getClient = (clientId: string, token?: string) =>
    apiGet<CrmClientDTO>(`/api/clients/${clientId}`, token);

export const createCrmClient = (body: CreateCrmClientBody, token?: string) =>
    apiPost<CrmClientDTO>("/api/clients/", body, token);

export const updateClient = (clientId: string, body: PatchCrmClientBody, token?: string) =>
    apiPatch<CrmClientDTO>(`/api/clients/${clientId}`, body, token);

export const deleteClient = (clientId: string, token?: string) =>
    apiDelete<void>(`/api/clients/${clientId}`, token);

export const lookupClientByPhone = (phone: string, token?: string, tenantId?: string) => {
    const p = new URLSearchParams({ phone });
    if (tenantId) p.set("tenant_id", tenantId);
    return apiGet<CrmClientDTO | null>(`/api/clients/lookup/by-phone?${p.toString()}`, token);
};

export type ClientLeadDTO = {
    id: string;
    contact_name: string;
    company_name: string;
    phone?: string | null;
    stage: string;
    value: number;
    created_at: string;
    updated_at: string;
    products_json?: unknown[];
    purchase_history_json?: unknown[];
};

export const listClientLeads = (clientId: string, token?: string) =>
    apiGet<ClientLeadDTO[]>(`/api/clients/${clientId}/leads`, token);

export type ClientOrderDTO = {
    id: string;
    lead_id?: string | null;
    client_name: string;
    product_summary: string;
    products_json?: unknown[];
    total: number;
    payment_status: string;
    created_at: string;
};

export const listClientOrders = (clientId: string, token?: string) =>
    apiGet<ClientOrderDTO[]>(`/api/clients/${clientId}/orders`, token);

// ── WhatsApp Instance Management (escopo opcional por inbox) ──

function whatsappInboxQuery(inboxId?: string) {
    return inboxId ? `?${new URLSearchParams({ inbox_id: inboxId }).toString()}` : "";
}

export const getWhatsappStatus = (token?: string, inboxId?: string) =>
    apiGet<{ status: string; data?: unknown; message?: string; scope?: string }>(
        `/api/whatsapp/status${whatsappInboxQuery(inboxId)}`,
        token
    );

export const initWhatsappInstance = (instanceName: string, token?: string, inboxId?: string) =>
    apiPost<{ message: string; token: string }>(
        "/api/whatsapp/init",
        { instance_name: instanceName, ...(inboxId ? { inbox_id: inboxId } : {}) },
        token
    );

export const connectWhatsappInstance = (token?: string, inboxId?: string) =>
    apiPost<{ message: string; data: unknown; scope?: string }>(
        `/api/whatsapp/connect${whatsappInboxQuery(inboxId)}`,
        {},
        token
    );

export const saveWhatsappToken = (instanceToken: string, token?: string, inboxId?: string) =>
    apiPost<{ message: string; status: string }>(
        "/api/whatsapp/token",
        { instance_token: instanceToken, ...(inboxId ? { inbox_id: inboxId } : {}) },
        token
    );

export const disconnectWhatsappInstance = (token?: string, inboxId?: string) =>
    apiDelete<{ message: string }>(`/api/whatsapp/disconnect${whatsappInboxQuery(inboxId)}`, token);

// ── Automação de etapa + auditoria (Sprint 11) ──

export type StageAutomationDTO = {
    id: string;
    organization_id: string;
    source_funnel_id: string;
    source_stage_id: string;
    target_user_id: string;
    target_funnel_id: string;
    target_stage_id: string;
    created_at?: string | null;
};

export const getStageAutomation = (stageId: string, token?: string) =>
    apiGet<StageAutomationDTO | null>(`/api/leads/stages/${encodeURIComponent(stageId)}/automation`, token);

export const putStageAutomation = (
    stageId: string,
    body: {
        organization_id: string;
        target_user_id: string;
        target_funnel_id: string;
        target_stage_id: string;
    },
    token?: string
) => apiPut<StageAutomationDTO>(`/api/leads/stages/${encodeURIComponent(stageId)}/automation`, body, token);

export const deleteStageAutomation = (stageId: string, token?: string) =>
    apiDelete<void>(`/api/leads/stages/${encodeURIComponent(stageId)}/automation`, token);

export type LeadActivityDTO = {
    id: string;
    event_type: string;
    from_stage_id?: string | null;
    to_stage_id?: string | null;
    actor_user_id?: string | null;
    occurred_at: string;
    metadata?: Record<string, unknown>;
};

export const getLeadActivity = (leadId: string, token?: string) =>
    apiGet<LeadActivityDTO[]>(`/api/leads/${encodeURIComponent(leadId)}/activity`, token);

export type PipelineStageBrief = {
    id: string;
    name: string;
    order_position: number;
    version: number;
    is_conversion?: boolean;
};

export const listOrgFunnelStages = (orgId: string, funnelId: string, token?: string) =>
    apiGet<PipelineStageBrief[]>(
        `/api/organizations/${encodeURIComponent(orgId)}/funnels/${encodeURIComponent(funnelId)}/stages`,
        token
    );
