"""Testes — ferramentas n8n (client-by-phone, last-order-by-phone)."""

import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.dependencies import get_supabase, verify_n8n_api_key
from app.main import app

FAKE_API_KEY = "test-n8n-tools-key"
FAKE_TENANT = "tenant-tools-1"
FAKE_CLIENT_ID = "client-uuid-1"

CLIENT_ROW_PJ = {
    "id": FAKE_CLIENT_ID,
    "tenant_id": FAKE_TENANT,
    "person_type": "PJ",
    "cnpj": "47992051000100",
    "cpf": None,
    "display_name": "WBT Solutions",
    "contact_name": "Aurora",
    "phones": ["554137984741"],
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
}

ORDER_ROW = {
    "id": "order-1",
    "tenant_id": FAKE_TENANT,
    "lead_id": "lead-1",
    "client_id": FAKE_CLIENT_ID,
    "client_name": "Aurora",
    "client_company": "WBT Solutions",
    "product_summary": "2x Geleia de Amora",
    "products_json": [{"sku": "GEL-AMO", "qty": 2}],
    "applied_promotions_json": {"code": "VIP10", "pct": 10},
    "subtotal": 40.0,
    "discount_total": 4.0,
    "total": 36.0,
    "stage": "pedido_feito",
    "notes": "Entregar na recepção",
    "payment_status": "pago",
    "payment_method": "PIX",
    "created_at": "2026-03-01T12:00:00+00:00",
}


