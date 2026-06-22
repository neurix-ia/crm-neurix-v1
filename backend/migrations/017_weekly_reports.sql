-- 017_weekly_reports.sql — Relatórios semanais de atendimento

CREATE TABLE IF NOT EXISTS public.client_report_config (
    tenant_id        UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    spreadsheet_id   TEXT NOT NULL,
    worksheet        TEXT NOT NULL DEFAULT 'Conversas',
    date_column      TEXT NOT NULL DEFAULT 'data',
    agent_keys       JSONB NOT NULL DEFAULT '[]',
    notify_whatsapp  TEXT,
    timezone         TEXT NOT NULL DEFAULT 'America/Sao_Paulo',
    enabled          BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.weekly_reports (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    week_key             TEXT NOT NULL,
    week_start           TIMESTAMPTZ NOT NULL,
    week_end             TIMESTAMPTZ NOT NULL,
    metrics              JSONB NOT NULL,
    problema_principal   TEXT NOT NULL,
    solucao_recomendada  TEXT NOT NULL,
    acoes                JSONB NOT NULL DEFAULT '[]',
    sheet_ref            JSONB NOT NULL DEFAULT '{}',
    status               TEXT NOT NULL DEFAULT 'draft',
    notified_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, week_key)
);
CREATE INDEX IF NOT EXISTS idx_weekly_reports_tenant ON public.weekly_reports(tenant_id, week_start DESC);

CREATE TABLE IF NOT EXISTS public.agent_improvement_reports (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_key     TEXT NOT NULL,
    agent_name    TEXT NOT NULL,
    tenant_id     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    week_key      TEXT NOT NULL,
    week_start    TIMESTAMPTZ NOT NULL,
    week_end      TIMESTAMPTZ NOT NULL,
    severidade    TEXT NOT NULL DEFAULT 'media',
    problema      TEXT NOT NULL,
    recomendacoes JSONB NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'aberto',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_key, week_key)
);
CREATE INDEX IF NOT EXISTS idx_agent_reports_week ON public.agent_improvement_reports(week_start DESC);

-- ============================================================
-- Row Level Security (tenant isolation — mirrors migration 001)
-- ============================================================
ALTER TABLE public.client_report_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.weekly_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_improvement_reports ENABLE ROW LEVEL SECURITY;

CREATE POLICY client_report_config_select ON public.client_report_config FOR SELECT USING (auth.uid() = tenant_id);
CREATE POLICY client_report_config_insert ON public.client_report_config FOR INSERT WITH CHECK (auth.uid() = tenant_id);
CREATE POLICY client_report_config_update ON public.client_report_config FOR UPDATE USING (auth.uid() = tenant_id);
CREATE POLICY client_report_config_delete ON public.client_report_config FOR DELETE USING (auth.uid() = tenant_id);

CREATE POLICY weekly_reports_select ON public.weekly_reports FOR SELECT USING (auth.uid() = tenant_id);
CREATE POLICY weekly_reports_insert ON public.weekly_reports FOR INSERT WITH CHECK (auth.uid() = tenant_id);
CREATE POLICY weekly_reports_update ON public.weekly_reports FOR UPDATE USING (auth.uid() = tenant_id);
CREATE POLICY weekly_reports_delete ON public.weekly_reports FOR DELETE USING (auth.uid() = tenant_id);

CREATE POLICY agent_improvement_reports_select ON public.agent_improvement_reports FOR SELECT USING (auth.uid() = tenant_id);
CREATE POLICY agent_improvement_reports_insert ON public.agent_improvement_reports FOR INSERT WITH CHECK (auth.uid() = tenant_id);
CREATE POLICY agent_improvement_reports_update ON public.agent_improvement_reports FOR UPDATE USING (auth.uid() = tenant_id);
CREATE POLICY agent_improvement_reports_delete ON public.agent_improvement_reports FOR DELETE USING (auth.uid() = tenant_id);
