"""Unit tests — resolução de telefone Vendi."""

from app.models.vendi import VendiSaleIngest
from app.routers.n8n_vendi import _resolve_match_and_phone


def test_audio_wins_over_typed():
    p = VendiSaleIngest(
        tenant_id="t",
        seller_name="A",
        phone_typed="41988887777",
        phone_from_audio="41999998888",
        pao_italiano_qtd=1,
    )
    phone, status = _resolve_match_and_phone(p)
    assert phone == "41999998888"
    assert status == "mismatch"


def test_typed_only_when_no_audio():
    p = VendiSaleIngest(
        tenant_id="t",
        seller_name="A",
        phone_typed="(41) 99999-8888",
        pao_italiano_qtd=1,
    )
    phone, status = _resolve_match_and_phone(p)
    assert phone == "41999998888"
    assert status == "typed_only"


def test_explicit_phone_final():
    p = VendiSaleIngest(
        tenant_id="t",
        seller_name="A",
        phone_typed="41111111111",
        phone_from_audio="42222222222",
        phone_final="43333333333",
        match_status="match",
        pao_integral_qtd=2,
    )
    phone, status = _resolve_match_and_phone(p)
    assert phone == "43333333333"
    assert status == "match"
