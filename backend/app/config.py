"""
Neurix CRM — Application Configuration
Loads settings from environment variables.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── Application ──
    APP_NAME: str = "Neurix CRM"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    CORS_ORIGINS: str = "*"  # Comma-separated origins in production

    # ── n8n Integration ──
    # Dokploy/UIs às vezes usam outro nome; o backend só lia N8N_API_KEY antes.
    N8N_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices(
            "N8N_API_KEY",
            "n8n_api_key",
            "N8N_APIKEY",
        ),
    )

    # ── Neurix HQ (outbound n8n instances) ──
    # JSON array: [{"id":"neurix","label":"Neurix","base_url":"https://...","api_key":"..."}]
    N8N_INSTANCES: str = ""
    HQ_CACHE_TTL_SECONDS: int = 300

    # ── Supabase ──
    SUPABASE_URL: str = ""
    SUPABASE_PUBLIC_URL: str = ""  # Browser-accessible URL (e.g. https://your-supabase.domain)
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    @field_validator(
        "SUPABASE_URL",
        "SUPABASE_PUBLIC_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_JWT_SECRET",
        mode="before",
    )
    @classmethod
    def strip_supabase_env(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    # ── Redis ──
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    # ── Auth ──
    SESSION_DURATION_DAYS: int = 14
    TWO_FACTOR_ENABLED: bool = True

    # ── Uazapi (WhatsApp) ──
    # URL pública do backend (sem barra final) — usada em POST /webhook na Uazapi e na doc do endpoint.
    PUBLIC_API_BASE_URL: str = "https://crm.wbtech.dev"
    UAZAPI_URL: str = ""
    UAZAPI_ADMIN_TOKEN: str = ""  # For /instance/all and admin endpoints
    UAZAPI_INSTANCE_TOKEN: str = ""  # For /send/* endpoints (per-instance)
    UAZAPI_WEBHOOK_SECRET: str = ""  # URL-based secret for webhook validation

    @property
    def uazapi_webhook_callback_url(self) -> str:
        """URL completa do webhook Uazapi → Neurix (inclui ?secret= se UAZAPI_WEBHOOK_SECRET estiver definido)."""
        base = f"{self.PUBLIC_API_BASE_URL.rstrip('/')}/api/webhooks/uazapi"
        if self.UAZAPI_WEBHOOK_SECRET:
            return f"{base}?secret={self.UAZAPI_WEBHOOK_SECRET}"
        return base

    # ── SMTP (for Supabase Auth 2FA emails) ──
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASS: str = ""

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://default:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

@lru_cache
def get_settings() -> Settings:
    return Settings()
