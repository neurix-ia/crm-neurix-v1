# Neurix HQ — setup n8n

Painel superadmin em `/admin/core`. O backend consulta as instâncias n8n via **Public API** (outbound).

## Credenciais necessárias

### 1. CRM (já existentes)

| Variável | Onde | Para quê |
|----------|------|----------|
| `SUPABASE_URL` | Backend | Auth + perfil `is_superadmin` |
| `SUPABASE_SERVICE_ROLE_KEY` | Backend | API |
| `SUPABASE_ANON_KEY` | Backend + Frontend | Login JWT |
| `REDIS_HOST` / `REDIS_PORT` | Backend | Cache HQ (TTL 5 min default) |

### 2. Neurix HQ — novas (backend)

| Variável | Descrição |
|----------|-----------|
| `N8N_INSTANCES` | JSON com as 2 instâncias (neurix + wbtech) |
| `HQ_CACHE_TTL_SECONDS` | Opcional, default `300` |

Exemplo com as instâncias de produção (substitua `api_key` pelos valores reais no Dokploy — **não commitar**):

```json
[
  {
    "id": "wbtech",
    "label": "WB Tech",
    "base_url": "https://n8n.wbtech.dev",
    "api_key": "..."
  },
  {
    "id": "neurix",
    "label": "Neurix",
    "base_url": "https://n8n-neurix-1.wbtech.dev",
    "api_key": "..."
  }
]
```

### 3. API keys n8n (uma por instância)

Criar em cada n8n: **Settings → n8n API → Create API key**

Scopes obrigatórios:

- `insights:read` — KPIs (summary + by-workflow)
- `workflow:read` — futuro: árvore de agentes
- `execution:read` + `execution:list` — futuro: modal de erro (Fase B)

Requisitos do plano n8n:

- **Insights** disponível (Pro/Business/Enterprise). Sem isso, `/api/v1/insights/*` retorna 403.

### 4. Superadmin

| Item | Como |
|------|------|
| Usuário | `augustogumi@gmail.com` em Supabase Auth |
| Flag | `profiles.is_superadmin = true` (migration `006_rbac_baseline.sql`) |

### 5. Não confundir

| Variável | Direção | Uso |
|----------|---------|-----|
| `N8N_API_KEY` | n8n → CRM | Webhook `/api/n8n/webhook` |
| `N8N_INSTANCES[].api_key` | CRM → n8n | Neurix HQ (insights) |

São secrets **diferentes**.

## Deploy

1. Adicionar `N8N_INSTANCES` no container **backend** (staging e prod).
2. Reiniciar API.
3. Login como superadmin → **Neurix HQ** ou `/admin/core`.
4. Se cards ficarem cinza: verificar log `N8N_INSTANCES não configurado` ou erro HTTP na instância.

## Troubleshooting "Internal Server Error" no HQ

1. **Redeploy** do backend com a branch `staging` (rotas `/api/admin/hq/*`).
2. **`N8N_INSTANCES`** no Dokploy — JSON em uma linha, aspas duplas.
3. **`REDIS_HOST` / `REDIS_PASSWORD`** — se Redis estiver down, versões recentes do HQ funcionam sem cache; confira mesmo assim.
4. Logs do container backend ao abrir `/admin/core` (erro `hq_summary` ou `hq n8n`).
5. Teste manual (substitua `TOKEN`):

```bash
curl -s -H "Authorization: Bearer TOKEN" "https://crm-staging.wbtech.dev/api/admin/hq/summary?period=7d"
```

## Endpoints (superadmin JWT)

- `GET /api/admin/hq/summary?period=7d`
- `GET /api/admin/hq/n8n/overview?period=7d`
- `GET /api/admin/hq/n8n/workflows/errors?period=7d&limit=20`
- `POST /api/admin/hq/n8n/refresh` — invalida cache
