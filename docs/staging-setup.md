# Neurix CRM — Setup do ambiente Staging

Guia para duplicar produção em um ambiente isolado onde o desenvolvedor trabalha sem risco para clientes reais.

**Produção hoje:** `crm.wbtech.dev` + Supabase `crm-supabase.wbtech.dev`  
**Staging alvo:** `crm-staging.wbtech.dev` + Supabase `crm-supabase-staging.wbtech.dev`

---

## Visão geral


| Componente              | Produção                 | Staging                                     |
| ----------------------- | ------------------------ | ------------------------------------------- |
| Frontend + API + Worker | App Dokploy `neurix-crm` | App Dokploy `neurix-crm-staging`            |
| Supabase                | Instância atual          | **Nova instância**                          |
| Redis                   | Instância atual          | **Nova instância**                          |
| Branch Git              | `main`                   | `staging`                                   |
| WhatsApp (Uazapi)       | Número real              | **Desligado** ou instância de teste         |
| n8n                     | Workflows prod           | Workflows duplicados → API staging          |
| Dados                   | Reais                    | Vazio + migrations **ou** cópia anonimizada |


**Regra:** staging nunca compartilha banco, Redis, webhook de WhatsApp nem secrets de produção.

---

## Divisão de tarefas

Legenda: **VOCÊ** = infraestrutura / Dokploy / DNS / credenciais de dono  
**EU (agente/repo)** = código, documentação, scripts, branch Git, templates

---

## Fase 0 — Segurança antes de começar (VOCÊ) — URGENTE

- [ ] **Rotacionar token GitHub** se o remote local tiver PAT embutido na URL (`git remote -v`). Use SSH ou credential manager; nunca PAT na URL.
- [x] Confirmar que `.env` real **não** está no Git (já está no `.gitignore`).
- [x] Listar quem tem acesso admin ao Dokploy — só você; dev **sem** acesso a prod.
- [ ] Preparar cofre de secrets (1Password, Bitwarden, ou env vars só no Dokploy) — **não** enviar secrets por WhatsApp/e-mail sem criptografia.

---

## Fase 1 — DNS e domínios (VOCÊ)

No painel DNS de `wbtech.dev` (ou Traefik/Dokploy):


| Registro               | Tipo       | Destino                   |
| ---------------------- | ---------- | ------------------------- |
| `crm-staging`          | A ou CNAME | Mesmo IP/servidor Dokploy |
| `crm-supabase-staging` | A ou CNAME | Mesmo IP/servidor Dokploy |


- [x] Criar registros DNS
- [x] Aguardar propagação (5–30 min)
- [ ] Anotar os hostnames finais (usados nas env vars abaixo)

---

## Fase 2 — Supabase staging (VOCÊ)

1. No Dokploy: **novo projeto** → deploy do template/stack Supabase (igual ao de prod, nome sugerido: `neurix-supabase-staging`).
2. Configurar domínio público: `https://crm-supabase-staging.wbtech.dev`
3. Gerar **secrets novos** (não copiar de prod):
  - `JWT_SECRET`
  - `ANON_KEY`
  - `SERVICE_ROLE_KEY`
4. Configurar SMTP no Supabase staging (ver `docs/supabase_smtp_config.md`), com URLs apontando para **staging**:

```env
SITE_URL=https://crm-staging.wbtech.dev
ADDITIONAL_REDIRECT_URLS=https://crm-staging.wbtech.dev/*,http://localhost:3000/*
API_EXTERNAL_URL=https://crm-supabase-staging.wbtech.dev
SUPABASE_PUBLIC_URL=https://crm-supabase-staging.wbtech.dev
```

