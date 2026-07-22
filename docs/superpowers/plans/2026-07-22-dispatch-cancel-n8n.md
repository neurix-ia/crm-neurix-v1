# Cancel Dispatch Campaign (CRM + n8n) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir cancelar uma campanha `running` no Comunicados, marcando `cancelled` no CRM e tentando stop/delete da execução no n8n.

**Architecture:** O workflow n8n registra `execution_id` no CRM no start (`POST /api/n8n/tools/dispatch-execution`). O botão Cancelar chama `POST /api/dispatch/campaigns/{id}/cancel`, que atualiza o status e usa `N8nInstanceClient` (via `N8N_INSTANCES` + `N8N_DISPATCH_INSTANCE_ID`) para stop → delete. Defesa extra: `dispatch-targets` retorna lista vazia se a campanha já estiver `cancelled`.

**Tech Stack:** FastAPI, Supabase/Postgres, Next.js, n8n Public API, httpx

## Global Constraints

- Respostas e UI em português
- Não commitar secrets; usar envs existentes (`N8N_API_KEY`, `N8N_INSTANCES`)
- Migration nova: `023_dispatch_cancel.sql` (não editar `019_dispatch.sql`)
- Status novo: `cancelled` (além de `draft|running|done|failed`)
- Cancel só para `status === running`
- Sem `n8n_execution_id`: cancelar só no CRM (sucesso parcial)
- Falha no n8n não reverte o cancelamento no CRM

## File map

| File | Responsibility |
|------|----------------|
| `backend/migrations/023_dispatch_cancel.sql` | Coluna `n8n_execution_id` + CHECK com `cancelled` |
| `backend/app/config.py` | `N8N_DISPATCH_INSTANCE_ID` opcional |
| `backend/app/services/n8n_instance_client.py` | `stop_execution`, `delete_execution`, helper `_request_json` |
| `backend/app/services/dispatch_service.py` | `resolve_dispatch_n8n_client`, `cancel_n8n_execution`, `save_campaign_execution_id` |
| `backend/app/routers/n8n_tools.py` | `POST /tools/dispatch-execution`; gate em `dispatch-targets` |
| `backend/app/routers/dispatch.py` | `POST /campaigns/{id}/cancel` |
| `backend/test_dispatch_cancel.py` | Testes unitários do cancel / resolve client |
| `frontend-next/lib/api.ts` | `cancelDispatchCampaign` + tipo resposta |
| `frontend-next/app/(dashboard)/disparador/page.tsx` | Botão Cancelar + estilos `cancelled` |
| n8n workflow disparador | HTTP no start com `$execution.id` (ops manual / MCP) |

---

### Task 1: Migration `cancelled` + `n8n_execution_id`

**Files:**
- Create: `backend/migrations/023_dispatch_cancel.sql`

**Interfaces:**
- Produces: coluna `dispatch_campaigns.n8n_execution_id`; status aceita `cancelled`

- [ ] **Step 1: Criar migration**

```sql
-- Cancelamento de campanhas do Comunicados + vínculo com execução n8n

ALTER TABLE public.dispatch_campaigns
    ADD COLUMN IF NOT EXISTS n8n_execution_id TEXT;

-- Recria CHECK de status incluindo cancelled
ALTER TABLE public.dispatch_campaigns
    DROP CONSTRAINT IF EXISTS dispatch_campaigns_status_check;

ALTER TABLE public.dispatch_campaigns
    ADD CONSTRAINT dispatch_campaigns_status_check
    CHECK (status IN ('draft', 'running', 'done', 'failed', 'cancelled'));
```

- [ ] **Step 2: Commit**

```bash
git add backend/migrations/023_dispatch_cancel.sql
git commit -m "feat(dispatch): migration cancelled + n8n_execution_id"
```

---

### Task 2: Cliente n8n — stop + delete

**Files:**
- Modify: `backend/app/services/n8n_instance_client.py`
- Create: `backend/test_dispatch_cancel.py` (parte client)

