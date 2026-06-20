"use client";

import { useMemo, useState } from "react";

import type { N8nAgentsTreeResponse, N8nClientFolderNode } from "@/lib/api";

type StatusFilter = "all" | "active" | "inactive";

function matchesStatus(active: boolean, filter: StatusFilter) {
    if (filter === "active") return active;
    if (filter === "inactive") return !active;
    return true;
}

function filterFolder(
    folder: N8nClientFolderNode,
    status: StatusFilter,
    tag: string,
    folderKey: string
): N8nClientFolderNode | null {
    if (folderKey !== "all") {
        const key = `${folder.instance_id}:${folder.folder_id ?? folder.folder_name}`;
        if (key !== folderKey) return null;
    }
    const workflows = folder.workflows.filter((wf) => {
        if (!matchesStatus(wf.active, status)) return false;
        if (tag !== "all" && !wf.tags.includes(tag)) return false;
        return true;
    });
    const hasFilters = status !== "all" || tag !== "all" || folderKey !== "all";
    if (workflows.length === 0 && hasFilters) return null;

    const active_agents = workflows.filter((w) => w.is_agent && w.active).length;
    return { ...folder, workflows, total_workflows: workflows.length, active_agents };
}

function FolderRow({ folder }: { folder: N8nClientFolderNode }) {
    const [open, setOpen] = useState(false);

    return (
        <div className="border-b border-border-light/50 dark:border-border-dark/50 last:border-0">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-primary/5 transition-colors"
            >
                <span className="text-text-secondary-light w-4 shrink-0">{open ? "▾" : "▸"}</span>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium truncate">{folder.folder_name}</span>
                        <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full shrink-0">
                            {folder.instance_label}
                        </span>
                    </div>
                    <p className="text-xs text-text-secondary-light mt-0.5">
                        {folder.active_agents} agente{folder.active_agents !== 1 ? "s" : ""} ativo
                        {folder.active_agents !== 1 ? "s" : ""} · {folder.total_workflows} workflow
                        {folder.total_workflows !== 1 ? "s" : ""}
                    </p>
                </div>
                {folder.active_agents > 0 && (
                    <span className="text-sm font-semibold text-emerald-600 dark:text-emerald-400 shrink-0">
                        {folder.active_agents}
                    </span>
                )}
            </button>
            {open && (
                <ul className="pb-2 pl-11 pr-4 space-y-1">
                    {folder.workflows.map((wf) => (
                        <li key={wf.workflow_id} className="flex items-center gap-2 text-sm py-1 min-w-0">
                            <span
                                className={`w-2 h-2 rounded-full shrink-0 ${
                                    wf.active ? "bg-emerald-500" : "bg-slate-300 dark:bg-slate-600"
                                }`}
                                title={wf.active ? "Ativo" : "Inativo"}
                            />
                            {wf.is_agent && (
                                <span className="text-[10px] uppercase tracking-wide font-semibold text-violet-600 dark:text-violet-400 shrink-0">
                                    Agente
                                </span>
                            )}
                            {wf.n8n_url ? (
                                <a
                                    href={wf.n8n_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="truncate hover:text-primary hover:underline"
                                    onClick={(e) => e.stopPropagation()}
                                >
                                    {wf.workflow_name}
                                </a>
                            ) : (
                                <span className="truncate">{wf.workflow_name}</span>
                            )}
                            {wf.tags.length > 0 && (
                                <span className="text-[10px] text-text-secondary-light truncate hidden sm:inline">
                                    {wf.tags.join(", ")}
                                </span>
                            )}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

export default function N8nAgentsTree({ tree }: { tree: N8nAgentsTreeResponse | null }) {
    const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
    const [tagFilter, setTagFilter] = useState("all");
    const [folderFilter, setFolderFilter] = useState("all");

    const filtered = useMemo(() => {
        if (!tree) return null;
        const folders = tree.folders
            .map((f) => filterFolder(f, statusFilter, tagFilter, folderFilter))
            .filter((f): f is N8nClientFolderNode => f !== null);
        const activeAgents = folders.reduce((n, f) => n + f.active_agents, 0);
        return { folders, activeAgents };
    }, [tree, statusFilter, tagFilter, folderFilter]);

    if (!tree) {
        return <p className="text-sm text-text-secondary-light">Carregando árvore…</p>;
    }

    if (tree.folders.length === 0) {
        const errors = (tree.instances ?? []).filter((i) => i.status === "error" && i.error_message);
        return (
            <div className="text-sm space-y-2">
                <p className="text-text-secondary-light">
                    Nenhuma pasta encontrada.
                    {errors.length === 0 &&
                        " Verifique scopes workflow:list, folder:list e project:list nas API keys."}
                </p>
                {errors.map((inst) => (
                    <p key={inst.instance_id} className="text-red-600 dark:text-red-400 text-xs">
                        <strong>{inst.instance_label}:</strong> {inst.error_message}
                    </p>
                ))}
            </div>
        );
    }

    const tags = tree.available_tags ?? [];
    const folderOptions = tree.available_folders ?? [];

    return (
        <div>
            <div className="flex flex-col sm:flex-row sm:items-center gap-3 mb-4">
                <div className="flex items-center gap-4 text-sm flex-1">
                    <span>
                        <strong className="text-lg font-display">{filtered?.activeAgents ?? tree.total_active_agents}</strong>{" "}
                        <span className="text-text-secondary-light">agentes ativos</span>
                    </span>
                    <span className="text-text-secondary-light">
                        · {filtered?.folders.length ?? tree.total_folders} pasta
                        {(filtered?.folders.length ?? tree.total_folders) !== 1 ? "s" : ""}
                    </span>
                    {tree.cached && <span className="text-xs text-text-secondary-light">· cache</span>}
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                    <select
                        value={folderFilter}
                        onChange={(e) => setFolderFilter(e.target.value)}
                        className="text-sm rounded-xl border border-border-light dark:border-border-dark bg-transparent px-3 py-1.5 max-w-[220px]"
                        aria-label="Filtrar por pasta"
                    >
                        <option value="all">Todas as pastas</option>
                        {folderOptions.map((f) => {
                            const key = `${f.instance_id}:${f.folder_id ?? f.folder_name}`;
                            return (
                                <option key={key} value={key}>
                                    {f.folder_name} ({f.instance_label})
                                </option>
                            );
                        })}
                    </select>
                    <select
                        value={statusFilter}
                        onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
                        className="text-sm rounded-xl border border-border-light dark:border-border-dark bg-transparent px-3 py-1.5"
                        aria-label="Filtrar por status"
                    >
                        <option value="all">Todos os status</option>
                        <option value="active">Somente ativos</option>
                        <option value="inactive">Somente inativos</option>
                    </select>
                    <select
                        value={tagFilter}
                        onChange={(e) => setTagFilter(e.target.value)}
                        className="text-sm rounded-xl border border-border-light dark:border-border-dark bg-transparent px-3 py-1.5 max-w-[200px]"
                        aria-label="Filtrar por tag"
                    >
                        <option value="all">Todas as tags</option>
                        {tags.map((tag) => (
                            <option key={tag} value={tag}>
                                {tag}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {filtered && filtered.folders.length === 0 ? (
                <p className="text-sm text-text-secondary-light">Nenhum workflow corresponde aos filtros.</p>
            ) : (
                <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark overflow-hidden">
                    {(filtered?.folders ?? tree.folders).map((folder) => (
                        <FolderRow
                            key={`${folder.instance_id}-${folder.folder_id ?? folder.folder_name}`}
                            folder={folder}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
