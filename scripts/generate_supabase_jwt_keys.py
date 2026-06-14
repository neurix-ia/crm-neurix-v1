#!/usr/bin/env python3
"""Gera ANON_KEY e SERVICE_ROLE_KEY para Supabase self-hosted (HS256)."""
from __future__ import annotations

import argparse
import json
import sys

try:
    import jwt
except ImportError:
    print("Instale PyJWT: pip install pyjwt", file=sys.stderr)
    raise SystemExit(1)

PAYLOAD_BASE = {
    "iss": "supabase",
    "iat": 1641769200,
    "exp": 1799535600,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera JWT anon + service_role para Supabase.")
    parser.add_argument("jwt_secret", help="JWT_SECRET da stack Supabase staging")
    args = parser.parse_args()
    secret = args.jwt_secret.strip()
    if not secret:
        print("JWT_SECRET vazio.", file=sys.stderr)
        return 1

    for role in ("anon", "service_role"):
        payload = {**PAYLOAD_BASE, "role": role}
        token = jwt.encode(payload, secret, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode()
        print(f"{role.upper()}={token}")
        header = token.split(".", 1)[0]
        print(f"  header_prefix={header}")

    print("\nCole no Dokploy (Supabase staging + CRM staging) e redeploy ambos.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