**Interfaces:**
- Produces:
  - `async def stop_execution(self, execution_id: str) -> dict[str, Any]`
  - `async def delete_execution(self, execution_id: str) -> dict[str, Any]`
  - `async def _request_json(self, method: str, path: str, *, params=None, json_body=None) -> dict[str, Any]`

- [ ] **Step 1: Escrever teste falhando**

Em `backend/test_dispatch_cancel.py`:

```python
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.n8n_instance_client import N8nInstanceClient, N8nInstanceConfig


class TestN8nStopDelete(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = N8nInstanceConfig(
            id="wb", label="WB", base_url="https://n8n.example", api_key="k"
        )
        self.client = N8nInstanceClient(self.cfg, verify_ssl=True)

    async def test_stop_execution_posts(self):
        with patch.object(self.client, "_request_json", new_callable=AsyncMock) as m:
            m.return_value = {"id": "99", "status": "canceled"}
            out = await self.client.stop_execution("99")
            m.assert_awaited_once_with("POST", "/api/v1/executions/99/stop")
            self.assertEqual(out["id"], "99")

    async def test_delete_execution_deletes(self):
        with patch.object(self.client, "_request_json", new_callable=AsyncMock) as m:
            m.return_value = {"id": "99"}
            out = await self.client.delete_execution("99")
            m.assert_awaited_once_with("DELETE", "/api/v1/executions/99")
            self.assertEqual(out["id"], "99")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Rodar e ver falha**

Run: `cd backend && python -m unittest test_dispatch_cancel.TestN8nStopDelete -v`  
Expected: FAIL (`_request_json` / métodos ausentes)

- [ ] **Step 3: Implementar em `n8n_instance_client.py`**

Refatorar `_get_json` para usar `_request_json`, e adicionar:

```python
async def _request_json(
    self,
    method: str,
    path: str,
    *,
    params: Optional[dict[str, str]] = None,
    json_body: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    url = f"{self._base}{path}"
    async with httpx.AsyncClient(timeout=N8N_REQUEST_TIMEOUT, verify=self._verify_ssl) as client:
        response = await client.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
        )
        response.raise_for_status()
        if response.status_code == 204 or not (response.content or b"").strip():
            return {}
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"Resposta inesperada de {url}")
        return data

async def _get_json(self, path: str, params: Optional[dict[str, str]] = None) -> dict[str, Any]:
    return await self._request_json("GET", path, params=params)

async def stop_execution(self, execution_id: str) -> dict[str, Any]:
    return await self._request_json("POST", f"/api/v1/executions/{execution_id}/stop")

async def delete_execution(self, execution_id: str) -> dict[str, Any]:
    return await self._request_json("DELETE", f"/api/v1/executions/{execution_id}")
```

- [ ] **Step 4: Rodar testes**

Run: `cd backend && python -m unittest test_dispatch_cancel.TestN8nStopDelete -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/n8n_instance_client.py backend/test_dispatch_cancel.py
git commit -m "feat(n8n): stop e delete de execuções no client"
```

---

### Task 3: Service — resolver instância + cancelar execução + salvar execution_id

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/services/dispatch_service.py`
- Modify: `backend/test_dispatch_cancel.py`

**Interfaces:**
- Produces:
  - `Settings.N8N_DISPATCH_INSTANCE_ID: str = ""`
  - `def resolve_dispatch_n8n_client(settings: Settings) -> Optional[N8nInstanceClient]`
  - `async def cancel_n8n_execution(execution_id: str) -> dict[str, Any]`  
    Retorno: `{ "n8n_stopped": bool, "n8n_deleted": bool, "n8n_error": Optional[str] }`
  - `def save_campaign_execution_id(supabase, campaign_id: str, execution_id: str) -> None`

- [ ] **Step 1: Adicionar config**

Em `backend/app/config.py`, após `N8N_DISPATCH_WEBHOOK_URL`:

