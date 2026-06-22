"""Weekly customer-service report metrics.

Pure-domain helpers for parsing conversation rows exported from the client
spreadsheet ("Conversas" worksheet) and aggregating weekly metrics.

The ``transcrição`` cell carries per-message markers shaped like
``[2026-06-21 13:38:23] Lead: oi``. Messages may be newline-separated OR fully
concatenated with no separator, so all parsing uses a GLOBAL (non
line-anchored) regex that finds every marker anywhere in the string.

Roles are exactly: ``Lead``, ``Agente``, ``Humano``.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Tuple

# Global marker regex: matches "[YYYY-MM-DD HH:MM:SS] Role:" anywhere.
# No ^/$ anchors so it works for both newline-separated and concatenated text.
_MARKER_RE = re.compile(
    r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(Lead|Agente|Humano)\s*:"
)
_TS_FMT = "%Y-%m-%d %H:%M:%S"


def parse_nota(raw) -> Optional[float]:
    """Parse a note cell to float.

    - comma decimals ("3,5") -> 3.5
    - "" / None -> None
    - int/float -> float
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        # avoid treating bools as ints silently
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    if s == "":
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def avg_notas(values: list, *, drop_zero: bool) -> float:
    """Average a list of note values, rounded to 2.

    Each value is run through ``parse_nota``. None values are excluded.
    When ``drop_zero`` is True, zeros are also excluded (zero == "no human").
    Empty (after filtering) -> 0.0.
    """
    notas: List[float] = []
    for v in values:
        n = parse_nota(v)
        if n is None:
            continue
        if drop_zero and n == 0:
            continue
        notas.append(n)
    if not notas:
        return 0.0
    return round(sum(notas) / len(notas), 2)


def parse_transcript_lines(transcricao: str) -> List[Tuple[datetime, str]]:
    """Return ordered (timestamp, role) for each parsed marker.

    Uses a global regex so concatenated markers are still found.
    """
    if not transcricao:
        return []
    out: List[Tuple[datetime, str]] = []
    for m in _MARKER_RE.finditer(transcricao):
        ts = datetime.strptime(m.group(1), _TS_FMT)
        role = m.group(2)
        out.append((ts, role))
    return out


def parse_tempo_resp_humano(transcricao: str) -> Optional[float]:
    """Minutes between the first Humano marker and the marker before it.

    Returns None if there is no Humano marker or it is the first message.
    """
    markers = parse_transcript_lines(transcricao)
    for i, (ts, role) in enumerate(markers):
        if role == "Humano":
            if i == 0:
                return None
            prev_ts = markers[i - 1][0]
            diff_min = (ts - prev_ts).total_seconds() / 60.0
            return round(diff_min, 2)
    return None


def parse_tempo_resp_ia_seg(transcricao: str) -> Optional[float]:
    """Mean seconds for each Lead marker immediately followed by an Agente marker.

    Returns None if there is no such pair.
    """
    markers = parse_transcript_lines(transcricao)
    diffs: List[float] = []
    for i in range(len(markers) - 1):
        ts, role = markers[i]
        next_ts, next_role = markers[i + 1]
        if role == "Lead" and next_role == "Agente":
            diffs.append((next_ts - ts).total_seconds())
    if not diffs:
        return None
    return round(sum(diffs) / len(diffs), 2)


def _mean_non_none(values: List[Optional[float]]) -> float:
    vals = [v for v in values if v is not None]
    if not vals:
        return 0.0
    return round(sum(vals) / len(vals), 2)


def aggregate_week(rows: list) -> dict:
    """Aggregate a week's worth of conversation rows into metrics."""
    transcripts = [r.get("transcrição", "") for r in rows]
    return {
        "total_conversas": len(rows),
        "nota_media_ia": avg_notas(
            [r.get("profissionalismo_agente") for r in rows], drop_zero=False
        ),
        "nota_media_humano": avg_notas(
            [r.get("profissionalismo_humano") for r in rows], drop_zero=True
        ),
        "tempo_resp_humano_min": _mean_non_none(
            [parse_tempo_resp_humano(t) for t in transcripts]
        ),
        "tempo_resp_ia_seg": _mean_non_none(
            [parse_tempo_resp_ia_seg(t) for t in transcripts]
        ),
    }
