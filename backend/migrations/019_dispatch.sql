-- Disparador CRM: membros, campanhas e targets (multi-tenant por tenant_id = auth.users.id)

CREATE TABLE IF NOT EXISTS public.dispatch_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    phone_e164 TEXT NOT NULL,
    extra JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, phone_e164)
);

CREATE INDEX IF NOT EXISTS idx_dispatch_members_tenant ON public.dispatch_members(tenant_id);

CREATE TABLE IF NOT EXISTS public.dispatch_campaigns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'running', 'done', 'failed')),
    min_delay INT NOT NULL DEFAULT 15,
    max_delay INT NOT NULL DEFAULT 21,
    total INT NOT NULL DEFAULT 0,
    sent INT NOT NULL DEFAULT 0,
    failed INT NOT NULL DEFAULT 0,
    instance_token TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_dispatch_campaigns_tenant ON public.dispatch_campaigns(tenant_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_campaigns_status ON public.dispatch_campaigns(status);

CREATE TABLE IF NOT EXISTS public.dispatch_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    campaign_id UUID NOT NULL REFERENCES public.dispatch_campaigns(id) ON DELETE CASCADE,
    member_id UUID REFERENCES public.dispatch_members(id) ON DELETE SET NULL,
    tenant_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name TEXT NOT NULL DEFAULT '',
    phone_e164 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sent', 'failed')),
    error TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dispatch_targets_campaign ON public.dispatch_targets(campaign_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_targets_status ON public.dispatch_targets(campaign_id, status);
