"""Tests for dispatch service (CSV parse, phone normalize)."""

import pytest

from app.services.dispatch_service import normalize_phone_e164, parse_members_csv


def test_normalize_phone_e164_brazil():
    assert normalize_phone_e164("11999998888") == "5511999998888"
    assert normalize_phone_e164("+55 11 99999-8888") == "5511999998888"
    assert normalize_phone_e164("5511999998888") == "5511999998888"


def test_normalize_phone_e164_invalid():
    assert normalize_phone_e164("123") is None
    assert normalize_phone_e164("") is None


def test_parse_members_csv_valid():
    content = b"nome,telefone\nJoao,11999998888\nMaria,5511888777666\n"
    valid, invalid = parse_members_csv(content)
    assert len(valid) == 2
    assert len(invalid) == 0
    assert valid[0]["name"] == "Joao"
    assert valid[0]["phone_e164"] == "5511999998888"


def test_parse_members_csv_invalid_rows():
    content = b"nome,telefone\n,11999998888\nSem Tel,\n"
    valid, invalid = parse_members_csv(content)
    assert len(valid) == 1
    assert len(invalid) == 1
    assert invalid[0]["reason"] == "telefone vazio"


def test_parse_members_csv_five_members():
  content = (
        b"nome,telefone\n"
        b"Membro 1,5511999000001\n"
        b"Membro 2,5511999000002\n"
        b"Membro 3,5511999000003\n"
        b"Membro 4,5511999000004\n"
        b"Membro 5,5511999000005\n"
    )
  valid, invalid = parse_members_csv(content)
  assert len(valid) == 5
  assert len(invalid) == 0
  assert {r["name"] for r in valid} == {f"Membro {i}" for i in range(1, 6)}
