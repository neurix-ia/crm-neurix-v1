-- Cancelamento de campanhas do Comunicados + vínculo com execução n8n

ALTER TABLE public.dispatch_campaigns
    ADD COLUMN IF NOT EXISTS n8n_execution_id TEXT;

-- Recria CHECK de status incluindo cancelled
ALTER TABLE public.dispatch_campaigns
    DROP CONSTRAINT IF EXISTS dispatch_campaigns_status_check;

ALTER TABLE public.dispatch_campaigns
    ADD CONSTRAINT dispatch_campaigns_status_check
    CHECK (status IN ('draft', 'running', 'done', 'failed', 'cancelled'));
