"""
Sprint 4 — Validação end-to-end: n8n webhook, /clientes, client→lead flow.

Run: cd backend && python -m pytest test_n8n_e2e.py -v

Tests are organized by sprint task:
  S4-T1: /clientes fix validation (CORS config, trailing slash, API)
  S4-T2: Automatic client → lead flow (webhook processor)
  S4-T3: n8n → CRM e2e (all intents, idempotency, product matching)
"""

import unittest
from collections import deque
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.dependencies import get_supabase, get_current_user
from app.models.n8n_webhook import (
    N8nWebhookPayload,
    N8nWebhookResponse,
    OrderItem,
    NoteTimelineEntry,
    ORPHAN_CATALOG_BLOCK_END,
    ORPHAN_CATALOG_BLOCK_START,
    build_products_json,
    generate_client_name,
    generate_product_summary,
    merge_notes_with_orphan_catalog_block,
    parse_brl_to_float,
    partition_products_by_match,
    strip_orphan_catalog_block,
)

FAKE_API_KEY = "test-api-key-abc123"
FAKE_TENANT_ID = "tenant-uuid-0001"
FAKE_FUNNEL_ID = "funnel-uuid-0001"
FAKE_INBOX_ID = "inbox-uuid-0001"
FAKE_LEAD_ID = "lead-uuid-0001"
FAKE_STAGE_ID = "stage-uuid-b2c"
FAKE_CHAT_ID = "554195802989@s.whatsapp.net"
FAKE_PRODUCT_ID = "product-uuid-geleia"
FAKE_CATEGORY_CLIENTE_FINAL_ID = "cat-cliente-final"
FAKE_CATEGORY_LOJISTA_ID = "cat-lojista-b2b"

INBOX_ROW = {
    "id": FAKE_INBOX_ID,
    "tenant_id": FAKE_TENANT_ID,
    "funnel_id": FAKE_FUNNEL_ID,
    "name": "Inbox Test",
    "uazapi_settings": {"instance_token": "token-abc"},
}

LEAD_ROW = {
    "id": FAKE_LEAD_ID,
    "tenant_id": FAKE_TENANT_ID,
    "inbox_id": FAKE_INBOX_ID,
    "funnel_id": FAKE_FUNNEL_ID,
    "whatsapp_chat_id": FAKE_CHAT_ID,
    "contact_name": "Augusto",
    "company_name": "Test Lead",
    "stage": "Novo",
    "value": 0,
    "client_id": None,
    "products_json": [],
    "notes": "",
    "phone": "+554195802989",
}

STAGE_B2C = {"id": FAKE_STAGE_ID, "name": "B2C", "order_position": 1}
STAGE_B2B = {"id": "stage-uuid-b2b", "name": "B2B", "order_position": 2}
STAGE_REVENDA = {"id": "stage-uuid-rev", "name": "Quero Vender", "order_position": 3}
STAGE_PEDIDO = {"id": "stage-uuid-ped", "name": "Pedido Feito", "order_position": 4}
ALL_STAGES = [STAGE_B2C, STAGE_B2B, STAGE_REVENDA, STAGE_PEDIDO]

PRODUCT_DB_ROW = {
    "id": FAKE_PRODUCT_ID,
    "name": "Geleia de Amora",
    "price": 18.0,
    "category_id": FAKE_CATEGORY_CLIENTE_FINAL_ID,
    "category": "cliente-final",
    "tenant_id": FAKE_TENANT_ID,
    "is_active": True,
}

CATEGORY_CLIENTE_FINAL_ROW = {
    "id": FAKE_CATEGORY_CLIENTE_FINAL_ID,
    "slug": "cliente-final",
}

CATEGORY_LOJISTA_ROW = {
    "id": FAKE_CATEGORY_LOJISTA_ID,
    "slug": "lojista-b2b",
}


# ═══════════════════════════════════════════════════════════════
# AC16: parse_brl_to_float — unit tests
# ═══════════════════════════════════════════════════════════════

class TestParseBrlToFloat(unittest.TestCase):
    def test_standard_brl(self):
        self.assertAlmostEqual(parse_brl_to_float("R$ 112,00"), 112.0)

    def test_brl_no_space(self):
        self.assertAlmostEqual(parse_brl_to_float("R$112,00"), 112.0)

    def test_plain_comma(self):
        self.assertAlmostEqual(parse_brl_to_float("112,00"), 112.0)

    def test_plain_dot(self):
        self.assertAlmostEqual(parse_brl_to_float("112.00"), 112.0)

    def test_thousands_separator(self):
        self.assertAlmostEqual(parse_brl_to_float("R$ 1.112,00"), 1112.0)

    def test_empty_string(self):
        self.assertAlmostEqual(parse_brl_to_float(""), 0.0)

    def test_none(self):
        self.assertAlmostEqual(parse_brl_to_float(None), 0.0)

    def test_small_value(self):
        self.assertAlmostEqual(parse_brl_to_float("R$ 36,00"), 36.0)

    def test_decimal_cents(self):
        self.assertAlmostEqual(parse_brl_to_float("R$ 54,50"), 54.5)
        self.assertAlmostEqual(
            parse_brl_to_float(
                "R$ 180,00 (produtos) | frete a confirmar pelo atendente"
            ),
            180.0,
        )


# ═══════════════════════════════════════════════════════════════
# Helpers: build_products_json, generate_*
# ═══════════════════════════════════════════════════════════════