class TestN8nAgentToolHelpers(unittest.TestCase):
    def test_phone_from_jid(self):
        from app.services.n8n_agent_tools import phone_from_whatsapp_jid_or_raw

        self.assertEqual(
            phone_from_whatsapp_jid_or_raw("554137984741@s.whatsapp.net"),
            "554137984741",
        )
        self.assertEqual(phone_from_whatsapp_jid_or_raw("+55 41 3798-4741"), "554137984741")

    def test_format_cnpj(self):
        from app.services.n8n_agent_tools import format_cnpj_display

        self.assertEqual(format_cnpj_display("47992051000100"), "47.992.051/0001-00")

    def test_normalize_whatsapp_chat_id(self):
        from app.services.n8n_agent_tools import normalize_whatsapp_chat_id

        self.assertEqual(
            normalize_whatsapp_chat_id("554197889864@s.whatsapp.net"),
            "554197889864@s.whatsapp.net",
        )
        self.assertEqual(
            normalize_whatsapp_chat_id("554197889864"),
            "554197889864@s.whatsapp.net",
        )

    def test_route_hint_from_stage(self):
        from app.services.n8n_agent_tools import route_hint_from_stage

        self.assertEqual(route_hint_from_stage("B2B"), "b2b")
        self.assertEqual(route_hint_from_stage("b2c"), "b2c")
        self.assertEqual(route_hint_from_stage("Quero Vender"), "revenda")
        self.assertEqual(route_hint_from_stage("Pedido Feito"), "pedido_feito")
        self.assertEqual(route_hint_from_stage("Pagto Confirmado"), "pagto_confirmado")
        self.assertEqual(route_hint_from_stage("PAGTO CONFIRMADO"), "pagto_confirmado")
        self.assertEqual(route_hint_from_stage("FINALIZADO"), "finalizado")
        self.assertEqual(route_hint_from_stage("Finalizado"), "finalizado")
        self.assertEqual(route_hint_from_stage("Novo"), "other")

    def test_phone_lookup_canonical_and_match_ranks(self):
        from app.services.n8n_agent_tools import (
            PHONE_MATCH_RANK_LAST10,
            PHONE_MATCH_RANK_LAST11,
            PHONE_MATCH_RANK_NONE,
            PHONE_MATCH_RANK_STRICT,
            crm_phone_entry_digits,
            is_insufficient_phone_lookup_digits,
            phone_match_rank,
            phone_match_tier,
            to_canonical_br_phone_digits,
        )

        self.assertEqual(to_canonical_br_phone_digits("554137984741"), "554137984741")
        self.assertEqual(to_canonical_br_phone_digits("4137984741"), "554137984741")
        self.assertEqual(to_canonical_br_phone_digits("+55 41 3798-4741"), "554137984741")
        self.assertEqual(to_canonical_br_phone_digits("04137984741"), "554137984741")

        self.assertEqual(crm_phone_entry_digits("+55 41 3798-4741"), "554137984741")
        self.assertEqual(crm_phone_entry_digits(None), "")

        q = "554137984741"
        self.assertEqual(phone_match_rank(q, "554137984741"), PHONE_MATCH_RANK_STRICT)
        self.assertEqual(phone_match_rank(q, "+55 41 3798-4741"), PHONE_MATCH_RANK_STRICT)
        self.assertEqual(phone_match_rank(q, "4137984741"), PHONE_MATCH_RANK_STRICT)
        self.assertEqual(phone_match_tier(q, "4137984741"), "strict")

        self.assertTrue(is_insufficient_phone_lookup_digits("123"))
        self.assertFalse(is_insufficient_phone_lookup_digits("1234"))

        long_a = "12000554137984741"
        long_b = "99000554137984741"
        self.assertEqual(phone_match_rank(long_a, long_b), PHONE_MATCH_RANK_LAST11)
        self.assertEqual(phone_match_tier(long_a, long_b), "last11")

        # Últimos 10 dígitos iguais; 11º a partir do fim diferente → apenas last10.
        ten_a = "00141234567890"
        ten_b = "00961234567890"
        self.assertEqual(phone_match_rank(ten_a, ten_b), PHONE_MATCH_RANK_LAST10)
        self.assertEqual(phone_match_tier(ten_a, ten_b), "last10")

        self.assertEqual(phone_match_rank("5541999999999", "5541888888888"), PHONE_MATCH_RANK_NONE)
        self.assertIsNone(phone_match_tier("5541999999999", "5541888888888"))

    def test_best_phone_match_rank_for_client_row(self):
        from app.services.n8n_agent_tools import (
            PHONE_MATCH_RANK_STRICT,
            best_phone_match_rank_for_client_row,
        )

        row = {"phones": ["+55 41 99999-9999", "5541888888888"]}
        self.assertEqual(
            best_phone_match_rank_for_client_row("5541999999999", row),
            PHONE_MATCH_RANK_STRICT,
        )

    @patch("app.services.n8n_agent_tools.fetch_last_order_for_client")
    def test_find_crm_client_row_by_phone_prefers_stage_person_type_over_history(
        self, mock_fetch
    ):
        """Se o lead atual já está em B2B/B2C, o match único desse perfil vence o histórico."""
        from app.services.n8n_agent_tools import find_crm_client_row_by_phone

        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "order", "execute"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [
            {
                "id": "client-pf",
                "person_type": "PF",
                "phones": ["554137984741"],
                "created_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": "client-pj",
                "person_type": "PJ",
                "cnpj": "47992051000100",
                "phones": ["554137984741"],
                "created_at": "2025-01-01T00:00:00+00:00",
            },
        ]
        chain.execute.return_value = exec_result

        def fetch_side(_sb, *, tenant_id, client_id):
            if client_id == "client-pf":
                return {"created_at": "2026-07-01T00:00:00+00:00", "id": "ord-pf"}
            if client_id == "client-pj":
                return {"created_at": "2026-02-01T00:00:00+00:00", "id": "ord-pj"}
            return None

        mock_fetch.side_effect = fetch_side

        row = find_crm_client_row_by_phone(
            mock_sb,
            tenant_id=FAKE_TENANT,
            phone_digits="554137984741",
            lead_row={"stage": "B2B", "client_id": None},
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "client-pj")

    @patch("app.services.n8n_agent_tools.fetch_last_order_for_client")
    def test_find_crm_client_row_by_phone_prefers_linked_lead_client_when_stage_missing(
        self, mock_fetch
    ):
        from app.services.n8n_agent_tools import find_crm_client_row_by_phone

        mock_fetch.return_value = None
        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "order", "execute"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [
            {
                "id": "client-pf",
                "person_type": "PF",
                "phones": ["554137984741"],
                "created_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": "client-pj",
                "person_type": "PJ",
                "phones": ["554137984741"],
                "created_at": "2025-01-01T00:00:00+00:00",
            },
        ]
        chain.execute.return_value = exec_result

        row = find_crm_client_row_by_phone(
            mock_sb,
            tenant_id=FAKE_TENANT,
            phone_digits="554137984741",
            lead_row={"stage": "Novo", "client_id": "client-pj"},
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "client-pj")

    @patch("app.services.n8n_agent_tools.fetch_last_order_for_client")
    def test_find_crm_client_row_by_phone_tie_break_latest_order(self, mock_fetch):
        """Task 2: entre candidatos com mesmo score, vence quem tem pedido mais recente."""
        from app.services.n8n_agent_tools import find_crm_client_row_by_phone

        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "order", "execute"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [
            {
                "id": "client-newer",
                "phones": ["5541999999999"],
                "created_at": "2026-06-01T00:00:00+00:00",
            },
            {
                "id": "client-older",
                "phones": ["5541999999999"],
                "created_at": "2025-01-01T00:00:00+00:00",
            },
        ]
        chain.execute.return_value = exec_result

        def fetch_side(_sb, *, tenant_id, client_id):
            if client_id == "client-newer":
                return {"created_at": "2026-03-15T00:00:00+00:00", "id": "o1"}
            if client_id == "client-older":
                return {"created_at": "2026-01-10T00:00:00+00:00", "id": "o2"}
            return None

        mock_fetch.side_effect = fetch_side

        row = find_crm_client_row_by_phone(
            mock_sb, tenant_id=FAKE_TENANT, phone_digits="5541999999999"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "client-newer")

    @patch("app.services.n8n_agent_tools.fetch_last_order_for_client")
    def test_find_crm_client_row_by_phone_tie_break_prefers_history_over_newer_empty(
        self, mock_fetch
    ):
        """Cenário raiz: cadastro novo sem pedido perde para o antigo com histórico."""
        from app.services.n8n_agent_tools import find_crm_client_row_by_phone

        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "order", "execute"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [
            {
                "id": "client-empty",
                "phones": ["554137984966"],
                "created_at": "2026-04-01T00:00:00+00:00",
            },
            {
                "id": "client-with-orders",
                "phones": ["554137984966"],
                "created_at": "2024-01-01T00:00:00+00:00",
            },
        ]
        chain.execute.return_value = exec_result

        def fetch_side(_sb, *, tenant_id, client_id):
            if client_id == "client-empty":
                return None
            if client_id == "client-with-orders":
                return {"created_at": "2025-06-01T00:00:00+00:00", "id": "ord-x"}
            return None

        mock_fetch.side_effect = fetch_side

        row = find_crm_client_row_by_phone(
            mock_sb, tenant_id=FAKE_TENANT, phone_digits="554137984966"
        )
        self.assertEqual(row["id"], "client-with-orders")

    @patch("app.services.n8n_agent_tools.fetch_last_order_for_client")
    def test_find_crm_client_row_by_phone_no_orders_uses_client_created_at_desc(
        self, mock_fetch
    ):
        """Sem pedidos: desempate por crm_clients.created_at descendente."""
        from app.services.n8n_agent_tools import find_crm_client_row_by_phone

        mock_fetch.return_value = None
        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "order", "execute"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [
            {
                "id": "older",
                "phones": ["5541888888888"],
                "created_at": "2025-01-01T00:00:00+00:00",
            },
            {
                "id": "newer",
                "phones": ["5541888888888"],
                "created_at": "2026-02-01T00:00:00+00:00",
            },
        ]
        chain.execute.return_value = exec_result

        row = find_crm_client_row_by_phone(
            mock_sb, tenant_id=FAKE_TENANT, phone_digits="5541888888888"
        )
        self.assertEqual(row["id"], "newer")

    @patch("app.services.n8n_agent_tools.fetch_last_order_for_client")
    def test_find_crm_client_row_by_phone_matches_legacy_masked_phones(self, mock_fetch):
        """AC6: telefones armazenados com máscara/pontuação casam com busca canônica."""
        from app.services.n8n_agent_tools import find_crm_client_row_by_phone

        mock_fetch.return_value = None
        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "order", "execute"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [
            {
                "id": "client-masked",
                "phones": ["+55 (41) 37984-966"],
                "created_at": "2025-01-01T00:00:00+00:00",
            },
        ]
        chain.execute.return_value = exec_result

        row = find_crm_client_row_by_phone(
            mock_sb, tenant_id=FAKE_TENANT, phone_digits="554137984966"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "client-masked")

    @patch(
        "app.services.n8n_agent_tools.find_crm_client_row_by_phone",
        return_value=CLIENT_ROW_PJ,
    )
    @patch(
        "app.services.n8n_agent_tools.find_lead_by_whatsapp_chat",
        return_value={"id": "lead-b2b", "stage": "B2B", "client_id": None},
    )
    @patch(
        "app.services.n8n_agent_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT},
    )
    def test_resolve_crm_client_for_n8n_phone_passes_lead_context(
        self, _mock_inbox, _mock_lead, mock_find
    ):
        from app.services.n8n_agent_tools import resolve_crm_client_for_n8n_phone

        tid, digits, row = resolve_crm_client_for_n8n_phone(
            MagicMock(),
            instance_token="tok",
            phone="554137984741@s.whatsapp.net",
        )
        self.assertEqual(tid, FAKE_TENANT)
        self.assertEqual(digits, "554137984741")
        self.assertEqual(row, CLIENT_ROW_PJ)
        self.assertEqual(
            mock_find.call_args.kwargs["lead_row"],
            {"id": "lead-b2b", "stage": "B2B", "client_id": None},
        )


