# Vendi — ingest n8n → CRM

O app do vendedor continua enviando base64 para o webhook:

`POST https://n8n-neurix-1.wbtech.dev/webhook/vendi-registro`

O workflow **VENDI - Registro de Venda de Rua** (`ERMqbe3LFvgeGYOe`) deve, após STT + upload Storage:

1. Extrair telefone da transcrição (se houver áudio).
2. Definir `phone_final`: áudio se válido, senão digitado.
3. Definir `match_status`: `match` | `mismatch` | `audio_only` | `typed_only` | `no_phone`.
4. Chamar o CRM:

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
  "photo_url": "https://.../placa.jpg",
  "audio_url": "https://.../audio.webm",
  "pao_italiano_qtd": 2,
  "pao_integral_qtd": 1,
  "sold_at": "2026-07-21T15:30:00.000Z",
  "geolocation": null,
  "metadata": {},
  "client_display_name": null
}
```

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

## Passo a passo no n8n (MCP bloqueado neste workflow)

1. Abrir workflow **VENDI - Registro de Venda de Rua**.
2. Após STT + upload, adicionar **Code** com o conteúdo de [`docs/vendi-n8n-code-node.js`](vendi-n8n-code-node.js).
3. Adicionar **HTTP Request**:
   - Method: POST
   - URL: `{{$env.CRM_API_URL}}/api/n8n/vendi` (ex. `https://crm.../api/n8n/vendi`)
   - Header `X-CRM-API-Key` = credencial/`N8N_API_KEY`
   - Body: JSON do Code node
4. Definir env `VENDI_TENANT_ID` (uuid do tenant Levíssimo) se o Code usar `$env.VENDI_TENANT_ID`.
5. Publicar o workflow.

Para editar via MCP depois: em Settings do workflow, habilitar **Available in MCP**.

