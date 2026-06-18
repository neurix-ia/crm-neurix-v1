# Plano — Integração WhatsApp API Oficial via Chatwoot (espelhamento em tempo real + etiquetas → etapas)

> Status: proposta para aplicar em `main`. Decisões confirmadas com o produto:
> 1. **Etiqueta do Chatwoot → nova etapa (coluna)** dentro do funil do inbox Chatwoot.
> 2. **Multi-provedor**: Chatwoot convive com a Uazapi (cada inbox escolhe `provider`). Uazapi permanece intacta.
> 3. **Bidirecional**: o CRM recebe mensagens/etiquetas em tempo real **e** envia respostas via API do Chatwoot.

---

## 1. Contexto: como o CRM funciona hoje

Fluxo de entrada (Uazapi):

```
WhatsApp → Uazapi → POST /api/webhooks/uazapi?secret=XXX
        → Redis queue → webhook_processor (worker)
        → chat_messages (Supabase) + keyword_engine + lead_board (move etapa)
        → Supabase Realtime/polling → Kanban (frontend-next)
```

Fluxo de saída (Uazapi): `POST /api/leads/{id}/messages/send` → `uazapi_service` → WhatsApp.

Modelo de dados relevante:

- `inboxes (id, tenant_id, funnel_id, name, uazapi_settings JSONB)` — **um funil por inbox**.
- `funnels` → `pipeline_stages (funnel_id, name, slug, order_position)` — funil = aba; etapa = coluna.
- `leads (stage, funnel_id, inbox_id)`, `lead_pipeline_positions`, `chat_messages`.
- Conexão na UI: `InboxConnectModal` em `frontend-next/app/(dashboard)/configuracoes/page.tsx` (abas QR / token manual).
- Resolução inbox↔instância: `webhook_lead_context.py` (`find_inbox_by_instance_token` / `_name`).

O modal e o webhook da Uazapi são o molde que vamos replicar para o Chatwoot.

## 2. O que o Chatwoot exige (resumo da documentação)

