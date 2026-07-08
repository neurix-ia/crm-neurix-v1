-- Carrinho/pedido persistido no card do Kanban.
-- `leads.products_json` existia em produção mas nunca foi capturada em migration
-- (drift prod/staging). Sem ela, o intent `pedido` (n8n_webhook) falha ao gravar
-- e o valor do pedido fica R$ 0,00. Idempotente.
ALTER TABLE public.leads
    ADD COLUMN IF NOT EXISTS products_json JSONB NOT NULL DEFAULT '[]'::jsonb;
