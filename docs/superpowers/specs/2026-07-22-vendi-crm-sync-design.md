# Vendi — sync CRM Neurix + poll / Atualizar agora

**Data:** 2026-07-22  
**Status:** implementado (código + workflow n8n publicados; confirmar envs `CRM_API_URL` / `VENDI_TENANT_ID` / `N8N_API_KEY` e migration `022` no Supabase)

## Problema

1. O workflow n8n **VENDI - Registro de Venda de Rua** (`ERMqbe3LFvgeGYOe`) grava no Twenty e na Data Table, mas **não** chama o Neurix. O dashboard `/vendi` lê `street_sales` e fica vazio / em erro.
2. O feed precisa de refresh manual fora da janela de poll (07h–19h BRT).

## Objetivo

- Cada venda registrada no app também é persistida no Neurix (`street_sales` + upsert `crm_clients`).
- Dashboard: poll automático a cada 15 min (07–19 BRT) + botão **Atualizar agora** (refresh imediato, qualquer horário).
- Sync Twenty permanece (caminho paralelo; Neurix não o substitui).

## Fluxo

```
/vendi/nova → webhook n8n vendi-registro
  → STT / placa / Twenty (people + notes)
  → Data Table VENDI_Vendas
  → POST {CRM_API_URL}/api/n8n/vendi  (X-CRM-API-Key)
  → street_sales + crm_clients
Dashboard /vendi ← GET /api/vendi/sales (JWT)
```

## Contrato ingest (n8n → Neurix)

`POST /api/n8n/vendi` — ver [`docs/vendi-n8n-ingest.md`](../../vendi-n8n-ingest.md).

Campos principais: `tenant_id` (`$env.VENDI_TENANT_ID`), `seller_name`, phones / `match_status`, qtys, `transcript`, `sold_at`, `metadata` (`placa`, `twenty_person_id`, `source`).

Nesta entrega: `photo_url` / `audio_url` = `null` (base64 fica no n8n/Data Table). Upload Storage no Neurix fica fora de escopo.

Se o HTTP CRM falhar: `continueOnFail` — Twenty/Data Table/resposta ao app não quebram.

## UI dashboard

| Mecanismo | Comportamento |
|-----------|----------------|
| Poll automático | A cada 15 min, só entre 07:00–19:00 America/Sao_Paulo; delta por `since`; erros silenciosos |
| **Atualizar agora** | `loadPeriod()` + clientes; refresh completo do período; **sem** restrição de horário; erros no banner |

## Backend listagem

`GET /api/vendi/sales` deve devolver detalhe claro se `street_sales` estiver ausente ou o Supabase falhar (não só “Internal Server Error”). Migration: `022_street_sales.sql`.

## Fora de escopo

- Upload de foto/áudio para Storage Neurix
- Substituir Twenty pelo Neurix
- Alterar formulário do vendedor (`/vendi/nova`)

## Ops pós-deploy

1. n8n Variables: `CRM_API_URL`, `VENDI_TENANT_ID`, `N8N_API_KEY` (mesmo valor do backend).
2. Supabase: garantir migration [`022_street_sales.sql`](../../../backend/migrations/022_street_sales.sql) aplicada.
3. Smoke: registrar venda → nó `Enviar CRM Neurix` 2xx → **Atualizar agora** no `/vendi` mostra a venda.

- Venda no app → aparece em Twenty **e** em `street_sales`
- `/vendi` sem 500; KPIs/feed atualizam com **Atualizar agora** ou no próximo poll
- SPEC + docs de ingest alinhados ao workflow publicado
