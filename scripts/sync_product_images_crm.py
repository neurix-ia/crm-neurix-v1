# -*- coding: utf-8 -*-
"""
One-off: associar imagens de `potes geleia recortado` aos produtos do CRM (produção).
Faz login, POST /api/upload/product-image e PATCH /api/products/{id} com image_url.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

# Mesmo mapeamento para lojista (b2b) e cliente final — a chave é o `name` retornado pela API.
IMAGE_BY_PRODUCT_NAME: dict[str, str] = {
    "Geleia de amora": "IMG_3284.png",
    "Geleia de amora 0% açúcar": "mockup-amora-zero-aberto.png",
    "Geleia de morango": "mockup-morango-aberto.png",
    "Geleia de morango 0% açúcar": "mockup-morango-zero-aberto.png",
    "Geleia de frutas vermelhas": "mockup-frutas-vermelhas-aberto.png",
    "Geleia de figo": "mockup-figo-aberto.png",
    "Geleia de abacaxi com pimenta": "mockup-abacaxi-aberto.png",
    "Geleia de framboesa 0% açúcar": "mockup-framboesa-zero-aberto.png",
    "Patê de Palmito": "mockup-palmito-aberto.png",
    "Caponata de beringela": "mockup-caponata-aberto.png",
    "Caponata de berinjela": "mockup-caponata-aberto.png",
    "Bruschetta": "mockup-bruschetta-aberto.png",
    "Raiz forte de Crem": "mockup-crem-aberto.png",
    "Manteiga de Palmito Veghee": "mockup-palmito-aberto.png",
    # Abaixo de 5MB (limite do endpoint /api/upload/product-image)
    "Manteiga Veghee com sal": "IMG_3331.png",
    "Manteiga Veghee sem sal": "IMG_3350.png",
    "Geleinhas": "IMG_3285.png",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--only",
        help="Nomes de produto exatos (repetir flag ou separar por ;). Ex.: --only 'Manteiga Veghee sem sal'",
        nargs="*",
        default=[],
    )
    args = ap.parse_args()
    only: set[str] = set()
    for chunk in args.only:
        for part in chunk.split(";"):
            p = part.strip()
            if p:
                only.add(p)
    base_url = "https://crm.wbtech.dev"
    email = "admin@villadora.com"
    password = "123456789"
    # Pasta das imagens: diretório deste script → raiz do repo → `potes geleia recortado`
    root = Path(__file__).resolve().parent.parent
    image_dir = root / "potes geleia recortado"

    if not image_dir.is_dir():
        print(f"ERRO: pasta de imagens não encontrada: {image_dir}", file=sys.stderr)
        return 1

    r0 = requests.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=60,
    )
    r0.raise_for_status()
    access = r0.json()["access_token"]
    h = {"Authorization": f"Bearer {access}"}

    pr = requests.get(f"{base_url}/api/products/", headers=h, timeout=60)
    pr.raise_for_status()
    products = pr.json()
    if not isinstance(products, list):
        print("Resposta inesperada de /api/products/", file=sys.stderr)
        return 1

    ok, fail = 0, 0
    for p in products:
        pid = p.get("id")
        name = (p.get("name") or "").strip()
        if not pid or not name:
            continue
        if only and name not in only:
            continue
        fname = IMAGE_BY_PRODUCT_NAME.get(name)
        if not fname:
            print(f"SKIP (sem mapeamento): {name!r} [{pid}]")
            continue
        path = image_dir / fname
        if not path.is_file():
            print(f"FAIL arquivo ausente: {path} — {name}", file=sys.stderr)
            fail += 1
            continue
        up = None
        last_err: str | None = None
        for attempt in range(3):
            try:
                with path.open("rb") as f:
                    up = requests.post(
                        f"{base_url}/api/upload/product-image",
                        headers=h,
                        files={"file": (fname, f, "image/png")},
                        timeout=120,
                    )
                if up.status_code < 500:
                    last_err = None
                    break
                last_err = f"HTTP {up.status_code} {up.text[:200]}"
            except requests.RequestException as e:
                last_err = str(e)
            time.sleep(0.6 * (attempt + 1))
        if up is None or not up.ok:
            if up is not None and not up.ok:
                err = f"{up.status_code} {up.text[:200]}"
            else:
                err = last_err or "upload falhou"
            print(f"FAIL upload {name}: {err}", file=sys.stderr)
            fail += 1
            continue
        url = up.json().get("url")
        if not url:
            print(f"FAIL resposta sem url: {name} {up.text!r}", file=sys.stderr)
            fail += 1
            continue
        patch = requests.patch(
            f"{base_url}/api/products/{pid}",
            headers={**h, "Content-Type": "application/json"},
            json={"image_url": url},
            timeout=60,
        )
        if not patch.ok:
            print(
                f"FAIL PATCH {name}: {patch.status_code} {patch.text[:300]}",
                file=sys.stderr,
            )
            fail += 1
            continue
        print(f"OK {name} -> {fname}")
        ok += 1
        time.sleep(0.4)

    print(f"\nConcluído: {ok} ok, {fail} falha(s), pasta={image_dir}")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
