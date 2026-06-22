# Staging → Produção — guia para o dev

Como promover melhorias testadas em `https://crm-staging.wbtech.dev` para `https://crm.wbtech.dev` **sem sessões longas**, **sem misturar secrets** e **sem copiar dados sensíveis**.

Complementa [`staging-setup.md`](./staging-setup.md) (como o staging foi criado).

---

## Visão rápida

| Ambiente | Git branch | CRM | Supabase | Redis |
|----------|------------|-----|----------|-------|
| Staging | `staging` | `crm-staging.wbtech.dev` | `crm-supabase-staging.wbtech.dev` | instância staging |
| Produção | `main` | `crm.wbtech.dev` | `crm-supabase.wbtech.dev` | instância prod |

**Regra de ouro:** código vai de `staging` → `main`. **Dados e secrets nunca** são dump/restore entre ambientes.

---

## Fluxo Git (dev)

```
feature/minha-melhoria  →  PR para staging  →  teste em staging  →  PR staging → main  →  deploy prod
```

1. Branch a partir de `staging`: `feature/...` ou `fix/...`
2. PR **pequeno** para `staging` (1 assunto por PR — facilita review e rollback)
3. Validar em staging (checklist abaixo)
4. Após aprovação do dono: PR `staging` → `main`
5. Dono aplica migrations em prod (se houver) **antes ou logo após** merge, conforme a migration
6. Dokploy redeploy prod (branch `main`)

O dev **não** precisa de acesso ao Dokploy prod nem às env vars de produção.

---

## O que entra no PR (código)

| Pode ir no PR | Não commitar |
|---------------|--------------|
| `backend/`, `frontend-next/`, `n8n/` (prompts/workflows versionados) | `.env`, secrets, PAT na URL do git |
| `backend/migrations/*.sql` novos ou alterados | Imagens de produto em massa (`potes geleia recortado/`, etc.) |
| `scripts/` utilitários | Dumps de banco |
| `docs/` | `produtos-lojista.csv` se for dado operacional |

**Compose:** alterações em `docker-compose.staging.yml` **não** afetam prod. Prod usa o compose principal do Dokploy (`neurix-crm` / `main`).

---

## Migrations (obrigatório ler antes de prod)

Arquivos em `backend/migrations/`, ordem numérica (`001`, `002`, …).

### Aplicar em prod

```bash
# No servidor ou máquina com acesso ao Postgres prod
python scripts/apply_migrations.py --database-url "postgresql://postgres:SENHA@HOST:5432/postgres" --dry-run
python scripts/apply_migrations.py --database-url "postgresql://postgres:SENHA@HOST:5432/postgres"
```

Ou, container prod (padrão Hostinger):

```bash
sudo docker exec -i supabase-319f-db psql -U postgres -d postgres < backend/migrations/0XX_nome.sql
```

Registrar em `schema_migrations` se aplicar SQL manualmente (o script `apply_migrations.py` faz isso automaticamente).

### Ver o que já está aplicado

```sql
SELECT filename, applied_at FROM public.schema_migrations ORDER BY filename;
```

### Migrations especiais

| Arquivo | Observação |
|---------|------------|
| `013_clone_funil_1_from_admin_villadora.sql` | **Só prod** com tenant `admin@villadora.com` — não rodar em staging vazio |
| `013_leads_chat_cycle_closed.sql` | Outro `013_*` — atenção à ordem alfabética/numerica no diretório |
| `014_trigger_clone_funil_1_on_new_auth_user.sql` | Depende de funil template existir em prod |

Antes de prod: compare `schema_migrations` **staging vs prod** e liste só o que falta em prod.

### Schema drift staging ↔ prod

Staging pode estar **atrás** ou **à frente** em colunas (ex.: `weight_grams` só em prod). O seed de catálogo filtra colunas ausentes; **código novo** pode assumir coluna que só existe após migration — por isso migrations em prod **antes** do deploy do código que depende delas.

---

## Dados: o que promover e como

### Não promover (ficam em cada ambiente)

- Leads, clientes (`crm_clients`), pedidos, chats
- `organization_members` de usuários reais
- `inboxes` / tokens WhatsApp (`uazapi_settings`)
- Secrets (JWT, service role, N8N, Uazapi)

### Catálogo / config (quando a melhoria é conteúdo Villadora)

Preferir **atualizar por `id`** (UUID igual em staging e prod após seed inicial), não dump completo.

Fluxo típico:

1. Dev altera catálogo em staging (UI ou script)
2. Exporta só o que mudou (produto X, promo Y, estágio Z)
3. Em prod: `UPDATE` / `UPSERT` por `id` no tenant de produção (`admin@villadora.com`)

Script de referência (staging **←** prod, não o inverso): `scripts/seed_villadora_catalog_staging.py`  
Para prod: inverter a lógica ou SQL manual com `WHERE tenant_id = <uuid admin prod>`.

Imagens de produto: `scripts/sync_product_images_crm.py` — apontar storage staging vs prod conforme README do script.

---

## Deploy produção (dono / quem tem Dokploy prod)

### Ordem recomendada

1. **Backup** Supabase prod (snapshot Dokploy)
2. **Migrations** novas em prod (`apply_migrations.py` ou SQL)
3. **Merge** `staging` → `main`
4. **Redeploy** app CRM prod no Dokploy
5. **Smoke test** (2 min)

### Env vars prod — não copiar de staging

Cada stack tem seu próprio par JWT + keys:

| Variável | Staging | Prod |
|----------|---------|------|
| `JWT_SECRET` | `fgQrtgN7...ggythi` (exemplo) | **outro** |
| `ANON_KEY` / `SERVICE_ROLE_KEY` | gerados com JWT staging | gerados com JWT prod |
| `SUPABASE_URL` | `http://supabase-staging-319f-kong:8000` | `http://supabase-319f-kong:8000` |
| `NEXT_PUBLIC_API_URL` | `https://crm-staging.wbtech.dev` | `https://crm.wbtech.dev` |

**Nunca** colar keys de prod no staging nem o contrário.  
Gerar keys: `python scripts/generate_supabase_jwt_keys.py '<JWT_SECRET>'`

---

## Checklist pós-deploy staging (dev faz antes do PR para main)

- [ ] `GET /api/health` → 200
- [ ] Login usuário de teste staging
- [ ] `/api/products/` → 200
- [ ] `/api/clients/` → 200
- [ ] `/api/leads/kanban` → 200
- [ ] Fluxo da feature tocada (1 caminho feliz)
- [ ] Sem regressão óbvia em Configurações / Funil

Script rápido no servidor:

```bash
bash scripts/check_jwt_staging.sh
```

---

## Smoke test produção (dono, após deploy)

- [ ] `https://crm.wbtech.dev/api/health`
- [ ] Login admin real
- [ ] Kanban abre (tenant com leads)
- [ ] Catálogo / pedido (conforme a mudança)
- [ ] WhatsApp: se não mexeu em webhook, só confirmar que mensagem de teste **não** foi alterada

---

## Rollback

| Camada | Ação |
|--------|------|
| Código | Revert commit em `main` + redeploy Dokploy |
| Banco | Restore snapshot **pré-migration** (só se migration destrutiva falhou) |
| Dados de catálogo | `UPDATE` pontual ou restore parcial — evitar restore full |

---

## Diagnóstico rápido (evita sessão de 2h)

| Sintoma | Causa comum | Comando / ação |
|---------|-------------|----------------|
| Login OK, resto 500 | `SERVICE_ROLE_KEY` inválida ou JWT mismatch | `bash scripts/check_jwt_staging.sh` |
| `PGRST301` invalid JSON | Key corrompida (copiar/colar) | Regenerar com `generate_supabase_jwt_keys.py` |
| `JWSInvalidSignature` | Key gerada com `JWT_SECRET` errado | Keys devem usar o **mesmo** `JWT_SECRET` da stack |
| Kanban 500, resto OK | Coluna ausente (`archived`/`deleted` em `leads`) | Atualizar código ou aplicar migration |
| Staging mostra dados de prod | `NEXT_PUBLIC_API_URL` apontando prod | Rebuild frontend com URL staging |
| Kong SR vazio | Env só no Dokploy, container desatualizado | Redeploy stack Supabase |

---

## Trabalhar com IA (Cursor) sem gastar token à toa

### Um assunto por sessão

| Sessão | Escopo |
|--------|--------|
| 1 | Só migrations + `apply_migrations` |
| 2 | Só feature X em código |
| 3 | Só seed/catálogo |
| 4 | Só debug 500 (colar saída de `check_jwt_staging.sh`) |

### Prompt inicial útil (copiar/colar)

```
Ambiente: staging (crm-staging.wbtech.dev). Branch: staging.
Objetivo: [uma frase]
Já testado: [sim/não — o que falhou]
Não mexer: prod secrets, dados de leads/clientes
```

### O que anexar quando pedir debug

1. Saída de `bash scripts/check_jwt_staging.sh`
2. Trecho relevante de `sudo docker logs crmneurix-crm-qhdg2z-backend-1 --tail 30`
3. Endpoint que falha + status HTTP (não screenshot)

### Evitar

- “Configura staging e prod e migra tudo” num único chat
- Colar `.env` completo no chat (usar prefixos `len=` / primeiros 8 chars)
- Commitar secrets ou imagens pesadas

---

## Referência de scripts

| Script | Uso |
|--------|-----|
| `scripts/apply_migrations.py` | Migrations em ordem + `schema_migrations` |
| `scripts/check_jwt_staging.sh` | Diagnóstico JWT + PostgREST |
| `scripts/generate_supabase_jwt_keys.py` | Gerar ANON + SERVICE_ROLE |
| `scripts/verify_staging_service_role.sh` | Comparar keys CRM vs Kong |
| `scripts/seed_villadora_catalog_staging.py` | Catálogo prod → staging (sem PII) |
| `scripts/run_seed_villadora_staging.sh` | Wrapper no servidor |
| `scripts/diag_staging_backend.sh` | Logs + teste Python no container |

---

## Contatos / acesso

| Recurso | Dev | Dono |
|---------|-----|------|
| GitHub Write | sim | admin |
| URL staging + login teste | sim | sim |
| Dokploy staging | opcional | sim |
| Dokploy prod | **não** | sim |
| `SERVICE_ROLE_KEY` prod | **não** | sim |

Login staging de teste (catálogo Villadora): ver dono — usuário `staging@villadora.com` (senha no cofre, não no Git).

---

## Resumo em 5 linhas

1. PR pequeno → `staging` → testar checklist → PR `staging` → `main`.
2. Migration nova → rodar em **prod** com backup antes.
3. **Nunca** copiar secrets ou dump de banco entre ambientes.
4. Catálogo/config → `UPSERT` por `id` no tenant prod.
5. Problema de API → `check_jwt_staging.sh` antes de investigar código.