```python
# id em N8N_INSTANCES usado para stop/delete do disparador (ex.: "wbtech")
N8N_DISPATCH_INSTANCE_ID: str = ""
```

- [ ] **Step 2: Teste resolve + cancel**

Acrescentar em `test_dispatch_cancel.py`:

```python
from app.config import Settings
from app.services.dispatch_service import cancel_n8n_execution, resolve_dispatch_n8n_client
from app.services.n8n_instance_client import N8nInstanceConfig


class TestResolveDispatchClient(unittest.TestCase):
    def test_resolve_by_instance_id(self):
        settings = Settings(
            N8N_DISPATCH_INSTANCE_ID="wb",
            N8N_INSTANCES='[{"id":"wb","label":"WB","base_url":"https://n8n.example","api_key":"k"}]',
        )
        client = resolve_dispatch_n8n_client(settings)
        self.assertIsNotNone(client)
        self.assertEqual(client.config.id, "wb")

    def test_resolve_by_webhook_host(self):
        settings = Settings(
            N8N_DISPATCH_INSTANCE_ID="",
            N8N_DISPATCH_WEBHOOK_URL="https://n8n.example/webhook/x",
            N8N_INSTANCES='[{"id":"wb","label":"WB","base_url":"https://n8n.example","api_key":"k"}]',
        )
        client = resolve_dispatch_n8n_client(settings)
        self.assertIsNotNone(client)
        self.assertEqual(client.config.id, "wb")


class TestCancelN8nExecution(unittest.IsolatedAsyncioTestCase):
    async def test_stop_then_delete(self):
        mock_client = MagicMock()
        mock_client.stop_execution = AsyncMock(return_value={})
        mock_client.delete_execution = AsyncMock(return_value={})
        with patch(
            "app.services.dispatch_service.resolve_dispatch_n8n_client",
            return_value=mock_client,
        ):
            out = await cancel_n8n_execution("42")
        self.assertTrue(out["n8n_stopped"])
        self.assertTrue(out["n8n_deleted"])
        self.assertIsNone(out["n8n_error"])

    async def test_no_client(self):
        with patch(
            "app.services.dispatch_service.resolve_dispatch_n8n_client",
            return_value=None,
        ):
            out = await cancel_n8n_execution("42")
        self.assertFalse(out["n8n_stopped"])
        self.assertFalse(out["n8n_deleted"])
        self.assertIn("N8N", out["n8n_error"] or "")
```

- [ ] **Step 3: Implementar em `dispatch_service.py`**

```python
from urllib.parse import urlparse
from app.services.hq_n8n_service import parse_n8n_instances
from app.services.n8n_instance_client import N8nInstanceClient


def resolve_dispatch_n8n_client(settings=None) -> Optional[N8nInstanceClient]:
    settings = settings or get_settings()
    instances = parse_n8n_instances(settings)
    if not instances:
        return None
    preferred = (settings.N8N_DISPATCH_INSTANCE_ID or "").strip()
    if preferred:
        for cfg in instances:
            if cfg.id == preferred:
                return N8nInstanceClient(cfg, verify_ssl=settings.N8N_SSL_VERIFY)
    webhook = (settings.N8N_DISPATCH_WEBHOOK_URL or "").strip()
    host = urlparse(webhook).netloc.lower() if webhook else ""
    if host:
        for cfg in instances:
            if urlparse(cfg.base_url).netloc.lower() == host:
                return N8nInstanceClient(cfg, verify_ssl=settings.N8N_SSL_VERIFY)
    return N8nInstanceClient(instances[0], verify_ssl=settings.N8N_SSL_VERIFY)


async def cancel_n8n_execution(execution_id: str) -> dict[str, Any]:
    client = resolve_dispatch_n8n_client()
    if not client:
        return {
            "n8n_stopped": False,
            "n8n_deleted": False,
            "n8n_error": "N8N_INSTANCES não configurado para stop/delete.",
        }
    stopped = False
    deleted = False
    err: Optional[str] = None
    try:
        await client.stop_execution(execution_id)
        stopped = True
    except Exception as exc:
        # 404 / já parada: segue para delete
        msg = str(exc)
        if "404" not in msg and "Not Found" not in msg:
            err = f"stop: {msg}"
    try:
        await client.delete_execution(execution_id)
        deleted = True
    except Exception as exc:
        err = (err + "; " if err else "") + f"delete: {exc}"
    return {"n8n_stopped": stopped, "n8n_deleted": deleted, "n8n_error": err}


def save_campaign_execution_id(
    supabase: SupabaseClient, campaign_id: str, execution_id: str
) -> None:
    supabase.table("dispatch_campaigns").update(
        {
            "n8n_execution_id": execution_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", campaign_id).execute()
```