class TestBuildProductsJson(unittest.TestCase):
    def test_matched_by_id(self):
        items = [OrderItem(product_id=FAKE_PRODUCT_ID, product="Geleia de Amora", quantity=2, total="R$ 36,00")]
        products_db = [PRODUCT_DB_ROW]
        result, warnings = build_products_json(items, products_db, FAKE_TENANT_ID)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], FAKE_PRODUCT_ID)
        self.assertEqual(result[0]["product_id"], FAKE_PRODUCT_ID)
        self.assertEqual(result[0]["quantity"], 2)
        self.assertEqual(result[0]["qty"], 2)
        self.assertAlmostEqual(result[0]["price"], 18.0)
        self.assertAlmostEqual(result[0]["line_subtotal"], 36.0)
        self.assertFalse(result[0].get("unmatched", False))
        self.assertEqual(len(warnings), 0)

    def test_matched_by_name_case_insensitive(self):
        items = [OrderItem(product="geleia de amora", quantity=1, total="R$ 18,00")]
        products_db = [PRODUCT_DB_ROW]
        result, warnings = build_products_json(items, products_db, FAKE_TENANT_ID)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], FAKE_PRODUCT_ID)
        self.assertEqual(len(warnings), 0)

    def test_unmatched_product(self):
        items = [OrderItem(product="Produto Inexistente", quantity=1, total="R$ 25,00")]
        products_db = [PRODUCT_DB_ROW]
        result, warnings = build_products_json(items, products_db, FAKE_TENANT_ID)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].get("unmatched"))
        self.assertAlmostEqual(result[0]["price"], 25.0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("não encontrado", warnings[0])

    def test_cross_tenant_product_id_rejected(self):
        other_tenant_product = {**PRODUCT_DB_ROW, "tenant_id": "other-tenant", "name": "Produto X"}
        items = [OrderItem(product_id=FAKE_PRODUCT_ID, product="Produto Y", quantity=1, total="R$ 18,00")]
        result, warnings = build_products_json(items, [other_tenant_product], FAKE_TENANT_ID)
        self.assertEqual(len(result), 1)
        self.assertTrue(any("outro tenant" in w for w in warnings))
        self.assertTrue(result[0].get("unmatched"))

    def test_empty_items(self):
        result, warnings = build_products_json([], [PRODUCT_DB_ROW], FAKE_TENANT_ID)
        self.assertEqual(len(result), 0)
        self.assertEqual(len(warnings), 0)

    def test_matched_accent_spacing_and_punctuation(self):
        row = {
            "id": FAKE_PRODUCT_ID,
            "name": "Geleia de amora 0% açúcar",
            "price": 22.0,
            "category_id": None,
            "tenant_id": FAKE_TENANT_ID,
            "is_active": True,
        }
        items = [
            OrderItem(
                product="  GELEIA   DE AMORA 0% acucar  ",
                quantity=1,
                total="R$ 22,00",
            )
        ]
        result, warnings = build_products_json(items, [row], FAKE_TENANT_ID)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], FAKE_PRODUCT_ID)
        self.assertFalse(result[0].get("unmatched"))
        self.assertEqual(len(warnings), 0)

    def test_matched_inactive_product_by_name(self):
        row = {**PRODUCT_DB_ROW, "is_active": False}
        items = [OrderItem(product="Geleia de Amora", quantity=1, total="R$ 18,00")]
        result, warnings = build_products_json(items, [row], FAKE_TENANT_ID)
        self.assertEqual(result[0]["id"], FAKE_PRODUCT_ID)
        self.assertFalse(result[0].get("unmatched"))
        self.assertEqual(len(warnings), 0)

    def test_fuzzy_unique_match_adds_warning(self):
        row = {
            "id": "prod-geleia-caseira",
            "name": "Geleia Caseira Especial Tradicional",
            "price": 10.0,
            "category_id": None,
            "tenant_id": FAKE_TENANT_ID,
            "is_active": True,
        }
        items = [
            OrderItem(
                product="Geleia Caseira Espeial Tradicional",
                quantity=1,
                total="R$ 10,00",
            )
        ]
        result, warnings = build_products_json(items, [row], FAKE_TENANT_ID)
        self.assertEqual(result[0]["id"], "prod-geleia-caseira")
        self.assertFalse(result[0].get("unmatched"))
        self.assertTrue(any("Match aproximado" in w for w in warnings))

    def test_fuzzy_ambiguous_no_match(self):
        a = {
            "id": "p-a",
            "name": "Geleia Premium Alpha Lote",
            "price": 1.0,
            "category_id": None,
            "tenant_id": FAKE_TENANT_ID,
            "is_active": True,
        }
        b = {
            "id": "p-b",
            "name": "Geleia Premium Alph Lote",
            "price": 1.0,
            "category_id": None,
            "tenant_id": FAKE_TENANT_ID,
            "is_active": True,
        }
        items = [OrderItem(product="Geleia Premium Alp Lote", quantity=1, total="R$ 1,00")]
        result, warnings = build_products_json(items, [a, b], FAKE_TENANT_ID)
        self.assertTrue(result[0].get("unmatched"))
        self.assertFalse(any("Match aproximado" in w for w in warnings))

    def test_matched_agent_accent_catalog_ascii_equivalent(self):
        """Catálogo só ASCII; agente envia acentos — mesma chave normalizada."""
        row = {
            "id": "prod-cafe",
            "name": "Cafe premium especial",
            "price": 5.0,
            "category_id": None,
            "tenant_id": FAKE_TENANT_ID,
            "is_active": True,
        }
        items = [OrderItem(product="Café prémiùm espécial", quantity=1, total="R$ 5,00")]
        result, warnings = build_products_json(items, [row], FAKE_TENANT_ID)
        self.assertEqual(result[0]["id"], "prod-cafe")
        self.assertFalse(result[0].get("unmatched"))
        self.assertEqual(len(warnings), 0)

    def test_matched_double_spaces_only_in_agent_string(self):
        row = {
            "id": "p-jam",
            "name": "Geleia Morango",
            "price": 12.0,
            "category_id": None,
            "tenant_id": FAKE_TENANT_ID,
            "is_active": True,
        }
        items = [OrderItem(product="Geleia    Morango", quantity=2, total="R$ 24,00")]
        result, warnings = build_products_json(items, [row], FAKE_TENANT_ID)
        self.assertEqual(result[0]["id"], "p-jam")
        self.assertEqual(result[0]["quantity"], 2)
        self.assertFalse(result[0].get("unmatched"))
        self.assertEqual(len(warnings), 0)


