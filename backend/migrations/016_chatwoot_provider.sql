-- Sprint 14 — Provedor de canal por inbox (Uazapi | Chatwoot) + mapeamento etiqueta->etapa.
-- Idempotente. NAO altera o comportamento Uazapi: provider default 'uazapi' faz backfill
-- automatico das caixas existentes; uazapi_settings permanece intacto.

-- =============================================================================
-- 1) INBOXES: provider + chatwoot_settings
--    chatwoot_settings guarda: base_url, account_id, inbox_id, api_access_token,
--    webhook_secret (HMAC), phone_number_id.
-- =============================================================================
ALTER TABLE public.inboxes
    ADD COLUMN IF NOT EXISTS provider TEXT NOT NULL DEFAULT 'uazapi',
    ADD COLUMN IF NOT EXISTS chatwoot_settings JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'inboxes_provider_check'
    ) THEN
        ALTER TABLE public.inboxes
            ADD CONSTRAINT inboxes_provider_check
            CHECK (provider IN ('uazapi', 'chatwoot'));
    END IF;
END $$;

-- =============================================================================
-- 2) PIPELINE_STAGES: source_label
--    Etiqueta do Chatwoot que originou/mapeia a etapa (coluna). Convencao:
--    nome da etiqueta == identificador da etapa (ex.: '01-interessado').
-- =============================================================================
ALTER TABLE public.pipeline_stages
    ADD COLUMN IF NOT EXISTS source_label TEXT;

-- 1 etiqueta <-> 1 etapa por funil (idempotencia da criacao automatica de coluna).
CREATE UNIQUE INDEX IF NOT EXISTS uq_pipeline_stages_funnel_source_label
    ON public.pipeline_stages(funnel_id, source_label)
    WHERE source_label IS NOT NULL;

-- =============================================================================
-- 3) CHAT_MESSAGES: origem e id de conversa externa (Chatwoot)
--    external_conversation_id = conversation.id do Chatwoot (usado para responder
--    via Application API e para correlacionar o espelho).
-- =============================================================================
ALTER TABLE public.chat_messages
    ADD COLUMN IF NOT EXISTS external_provider TEXT,
    ADD COLUMN IF NOT EXISTS external_conversation_id TEXT;

CREATE INDEX IF NOT EXISTS idx_chat_messages_external_conversation
    ON public.chat_messages(external_conversation_id);
