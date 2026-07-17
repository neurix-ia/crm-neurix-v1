"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import {
    addOrgMember,
    getMenuCatalog,
    getOrganization,
    listOrgMembers,
    listOrganizationFunnels,
    removeOrgMember,
    updateOrgMember,
    updateOrganization,
    type MenuCatalogItemDTO,
    type OrganizationDTO,
    type OrganizationFunnelItem,
    type OrganizationMemberDTO,
} from "@/lib/api";
import { DEFAULT_MENU_CONFIG, resolveMenuConfig, type MenuItemKey } from "@/lib/menu-catalog";

export default function AdminOrganizationDetailPage() {
    const params = useParams();
    const orgId = params.orgId as string;
    const [org, setOrg] = useState<OrganizationDTO | null>(null);
    const [members, setMembers] = useState<OrganizationMemberDTO[] | null>(null);
    const [orgFunnels, setOrgFunnels] = useState<OrganizationFunnelItem[]>([]);
    const [catalog, setCatalog] = useState<MenuCatalogItemDTO[]>([]);
    const [menuDraft, setMenuDraft] = useState<Record<MenuItemKey, boolean>>({ ...DEFAULT_MENU_CONFIG });
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [menuBusy, setMenuBusy] = useState(false);
    const [menuSaved, setMenuSaved] = useState(false);

    const [addOpen, setAddOpen] = useState(false);
    const [newUserId, setNewUserId] = useState("");
    const [newRole, setNewRole] = useState<"admin" | "read_only">("admin");
    const [newFunnelId, setNewFunnelId] = useState("");
    const [busy, setBusy] = useState(false);

    const [edit, setEdit] = useState<OrganizationMemberDTO | null>(null);
    const [editRole, setEditRole] = useState<"admin" | "read_only">("admin");
    const [editFunnelId, setEditFunnelId] = useState("");

    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

    const load = async () => {
        if (!token || !orgId) return;
        setLoading(true);
        setError(null);
        try {
            const [o, m, cat] = await Promise.all([
                getOrganization(orgId, token),
                listOrgMembers(orgId, token),
                getMenuCatalog(token).catch(() => []),
            ]);
            setOrg(o);
            setMembers(m);
            setCatalog(cat);
            setMenuDraft(resolveMenuConfig(o.menu_config));
            try {
                const f = await listOrganizationFunnels(orgId, token);
                setOrgFunnels(f);
            } catch {
                setOrgFunnels([]);
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : "Erro ao carregar.");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [orgId]);

    const toggleMenuItem = (key: MenuItemKey) => {
        setMenuSaved(false);
        setMenuDraft((prev) => ({ ...prev, [key]: !prev[key] }));
    };

    const saveMenu = async () => {
        if (!token || !orgId) return;
        setMenuBusy(true);
        setError(null);
        setMenuSaved(false);
        try {
            const updated = await updateOrganization(orgId, { menu_config: menuDraft }, token);
            setOrg(updated);
            setMenuDraft(resolveMenuConfig(updated.menu_config));
            setMenuSaved(true);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao salvar menu.");
        } finally {
            setMenuBusy(false);
        }
    };

    const restoreMenuDefaults = async () => {
        if (!token || !orgId) return;
        if (!confirm("Restaurar o menu padrão desta organização?")) return;
        setMenuBusy(true);
        setError(null);
        setMenuSaved(false);
        try {
            const updated = await updateOrganization(orgId, { menu_config: { ...DEFAULT_MENU_CONFIG } }, token);
            setOrg(updated);
            setMenuDraft(resolveMenuConfig(updated.menu_config));
            setMenuSaved(true);
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao restaurar menu.");
        } finally {
            setMenuBusy(false);
        }
    };

    const submitAdd = async () => {
        if (!token || !newUserId.trim()) return;
        if (newRole === "read_only" && !newFunnelId.trim()) {
            setError("Informe o UUID do funil para membro read_only.");
            return;
        }
        setBusy(true);
        setError(null);
        try {
            await addOrgMember(
                orgId,
                {
                    user_id: newUserId.trim(),
                    role: newRole,
                    assigned_funnel_id: newRole === "read_only" ? newFunnelId.trim() : null,
                },
                token
            );
            setAddOpen(false);
            setNewUserId("");
            setNewFunnelId("");
            setNewRole("admin");
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao adicionar membro.");
        } finally {
            setBusy(false);
        }
    };

    const openEdit = (m: OrganizationMemberDTO) => {
        setEdit(m);
        setEditRole(m.role);
        setEditFunnelId(m.assigned_funnel_id || "");
    };

    const submitEdit = async () => {
        if (!token || !edit) return;
        if (editRole === "read_only" && !editFunnelId.trim()) {
            setError("Funil obrigatório para read_only.");
            return;
        }
        setBusy(true);
        setError(null);
        try {
            await updateOrgMember(
                orgId,
                edit.user_id,
                {
                    role: editRole,
                    assigned_funnel_id: editRole === "read_only" ? editFunnelId.trim() : null,
                },
                token
            );
            setEdit(null);
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao atualizar.");
        } finally {
            setBusy(false);
        }
    };

    const confirmRemove = async (m: OrganizationMemberDTO) => {
        if (!token) return;
        if (!confirm("Remover este membro da organização?")) return;
        setBusy(true);
        try {
            await removeOrgMember(orgId, m.user_id, token);
            await load();
        } catch (e) {
            setError(e instanceof Error ? e.message : "Falha ao remover.");
        } finally {
            setBusy(false);
        }
    };

    const catalogItems =
        catalog.length > 0
            ? catalog
            : Object.keys(DEFAULT_MENU_CONFIG).map((key) => ({
                  key,
                  label: key,
                  route: "",
                  icon: "",
              }));

    return (
        <div className="max-w-5xl space-y-6">
            <div className="flex flex-wrap items-center gap-4">
                <Link href="/admin/organizations" className="text-sm text-primary hover:underline">
                    ← Organizações
                </Link>
            </div>

            {loading && <p className="text-sm text-text-secondary-light">Carregando…</p>}
            {error && (
                <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300 text-sm px-4 py-3">
                    {error}
                </div>
            )}

            {org && (
                <div>
                    <h1 className="text-2xl font-bold font-display">{org.name}</h1>
                    <p className="text-xs text-text-secondary-light mt-1 font-mono">{org.id}</p>
                </div>
            )}

            {org && (
                <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-6 space-y-4">
                    <div>
                        <h2 className="text-lg font-semibold">Menu lateral do app</h2>
                        <p className="text-xs text-text-secondary-light mt-1">
                            Define quais itens os membros desta organização veem no menu. Itens desabilitados também
                            bloqueiam o acesso direto pela URL.
                        </p>
                    </div>
                    <ul className="space-y-2">
                        {catalogItems.map((item) => {
                            const key = item.key as MenuItemKey;
                            const checked = Boolean(menuDraft[key]);
                            return (
                                <li key={item.key}>
                                    <label className="flex items-center gap-3 cursor-pointer rounded-xl px-3 py-2 hover:bg-black/5 dark:hover:bg-white/5">
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 accent-primary"
                                            checked={checked}
                                            onChange={() => toggleMenuItem(key)}
                                        />
                                        <span className="text-sm font-medium flex-1">{item.label}</span>
                                        {item.route ? (
                                            <span className="text-xs font-mono text-text-secondary-light">{item.route}</span>
                                        ) : null}
                                    </label>
                                </li>
                            );
                        })}
                    </ul>
                    <div className="flex flex-wrap items-center gap-2 pt-2">
                        <button
                            type="button"
                            disabled={menuBusy}
                            onClick={saveMenu}
                            className="h-10 px-4 rounded-xl bg-primary text-white text-sm font-semibold disabled:opacity-60"
                        >
                            {menuBusy ? "Salvando…" : "Salvar menu"}
                        </button>
                        <button
                            type="button"
                            disabled={menuBusy}
                            onClick={restoreMenuDefaults}
                            className="h-10 px-4 rounded-xl border border-border-light dark:border-border-dark text-sm"
                        >
                            Restaurar padrão
                        </button>
                        {menuSaved && (
                            <span className="text-xs text-emerald-600 dark:text-emerald-400">Menu salvo.</span>
                        )}
                    </div>
                </div>
            )}

            <div>
                <h2 className="text-lg font-semibold mb-2">Funis da organização</h2>
                <p className="text-xs text-text-secondary-light mb-3">
                    Funis cujo tenant é um membro <strong>admin</strong> (mesma regra que{" "}
                    <code className="font-mono">org_scope</code> no backend).
                </p>
                {orgFunnels.length === 0 ? (
                    <p className="text-sm text-text-secondary-light mb-6">
                        Nenhum funil encontrado (adicione um admin com funil Default ou migração 008).
                    </p>
                ) : (
                    <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark overflow-x-auto mb-8">
                        <table className="w-full text-sm min-w-[520px]">
                            <thead className="bg-black/5 dark:bg-white/5 text-left">
                                <tr>
                                    <th className="p-3 font-semibold">Nome</th>
                                    <th className="p-3 font-semibold">Tenant</th>
                                    <th className="p-3 font-semibold w-40">Ação</th>
                                </tr>
                            </thead>
                            <tbody>
                                {orgFunnels.map((fn) => (
                                    <tr key={fn.id} className="border-t border-border-light dark:border-border-dark">
                                        <td className="p-3">{fn.name}</td>
                                        <td className="p-3 font-mono text-xs break-all">{fn.tenant_id}</td>
                                        <td className="p-3">
                                            <Link
                                                href={`/kanban?funnel_id=${encodeURIComponent(fn.id)}`}
                                                className="text-primary text-xs hover:underline"
                                            >
                                                Abrir Kanban neste funil
                                            </Link>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>

            <div className="flex justify-between items-center gap-4">
                <h2 className="text-lg font-semibold">Membros</h2>
                <button
                    type="button"
                    onClick={() => setAddOpen(true)}
                    className="h-10 px-4 rounded-xl bg-primary text-white text-sm font-semibold"
                >
                    Adicionar membro
                </button>
            </div>

            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark overflow-x-auto">
                {!members || members.length === 0 ? (
                    <p className="p-6 text-sm text-text-secondary-light">Nenhum membro ou ainda carregando.</p>
                ) : (
                    <table className="w-full text-sm min-w-[640px]">
                        <thead className="bg-black/5 dark:bg-white/5 text-left">
                            <tr>
                                <th className="p-3 font-semibold">User ID</th>
                                <th className="p-3 font-semibold">Papel</th>
                                <th className="p-3 font-semibold">Funil (read_only)</th>
                                <th className="p-3 font-semibold w-40">Ações</th>
                            </tr>
                        </thead>
                        <tbody>
                            {members.map((m) => (
                                <tr key={m.id} className="border-t border-border-light dark:border-border-dark">
                                    <td className="p-3 font-mono text-xs break-all">{m.user_id}</td>
                                    <td className="p-3">{m.role}</td>
                                    <td className="p-3 font-mono text-xs">{m.assigned_funnel_id || "—"}</td>
                                    <td className="p-3 flex flex-wrap gap-2">
                                        <button
                                            type="button"
                                            onClick={() => openEdit(m)}
                                            className="text-xs px-2 py-1 rounded-lg border border-border-light dark:border-border-dark"
                                        >
                                            Editar
                                        </button>
                                        <button
                                            type="button"
                                            onClick={() => confirmRemove(m)}
                                            disabled={busy}
                                            className="text-xs px-2 py-1 rounded-lg border border-red-300 text-red-700"
                                        >
                                            Remover
                                        </button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </div>

            {addOpen && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
                    <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-6 w-full max-w-lg shadow-xl space-y-4">
                        <h3 className="text-lg font-bold">Adicionar membro</h3>
                        <div>
                            <label className="text-sm font-medium">User ID (UUID)</label>
                            <input
                                className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3 text-sm font-mono"
                                value={newUserId}
                                onChange={(e) => setNewUserId(e.target.value)}
                                placeholder="uuid do usuário em auth.users"
                            />
                        </div>
                        <div>
                            <label className="text-sm font-medium">Papel</label>
                            <select
                                className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3"
                                value={newRole}
                                onChange={(e) => setNewRole(e.target.value as "admin" | "read_only")}
                            >
                                <option value="admin">admin</option>
                                <option value="read_only">read_only</option>
                            </select>
                        </div>
                        {newRole === "read_only" && (
                            <div>
                                <label className="text-sm font-medium">Funil (read_only)</label>
                                {orgFunnels.length > 0 ? (
                                    <select
                                        className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3 text-sm"
                                        value={newFunnelId}
                                        onChange={(e) => setNewFunnelId(e.target.value)}
                                    >
                                        <option value="">— selecione —</option>
                                        {orgFunnels.map((f) => (
                                            <option key={f.id} value={f.id}>
                                                {f.name} ({f.id.slice(0, 8)}…)
                                            </option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3 text-sm font-mono"
                                        value={newFunnelId}
                                        onChange={(e) => setNewFunnelId(e.target.value)}
                                        placeholder="UUID do funil (sem lista — migração 008?)"
                                    />
                                )}
                            </div>
                        )}
                        <div className="flex justify-end gap-2 pt-2">
                            <button
                                type="button"
                                onClick={() => setAddOpen(false)}
                                className="h-10 px-4 rounded-xl border border-border-light dark:border-border-dark text-sm"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                disabled={busy}
                                onClick={submitAdd}
                                className="h-10 px-4 rounded-xl bg-primary text-white text-sm font-semibold"
                            >
                                Adicionar
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {edit && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
                    <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark p-6 w-full max-w-lg shadow-xl space-y-4">
                        <h3 className="text-lg font-bold">Editar membro</h3>
                        <p className="text-xs font-mono break-all text-text-secondary-light">{edit.user_id}</p>
                        <div>
                            <label className="text-sm font-medium">Papel</label>
                            <select
                                className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3"
                                value={editRole}
                                onChange={(e) => setEditRole(e.target.value as "admin" | "read_only")}
                            >
                                <option value="admin">admin</option>
                                <option value="read_only">read_only</option>
                            </select>
                        </div>
                        {editRole === "read_only" && (
                            <div>
                                <label className="text-sm font-medium">Funil</label>
                                {orgFunnels.length > 0 ? (
                                    <select
                                        className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3 text-sm"
                                        value={editFunnelId}
                                        onChange={(e) => setEditFunnelId(e.target.value)}
                                    >
                                        <option value="">—</option>
                                        {orgFunnels.map((f) => (
                                            <option key={f.id} value={f.id}>
                                                {f.name} ({f.id.slice(0, 8)}…)
                                            </option>
                                        ))}
                                    </select>
                                ) : (
                                    <input
                                        className="mt-1 w-full h-10 rounded-xl border border-border-light dark:border-border-dark bg-white dark:bg-surface-dark px-3 text-sm font-mono"
                                        value={editFunnelId}
                                        onChange={(e) => setEditFunnelId(e.target.value)}
                                    />
                                )}
                            </div>
                        )}
                        <div className="flex justify-end gap-2 pt-2">
                            <button
                                type="button"
                                onClick={() => setEdit(null)}
                                className="h-10 px-4 rounded-xl border border-border-light dark:border-border-dark text-sm"
                            >
                                Cancelar
                            </button>
                            <button
                                type="button"
                                disabled={busy}
                                onClick={submitEdit}
                                className="h-10 px-4 rounded-xl bg-primary text-white text-sm font-semibold"
                            >
                                Salvar
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
