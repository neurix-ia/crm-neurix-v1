"""
Pydantic models and helpers for the n8n unified webhook endpoint.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OrderItem(BaseModel):
    product_id: Optional[str] = None
    product: str = Field(max_length=255)
    quantity: int
    total: str


class NoteTimelineEntry(BaseModel):
    content: str = Field(max_length=2000)
    timestamp: Optional[str] = None


class N8nWebhookPayload(BaseModel):
    instance_token: str
    whatsapp_chat_id: str
    phone: Optional[str] = Field(None, max_length=50)
    lead_name: Optional[str] = Field(None, max_length=200)
    lead_cnpj: Optional[str] = Field(None, max_length=20)
    intent: Literal[
        "perfil_b2c",
        "perfil_b2b",
        "perfil_revenda",
        "cart_update",
        "pedido",
        "pagto_confirmado",
    ]
    button_id: Optional[str] = None
    order_id: Optional[str] = None
    order_summary: Optional[list[OrderItem]] = None
    payment_method: Optional[str] = None
    total_value: Optional[str] = None
    note_timeline: Optional[list[NoteTimelineEntry]] = None


class N8nWebhookResponse(BaseModel):
    status: str
    lead_id: Optional[str] = None
    client_id: Optional[str] = None
    stage: Optional[str] = None
    order_id: Optional[str] = None
    message: str
    warnings: list[str] = []


# ── Helpers ──

_BRL_STRIP_RE = re.compile(r"[R$\s]")

# Match aproximado só com limiar alto e candidato único (evita SKU errado).
FUZZY_NAME_MATCH_MIN_RATIO = 0.92
FUZZY_NAME_MATCH_MIN_LEN = 4


def normalize_product_name_key(name: str) -> str:
    """Chave determinística para comparar nomes do agente com o catálogo.

    NFKC, minúsculas, remove marcas diacríticas, normaliza hífens/pontuação
    comuns e colapsa espaços — alinha com AC de variações de acento e rótulo.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name).strip().lower())
    s = "".join(
        ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn"
    )
    s = re.sub(r"[-–—_/]+", " ", s)
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _fuzzy_match_unique_product(
    needle_norm: str,
    products_db: list[dict],
    tenant_id: str,
) -> dict | None:
    """Retorna o produto só se existir exatamente um com similaridade >= limiar."""
    if len(needle_norm) < FUZZY_NAME_MATCH_MIN_LEN:
        return None
    hits: list[tuple[float, dict]] = []
    for p in products_db:
        if str(p.get("tenant_id", "")) != tenant_id:
            continue
        catalog_norm = normalize_product_name_key(str(p.get("name") or ""))
        if not catalog_norm:
            continue
        ratio = SequenceMatcher(None, needle_norm, catalog_norm).ratio()
        if ratio >= FUZZY_NAME_MATCH_MIN_RATIO:
            hits.append((ratio, p))
    if len(hits) != 1:
        return None
    return hits[0][1]


def parse_brl_to_float(val: str | None) -> float:
    """Parse Brazilian Real strings like 'R$ 112,00' → 112.0.

    Handles BRL ("1.112,00" → 1112.0) and plain ("112.00" → 112.0).
    If the string contains a comma, dots are thousands separators.
    If no comma, dots are treated as decimal separators.

    When the agent appends notes (e.g. ``R$ 180,00 (produtos) | frete…``),
    extracts the **first** ``R$ …`` monetary amount so ``lead.value`` updates.
    """
    if not val:
        return 0.0
    s = str(val).strip()
    m = re.search(
        r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})",
        s,
        re.IGNORECASE,
    )
    if m:
        chunk = m.group(1)
        try:
            if "," in chunk:
                chunk = chunk.replace(".", "").replace(",", ".")
            parsed = float(chunk)
            if parsed > 0:
                return parsed
        except (ValueError, TypeError):
            pass
    try:
        cleaned = _BRL_STRIP_RE.sub("", s)
        if not cleaned:
            return 0.0
        if "," in cleaned:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)
    except (ValueError, TypeError):
        return 0.0