**Canal WhatsApp Cloud API (oficial, Meta).** No Chatwoot cria-se um *inbox* do tipo WhatsApp Cloud API, fornecendo: `phone_number_id`, `business_account_id` (WABA), `api_key` (token permanente de System User Meta) e um `webhook_verify_token`. A própria Meta entrega as mensagens ao Chatwoot — o CRM **não** fala com a Meta; fala com o Chatwoot. ([setup](https://www.chatwoot.com/hc/user-guide/articles/1677832735-how-to-setup-a-whats_app-channel), [manual flow](https://www.chatwoot.com/hc/user-guide/articles/1756799850-how-to-setup-a-whats_app-channel-manual-flow))

**Entrada no CRM — webhooks do Chatwoot.** O Chatwoot dispara webhooks para uma URL nossa nos eventos: `message_created`, `message_updated`, `conversation_created`, `conversation_updated` (inclui `changed_attributes` com mudanças de **labels**), `conversation_status_changed`, `contact_created/updated`. É a fonte do espelhamento em tempo real. ([webhooks](https://www.chatwoot.com/hc/user-guide/articles/1677693021-how-to-use-webhooks))

**Saída do CRM — Application API.** Enviar resposta:
`POST {chatwoot_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages`
header `api_access_token: <token>`, body `{ content, message_type: "outgoing", content_type, ... }`. Anexos via `multipart/form-data` campo `attachments[]`. ([create message](https://developers.chatwoot.com/api-reference/messages/create-new-message))

**Etiquetas (labels).**
- Lista de labels da conta: `GET /api/v1/accounts/{account_id}/labels`.
- Labels de uma conversa: `GET`/`POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/labels`.
- Mudança de labels chega em `conversation_updated`. **Não existe evento dedicado de "label criada"**; uma etiqueta nova é detectada quando aparece pela primeira vez num `conversation_updated`/`conversation_created` (ou via sync periódico do endpoint de labels).

> ⚠️ A forma exata do payload de labels (`labels` no objeto da conversa vs. dentro de `changed_attributes`) varia por versão do Chatwoot. Antes de codar o parser, **fazer um POST real de teste** do Chatwoot para um endpoint de captura e inspecionar o JSON (ver Fase 0).

## 3. Arquitetura proposta (reaproveita o pipeline da Uazapi)

```
WhatsApp ⇄ Meta Cloud API ⇄ Chatwoot (inbox WhatsApp oficial)
   │ (webhook)                         ▲ (Application API: enviar)
   ▼                                   │
POST /api/webhooks/chatwoot?secret=XXX │
   → Redis queue (mesma fila)          │
   → webhook_processor (novo branch p/ eventos Chatwoot)
   → chat_messages + mapeamento label→etapa + lead_board
   → Supabase Realtime → Kanban
                                       │
CRM UI → POST /api/leads/{id}/messages/send (roteia p/ provider do inbox)
   → chatwoot_service.send_message ────┘
```

Princípio-chave: **`provider` no inbox**. `uazapi_settings` continua; adiciona-se `provider ∈ {uazapi, chatwoot}` e um `chatwoot_settings JSONB`. Todo ponto que hoje assume Uazapi passa a checar `provider` e despachar para o serviço certo.

## 4. Mudanças por camada

### 4.1 Banco de dados (nova migração `016_chatwoot_provider.sql`)

- `ALTER TABLE inboxes ADD COLUMN provider TEXT NOT NULL DEFAULT 'uazapi'` (`CHECK (provider IN ('uazapi','chatwoot'))`).
- `ALTER TABLE inboxes ADD COLUMN chatwoot_settings JSONB NOT NULL DEFAULT '{}'::jsonb`
  guarda: `base_url`, `account_id`, `inbox_id` (do Chatwoot), `api_access_token`, `webhook_secret`, `phone_number_id`.
- `chat_messages`: adicionar `external_provider TEXT` e `external_conversation_id TEXT` (id da conversa no Chatwoot) — `whatsapp_chat_id`/`whatsapp_message_id` continuam servindo como chave natural.
- `pipeline_stages`: adicionar `source_label TEXT NULL` — marca etapas criadas a partir de uma etiqueta do Chatwoot (idempotência: 1 label ↔ 1 etapa por funil; `UNIQUE (funnel_id, source_label)`).
- Tudo idempotente (`IF NOT EXISTS`), seguindo o padrão das migrações existentes.

### 4.2 Backend — novos arquivos / endpoints

**`app/services/chatwoot_service.py`** (espelha `uazapi_service.py`):
- `verify_credentials()` — `GET /api/v1/accounts/{id}/labels` ou `/conversations` para validar token/URL.
- `send_text()` / `send_media()` — Application API.
- `list_labels()`, `add_conversation_label()`.
- `get_conversation()` — para resolver contato/telefone.

**`app/routers/chatwoot.py`** (espelha `whatsapp.py`, prefixo `/api/chatwoot`):
- `POST /connect` — salva `chatwoot_settings` no inbox e valida credenciais.
- `GET /status` — testa conexão (verde/vermelho no modal).
- `DELETE /disconnect`.

**`app/routers/webhooks.py`** — adicionar `POST /chatwoot`:
- valida `?secret=` (mesmo mecanismo do `_validate_webhook_secret`, novo `CHATWOOT_WEBHOOK_SECRET`);
- enfileira no Redis com envelope `{"source": "chatwoot", "payload": ...}`.

**`app/workers/webhook_processor.py`** — ramificar por `source`:
- `chatwoot.message_created` → extrair texto/mídia (parser próprio do formato Chatwoot, diferente do Baileys/Uazapi), normalizar telefone, resolver/criar lead via `inbox` (achado por `chatwoot_settings.inbox_id` no payload), gravar em `chat_messages` com `direction` por `message_type` (`incoming`/`outgoing`).
- `chatwoot.conversation_created` / `conversation_updated` → ler labels da conversa e aplicar **etiqueta → etapa** (4.4).

**`app/services/webhook_lead_context.py`** — novas funções `find_inbox_by_chatwoot_inbox_id(account_id, inbox_id)` e helpers de etapa.

**`app/routers/leads.py`** — em `/{lead_id}/messages/send`: ler `inbox.provider`; se `chatwoot`, chamar `chatwoot_service` (mantém Uazapi como está). Mesmo para `GET /{lead_id}/messages` (histórico).

**`app/config.py`** — `CHATWOOT_WEBHOOK_SECRET` (+ defaults). Credenciais por inbox ficam em `chatwoot_settings`, não no `.env`.

### 4.3 Frontend — modal específico do Chatwoot

Em `configuracoes/page.tsx`:
- Ao criar/editar inbox, **seletor de provedor** (Uazapi | WhatsApp Oficial/Chatwoot).
- Novo componente `ChatwootConnectModal` (irmão de `InboxConnectModal`), com campos: `base_url`, `account_id`, `inbox_id`, `api_access_token`; botão **Testar conexão** (`GET /api/chatwoot/status`) e exibição da URL de webhook a colar no Chatwoot (`/api/webhooks/chatwoot?secret=...`).
- `lib/api.ts`: funções `connectChatwoot`, `getChatwootStatus`, `disconnectChatwoot`.
- Kanban: nenhuma mudança estrutural — as etapas criadas a partir de labels aparecem como colunas normais (badge opcional "via etiqueta").

### 4.4 Etiqueta → etapa (coluna) — regra central

Quando um evento de conversa do Chatwoot traz labels:
1. resolver o `inbox` (e portanto o `funnel_id`) pelo `account_id` + `inbox_id` do payload;
2. para cada label da conversa, procurar `pipeline_stages` com `(funnel_id, source_label = label)`;
3. se não existir, **criar a etapa** (nome = label, `order_position` = última+1, `source_label` = label) — é o "cria-se nova aba/coluna respectiva";
4. mover o lead para a etapa correspondente à label "ativa" (definir precedência quando há várias labels — sugestão: última alterada em `changed_attributes`, ou prioridade configurável), reusando `lead_board.move`.

Idempotência garante que reprocessar o mesmo webhook não duplica etapas. Labels removidas **não** apagam a coluna (evita perder histórico) — opcionalmente arquivá-la.

### 4.5 Tempo real

Mantém-se o mecanismo atual: worker grava em `chat_messages`/`leads` → **Supabase Realtime** já consumido pelo Kanban propaga a mudança. Ou seja, "tempo real" = latência do webhook Chatwoot + fila Redis (sub-segundo na prática). Nenhuma nova infra de WebSocket é necessária.

## 5. Fases de execução

- **Fase 0 — Spike de payload (meio dia).** Configurar um inbox WhatsApp Cloud API de teste no Chatwoot, apontar webhook para um endpoint de captura e salvar exemplos reais de `message_created` e `conversation_updated` (com labels). Validar o formato antes de escrever parsers. **Bloqueia 4.2/4.4.**
- **Fase 1 — DB + multi-provedor.** Migração `016`, campo `provider`, `chatwoot_settings`. Garantir que Uazapi continua 100% funcional (`provider='uazapi'` default).
- **Fase 2 — Conexão.** `chatwoot_service`, router `/api/chatwoot`, `ChatwootConnectModal`, seletor de provedor. Critério: testar conexão fica verde.
- **Fase 3 — Espelhamento de entrada.** `POST /api/webhooks/chatwoot`, branch no worker, gravar `chat_messages`, ver mensagens no Kanban em tempo real.
- **Fase 4 — Etiqueta → etapa.** Lógica 4.4 + migração da coluna `source_label`.
- **Fase 5 — Envio (bidirecional).** Rotear `messages/send` por `provider`; testar resposta saindo do CRM e chegando no WhatsApp via Chatwoot.
- **Fase 6 — Verificação.** Testes (ver §7), doc `docs/chatwoot_webhook_setup.md` espelhando o `uazapi_webhook_setup.md`, validação em staging (`docs/staging-setup.md`) antes de `main`.

## 6. Riscos e decisões em aberto

- **Formato do payload de labels** varia por versão do Chatwoot → mitigado pela Fase 0.
- **Loop de eco**: mensagem enviada pelo CRM volta como `message_created` `outgoing`. Filtrar por `message_type`/`source_id` para não reprocessar (análogo ao `wasSentByApi` da Uazapi).
- **Precedência de múltiplas labels** numa conversa: definir regra (última alterada vs. prioridade). **Decisão de produto pendente.**
- **Mapeamento contato→lead**: Chatwoot identifica por `contact`/`conversation_id`; normalizar telefone com `phone_normalize` para casar com leads/uazapi existentes e evitar duplicatas.
- **Rate limits** da Application API do Chatwoot no envio em massa.
- **Segurança**: `api_access_token` do Chatwoot é sensível — guardar em `chatwoot_settings` (já fora do git via RLS/Supabase), nunca logar; webhook protegido por `?secret=`.

## 7. Testes / verificação

- Unit: parser de `message_created` (texto, imagem, áudio, documento); resolução inbox por `account_id+inbox_id`; idempotência de criação de etapa por label.
- Integração: replay dos payloads da Fase 0 na fila → asserts em `chat_messages` e `pipeline_stages`.
- Regressão Uazapi: a suíte atual (`backend/test_*.py`) deve permanecer verde — `provider='uazapi'` não muda de comportamento.
- E2E manual em staging: mensagem real entra → aparece no Kanban; label nova no Chatwoot → nova coluna + lead movido; resposta do CRM → chega no WhatsApp.

## 8. Resumo de arquivos tocados

```
backend/migrations/016_chatwoot_provider.sql            (novo)
backend/app/services/chatwoot_service.py                (novo)
backend/app/routers/chatwoot.py                         (novo)
backend/app/routers/webhooks.py                         (+ POST /chatwoot)
backend/app/routers/leads.py                            (roteia send/history por provider)
backend/app/workers/webhook_processor.py                (branch source=chatwoot + label→etapa)
backend/app/services/webhook_lead_context.py            (resolução por inbox Chatwoot)
backend/app/models/inbox.py                             (provider + chatwoot_settings)
backend/app/config.py                                   (CHATWOOT_WEBHOOK_SECRET)
backend/app/main.py                                     (include_router chatwoot)
frontend-next/app/(dashboard)/configuracoes/page.tsx    (seletor provedor + ChatwootConnectModal)
frontend-next/lib/api.ts                                (connect/status/disconnect Chatwoot)
docs/chatwoot_webhook_setup.md                          (novo, espelha uazapi)
```

## 9. Fase 0 — payloads confirmados (instância chatwoot.wbtech.dev, conta 2, inbox 65)

Spike concluído via workflow n8n `Dev - API oficial Chatwoot 2595`. Fatos verificados em payloads reais:

**Eventos por mensagem recebida.** Cada inbound dispara `message_created` **e** um `conversation_updated`. A conversa nova também dispara `conversation_created` (redundante — descartado). Conjunto mínimo a assinar: **`message_created`** (mensagens) + **`conversation_updated`** (etiquetas/funil).

**Resolução de inbox.** `body.account.id` (2) + `body.inbox.id` (65) no `message_created`; em `conversation_updated`/`conversation_created` o id da conversa é `body.id` e o inbox `body.inbox_id`. → casa com `chatwoot_settings.account_id` + `inbox_id`.

**Parser de mensagem (`message_created`).**
- `content` = texto/legenda (pode ser `null`); `content_type` é **sempre `"text"`**, mesmo para mídia — **não usar para detectar tipo**.
- Mídia: detectar por `attachments[]`. `attachments[0].file_type ∈ {image, audio, video, file}`; URL de download em `attachments[0].data_url`; `file_size` disponível; áudio traz `transcribed_text`.
- Direção: `message_type` = `"incoming"`/`"outgoing"` (string no topo; dentro de `conversation.messages[]` é numérico 0/1).
- Dedup/IDs: `id` = id da msg no Chatwoot; `source_id` = `wamid…` (id no WhatsApp → `whatsapp_message_id`); `conversation.id` = `external_conversation_id` (usado para responder via API).
- Contato/lead: `sender.phone_number` (`+55…`), `sender.name`, `sender.identifier` (`…@s.whatsapp.net`), `sender.email`.

**Parser de etiquetas (`conversation_updated`).**
- Estado atual completo em `body.labels` (array de strings, ex.: `["01-interessado","02-demo-agendada"]`).
- Mudança em `body.changed_attributes[]`, chave `label_list` com `previous_value`/`current_value` (arrays). Também há `cached_label_list` (string CSV).
- **Guard obrigatório**: `conversation_updated` dispara também para `waiting_since`/`updated_at`/`assignee` etc. Só agir no funil quando `label_list` estiver presente em `changed_attributes`. Diff previous→current revela etiqueta adicionada/removida → criar coluna (`source_label`) e mover o lead.

**Assinatura.** Headers `x-chatwoot-signature` (`sha256=HMAC(secret, "{ts}.{raw_body}")`) e `x-chatwoot-timestamp` presentes. Secret de assinatura gerado no Chatwoot guardado para a verificação no endpoint do CRM (corrige o §6: é HMAC por header, **não** `?secret=`).

**Regra de etapa (definida).** Invariante: cada lead/conversa carrega **uma única etiqueta de etapa** = sua coluna atual. Mover de etapa = adicionar a etiqueta nova e remover a antiga (vale para CRM, agentes de IA e ação manual). Não há regra de precedência — por construção só há um rótulo válido por vez. Implicações:
- **Chatwoot → CRM**: em `conversation_updated` com `label_list`, a etapa-alvo é a etiqueta **adicionada** (diff `current − previous`); cria a coluna se não existir (`source_label`) e move o lead. A sequência add-B / remove-A converge em B; o evento de remoção pura é no-op se a etapa já é a remanescente.
- **CRM → Chatwoot**: ao mover o card no Kanban, o CRM faz `POST /api/v1/accounts/{id}/conversations/{conv}/labels` enviando o array com **apenas** a etiqueta da nova etapa. O Chatwoot substitui o conjunto inteiro → a troca é atômica (um único `conversation_updated`, sem o transiente de dois eventos da troca manual).
- **Prevenção de loop**: CRM grava label → Chatwoot emite `conversation_updated` → CRM recebe → etapa-alvo == etapa atual → no-op (idempotente). Opcionalmente marcar a origem para ignorar o eco.
- **Nome da etiqueta = nome da etapa**: a convenção exige que as etiquetas do Chatwoot e as colunas do funil compartilhem o mesmo identificador (ex.: `01-interessado`). Mapear no `pipeline_stages.source_label`.
