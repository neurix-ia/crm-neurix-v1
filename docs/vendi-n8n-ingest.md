# Vendi — ingest n8n → CRM

**Status:** integrado no workflow **VENDI - Registro de Venda de Rua** (`ERMqbe3LFvgeGYOe`) — nós `Preparar Payload CRM Neurix` + `Enviar CRM Neurix` (após Data Table; `continueOnFail` se o CRM falhar).

O app do vendedor continua enviando base64 para o webhook:

`POST https://n8n-neurix-1.wbtech.dev/webhook/vendi-registro`

O workflow, após STT + Twenty + Data Table:

1. Extrai telefone (digitado / falado) e define `match_status`.
2. Chama o CRM:

```
POST {CRM_BASE_URL}/api/n8n/vendi
Header: X-CRM-API-Key: {N8N_API_KEY}
Content-Type: application/json
```

## Body esperado

```json
{
  "tenant_id": "<uuid do admin/tenant Levíssimo>",
  "seller_name": "Maria",
  "seller_user_id": null,
  "phone_typed": "41999999999",
  "phone_from_audio": "41999999999",
  "phone_final": "41999999999",
  "match_status": "match",
  "transcript": "texto do whisper...",
  "photo_url": null,
  "audio_url": null,
  "pao_italiano_qtd": 2,
  "pao_integral_qtd": 1,
  "sold_at": "2026-07-21T15:30:00.000Z",
  "geolocation": null,
  "metadata": {
    "source": "n8n-vendi",
    "placa": "ABC1D23",
    "twenty_person_id": "..."
  },
  "client_display_name": null
}
```

Nesta entrega `photo_url` / `audio_url` ficam `null` (base64 permanece na Data Table). Upload Storage no Neurix: fora de escopo (ver SPEC `docs/superpowers/specs/2026-07-22-vendi-crm-sync-design.md`).

## Resposta

```json
{
  "status": "ok",
  "sale_id": "...",
  "client_id": "...",
  "phone_final": "41999999999",
  "match_status": "match",
  "message": "Venda registrada"
}
```

Se `match_status` / `phone_final` forem omitidos, o CRM deriva a partir de `phone_typed` e `phone_from_audio` (áudio tem prioridade sobre digitado).

## Auth / URLs (self-hosted, sem env vars)

| Item | Valor |
|------|--------|
| URL HTTP | `https://crm.wbtech.dev/api/n8n/vendi` (fixa no nó) |
| Auth | Generic → **Header Auth** → credencial **CRM API Key** |
| `tenant_id` | Constante `TENANT_ID` no nó **Preparar Payload CRM Neurix** (UUID Levíssimo) |

O MCP não consegue anexar `httpHeaderAuth` via API — selecionar a credencial **CRM API Key** no nó `Enviar CRM Neurix` na UI (Authentication já está em Header Auth).

## Referência do Code node

Trecho reutilizável: [`docs/vendi-n8n-code-node.js`](vendi-n8n-code-node.js) (ajustado no workflow aos campos reais: `vendedor`, `cliente_whatsapp_*`, `transcricao`, `timestamp_venda`, `placa`, `twenty_person_id`).
