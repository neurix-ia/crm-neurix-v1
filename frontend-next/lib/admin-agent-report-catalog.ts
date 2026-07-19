/** Catálogo de agentes na tela superadmin de saúde/relatórios. */

export type AdminAgentReportEntry = {
    id: string;
    label: string;
    /** Workflow IDs n8n usados como agent_key nos relatórios. */
    agentKeys: string[];
    /** Tem (ou terá) geração semanal ligada; botões sem dados mostram empty state. */
    hasWeeklyPipeline: boolean;
};

export const ADMIN_AGENT_REPORT_CATALOG: AdminAgentReportEntry[] = [
    {
        id: "ely-flex",
        label: "Ely Flex",
        agentKeys: ["NhL2pBGEXBn8sGXi"],
        hasWeeklyPipeline: true,
    },
    {
        id: "arpa-renova",
        label: "Arpa (+ Renova Green)",
        agentKeys: ["Yp8DuEmqb0Z43ahnJy6Gs", "GPOZxMZ0lF4w6m7w"],
        hasWeeklyPipeline: true,
    },
    {
        id: "emporio",
        label: "Empório",
        agentKeys: ["DTJgDB8jPfBrk8EA"],
        hasWeeklyPipeline: true,
    },
    {
        id: "chef-gourmet-cwb",
        label: "Chef Gourmet CWB",
        agentKeys: ["Puc7SfP5n50BOd8o"],
        hasWeeklyPipeline: false,
    },
    {
        id: "thamy-festas",
        label: "Thamy Festas",
        agentKeys: ["MBbJw7WFUgNk0Oh1"],
        hasWeeklyPipeline: false,
    },
    {
        id: "levissimo",
        label: "Levissimo",
        agentKeys: ["KEUoND3ozFD2MTco"],
        hasWeeklyPipeline: false,
    },
    {
        id: "top-mundi",
        label: "Top Mundi",
        agentKeys: ["z8ZsBhVd9f1QjJ8x"],
        hasWeeklyPipeline: false,
    },
    {
        id: "condo-up",
        label: "Condo UP",
        agentKeys: ["pmT8VXyu5lPF5dvW"],
        hasWeeklyPipeline: false,
    },
    {
        id: "villa-dora",
        label: "Villa Dora",
        agentKeys: ["XDtXohhHve2uJRSK"],
        hasWeeklyPipeline: false,
    },
    {
        id: "evo-health-21",
        label: "Evo Health 21",
        agentKeys: ["eie7Pks84N6XLmfS"],
        hasWeeklyPipeline: false,
    },
];

export function findAdminAgentById(id: string | null | undefined): AdminAgentReportEntry | undefined {
    if (!id) return undefined;
    return ADMIN_AGENT_REPORT_CATALOG.find((a) => a.id === id);
}
