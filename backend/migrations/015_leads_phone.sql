-- Telefone de exibição no card do Kanban (sincronizado com crm_clients.phones).
ALTER TABLE public.leads
    ADD COLUMN IF NOT EXISTS phone TEXT;
