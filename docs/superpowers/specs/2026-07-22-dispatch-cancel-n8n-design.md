# Cancelar campanha de Comunicados (CRM + n8n)

**Data:** 2026-07-22  
**Status:** aprovado em conversa — aguardando review do arquivo

## Problema

Não há como interromper um disparo em andamento. Apagar a execução no painel n8n não atualiza o CRM, e o CRM não guarda o `execution_id` da execução.

## Objetivo

Botão **Cancelar envio** no Comunicados que:

1. Marca a campanha como `cancelled` no CRM.
2. Tenta **stop** e depois **delete** da execução no n8n (quando houver `n8n_execution_id`).

Mensagens já enviadas permanecem. Targets `pending` não são reenviados porque a execução para / é removida.

## Solução

### 1. Dados

Migration em `dispatch_campaigns`:

- `n8n_execution_id TEXT NULL` — ID da execução no n8n
- Ampliar CHECK de `status` para incluir `cancelled`

### 2. Callback n8n → CRM (início do workflow)

Novo endpoint (API key n8n, mesmo padrão de `/api/n8n/tools/*`):

`POST /api/n8n/tools/dispatch-execution`

Body:

```json
{ "campaign_id": "<uuid>", "execution_id": "<string>" }
```

Comportamento: valida campanha, grava `n8n_execution_id`, responde `{ ok: true }`.

**Obrigatório no workflow do disparador:** HTTP Request no início com `$execution.id` + `campaign_id` do payload do webhook.

### 3. Cancelar (JWT do tenant)

`POST /api/dispatch/campaigns/{campaign_id}/cancel`

Regras:

- Só se `status === running` e `tenant_id` do usuário
- Atualiza: `status=cancelled`, `finished_at=now`, `updated_at=now`
- Se existir `n8n_execution_id`:
  - Resolve instância via `N8N_INSTANCES` (mesma usada pelo HQ; config/env do host do webhook se necessário)
  - Tenta `POST /api/v1/executions/{id}/stop` (ignora 404 se já parou)
  - Tenta `DELETE /api/v1/executions/{id}`
- Resposta sempre com campanha cancelada no CRM; inclui `n8n_stopped` / `n8n_deleted` / `n8n_error` opcional

Sem `n8n_execution_id`: cancela só no CRM (campanhas antigas ou callback ainda não chegou).

### 4. Cliente n8n

Estender `N8nInstanceClient` com:

- `stop_execution(execution_id)`
- `delete_execution(execution_id)`

### 5. Frontend (Comunicados)

- Botão **Cancelar envio** no bloco de progresso quando `campaign.status === 'running'`
- Confirmação simples antes de cancelar
- Chama `cancelDispatchCampaign`; atualiza UI; se `n8n_error`, toast/aviso sem reverter o cancelamento no CRM
- Histórico: exibir status `cancelled`

### 6. Loop do n8n (recomendado)

No loop de envio, antes de cada mensagem: se a campanha no CRM estiver `cancelled`, abortar o fluxo. Defesa extra caso o delete falhe.

## Fora de escopo

- Cancelar campanhas `done` / `failed`
- Rollback de mensagens já enviadas
- UI admin para gerenciar execuções n8n

## Riscos

| Risco | Mitigação |
|-------|-----------|
| Callback ainda não chegou | Cancel só no CRM; botão ainda funciona |
| DELETE bloqueia se running | Stop antes do delete |
| Stop/delete não disponível na versão do n8n | CRM já cancelled; mensagem de erro parcial |
| Instância n8n errada em `N8N_INSTANCES` | Documentar qual `id` aponta para o host do disparador |

## Critérios de aceite

- [ ] Campanha `running` pode ser cancelada na UI
- [ ] Status no CRM vira `cancelled` mesmo se n8n falhar
- [ ] Com `n8n_execution_id` válido, execução some/para no n8n
- [ ] Workflow registra `execution_id` no start
- [ ] Campanha sem `execution_id` ainda cancela no CRM