class TestGenerateProductSummary(unittest.TestCase):
    def test_multiple_items(self):
        items = [
            OrderItem(product="Geleia de Amora", quantity=2, total="R$ 36,00"),
            OrderItem(product="Geleia de Morango", quantity=3, total="R$ 54,00"),
        ]
        result = generate_product_summary(items)
        self.assertIn("2x Geleia de Amora", result)
        self.assertIn("3x Geleia de Morango", result)

    def test_empty(self):
        self.assertEqual(generate_product_summary([]), "Sem itens")


class TestGenerateClientName(unittest.TestCase):
    def test_client_row_has_display_name(self):
        name = generate_client_name(LEAD_ROW, N8nWebhookPayload(
            instance_token="t", whatsapp_chat_id="c", intent="perfil_b2c",
        ), {"display_name": "Maria"})
        self.assertEqual(name, "Maria")

    def test_payload_lead_name(self):
        name = generate_client_name(LEAD_ROW, N8nWebhookPayload(
            instance_token="t", whatsapp_chat_id="c", intent="perfil_b2c", lead_name="Augusto",
        ), None)
        self.assertEqual(name, "Augusto")

    def test_fallback_contact_name(self):
        name = generate_client_name(LEAD_ROW, N8nWebhookPayload(
            instance_token="t", whatsapp_chat_id="c", intent="perfil_b2c",
        ), None)
        self.assertEqual(name, "Augusto")

    def test_final_fallback(self):
        empty_lead = {**LEAD_ROW, "contact_name": "", "company_name": ""}
        name = generate_client_name(empty_lead, N8nWebhookPayload(
            instance_token="t", whatsapp_chat_id="c", intent="perfil_b2c",
        ), None)
        self.assertEqual(name, "Cliente WhatsApp")


# ═══════════════════════════════════════════════════════════════
# Pydantic model validation
# ═══════════════════════════════════════════════════════════════

class TestN8nPayloadValidation(unittest.TestCase):
    def test_valid_perfil_payload(self):
        p = N8nWebhookPayload(
            instance_token="abc",
            whatsapp_chat_id="554195802989@s.whatsapp.net",
            phone="+55 41 9580-2989",
            lead_name="Augusto",
            intent="perfil_b2c",
            button_id="btn_cliente_final",
        )
        self.assertEqual(p.intent, "perfil_b2c")
        self.assertIsNone(p.order_summary)

    def test_valid_pedido_payload(self):
        p = N8nWebhookPayload(
            instance_token="abc",
            whatsapp_chat_id="554195802989@s.whatsapp.net",
            intent="pedido",
            order_summary=[
                OrderItem(product_id="uuid-1", product="Geleia de Amora", quantity=2, total="R$ 36,00"),
            ],
            payment_method="PIX",
            total_value="R$ 36,00",
        )
        self.assertEqual(p.intent, "pedido")
        self.assertEqual(len(p.order_summary), 1)

    def test_valid_pagto_confirmado_payload(self):
        p = N8nWebhookPayload(
            instance_token="abc",
            whatsapp_chat_id="554195802989@s.whatsapp.net",
            intent="pagto_confirmado",
            order_id="order-uuid-1",
        )
        self.assertEqual(p.intent, "pagto_confirmado")
        self.assertEqual(p.order_id, "order-uuid-1")

    def test_invalid_intent_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            N8nWebhookPayload(
                instance_token="abc",
                whatsapp_chat_id="chat",
                intent="invalid_intent",
            )

    def test_note_timeline(self):
        p = N8nWebhookPayload(
            instance_token="abc",
            whatsapp_chat_id="chat",
            intent="pedido",
            note_timeline=[
                NoteTimelineEntry(content="Evento 1"),
                NoteTimelineEntry(content="Evento 2", timestamp="2026-04-03 10:00"),
            ],
        )
        self.assertEqual(len(p.note_timeline), 2)


# ═══════════════════════════════════════════════════════════════
# S4-T1: /clientes — CORS config + API trailing slash
# ═══════════════════════════════════════════════════════════════

class TestClientesConfig(unittest.TestCase):
    """Verify that CORS config and URL patterns are correct."""

    def test_cors_origins_list_parses_comma_separated(self):
        from app.config import Settings
        s = Settings(CORS_ORIGINS="https://crm.wbtech.dev,https://other.dev")
        self.assertEqual(s.cors_origins_list, ["https://crm.wbtech.dev", "https://other.dev"])

    def test_cors_wildcard_works(self):
        from app.config import Settings
        s = Settings(CORS_ORIGINS="*")
        self.assertEqual(s.cors_origins_list, ["*"])

    def test_api_ts_list_clients_trailing_slash(self):
        """Verify listClients uses /api/clients/ (with trailing slash) in api.ts."""
        import re
        with open("../frontend-next/lib/api.ts", "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'listClients.*?apiGet.*?["\']([^"\']+)["\']', content, re.DOTALL)
        self.assertIsNotNone(match, "listClients not found in api.ts")
        url = match.group(1)
        self.assertTrue(url.endswith("/"), f"listClients URL should end with '/': {url}")

    def test_api_ts_create_client_trailing_slash(self):
        """Verify createCrmClient uses /api/clients/ (with trailing slash)."""
        import re
        with open("../frontend-next/lib/api.ts", "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(r'createCrmClient.*?apiPost.*?["\']([^"\']+)["\']', content, re.DOTALL)
        self.assertIsNotNone(match, "createCrmClient not found in api.ts")
        url = match.group(1)
        self.assertTrue(url.endswith("/"), f"createCrmClient URL should end with '/': {url}")


# ═══════════════════════════════════════════════════════════════
# S4-T1 continued: /clientes API endpoint (mock Supabase)
# ═══════════════════════════════════════════════════════════════

class _FakeExec:
    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count


def _make_mock_supabase():
    sb = MagicMock()
    return sb


def _make_fake_user():
    user = MagicMock()
    user.id = FAKE_TENANT_ID
    return user


