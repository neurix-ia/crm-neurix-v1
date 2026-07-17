-- 020_org_menu_config.sql
-- Menu lateral do app do tenant, configurável por organização (Console Admin).

BEGIN;

ALTER TABLE public.organizations
    ADD COLUMN IF NOT EXISTS menu_config JSONB NOT NULL DEFAULT '{}'::jsonb;

COMMENT ON COLUMN public.organizations.menu_config IS
    'Flags de itens do menu lateral (dashboard, kanban, clientes, produtos, comunicados, relatorios, configuracoes). {} = defaults do backend.';

COMMIT;