- [ ] **Step 4: Rodar testes**

Run: `cd backend && python -m unittest test_dispatch_cancel -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/services/dispatch_service.py backend/test_dispatch_cancel.py
git commit -m "feat(dispatch): resolver cliente n8n e cancelar execução"
```

---

### Task 4: Endpoints n8n — registrar execution_id + gate cancelled

**Files:**
- Modify: `backend/app/routers/n8n_tools.py`

**Interfaces:**
- Consumes: `save_campaign_execution_id`
- Produces: `POST /api/n8n/tools/dispatch-execution` body `{campaign_id, execution_id}`
- `GET /tools/dispatch-targets` retorna `targets: []` e `cancelled: true` se status da campanha for `cancelled`

- [ ] **Step 1: Adicionar body + endpoint**

```python
class DispatchExecutionBody(BaseModel):
    campaign_id: str
    execution_id: str


@router.post("/tools/dispatch-execution")
async def n8n_tool_dispatch_execution(
    body: DispatchExecutionBody,
    _caller: dict = Depends(verify_n8n_api_key),
    supabase: SupabaseClient = Depends(get_supabase),
):
    """Registra o execution_id n8n na campanha (chamar no início do workflow)."""
    from app.services.dispatch_service import save_campaign_execution_id

    camp_res = (
        supabase.table("dispatch_campaigns")
        .select("id")
        .eq("id", body.campaign_id)
        .limit(1)
        .execute()
    )
    if not camp_res.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    eid = (body.execution_id or "").strip()
    if not eid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="execution_id obrigatório.")
    save_campaign_execution_id(supabase, body.campaign_id, eid)
    return {"ok": True, "campaign_id": body.campaign_id, "execution_id": eid}
```

- [ ] **Step 2: Em `n8n_tool_dispatch_targets`, selecionar também `status`**

Trocar select para `"id,message,min_delay,max_delay,instance_token,status"`. Após carregar campaign:

```python
if (campaign.get("status") or "") == "cancelled":
    return {
        "campaign_id": campaign_id,
        "message": campaign.get("message") or "",
        "min_delay": campaign.get("min_delay") or 180,
        "max_delay": campaign.get("max_delay") or 540,
        "instance_token": campaign.get("instance_token"),
        "cancelled": True,
        "targets": [],
    }
```

Atualizar docstring do módulo (lista de endpoints).

- [ ] **Step 3: Smoke import**

Run: `cd backend && python -c "from app.routers.n8n_tools import n8n_tool_dispatch_execution; print('ok')"`  
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/app/routers/n8n_tools.py
git commit -m "feat(n8n): registrar execution_id e bloquear targets cancelled"
```

---

### Task 5: Endpoint JWT cancel + resposta

**Files:**
- Modify: `backend/app/routers/dispatch.py`
- Modify: `backend/test_dispatch_cancel.py`

**Interfaces:**
- Produces: `POST /api/dispatch/campaigns/{campaign_id}/cancel` →  
  `{ id, status, n8n_stopped, n8n_deleted, n8n_error?, ...CampaignOut fields }`

- [ ] **Step 1: Modelo de resposta**

```python
class CancelCampaignOut(CampaignOut):
    n8n_stopped: bool = False
    n8n_deleted: bool = False
    n8n_error: Optional[str] = None