class TestClientesEndpoint(unittest.TestCase):
    """Verify /api/clients/ route is registered and responds (not 404/405)."""

    def test_clients_route_exists(self):
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        self.assertIn("/api/clients/", routes)

    def test_clients_requires_auth(self):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/clients/")
        self.assertIn(resp.status_code, [401, 403])


# ═══════════════════════════════════════════════════════════════
# S4-T2: Webhook processor — client auto-creation
# ═══════════════════════════════════════════════════════════════

class TestWebhookClientAutoCreation(unittest.TestCase):
    """Verify webhook_processor calls resolve_or_create_crm_client."""

    def test_resolve_or_create_crm_client_creates_pf(self):
        from app.services.webhook_lead_context import resolve_or_create_crm_client
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = _FakeExec(data=[])
        sb.table.return_value.insert.return_value.execute.return_value = _FakeExec(data=[
            {"id": "new-client-id"}
        ])
        result = resolve_or_create_crm_client(
            sb,
            tenant_id=FAKE_TENANT_ID,
            sender_phone_raw="+5541995802989",
            sender_name="Augusto",
        )
        self.assertEqual(result, "new-client-id")

    def test_resolve_or_create_crm_client_finds_existing(self):
        from app.services.webhook_lead_context import resolve_or_create_crm_client
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value = _FakeExec(data=[
            {"id": "existing-client", "phones": ["5541995802989"]}
        ])
        result = resolve_or_create_crm_client(
            sb,
            tenant_id=FAKE_TENANT_ID,
            sender_phone_raw="+5541995802989",
            sender_name="Augusto",
        )
        self.assertEqual(result, "existing-client")

    def test_resolve_or_create_returns_none_no_phone(self):
        from app.services.webhook_lead_context import resolve_or_create_crm_client
        sb = MagicMock()
        result = resolve_or_create_crm_client(
            sb,
            tenant_id=FAKE_TENANT_ID,
            sender_phone_raw="",
            sender_name="Augusto",
        )
        self.assertIsNone(result)


class TestGetFirstStageFunnel(unittest.TestCase):
    """Verify first stage resolution uses dynamic pipeline_stages, not legacy."""

    def test_returns_first_stage_name(self):
        from app.services.webhook_lead_context import get_first_stage_slug_for_funnel
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _FakeExec(data=[
            {"name": "Novo Lead", "order_position": 0}
        ])
        result = get_first_stage_slug_for_funnel(sb, tenant_id=FAKE_TENANT_ID, funnel_id=FAKE_FUNNEL_ID)
        self.assertEqual(result, "Novo Lead")

    def test_returns_empty_if_no_stages(self):
        from app.services.webhook_lead_context import get_first_stage_slug_for_funnel
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _FakeExec(data=[])
        result = get_first_stage_slug_for_funnel(sb, tenant_id=FAKE_TENANT_ID, funnel_id=FAKE_FUNNEL_ID)
        self.assertEqual(result, "")


# ═══════════════════════════════════════════════════════════════
# S4-T2: Legacy stages fully removed
# ═══════════════════════════════════════════════════════════════