1. Anotar o **nome da rede Docker** do Supabase staging (Dokploy → redes do compose). Exemplo prod: `crmneurix-pre0225supabase-fhydlr` — staging terá outro nome.
2. Copiar para o cofre (só staging):
  - `SUPABASE_URL` (URL interna, ex. `http://kong:8000` — use a mesma convenção de prod)
  - `SUPABASE_PUBLIC_URL`
  - `SUPABASE_ANON_KEY`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_JWT_SECRET`

- [x] Stack Supabase staging no ar
- [x] HTTPS funcionando no subdomínio
- [x] Secrets anotados no cofre

---

## Fase 3 — Redis staging (VOCÊ)

1. Novo serviço Redis no Dokploy (nome: `neurix-redis-staging`).
2. Senha **nova** (`REDIS_PASSWORD`).
3. Anotar host interno (ex. nome do container na rede Docker).

- [x] Redis staging criado
- [x] `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` no cofre

---

## Fase 4 — Banco staging: schema e dados (VOCÊ + EU)

### 4a — Aplicar migrations (EU prepara script; VOCÊ executa)

O repositório tem migrations em `backend/migrations/` (001 → 014).

**VOCÊ:** conectar ao Postgres do Supabase staging (Dokploy → terminal do container `db` ou SQL Editor) e rodar:

```bash
# Opção A — pelo host, se tiver psql e acesso à porta do Postgres staging
python scripts/apply_migrations.py --database-url "postgresql://postgres:SENHA@HOST:5432/postgres"

# Opção B — copiar/colar cada .sql na ordem numérica pelo SQL Editor do Supabase Studio
```

- [ ] Todas as migrations aplicadas sem erro
- [ ] No Studio staging: tabelas `leads`, `products`, `promotions`, etc. existem

### 4b — Dados iniciais (opcional)

**Recomendado para dev:** banco vazio + criar 1 usuário admin de teste no Auth staging.

**Se precisar de dados realistas:** VOCÊ faz dump anonimizado de prod (sem telefones/CNPJ reais) — **nunca** restore direto de prod em staging sem anonimizar.

- [ ] Usuário de teste criado em staging (e-mail que só você/dev controlam)

---

## Fase 5 — App CRM staging no Dokploy (VOCÊ)

1. Novo app Compose no Dokploy: `neurix-crm-staging`
2. Repositório: `github.com/tupimarines/crm-neurix-v1`
3. Branch de deploy: `staging` (criada na Fase 6)
4. Compose file: `docker-compose.staging.yml`
5. **Project name / Compose name:** `neurix-crm-staging` (evita conflito de containers com prod)
6. Rede externa: conectar `dokploy-network` + rede do Supabase staging (`SUPABASE_DOCKER_NETWORK`)

### Variáveis de ambiente (staging — valores novos onde indicado)

```env
# Identificação
APP_NAME=Neurix CRM [STAGING]
DEBUG=true

# URLs públicas
NEXT_PUBLIC_API_URL=https://crm-staging.wbtech.dev
PUBLIC_API_BASE_URL=https://crm-staging.wbtech.dev
CORS_ORIGINS=https://crm-staging.wbtech.dev

# Supabase staging (do cofre — Fase 2)
SUPABASE_URL=<interno>
SUPABASE_PUBLIC_URL=https://crm-supabase-staging.wbtech.dev
SUPABASE_ANON_KEY=<novo>
SUPABASE_SERVICE_ROLE_KEY=<novo>
SUPABASE_JWT_SECRET=<novo>

# Redis staging (Fase 3)
REDIS_HOST=<host interno redis staging>
REDIS_PORT=6379
REDIS_PASSWORD=<novo>
REDIS_DB=0

# Rede Docker do Supabase staging
SUPABASE_DOCKER_NETWORK=<nome da rede externa do compose supabase staging>

# n8n — chave NOVA (gerar: python -c "import secrets; print(secrets.token_urlsafe(32))")
N8N_API_KEY=<novo>

# WhatsApp — DESLIGADO em staging (deixar vazio ou tokens de instância de teste)
UAZAPI_URL=
UAZAPI_ADMIN_TOKEN=
UAZAPI_INSTANCE_TOKEN=
UAZAPI_WEBHOOK_SECRET=

# SMTP — pode reutilizar Brevo com remetente diferente ou desabilitar 2FA em staging
TWO_FACTOR_ENABLED=false
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<brevo>
SMTP_PASS=<brevo>
```

1. Domínio Traefik: `crm-staging.wbtech.dev` → serviço `frontend` (porta 3000); API em mesmo host (`/api` via frontend ou rota direta ao backend — igual prod).

- [ ] Deploy staging concluído
- [ ] `https://crm-staging.wbtech.dev/api/health` retorna OK
- [ ] Login no CRM staging funciona

---

## Fase 6 — Git e fluxo do dev (EU + VOCÊ)

### EU (no repositório)

