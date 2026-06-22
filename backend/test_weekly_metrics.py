"""Tests for app.services.weekly_metrics — written first (TDD)."""
from app.services.weekly_metrics import (
    parse_nota,
    avg_notas,
    parse_transcript_lines,
    parse_tempo_resp_humano,
    parse_tempo_resp_ia_seg,
    aggregate_week,
)


def test_parse_nota_comma_decimal():
    assert parse_nota("3,5") == 3.5


def test_parse_nota_empty_is_none():
    assert parse_nota("") is None
    assert parse_nota(None) is None


def test_parse_nota_int_to_float():
    assert parse_nota(4) == 4.0
    assert isinstance(parse_nota(4), float)


def test_avg_notas_drop_zero():
    assert avg_notas([5, 0, 4], drop_zero=True) == 4.5


def test_avg_notas_keep_zero():
    assert avg_notas([5, 0, 4], drop_zero=False) == 3.0


def test_avg_notas_empty():
    assert avg_notas([], drop_zero=False) == 0.0
    assert avg_notas([], drop_zero=True) == 0.0


def test_human_resp_time_newline_separated():
    transcript = (
        "[2026-06-21 14:00:00] Lead: oi\n"
        "[2026-06-21 14:00:10] Agente: ola, tudo bem?\n"
        "[2026-06-21 14:05:10] Humano: Boa tarde"
    )
    # Humano - previous marker (Agente 14:00:10) = 5 min
    assert parse_tempo_resp_humano(transcript) == 5.0


def test_human_resp_time_concatenated():
    # Markers back-to-back, no separators anywhere.
    transcript = (
        "[2026-06-21 13:43:25] Lead: pode me ajudar?"
        "[2026-06-21 13:43:35] Agente: Por nada"
        "[2026-06-21 13:49:32] Humano: Boa tarde"
    )
    # Humano 13:49:32 - prev marker (Agente 13:43:35) = 5min 57s = 5.95 min
    assert parse_tempo_resp_humano(transcript) == 5.95


def test_human_resp_time_no_human():
    transcript = (
        "[2026-06-21 14:00:00] Lead: oi"
        "[2026-06-21 14:00:10] Agente: ola"
    )
    assert parse_tempo_resp_humano(transcript) is None


def test_parse_transcript_lines_global_concatenated():
    transcript = (
        "[2026-06-21 14:00:00] Lead: oi[2026-06-21 14:00:10] Agente: ola"
    )
    parsed = parse_transcript_lines(transcript)
    assert len(parsed) == 2
    assert parsed[0][1] == "Lead"
    assert parsed[1][1] == "Agente"


def test_tempo_resp_ia_seg():
    # Lead followed immediately by Agente -> diff in seconds
    transcript = (
        "[2026-06-21 14:00:00] Lead: oi"
        "[2026-06-21 14:00:10] Agente: ola"
        "[2026-06-21 14:05:00] Lead: e isso?"
        "[2026-06-21 14:05:30] Agente: claro"
    )
    # diffs: 10s and 30s -> mean 20.0
    assert parse_tempo_resp_ia_seg(transcript) == 20.0


def test_tempo_resp_ia_seg_none():
    transcript = "[2026-06-21 14:00:00] Lead: oi sozinho"
    assert parse_tempo_resp_ia_seg(transcript) is None


def test_aggregate_week():
    rows = [
        {
            "profissionalismo_agente": "5",
            "profissionalismo_humano": "4",
            "transcrição": (
                "[2026-06-21 14:00:00] Lead: oi"
                "[2026-06-21 14:00:10] Agente: ola"
                "[2026-06-21 14:05:10] Humano: boa tarde"
            ),
        },
        {
            "profissionalismo_agente": "3",
            "profissionalismo_humano": "0",
            "transcrição": (
                "[2026-06-21 15:00:00] Lead: ajuda"
                "[2026-06-21 15:00:20] Agente: claro"
            ),
        },
    ]
    result = aggregate_week(rows)
    assert result["total_conversas"] == 2
    assert result["nota_media_ia"] == 4.0          # (5+3)/2
    assert result["nota_media_humano"] == 4.0      # 0 dropped -> just 4
    # row1 humano resp: Humano 14:05:10 - Agente 14:00:10 = 5.0 min; row2 no human
    assert result["tempo_resp_humano_min"] == 5.0
    # row1 ia: Lead->Agente 10s; row2 ia: Lead->Agente 20s -> mean of [10,20]=15.0
    assert result["tempo_resp_ia_seg"] == 15.0
