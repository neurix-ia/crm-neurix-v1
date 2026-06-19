"""
Neurix CRM — FastAPI Application Entry Point
"""

import logging
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.dependencies import get_supabase
from app.observability import metrics
from app.routers import (
    admin_api,
    auth,
    hq_n8n,
    hq_summary,
    catalog_search,
    chatwoot,
    clients,
    dashboard,
    funnels,
    inboxes,
    keyword_rules,
    leads,
    n8n_tools,
    n8n_webhook,
    orders,
    organizations,
    product_categories,
    products,
    promotions,
    settings as settings_router,
    upload,
    users,
    webhooks,
    whatsapp,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    cfg = get_settings()
    print(f"🚀 {cfg.APP_NAME} v{cfg.APP_VERSION} starting...")
    print(f"   Redis: {cfg.REDIS_HOST}:{cfg.REDIS_PORT}")
    print(f"   Supabase: {'✅ Configured' if cfg.SUPABASE_URL else '⚠️ Not configured'}")
    print(f"   Uazapi: {'✅ Configured' if cfg.UAZAPI_URL else '⚠️ Not configured'}")
    if not cfg.N8N_API_KEY:
        logger.warning(
            "N8N_API_KEY não configurada — endpoint /api/n8n/webhook rejeitará todos os requests"
        )
    if not (cfg.N8N_INSTANCES or "").strip():
        logger.warning(
            "N8N_INSTANCES não configurado — Neurix HQ (/admin/core) não conseguirá consultar n8n"
        )
    yield
    print(f"👋 {cfg.APP_NAME} shutting down...")


def create_app() -> FastAPI:
    cfg = get_settings()

    app = FastAPI(
        title=cfg.APP_NAME,
        version=cfg.APP_VERSION,
        description="Backend API para o Neurix Smart CRM — Gestão de Leads, Produtos, Pedidos e Integrações.",
        lifespan=lifespan,
    )

    if cfg.DEBUG:
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.exception_handler(Exception)
        async def debug_unhandled_exception(request: Request, exc: Exception):
            if isinstance(exc, HTTPException):
                raise exc
            logger.exception("unhandled_exception path=%s", request.url.path)
            return JSONResponse(
                status_code=500,
                content={"detail": str(exc), "error_type": type(exc).__name__, "path": str(request.url.path)},
            )

    # ── CORS ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ──
    app.include_router(auth.router, prefix="/api/auth", tags=["Autenticação"])
    app.include_router(admin_api.router, prefix="/api/admin", tags=["Console Admin"])
    app.include_router(hq_summary.router, prefix="/api/admin", tags=["Neurix HQ"])
    app.include_router(hq_n8n.router, prefix="/api/admin", tags=["Neurix HQ"])
    app.include_router(organizations.router, prefix="/api/organizations", tags=["Organizações"])
    app.include_router(users.router, prefix="/api/users", tags=["Usuários (Admin)"])
    app.include_router(funnels.router, prefix="/api/funnels", tags=["Funis"])
    app.include_router(inboxes.router, prefix="/api/inboxes", tags=["Caixas de entrada"])
    app.include_router(clients.router, prefix="/api/clients", tags=["Clientes CRM"])
    app.include_router(leads.router, prefix="/api/leads", tags=["Leads / Kanban"])
    app.include_router(products.router, prefix="/api/products", tags=["Produtos"])
    app.include_router(product_categories.router, prefix="/api/product-categories", tags=["Categorias de Produto"])
    app.include_router(promotions.router, prefix="/api/promotions", tags=["Promoções"])
    app.include_router(catalog_search.router, prefix="/api/catalog", tags=["Busca de Catálogo"])
    app.include_router(orders.router, prefix="/api/orders", tags=["Pedidos"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(settings_router.router, prefix="/api/settings", tags=["Configurações"])
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["Webhooks"])
    app.include_router(n8n_webhook.router, prefix="/api/n8n", tags=["N8n Integration"])
    app.include_router(n8n_tools.router, prefix="/api/n8n", tags=["N8n Integration"])
    app.include_router(keyword_rules.router, prefix="/api/keyword-rules", tags=["Regras de Keywords"])
    app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])
    app.include_router(whatsapp.router, prefix="/api/whatsapp", tags=["WhatsApp"])
    app.include_router(chatwoot.router, prefix="/api/chatwoot", tags=["Chatwoot"])

    # ── Health Check ──
    @app.get("/api/health", tags=["Sistema"])
    async def health_check():
        return {
            "status": "ok",
            "app": cfg.APP_NAME,
            "version": cfg.APP_VERSION,
            "supabase_configured": bool(cfg.SUPABASE_URL),
            "redis_configured": bool(cfg.REDIS_HOST),
        }

    @app.get("/api/health/db", tags=["Sistema"])
    async def health_db(supabase=Depends(get_supabase)):
        """Testa PostgREST com SERVICE_ROLE_KEY (mesmo client das rotas autenticadas)."""
        try:
            supabase.table("profiles").select("id").limit(1).execute()
            return {"db": "ok"}
        except Exception as exc:
            payload = {"db": "error", "error_type": type(exc).__name__}
            if cfg.DEBUG:
                payload["detail"] = str(exc)
            return payload

    @app.get("/api/metrics", tags=["Sistema"])
    async def metrics_snapshot():
        return {"metrics": metrics.snapshot()}

    return app


app = create_app()