class TestN8nToolsHttp(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.mock_sb = MagicMock()
        app.dependency_overrides[get_supabase] = lambda: self.mock_sb
        app.dependency_overrides[verify_n8n_api_key] = lambda: {"source": "n8n"}

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch(
        "app.routers.n8n_tools.resolve_crm_client_for_n8n_phone",
        return_value=(None, "", None),
    )
    def test_client_by_phone_inbox_404(self, _mock_resolve):
        r = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "bad", "phone": "5541999999999@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored-with-override"},
        )
        self.assertEqual(r.status_code, 404)

    @patch(
        "app.routers.n8n_tools.resolve_crm_client_for_n8n_phone",
        return_value=(FAKE_TENANT, "5541999999999", None),
    )
    def test_client_by_phone_not_found(self, _mock_resolve):
        r = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "tok", "phone": "5541999999999@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["found"])

    @patch(
        "app.routers.n8n_tools.resolve_crm_client_for_n8n_phone",
        return_value=(FAKE_TENANT, "554137984741", CLIENT_ROW_PJ),
    )
    def test_client_by_phone_found_pj(self, _mock_resolve):
        r = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "tok", "phone": "554137984741@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["found"])
        self.assertEqual(body["display_name"], "WBT Solutions")
        self.assertEqual(body["cnpj_formatted"], "47.992.051/0001-00")

    @patch(
        "app.routers.n8n_tools.resolve_crm_client_for_n8n_phone",
        return_value=(FAKE_TENANT, "5541999999999", None),
    )
    def test_last_order_client_missing(self, _mock_resolve):
        r = self.client.get(
            "/api/n8n/tools/last-order-by-phone",
            params={"instance_token": "tok", "phone": "5541999999999@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["client_found"])
        self.assertIn("message_last", body)
        self.assertIn("cadastro", body["message_last"].lower())

    @patch(
        "app.routers.n8n_tools.resolve_crm_client_for_n8n_phone",
        return_value=(FAKE_TENANT, "554137984741", CLIENT_ROW_PJ),
    )
    @patch("app.routers.n8n_tools.fetch_last_order_for_client", return_value=ORDER_ROW)
    def test_last_order_found(self, _mock_fetch, _mock_resolve):
        r = self.client.get(
            "/api/n8n/tools/last-order-by-phone",
            params={"instance_token": "tok", "phone": "554137984741@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["client_found"])
        self.assertTrue(body["has_previous_order"])
        o = body["order"]
        self.assertEqual(o["product_summary"], "2x Geleia de Amora")
        self.assertEqual(o["id"], "order-1")
        self.assertEqual(o["tenant_id"], FAKE_TENANT)
        self.assertEqual(o["client_name"], "Aurora")
        self.assertEqual(o["client_company"], "WBT Solutions")
        self.assertEqual(o["notes"], "Entregar na recepção")
        self.assertEqual(o["subtotal"], 40.0)
        self.assertEqual(o["discount_total"], 4.0)
        self.assertEqual(o["total"], 36.0)
        self.assertEqual(o["stage"], "pedido_feito")
        self.assertEqual(o["applied_promotions_json"], {"code": "VIP10", "pct": 10})
        self.assertEqual(o["products_json"], [{"sku": "GEL-AMO", "qty": 2}])
        self.assertEqual(o["payment_status"], "pago")
        self.assertEqual(o["payment_method"], "PIX")
        ml = body["message_last"]
        self.assertIn("Seu último pedido foi:", ml)
        self.assertIn("2x Geleia de Amora", ml)
        self.assertIn("R$", ml)
        self.assertIn("36,00", ml)
        self.assertIn("Gostaria de repetir", ml)

    @patch(
        "app.services.n8n_agent_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT},
    )
    @patch(
        "app.services.n8n_agent_tools.find_crm_client_row_by_phone",
        return_value=CLIENT_ROW_PJ,
    )
    def test_client_by_phone_and_last_order_same_client_id_jid_vs_plain_digits(
        self, _mock_find, _mock_inbox
    ):
        """AC4: RemoteJid e dígitos puros resolvem o mesmo client_id nos dois endpoints."""
        r_jid = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "tok", "phone": "554137984741@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r_jid.status_code, 200)
        self.assertEqual(r_jid.json()["client_id"], FAKE_CLIENT_ID)

        with patch(
            "app.routers.n8n_tools.fetch_last_order_for_client", return_value=ORDER_ROW
        ):
            r_last_jid = self.client.get(
                "/api/n8n/tools/last-order-by-phone",
                params={
                    "instance_token": "tok",
                    "phone": "554137984741@s.whatsapp.net",
                },
                headers={"X-CRM-API-Key": "ignored"},
            )
            r_last_digits = self.client.get(
                "/api/n8n/tools/last-order-by-phone",
                params={"instance_token": "tok", "phone": "554137984741"},
                headers={"X-CRM-API-Key": "ignored"},
            )
        self.assertEqual(r_last_jid.status_code, 200)
        self.assertEqual(r_last_digits.status_code, 200)
        self.assertEqual(r_last_jid.json()["client_id"], FAKE_CLIENT_ID)
        self.assertEqual(r_last_digits.json()["client_id"], FAKE_CLIENT_ID)

        r_digits = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "tok", "phone": "554137984741"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r_digits.status_code, 200)
        self.assertEqual(r_digits.json()["client_id"], FAKE_CLIENT_ID)

    @patch(
        "app.services.n8n_agent_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT},
    )
    def test_client_by_phone_insufficient_digits_returns_400(self, _mock_inbox):
        """AC7: menos de 4 dígitos úteis → 400 (contrato atual)."""
        r = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "tok", "phone": "abc1"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("curto", r.json()["detail"].lower())

    @patch(
        "app.services.n8n_agent_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT},
    )
    def test_last_order_by_phone_insufficient_digits_returns_400(self, _mock_inbox):
        r = self.client.get(
            "/api/n8n/tools/last-order-by-phone",
            params={"instance_token": "tok", "phone": "xy12"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("curto", r.json()["detail"].lower())

    def test_last_order_message_last_no_order(self):
        from app.services.n8n_agent_tools import build_last_order_tool_payload

        out = build_last_order_tool_payload(None)
        self.assertFalse(out["has_previous_order"])
        self.assertIn("pedido anterior", out["message_last"].lower())

    def test_format_last_order_client_message(self):
        from app.services.n8n_agent_tools import format_last_order_client_message

        msg = format_last_order_client_message(
            {
                "product_summary": "4x Geleia de Figo",
                "total": 72,
                "created_at": "2026-04-07T00:11:09.945359+00:00",
            }
        )
        self.assertIn("4x Geleia de Figo", msg)
        self.assertIn("72,00", msg)
        self.assertRegex(msg, r"Data: \d{2}/\d{2}/2026")

    def test_fetch_last_order_for_client_excludes_canceled(self):
        """AC1: query chain must filter out payment_status = cancelado."""
        from app.services.n8n_agent_tools import fetch_last_order_for_client

        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "neq", "order", "limit", "in_"):
            getattr(chain, name).return_value = chain
        exec_result = MagicMock()
        exec_result.data = [ORDER_ROW]
        chain.execute.return_value = exec_result

        out = fetch_last_order_for_client(
            mock_sb, tenant_id=FAKE_TENANT, client_id=FAKE_CLIENT_ID
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["id"], "order-1")
        chain.neq.assert_called_with("payment_status", "cancelado")

    def test_fetch_last_order_for_client_fallback_via_lead_id(self):
        """AC5: sem pedido direto por client_id, usa leads do cliente e pedido por lead_id."""
        from app.services.n8n_agent_tools import fetch_last_order_for_client

        order_via_lead = {
            **ORDER_ROW,
            "id": "order-via-lead",
            "lead_id": "lead-for-client",
            "client_id": None,
        }
        mock_sb = MagicMock()
        chain = MagicMock()
        mock_sb.table.return_value = chain
        for name in ("select", "eq", "neq", "order", "limit", "in_"):
            getattr(chain, name).return_value = chain

        exec_empty = MagicMock()
        exec_empty.data = []
        exec_leads = MagicMock()
        exec_leads.data = [{"id": "lead-for-client"}]
        exec_order = MagicMock()
        exec_order.data = [order_via_lead]
        chain.execute.side_effect = [exec_empty, exec_leads, exec_order]

        out = fetch_last_order_for_client(
            mock_sb, tenant_id=FAKE_TENANT, client_id=FAKE_CLIENT_ID
        )
        self.assertIsNotNone(out)
        self.assertEqual(out["id"], "order-via-lead")
        self.assertEqual(out["lead_id"], "lead-for-client")

    def test_tools_require_api_key(self):
        app.dependency_overrides.pop(verify_n8n_api_key, None)
        r = self.client.get(
            "/api/n8n/tools/client-by-phone",
            params={"instance_token": "tok", "phone": "554137984741@s.whatsapp.net"},
        )
        self.assertIn(r.status_code, (401, 503))

    @patch("app.routers.n8n_tools.resolve_inbox_row_for_n8n", return_value=None)
    def test_lead_context_inbox_missing(self, _mock_inbox):
        r = self.client.get(
            "/api/n8n/tools/lead-context",
            params={"instance_token": "bad", "phone": "554197889864@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 404)

    @patch(
        "app.routers.n8n_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT, "funnel_id": "f1"},
    )
    @patch("app.routers.n8n_tools.find_lead_by_whatsapp_chat", return_value=None)
    def test_lead_context_no_lead(self, _mock_lead, _mock_inbox):
        r = self.client.get(
            "/api/n8n/tools/lead-context",
            params={"instance_token": "tok", "phone": "554197889864@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["found"])
        self.assertEqual(r.json()["route_hint"], "no_lead")

    @patch(
        "app.routers.n8n_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT, "funnel_id": "f1"},
    )
    @patch(
        "app.routers.n8n_tools.find_lead_by_whatsapp_chat",
        return_value={
            "id": "lead-x",
            "stage": "B2B",
            "client_id": FAKE_CLIENT_ID,
            "contact_name": "Aurora",
            "whatsapp_chat_id": "554197889864@s.whatsapp.net",
        },
    )
    def test_lead_context_b2b(self, _mock_lead, _mock_inbox):
        r = self.client.get(
            "/api/n8n/tools/lead-context",
            params={"instance_token": "tok", "phone": "554197889864@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertTrue(b["found"])
        self.assertEqual(b["route_hint"], "b2b")
        self.assertEqual(b["stage"], "B2B")

    @patch(
        "app.routers.n8n_tools.resolve_inbox_row_for_n8n",
        return_value={"id": "inbox-1", "tenant_id": FAKE_TENANT, "funnel_id": "f1"},
    )
    @patch(
        "app.routers.n8n_tools.find_lead_by_whatsapp_chat",
        return_value={
            "id": "lead-final",
            "stage": "FINALIZADO",
            "client_id": FAKE_CLIENT_ID,
            "contact_name": "Aurora",
            "whatsapp_chat_id": "554197889864@s.whatsapp.net",
        },
    )
    def test_lead_context_finalizado(self, _mock_lead, _mock_inbox):
        r = self.client.get(
            "/api/n8n/tools/lead-context",
            params={"instance_token": "tok", "phone": "554197889864@s.whatsapp.net"},
            headers={"X-CRM-API-Key": "ignored"},
        )
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertTrue(b["found"])
        self.assertEqual(b["route_hint"], "finalizado")
        self.assertEqual(b["stage"], "FINALIZADO")


if __name__ == "__main__":
    unittest.main()
