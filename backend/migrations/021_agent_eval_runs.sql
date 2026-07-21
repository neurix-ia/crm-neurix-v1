-- 021_agent_eval_runs.sql — Histórico de runs da suíte de evals (DeepEval) por agente
--
-- Cada linha é um run completo da bateria contra um agente (workflow n8n).
-- `result` guarda o JSON integral devolvido pelo deep-eval (/result/{job_id}),
-- `suggestions` guarda as recomendações geradas por LLM no pipeline n8n.
-- Ingestão: POST /api/n8n/reports/agent-eval (X-CRM-API-Key).
-- Leitura: GET /api/admin/agent-evals (superadmin).

CREATE TABLE IF NOT EXISTS public.agent_eval_runs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_key    TEXT NOT NULL,                  -- workflow id do n8n (ex.: KEUoND3ozFD2MTco)
    agent_name   TEXT NOT NULL,
    job_id       TEXT NOT NULL,                  -- job_id do deep-eval (idempotência)
    mode         TEXT NOT NULL DEFAULT 'baseline',  -- baseline | mangle
    pass_rate    NUMERIC(5,4),                   -- 0..1
    total        INTEGER NOT NULL DEFAULT 0,
    passed       INTEGER NOT NULL DEFAULT 0,
    result       JSONB NOT NULL DEFAULT '{}',    -- dict completo do /result (test_cases + summary)
    suggestions  JSONB NOT NULL DEFAULT '[]',    -- [{severidade, problema, recomendacao}]
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (job_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_eval_runs_agent
    ON public.agent_eval_runs(agent_key, created_at DESC);

-- RLS: sem policies de usuário — tabela é operada apenas pelo backend
-- (service role, bypassa RLS) e lida somente por superadmin via API.
ALTER TABLE public.agent_eval_runs ENABLE ROW LEVEL SECURITY;
