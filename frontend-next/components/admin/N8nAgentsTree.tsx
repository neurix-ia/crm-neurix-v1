"use client";

import { useState } from "react";

import type { N8nAgentsTreeResponse, N8nClientFolderNode } from "@/lib/api";

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
                        <li key={wf.workflow_id} className="flex items-center gap-2 text-sm py-1">
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
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

export default function N8nAgentsTree({ tree }: { tree: N8nAgentsTreeResponse | null }) {
    if (!tree) {
        return <p className="text-sm text-text-secondary-light">Carregando árvore…</p>;
    }

    if (tree.folders.length === 0) {
        return (
            <p className="text-sm text-text-secondary-light">
                Nenhuma pasta encontrada — verifique scopes workflow:list e folder:list nas API keys.
            </p>
        );
    }

    return (
        <div>
            <div className="flex items-center gap-4 mb-4 text-sm">
                <span>
                    <strong className="text-lg font-display">{tree.total_active_agents}</strong>{" "}
                    <span className="text-text-secondary-light">agentes ativos</span>
                </span>
                <span className="text-text-secondary-light">
                    · {tree.total_folders} pasta{tree.total_folders !== 1 ? "s" : ""}
                </span>
                {tree.cached && (
                    <span className="text-xs text-text-secondary-light">· cache</span>
                )}
            </div>
            <div className="glass-effect rounded-2xl border border-border-light dark:border-border-dark overflow-hidden">
                {tree.folders.map((folder) => (
                    <FolderRow
                        key={`${folder.instance_id}-${folder.folder_id ?? folder.folder_name}`}
                        folder={folder}
                    />
                ))}
            </div>
        </div>
    );
}