class TestLegacyStagesRemoved(unittest.TestCase):
    """AC9: Verify legacy stage references are fully removed from codebase."""

    def test_no_lead_stage_enum(self):
        import app.models.lead as lead_mod
        self.assertFalse(hasattr(lead_mod, "LeadStage"), "LeadStage enum should be removed")

    def test_keyword_rule_target_stage_is_str(self):
        from app.models.keyword_rule import KeywordRuleBase
        field = KeywordRuleBase.model_fields["target_stage"]
        self.assertEqual(field.annotation, str)

    def test_keyword_engine_target_stage_is_str(self):
        from app.services.keyword_engine import KeywordRule
        import dataclasses
        fields = {f.name: f for f in dataclasses.fields(KeywordRule)}
        self.assertEqual(fields["target_stage"].type, str)

    def test_keyword_engine_fallback_rules_empty(self):
        from app.services.keyword_engine import FALLBACK_RULES
        self.assertEqual(FALLBACK_RULES, [])

    def test_webhook_lead_context_no_allowed_stages(self):
        import app.services.webhook_lead_context as wlc
        self.assertFalse(hasattr(wlc, "_ALLOWED_LEAD_STAGES"))
        self.assertFalse(hasattr(wlc, "clamp_stage_slug"))

    def test_webhook_processor_no_stage_order(self):
        import app.workers.webhook_processor as wp
        self.assertFalse(hasattr(wp, "stage_order"))

    def test_new_order_modal_no_contato_inicial(self):
        with open("../frontend-next/components/NewOrderModal.tsx", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("contato_inicial", content)

    def test_leads_router_no_stage_labels(self):
        import app.routers.leads as leads_mod
        self.assertFalse(hasattr(leads_mod, "STAGE_LABELS"))

    def test_test_db_sim_no_contato_inicial(self):
        with open("test_db_sim.py", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("contato_inicial", content)

    def test_lead_model_stage_default_empty(self):
        from app.models.lead import LeadBase
        field = LeadBase.model_fields["stage"]
        self.assertEqual(field.default, "")


# ═══════════════════════════════════════════════════════════════
# S4-T3: n8n webhook — API auth
# ═══════════════════════════════════════════════════════════════

class TestN8nWebhookAuth(unittest.TestCase):
    """AC1: API key auth via X-CRM-API-Key header."""

    def setUp(self):
        from app.config import Settings
        self.client = TestClient(app)
        self.mock_sb = _make_mock_supabase()
        self.settings_patch = patch("app.dependencies.get_settings")
        self.mock_settings = self.settings_patch.start()
        s = Settings(N8N_API_KEY=FAKE_API_KEY, SUPABASE_URL="http://fake", SUPABASE_ANON_KEY="fakekey")
        self.mock_settings.return_value = s
        app.dependency_overrides[get_supabase] = lambda: self.mock_sb

    def tearDown(self):
        app.dependency_overrides.clear()
        self.settings_patch.stop()

    def test_missing_api_key_returns_401(self):
        resp = self.client.post("/api/n8n/webhook", json={
            "instance_token": "abc",
            "whatsapp_chat_id": FAKE_CHAT_ID,
            "intent": "perfil_b2c",
        })
        self.assertIn(resp.status_code, [401, 503])

    def test_wrong_api_key_returns_401(self):
        resp = self.client.post(
            "/api/n8n/webhook",
            json={
                "instance_token": "abc",
                "whatsapp_chat_id": FAKE_CHAT_ID,
                "intent": "perfil_b2c",
            },
            headers={"X-CRM-API-Key": "wrong-key"},
        )
        self.assertIn(resp.status_code, [401, 503])


# ═══════════════════════════════════════════════════════════════
# S4-T3: n8n webhook — n8n config presence
# ═══════════════════════════════════════════════════════════════

class TestN8nConfigPresence(unittest.TestCase):
    """Verify N8N_API_KEY config field exists."""

    def test_settings_has_n8n_api_key(self):
        from app.config import Settings
        s = Settings()
        self.assertTrue(hasattr(s, "N8N_API_KEY"))
        self.assertEqual(s.N8N_API_KEY, "")

    def test_env_example_has_n8n_api_key(self):
        with open(".env.example", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("N8N_API_KEY", content)

    def test_n8n_router_registered(self):
        """Verify POST /api/n8n/webhook is registered in the app."""
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        self.assertIn("/api/n8n/webhook", routes)

    def test_verify_n8n_api_key_dependency_exists(self):
        from app.dependencies import verify_n8n_api_key
        self.assertTrue(callable(verify_n8n_api_key))


# ═══════════════════════════════════════════════════════════════
# S4-T3: n8n webhook — intent routing (mocked Supabase)
# ═══════════════════════════════════════════════════════════════

class TestN8nIntentRouting(unittest.TestCase):
    """Test that the router resolves inbox → lead and routes by intent."""

    def test_resolve_inbox_returns_inbox_row(self):
        from app.routers.n8n_webhook import _resolve_inbox
        sb = MagicMock()
        with patch("app.routers.n8n_webhook.find_inbox_by_instance_token", return_value=INBOX_ROW):
            result = _resolve_inbox(sb, "token-abc")
        self.assertEqual(result["id"], FAKE_INBOX_ID)

    def test_resolve_inbox_404_if_not_found(self):
        from app.routers.n8n_webhook import _resolve_inbox
        sb = MagicMock()
        with patch("app.routers.n8n_webhook.find_inbox_by_instance_token", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                _resolve_inbox(sb, "bad-token")
            self.assertEqual(ctx.exception.status_code, 404)

    def test_resolve_lead_by_inbox_id(self):
        from app.routers.n8n_webhook import _resolve_lead
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = _FakeExec(data=[LEAD_ROW])
        result = _resolve_lead(sb, inbox_id=FAKE_INBOX_ID, tenant_id=FAKE_TENANT_ID, whatsapp_chat_id=FAKE_CHAT_ID)
        self.assertEqual(result["id"], FAKE_LEAD_ID)

    def test_resolve_lead_404_if_not_found(self):
        from app.routers.n8n_webhook import _resolve_lead
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = _FakeExec(data=[])
        with self.assertRaises(HTTPException) as ctx:
            _resolve_lead(sb, inbox_id=FAKE_INBOX_ID, tenant_id=FAKE_TENANT_ID, whatsapp_chat_id="unknown@chat")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertIn("Lead não encontrado", ctx.exception.detail)

    def test_resolve_or_create_lead_creates_when_profile_intent_and_missing(self):
        from app.routers.n8n_webhook import _resolve_or_create_lead

        sb = MagicMock()
        empty = _FakeExec(data=[])
        created = _FakeExec(data=[{**LEAD_ROW, "id": "new-lead-id"}])
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.side_effect = [
            empty,
            empty,
        ]
        sb.table.return_value.insert.return_value.execute.return_value = created
        with patch("app.routers.n8n_webhook.get_first_stage_slug_for_funnel", return_value="Contato Inicial"):
            with patch("app.routers.n8n_webhook.resolve_or_create_crm_client", return_value=None):
                row, created_flag = _resolve_or_create_lead(
                    sb,
                    inbox=INBOX_ROW,
                    whatsapp_chat_id=FAKE_CHAT_ID,
                    lead_name="Augusto",
                    phone="+55 41 9580-2989",
                    create_if_missing=True,
                )
        self.assertTrue(created_flag)
        self.assertEqual(row["id"], "new-lead-id")

    def test_resolve_or_create_lead_raises_when_not_profile_and_missing(self):
        from app.routers.n8n_webhook import _resolve_or_create_lead

        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = _FakeExec(data=[])
        with self.assertRaises(HTTPException) as ctx:
            _resolve_or_create_lead(
                sb,
                inbox=INBOX_ROW,
                whatsapp_chat_id="unknown@chat",
                lead_name=None,
                phone=None,
                create_if_missing=False,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_resolve_stage_case_insensitive(self):
        from app.routers.n8n_webhook import _resolve_stage_case_insensitive
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = _FakeExec(data=ALL_STAGES)
        result = _resolve_stage_case_insensitive(
            sb, tenant_id=FAKE_TENANT_ID, funnel_id=FAKE_FUNNEL_ID, target_stage_name="b2c",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "B2C")

    def test_resolve_stage_not_found(self):
        from app.routers.n8n_webhook import _resolve_stage_case_insensitive
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = _FakeExec(data=ALL_STAGES)
        result = _resolve_stage_case_insensitive(
            sb, tenant_id=FAKE_TENANT_ID, funnel_id=FAKE_FUNNEL_ID, target_stage_name="Inexistente",
        )
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════
# S4-T3: INTENT_TO_STAGE mapping
# ═══════════════════════════════════════════════════════════════

class TestIntentStageMapping(unittest.TestCase):
    def test_all_intents_mapped(self):
        from app.routers.n8n_webhook import INTENT_TO_STAGE
        self.assertEqual(INTENT_TO_STAGE["perfil_b2c"], "B2C")
        self.assertEqual(INTENT_TO_STAGE["perfil_b2b"], "B2B")
        self.assertEqual(INTENT_TO_STAGE["perfil_revenda"], "Quero Vender")
        self.assertEqual(INTENT_TO_STAGE["pedido"], "Pedido Feito")
        self.assertEqual(INTENT_TO_STAGE["pagto_confirmado"], "Pagto Confirmado")


class TestCommercialProfileResolution(unittest.TestCase):
    def test_prefers_linked_client_person_type_over_stage(self):
        from app.routers.n8n_webhook import _resolve_effective_order_profile

        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _FakeExec(
            data=[{"person_type": "PJ"}]
        )

        profile = _resolve_effective_order_profile(
            sb,
            lead_row={**LEAD_ROW, "client_id": "client-uuid", "stage": "B2C"},
            tenant_id=FAKE_TENANT_ID,
        )
        self.assertEqual(profile, "PJ")

    def test_falls_back_to_stage_and_then_pf(self):
        from app.routers.n8n_webhook import _resolve_effective_order_profile

        profile_from_stage = _resolve_effective_order_profile(
            MagicMock(),
            lead_row={**LEAD_ROW, "client_id": None, "stage": "B2B"},
            tenant_id=FAKE_TENANT_ID,
        )
        profile_default = _resolve_effective_order_profile(
            MagicMock(),
            lead_row={**LEAD_ROW, "client_id": None, "stage": "Novo"},
            tenant_id=FAKE_TENANT_ID,
        )

        self.assertEqual(profile_from_stage, "PJ")
        self.assertEqual(profile_default, "PF")


# ═══════════════════════════════════════════════════════════════
# S4-T3: Migration file validation
# ═══════════════════════════════════════════════════════════════

class TestMigration012(unittest.TestCase):
    def test_migration_file_exists(self):
        import os
        self.assertTrue(os.path.exists("migrations/012_remove_legacy_stage_checks_and_orders_cols.sql"))

    def test_migration_drops_constraints_idempotent(self):
        with open("migrations/012_remove_legacy_stage_checks_and_orders_cols.sql", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("DROP CONSTRAINT IF EXISTS", content)
        self.assertIn("leads", content)
        self.assertIn("keyword_rules", content)

    def test_migration_adds_payment_method(self):
        with open("migrations/012_remove_legacy_stage_checks_and_orders_cols.sql", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("payment_method", content)
        self.assertIn("ADD COLUMN IF NOT EXISTS", content)

    def test_migration_adds_client_id_to_orders(self):
        with open("migrations/012_remove_legacy_stage_checks_and_orders_cols.sql", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("client_id", content)
        self.assertIn("crm_clients", content)

    def test_migration_deactivates_legacy_rules(self):
        with open("migrations/012_remove_legacy_stage_checks_and_orders_cols.sql", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("is_active = false", content)
        self.assertIn("contato_inicial", content)
        self.assertIn("escolhendo_sabores", content)


# ═══════════════════════════════════════════════════════════════
# S4-T3: Kanban board with zero stages (AC9)
# ═══════════════════════════════════════════════════════════════

class TestKanbanEmptyBoard(unittest.TestCase):
    """AC9: When pipeline_stages is empty, return board with zero columns."""

    def test_empty_stages_returns_zero_columns(self):
        from app.models.lead import KanbanBoard
        board = KanbanBoard(columns=[], funnel_id=FAKE_FUNNEL_ID)
        self.assertEqual(len(board.columns), 0)
        self.assertEqual(board.funnel_id, FAKE_FUNNEL_ID)


# ═══════════════════════════════════════════════════════════════
# S4-T3: Keyword engine with dynamic stages
# ═══════════════════════════════════════════════════════════════

class TestKeywordEngineNonLegacy(unittest.TestCase):
    """AC9: Keyword engine uses string stages, not enums."""

    def test_analyze_returns_str_or_none(self):
        from app.services.keyword_engine import KeywordEngine, KeywordRule
        engine = KeywordEngine()
        rules = [
            KeywordRule(keywords=["comprar", "pagar"], target_stage="Pedido Feito", priority=2),
            KeywordRule(keywords=["cardápio"], target_stage="Escolhendo", priority=1),
        ]
        result = engine.analyze_message("quero comprar geleia", rules)
        self.assertEqual(result, "Pedido Feito")

    def test_no_match_returns_none(self):
        from app.services.keyword_engine import KeywordEngine, KeywordRule
        engine = KeywordEngine()
        rules = [
            KeywordRule(keywords=["comprar"], target_stage="Pedido Feito", priority=1),
        ]
        result = engine.analyze_message("olá, bom dia", rules)
        self.assertIsNone(result)

    def test_empty_rules_returns_none(self):
        from app.services.keyword_engine import KeywordEngine
        engine = KeywordEngine()
        result = engine.analyze_message("quero comprar", [])
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════
# S4-T3: Response model shape
# ═══════════════════════════════════════════════════════════════

class TestN8nResponseModel(unittest.TestCase):
    def test_response_shape(self):
        r = N8nWebhookResponse(
            status="ok",
            lead_id=FAKE_LEAD_ID,
            client_id="client-1",
            stage="B2C",
            order_id=None,
            message="Lead movido para 'B2C'.",
            warnings=["product not found"],
        )
        d = r.model_dump()
        self.assertEqual(d["status"], "ok")
        self.assertEqual(d["lead_id"], FAKE_LEAD_ID)
        self.assertEqual(d["stage"], "B2C")
        self.assertIsNone(d["order_id"])
        self.assertEqual(len(d["warnings"]), 1)


# ═══════════════════════════════════════════════════════════════
# Tech-spec Task 5 — testes: match, estoque no webhook, regressão
# ═══════════════════════════════════════════════════════════════


def _make_supabase_for_update_products_json(responses: deque, capture_updates: list | None = None):
    """Encadeia `.execute()` na ordem usada por `_update_products_json` (sem apply_stock_delta real)."""

    def next_execute(*_a, **_kw):
        if not responses:
            return _FakeExec(data=[])
        return responses.popleft()

    def table(table_name):
        t = MagicMock()

        def select_side_effect(*_a, **_kw):
            q = MagicMock()
            q.eq.return_value = q
            q.in_.return_value = q
            q.single.return_value = q
            q.execute.side_effect = next_execute
            return q

        def update_side_effect(data, *_a, **_kw):
            if capture_updates is not None and table_name == "leads":
                capture_updates.append(dict(data))
            q = MagicMock()
            q.eq.return_value = q
            q.execute.side_effect = next_execute
            return q

        t.select.side_effect = select_side_effect
        t.update.side_effect = update_side_effect
        return t

    sb = MagicMock()
    sb.table.side_effect = table
    return sb


class TestUpdateProductsJsonStock(unittest.TestCase):
    """`_update_products_json` deve acionar a mesma reserva de estoque que o PATCH do lead."""

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_cart_update_applies_positive_delta_when_no_prior_reservation(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        catalog = [{**PRODUCT_DB_ROW, "stock_quantity": 100}]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "",
        }
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(product="Geleia de Amora", quantity=4, total="R$ 72,00"),
            ],
            total_value="R$ 72,00",
        )
        lead_row = {**LEAD_ROW, "id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}
        products_json, _warnings = _update_products_json(
            sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID,
        )

        mock_apply.assert_called_once()
        _call_kw = mock_apply.call_args.kwargs
        self.assertEqual(_call_kw["tenant_id"], FAKE_TENANT_ID)
        self.assertEqual(_call_kw["delta"], {FAKE_PRODUCT_ID: 4})
        self.assertEqual(len(products_json), 1)
        self.assertEqual(products_json[0]["quantity"], 4)
        self.assertFalse(responses, "todas as respostas Supabase devem ter sido consumidas")

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_cart_update_delta_is_increment_over_existing_reservation(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        catalog = [{**PRODUCT_DB_ROW, "stock_quantity": 100}]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [
                {
                    "id": FAKE_PRODUCT_ID,
                    "product_id": FAKE_PRODUCT_ID,
                    "quantity": 1,
                    "qty": 1,
                    "name": "Geleia de Amora",
                    "price": 18.0,
                    "line_total": 18.0,
                }
            ],
            "stock_reserved_json": [{"product_id": FAKE_PRODUCT_ID, "quantity": 1}],
            "notes": "",
        }
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(product="Geleia de Amora", quantity=5, total="R$ 90,00"),
            ],
            total_value="R$ 90,00",
        )
        lead_row = {**LEAD_ROW, "id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}
        _update_products_json(sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID)

        self.assertEqual(mock_apply.call_args.kwargs["delta"], {FAKE_PRODUCT_ID: 4})

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_insufficient_stock_aborts_before_lead_update(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        mock_apply.side_effect = HTTPException(status_code=400, detail="Estoque insuficiente")
        catalog = [{**PRODUCT_DB_ROW, "stock_quantity": 0}]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "",
        }
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(product="Geleia de Amora", quantity=1, total="R$ 18,00"),
            ],
            total_value="R$ 18,00",
        )
        lead_row = {**LEAD_ROW, "id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}
        with self.assertRaises(HTTPException) as ctx:
            _update_products_json(sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertTrue(responses, "update do lead não deve ter sido solicitado")
        self.assertEqual(len(responses), 1)

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_cart_update_ac6_matched_only_in_json_orphans_in_notes(self, mock_apply):
        """AC6: só matched em products_json; órfãos no bloco delimitado em notes; estoque só do matched."""
        from app.routers.n8n_webhook import _update_products_json

        catalog = [{**PRODUCT_DB_ROW, "stock_quantity": 100}]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "Linha fixa do operador",
        }
        captured: list[dict] = []
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses, capture_updates=captured)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(product="Geleia de Amora", quantity=2, total="R$ 36,00"),
                OrderItem(product="Produto Fantasma XYZ", quantity=1, total="R$ 25,00"),
            ],
            total_value="R$ 61,00",
        )
        lead_row = {**LEAD_ROW, "id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}
        products_json, _warnings = _update_products_json(
            sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID,
        )

        self.assertEqual(len(products_json), 1)
        self.assertEqual(products_json[0]["id"], FAKE_PRODUCT_ID)
        self.assertEqual(mock_apply.call_args.kwargs["delta"], {FAKE_PRODUCT_ID: 2})
        self.assertEqual(len(captured), 1)
        upd = captured[0]
        self.assertEqual(upd["value"], 36.0)
        self.assertNotIn("unmatched", upd["products_json"][0])
        notes = upd.get("notes", "")
        self.assertIn(ORPHAN_CATALOG_BLOCK_START, notes)
        self.assertIn(ORPHAN_CATALOG_BLOCK_END, notes)
        self.assertIn("Produto Fantasma XYZ", notes)
        self.assertIn("Linha fixa do operador", notes)
        self.assertFalse(responses, "todas as respostas Supabase devem ter sido consumidas")

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_cart_update_all_unmatched_clears_products_and_sets_notes(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        catalog = [PRODUCT_DB_ROW]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "",
        }
        captured: list[dict] = []
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses, capture_updates=captured)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(product="Só Órfão", quantity=3, total="R$ 30,00"),
            ],
            total_value="R$ 30,00",
        )
        lead_row = {**LEAD_ROW, "id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}
        products_json, _warnings = _update_products_json(
            sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID,
        )

        self.assertEqual(products_json, [])
        self.assertEqual(mock_apply.call_args.kwargs["delta"], {})
        self.assertEqual(captured[0]["value"], 0.0)
        self.assertIn("- 3x Só Órfão", captured[0]["notes"])

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_cart_update_filters_products_by_pf_catalog(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        catalog = [
            {**PRODUCT_DB_ROW, "name": "Geleia PF"},
            {
                "id": "prod-lojista",
                "name": "Combo Lojista",
                "price": 45.0,
                "category_id": FAKE_CATEGORY_LOJISTA_ID,
                "category": "lojista-b2b",
                "tenant_id": FAKE_TENANT_ID,
                "is_active": True,
            },
        ]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "",
        }
        captured: list[dict] = []
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses, capture_updates=captured)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(product="Geleia PF", quantity=1, total="R$ 18,00"),
                OrderItem(product="Combo Lojista", quantity=2, total="R$ 90,00"),
            ],
            total_value="R$ 108,00",
        )
        lead_row = {**LEAD_ROW, "stage": "B2C", "client_id": None}
        products_json, warnings = _update_products_json(
            sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID,
        )

        self.assertEqual(len(products_json), 1)
        self.assertEqual(products_json[0]["name"], "Geleia PF")
        self.assertEqual(mock_apply.call_args.kwargs["delta"], {FAKE_PRODUCT_ID: 1})
        self.assertTrue(any("não encontrado" in warning for warning in warnings))
        self.assertIn("Combo Lojista", captured[0]["notes"])

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_linked_pj_client_overrides_stage_for_catalog_filter(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        catalog = [
            {
                "id": "prod-lojista",
                "name": "Combo Lojista",
                "price": 45.0,
                "category_id": FAKE_CATEGORY_LOJISTA_ID,
                "category": "lojista-b2b",
                "tenant_id": FAKE_TENANT_ID,
                "is_active": True,
            },
            {**PRODUCT_DB_ROW, "name": "Geleia PF"},
        ]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "",
        }
        responses = deque(
            [
                _FakeExec(data=[{"person_type": "PJ"}]),
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_LOJISTA_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="pedido",
            order_summary=[
                OrderItem(product="Combo Lojista", quantity=2, total="R$ 90,00"),
            ],
            total_value="R$ 90,00",
        )
        lead_row = {**LEAD_ROW, "stage": "B2C", "client_id": "client-pj-1"}
        products_json, warnings = _update_products_json(
            sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID,
        )

        self.assertEqual(len(products_json), 1)
        self.assertEqual(products_json[0]["name"], "Combo Lojista")
        self.assertEqual(mock_apply.call_args.kwargs["delta"], {"prod-lojista": 2})
        self.assertEqual(warnings, [])

    @patch("app.routers.n8n_webhook.apply_stock_delta")
    def test_explicit_disallowed_product_id_is_forced_unmatched(self, mock_apply):
        from app.routers.n8n_webhook import _update_products_json

        catalog = [
            {**PRODUCT_DB_ROW, "name": "Kit Degustação"},
            {
                "id": "prod-lojista-kit",
                "name": "Kit Degustação",
                "price": 99.0,
                "category_id": FAKE_CATEGORY_LOJISTA_ID,
                "category": "lojista-b2b",
                "tenant_id": FAKE_TENANT_ID,
                "is_active": True,
            },
        ]
        lead_snap = {
            "id": FAKE_LEAD_ID,
            "tenant_id": FAKE_TENANT_ID,
            "products_json": [],
            "stock_reserved_json": [],
            "notes": "",
        }
        captured: list[dict] = []
        responses = deque(
            [
                _FakeExec(data=catalog),
                _FakeExec(data=[CATEGORY_CLIENTE_FINAL_ROW]),
                MagicMock(data=lead_snap),
                _FakeExec(data=[{"id": FAKE_LEAD_ID, "tenant_id": FAKE_TENANT_ID}]),
            ]
        )
        sb = _make_supabase_for_update_products_json(responses, capture_updates=captured)

        payload = N8nWebhookPayload(
            instance_token="t",
            whatsapp_chat_id=FAKE_CHAT_ID,
            intent="cart_update",
            order_summary=[
                OrderItem(
                    product_id="prod-lojista-kit",
                    product="Kit Degustação",
                    quantity=1,
                    total="R$ 99,00",
                ),
            ],
            total_value="R$ 99,00",
        )
        lead_row = {**LEAD_ROW, "stage": "B2C", "client_id": None}
        products_json, warnings = _update_products_json(
            sb, lead_row=lead_row, payload=payload, tenant_id=FAKE_TENANT_ID,
        )

        self.assertEqual(products_json, [])
        self.assertEqual(mock_apply.call_args.kwargs["delta"], {})
        self.assertTrue(any("perfil PF" in warning for warning in warnings))
        self.assertTrue(any("product_id 'prod-lojista-kit'" in warning for warning in warnings))
        self.assertIn("Kit Degustação", captured[0]["notes"])


class TestOrphanCatalogNotesHelpers(unittest.TestCase):
    """Task 3b — helpers puros de partição e bloco em notes."""

    def test_partition_splits_unmatched(self):
        raw, _w = build_products_json(
            [
                OrderItem(product="Geleia de Amora", quantity=1, total="R$ 18,00"),
                OrderItem(product="Órfão", quantity=2, total="R$ 10,00"),
            ],
            [PRODUCT_DB_ROW],
            FAKE_TENANT_ID,
        )
        matched, unmatched = partition_products_by_match(raw)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["id"], FAKE_PRODUCT_ID)
        self.assertEqual(len(unmatched), 1)
        self.assertTrue(unmatched[0].get("unmatched"))
        self.assertEqual(unmatched[0]["name"], "Órfão")

    def test_strip_orphan_block(self):
        base = "Nota A"
        block = f"{ORPHAN_CATALOG_BLOCK_START}\n- 1x X\n{ORPHAN_CATALOG_BLOCK_END}"
        merged = f"{base}\n\n{block}"
        self.assertEqual(strip_orphan_catalog_block(merged), base)

    def test_merge_replaces_previous_block(self):
        first = merge_notes_with_orphan_catalog_block(
            "Intro",
            [{"name": "Velho", "quantity": 1, "unmatched": True}],
        )[0]
        second, _trunc = merge_notes_with_orphan_catalog_block(
            first,
            [{"name": "Novo", "quantity": 2, "unmatched": True}],
        )
        self.assertIn("Novo", second)
        self.assertNotIn("Velho", second)
        self.assertEqual(second.count(ORPHAN_CATALOG_BLOCK_START), 1)


if __name__ == "__main__":
    unittest.main()