```

- [ ] **Step 2: Endpoint**

```python
@router.post("/campaigns/{campaign_id}/cancel", response_model=CancelCampaignOut)
async def cancel_campaign(
    campaign_id: UUID,
    user=Depends(get_current_user),
    supabase: SupabaseClient = Depends(get_supabase),
):
    from app.services.dispatch_service import cancel_n8n_execution

    tid = _tenant_id(user)
    res = (
        supabase.table("dispatch_campaigns")
        .select("*")
        .eq("id", str(campaign_id))
        .eq("tenant_id", tid)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campanha não encontrada.")
    campaign = rows[0]
    if campaign.get("status") != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Só é possível cancelar campanhas em andamento.",
        )

    now = datetime.now(timezone.utc).isoformat()
    supabase.table("dispatch_campaigns").update(
        {"status": "cancelled", "finished_at": now, "updated_at": now}
    ).eq("id", str(campaign_id)).eq("tenant_id", tid).execute()

    n8n_stopped = False
    n8n_deleted = False
    n8n_error = None
    eid = (campaign.get("n8n_execution_id") or "").strip()
    if eid:
        n8n_res = await cancel_n8n_execution(eid)
        n8n_stopped = bool(n8n_res.get("n8n_stopped"))
        n8n_deleted = bool(n8n_res.get("n8n_deleted"))
        n8n_error = n8n_res.get("n8n_error")
    else:
        n8n_error = "Sem execution_id — cancelado só no CRM."

    refreshed = (
        supabase.table("dispatch_campaigns")
        .select("*")
        .eq("id", str(campaign_id))
        .limit(1)
        .execute()
    ).data[0]

    return CancelCampaignOut(
        id=str(refreshed["id"]),
        message=refreshed["message"],
        status=refreshed["status"],
        min_delay=refreshed["min_delay"],
        max_delay=refreshed["max_delay"],
        total=refreshed.get("total") or 0,
        sent=refreshed.get("sent") or 0,
        failed=refreshed.get("failed") or 0,
        created_at=refreshed.get("created_at"),
        started_at=refreshed.get("started_at"),
        finished_at=refreshed.get("finished_at"),
        n8n_stopped=n8n_stopped,
        n8n_deleted=n8n_deleted,
        n8n_error=n8n_error,
    )
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/dispatch.py
git commit -m "feat(dispatch): endpoint cancelar campanha"
```

---

### Task 6: Frontend — API + botão Cancelar

**Files:**
- Modify: `frontend-next/lib/api.ts`
- Modify: `frontend-next/app/(dashboard)/disparador/page.tsx`

**Interfaces:**
- Consumes: `POST /api/dispatch/campaigns/{id}/cancel`
- Produces: `cancelDispatchCampaign(campaignId, token)`

- [ ] **Step 1: API client**

Em `api.ts`, após `listDispatchCampaigns`:

```typescript
export type CancelDispatchCampaignResult = DispatchCampaign & {
    n8n_stopped: boolean;
    n8n_deleted: boolean;
    n8n_error?: string | null;
};

export const cancelDispatchCampaign = (campaignId: string, token?: string) =>
    apiPost<CancelDispatchCampaignResult>(
        `/api/dispatch/campaigns/${encodeURIComponent(campaignId)}/cancel`,
        {},
        token
    );