def build_products_json(
    items: list[OrderItem],
    products_db: list[dict],
    tenant_id: str,
) -> tuple[list[dict], list[str]]:
    """Convert n8n OrderItems to the products_json format used by Kanban UI.
    Returns (products_json_list, warnings_list)."""
    by_id: dict[str, dict] = {}
    by_name_norm: dict[str, dict] = {}
    for p in products_db:
        pid = str(p.get("id") or "")
        if pid:
            by_id[pid] = p
        nk = normalize_product_name_key(str(p.get("name") or ""))
        if nk:
            by_name_norm[nk] = p

    result: list[dict] = []
    warnings: list[str] = []

    for item in items:
        matched: dict | None = None

        if item.product_id:
            matched = by_id.get(item.product_id)
            if matched and str(matched.get("tenant_id", "")) != tenant_id:
                warnings.append(f"product_id '{item.product_id}' pertence a outro tenant — ignorado")
                matched = None

        if not matched:
            item_norm = normalize_product_name_key(item.product)
            matched = by_name_norm.get(item_norm) if item_norm else None

        if not matched:
            item_norm = normalize_product_name_key(item.product)
            fuzzy = _fuzzy_match_unique_product(item_norm, products_db, tenant_id)
            if fuzzy:
                matched = fuzzy
                catalog_name = str(fuzzy.get("name") or "")
                warnings.append(
                    f"Match aproximado: '{item.product}' associado ao produto "
                    f"'{catalog_name}' do catálogo — conferir quantidade/preço."
                )

        unit_price = _derive_unit_price(item, matched)
        line_subtotal = round(unit_price * item.quantity, 2)
        line_total_parsed = parse_brl_to_float(item.total)
        line_total = line_total_parsed if line_total_parsed > 0 else line_subtotal

        if matched:
            pid = str(matched["id"])
            entry = {
                "id": pid,
                "product_id": pid,
                "name": str(matched.get("name") or item.product),
                "price": float(matched.get("price") or unit_price),
                "quantity": item.quantity,
                "qty": item.quantity,
                "category_id": str(matched.get("category_id")) if matched.get("category_id") else None,
                "line_subtotal": round(float(matched.get("price") or unit_price) * item.quantity, 2),
                "line_discount": 0.0,
                "line_total": round(float(matched.get("price") or unit_price) * item.quantity, 2),
                "applied_promotion_name": None,
            }
        else:
            warnings.append(
                f"Produto '{item.product}' não encontrado no catálogo — quantidade/nome "
                "registrados nas observações do lead."
            )
            entry = {
                "id": "",
                "product_id": item.product_id or "",
                "name": item.product,
                "price": unit_price,
                "quantity": item.quantity,
                "qty": item.quantity,
                "category_id": None,
                "line_subtotal": line_subtotal,
                "line_discount": 0.0,
                "line_total": line_total,
                "applied_promotion_name": None,
                "unmatched": True,
            }

        result.append(entry)

    return result, warnings


# Bloco único em `leads.notes` para itens sem SKU no CRM (Task 3b / AC6).
ORPHAN_CATALOG_BLOCK_START = "[Itens sem cadastro no CRM]"
ORPHAN_CATALOG_BLOCK_END = "[/Itens sem cadastro no CRM]"
# Alinhado a `LeadBase.notes` e `_sanitize_notes_field` no Kanban.
LEAD_NOTES_MAX_LEN_WEBHOOK = 1000

_ORPHAN_CATALOG_BLOCK_RE = re.compile(
    r"(?:^|\n)\s*\[Itens sem cadastro no CRM\][\s\S]*?\[/Itens sem cadastro no CRM\]\s*",
    re.MULTILINE,
)


def strip_orphan_catalog_block(notes: str) -> str:
    """Remove o último bloco delimitado de itens órfãos (evita duplicar a cada cart_update)."""
    if not notes:
        return ""
    s = _ORPHAN_CATALOG_BLOCK_RE.sub("\n", notes)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s


def partition_products_by_match(products_json: list[dict]) -> tuple[list[dict], list[dict]]:
    """Separa linhas resolvidas no catálogo das `unmatched` geradas por `build_products_json`."""
    matched: list[dict] = []
    unmatched: list[dict] = []
    for line in products_json or []:
        if line.get("unmatched"):
            unmatched.append(dict(line))
        else:
            matched.append({k: v for k, v in line.items() if k != "unmatched"})
    return matched, unmatched


def format_orphan_catalog_block_lines(unmatched_lines: list[dict]) -> str:
    """Texto delimitado com quantidade e nome informados pelo agente."""
    parts: list[str] = []
    for line in unmatched_lines:
        qty = int(line.get("quantity") or line.get("qty") or 0)
        name = str(line.get("name") or "").strip() or "(sem descrição)"
        parts.append(f"- {qty}x {name}")
    body = "\n".join(parts)
    return f"{ORPHAN_CATALOG_BLOCK_START}\n{body}\n{ORPHAN_CATALOG_BLOCK_END}"


def merge_notes_with_orphan_catalog_block(
    existing_notes: str,
    unmatched_lines: list[dict],
    *,
    max_length: int = LEAD_NOTES_MAX_LEN_WEBHOOK,
) -> tuple[str, bool]:
    """Substitui bloco anterior (mesmos marcadores) e anexa lista atual de órfãos. Retorna (texto, truncado)."""
    base = strip_orphan_catalog_block(existing_notes or "")
    if not unmatched_lines:
        return base, False
    block = format_orphan_catalog_block_lines(unmatched_lines)
    merged = f"{base.rstrip()}\n\n{block}" if base.strip() else block
    truncated = False
    if len(merged) > max_length:
        truncated = True
        merged = merged[: max_length - 1].rstrip() + "…"
    return merged, truncated


def _derive_unit_price(item: OrderItem, matched_product: dict | None) -> float:
    if matched_product:
        return float(matched_product.get("price") or 0.0)
    total = parse_brl_to_float(item.total)
    return round(total / max(item.quantity, 1), 2)


def generate_product_summary(items: list[OrderItem]) -> str:
    parts = [f"{item.quantity}x {item.product}" for item in items]
    return ", ".join(parts) if parts else "Sem itens"


def generate_client_name(
    lead_row: dict,
    payload: N8nWebhookPayload,
    client_row: dict | None,
) -> str:
    if client_row and client_row.get("display_name"):
        return str(client_row["display_name"])
    if payload.lead_name:
        return payload.lead_name
    for key in ("contact_name", "company_name"):
        val = lead_row.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return "Cliente WhatsApp"