- [x] `docker-compose.staging.yml` (sem `container_name` fixo; rede Supabase parametrizada)
- [x] `backend/.env.staging.example` (template sem secrets)
- [x] `scripts/apply_migrations.py`
- [x] Branch `staging` criada a partir de `main`
- [x] Este documento

### VOCÊ

- [ ] Convidar dev no GitHub: role **Write** (não Admin)
- [ ] Configurar Dokploy staging para auto-deploy na branch `staging`
- [ ] Manter Dokploy **prod** deployando só `main`
- [ ] Definir regra: PR → `staging` → você testa → merge `staging` → `main` → deploy prod

### Dev (instruções que você repassa)

1. Clonar repo; nunca commitar `.env`
2. Branch `feature/...` → PR para `staging`
3. Testar em `https://crm-staging.wbtech.dev`
4. Só após sua aprovação: merge `staging` → `main`

---

## Fase 7 — n8n (VOCÊ, com apoio EU)

**Produção não deve chamar API de staging.**

- [ ] Duplicar workflows relevantes (ex. Dorinha) no n8n
- [ ] Nos nodes HTTP: base URL `https://crm-staging.wbtech.dev`
- [ ] Header `X-API-Key` = `N8N_API_KEY` **de staging**
- [ ] Desativar triggers WhatsApp nos workflows de staging **ou** usar número de teste separado

EU pode atualizar docs/prompts em `n8n/` referenciando variáveis por ambiente.

---

## Fase 8 — WhatsApp / Uazapi (VOCÊ)


| Opção                   | Quando usar                                        |
| ----------------------- | -------------------------------------------------- |
| **A — Desligado**       | Maioria dos devs (UI, catálogo, pedidos, n8n HTTP) |
| **B — Instância teste** | Precisa testar webhook de ponta a ponta            |


Se opção B:

- [ ] Instância Uazapi separada
- [ ] Webhook → `https://crm-staging.wbtech.dev/api/webhooks/uazapi?secret=<NOVO_SECRET>`
- [ ] **Nunca** alterar webhook da instância de produção

---

## Fase 9 — Validação final (VOCÊ + dev)

Checklist de aceite:

- [ ] `crm-staging.wbtech.dev` abre com banner/indicador de staging (`APP_NAME`)
- [ ] Login cria sessão só no Supabase staging (verificar no Studio staging)
- [ ] Criar lead/produto em staging **não** aparece em prod
- [ ] `crm.wbtech.dev` (prod) inalterado
- [ ] Dev **não** tem acesso às env vars de prod no Dokploy
- [ ] Secrets de staging estão só no cofre / Dokploy staging

---

## Credenciais: o que o dev recebe vs. o que fica só com você


| Item                        | Dev                                                       | Você  |
| --------------------------- | --------------------------------------------------------- | ----- |
| Acesso GitHub (Write)       | Sim                                                       | Admin |
| URL staging                 | Sim                                                       | Sim   |
| Login usuário teste staging | Sim                                                       | Sim   |
| Dokploy staging             | Opcional (só se necessário)                               | Sim   |
| Dokploy prod                | **Não**                                                   | Sim   |
| `SERVICE_ROLE_KEY` prod     | **Não**                                                   | Sim   |
| `N8N_API_KEY` prod          | **Não**                                                   | Sim   |
| Uazapi prod                 | **Não**                                                   | Sim   |
| Secrets staging             | Via `.env.local` só se dev rodar local; senão nem precisa | Sim   |


---

## Promover alteração para produção

1. Dev abre PR `staging` → `main` (ou você faz merge após testar staging)
2. **VOCÊ:** backup do Supabase prod (Dokploy/snapshot)
3. Se o PR inclui arquivo em `backend/migrations/`: rodar migration em **prod** na ordem
4. Merge em `main` → Dokploy redeploy prod
5. Smoke test: health, login, um fluxo crítico (sem quebrar WhatsApp)

---

## Rollback

- **Código:** revert commit em `main` + redeploy Dokploy prod
- **Banco:** restore do snapshot pré-deploy (por isso backup antes de migration em prod)

---

## Referências no repo

- `docker-compose.staging.yml` — compose para Dokploy staging
- `backend/.env.staging.example` — template de variáveis
- `scripts/apply_migrations.py` — aplicar SQL em ordem
- `docs/supabase_smtp_config.md` — SMTP Auth
- `docs/uazapi_webhook_setup.md` — só se habilitar WhatsApp em staging