```

- [ ] **Step 2: Import + handler na page**

Importar `cancelDispatchCampaign`. Estado `cancelling` (boolean). Handler:

```typescript
const handleCancelCampaign = async () => {
    if (!token || !campaign || campaign.status !== "running") return;
    if (!window.confirm("Cancelar o envio desta campanha?")) return;
    setCancelling(true);
    setError(null);
    try {
        const res = await cancelDispatchCampaign(campaign.id, token);
        setCampaign({ ...campaign, ...res, targets: campaign.targets });
        await loadRecentCampaigns();
        if (res.n8n_error) {
            setError(
                res.n8n_deleted
                    ? null
                    : `Campanha cancelada. Aviso n8n: ${res.n8n_error}`
            );
        }
    } catch (e) {
        setError(e instanceof Error ? e.message : "Erro ao cancelar campanha.");
    } finally {
        setCancelling(false);
    }
};
```

(Ajustar `loadRecentCampaigns` para o nome real da função que lista campanhas na page.)

- [ ] **Step 3: UI no bloco progresso**

No header da section (junto ao status), se `campaign.status === "running"`:

```tsx
<button
    type="button"
    onClick={() => void handleCancelCampaign()}
    disabled={cancelling}
    className="rounded-lg border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-300 dark:hover:bg-red-950/40"
>
    {cancelling ? "Cancelando…" : "Cancelar envio"}
</button>
```

No badge de campanhas recentes, tratar `cancelled`:

```tsx
c.status === "cancelled"
  ? "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
  : /* existing branches */
```

Parar o poll quando status não for `running` (já deve estar no `pollCampaign` — confirmar e incluir `cancelled`).

- [ ] **Step 4: Commit**

```bash
git add frontend-next/lib/api.ts "frontend-next/app/(dashboard)/disparador/page.tsx"
git commit -m "feat(dispatch): botão cancelar envio no Comunicados"
```

---

### Task 7: Workflow n8n — registrar execution_id no start

**Files:**
- n8n (host do `N8N_DISPATCH_WEBHOOK_URL`, tipicamente wbtech / `n8n-neurix-1.wbtech.dev`)

**Interfaces:**
- Consumes: `POST {CRM}/api/n8n/tools/dispatch-execution` com header `X-API-Key: N8N_API_KEY`
- Body: `{ "campaign_id": "{{ $json.campaign_id }}", "execution_id": "{{ $execution.id }}" }`

- [ ] **Step 1: Localizar workflow ativo do webhook `disparador-crm-start`**

Usar MCP n8n (`search_workflows` / UI) no host correto.

- [ ] **Step 2: Inserir HTTP Request imediatamente após o Webhook**

- Method: POST  
- URL: `{CRM_BASE}/api/n8n/tools/dispatch-execution` (staging/prod conforme env)  
- Header: `X-API-Key` = mesma key do CRM  
- JSON body com `campaign_id` do payload e `$execution.id`  
- `onError: continueRegularOutput` (não derrubar o disparo se o registro falhar)

- [ ] **Step 3: (Opcional) No loop, se `cancelled: true` em dispatch-targets, encerrar**

- [ ] **Step 4: Documentar no PR / nota de deploy**

Ops: rodar migration `023`; garantir `N8N_INSTANCES` inclui o host do disparador; opcional `N8N_DISPATCH_INSTANCE_ID`.

- [ ] **Step 5: Commit** (se houver doc de ops no repo)

```bash
# se atualizar docs/staging-setup.md com a env nova:
git add docs/staging-setup.md
git commit -m "docs: N8N_DISPATCH_INSTANCE_ID e cancelamento do disparador"
```

---

## Spec coverage (self-review)

| Spec item | Task |
|-----------|------|
| Migration `n8n_execution_id` + status `cancelled` | 1 |
| Callback `dispatch-execution` | 4 |
| `POST .../cancel` + stop/delete | 3, 5 |
| Cliente n8n stop/delete | 2 |
| Botão UI running | 6 |
| Sem execution_id → só CRM | 5 |
| Loop n8n / gate cancelled | 4 + 7 |
| Fora de escopo (done/failed, rollback) | não implementado |

## Placeholder scan

Nenhum TBD/TODO residual nas tasks.

## Type consistency

- `n8n_stopped` / `n8n_deleted` / `n8n_error` alinhados entre service, router e `CancelDispatchCampaignResult`
- Status literal `cancelled` em DB, backend e UI
