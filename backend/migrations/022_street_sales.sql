-- 022_street_sales.sql — Vendi: vendas de rua (Levíssimo)

BEGIN;

CREATE TABLE IF NOT EXISTS public.street_sales (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    seller_name          TEXT NOT NULL,
    seller_user_id       UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    client_id            UUID REFERENCES public.crm_clients(id) ON DELETE SET NULL,
    order_id             UUID REFERENCES public.orders(id) ON DELETE SET NULL,
    phone_typed          TEXT,
    phone_from_audio     TEXT,
    phone_final          TEXT NOT NULL,
    match_status         TEXT NOT NULL DEFAULT 'typed_only'
        CHECK (match_status IN ('match', 'mismatch', 'audio_only', 'typed_only', 'no_phone')),
    transcript           TEXT,
    photo_url            TEXT,
    audio_url            TEXT,
    pao_italiano_qtd     INTEGER NOT NULL DEFAULT 0 CHECK (pao_italiano_qtd >= 0),
    pao_integral_qtd     INTEGER NOT NULL DEFAULT 0 CHECK (pao_integral_qtd >= 0),
    geolocation          JSONB,
    sold_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata             JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_street_sales_tenant_sold
    ON public.street_sales (tenant_id, sold_at DESC);

CREATE INDEX IF NOT EXISTS idx_street_sales_tenant_phone
    ON public.street_sales (tenant_id, phone_final);

CREATE INDEX IF NOT EXISTS idx_street_sales_client
    ON public.street_sales (client_id)
    WHERE client_id IS NOT NULL;

ALTER TABLE public.street_sales ENABLE ROW LEVEL SECURITY;

CREATE POLICY street_sales_select ON public.street_sales
    FOR SELECT USING (auth.uid() = tenant_id);
CREATE POLICY street_sales_insert ON public.street_sales
    FOR INSERT WITH CHECK (auth.uid() = tenant_id);
CREATE POLICY street_sales_update ON public.street_sales
    FOR UPDATE USING (auth.uid() = tenant_id);
CREATE POLICY street_sales_delete ON public.street_sales
    FOR DELETE USING (auth.uid() = tenant_id);

COMMIT;
