#!/usr/bin/env python3
"""
Aplica migrations SQL do Neurix CRM em ordem numérica.

Uso:
  python scripts/apply_migrations.py --database-url "postgresql://postgres:PASS@host:5432/postgres"
  python scripts/apply_migrations.py --database-url "$DATABASE_URL" --dry-run

Requer: pip install psycopg[binary]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "backend" / "migrations"


def sorted_migration_files() -> list[Path]:
    files = list(MIGRATIONS_DIR.glob("*.sql"))
    files.sort(key=lambda p: [int(x) for x in re.findall(r"\d+", p.stem.split("_")[0])])
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Neurix CRM SQL migrations in order.")
    parser.add_argument("--database-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--dry-run", action="store_true", help="List files only, do not execute")
    args = parser.parse_args()

    files = sorted_migration_files()
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    print(f"Found {len(files)} migration(s) in {MIGRATIONS_DIR}")
    for f in files:
        print(f"  - {f.name}")

    if args.dry_run:
        return 0

    try:
        import psycopg
    except ImportError:
        print("Install psycopg: pip install 'psycopg[binary]'", file=sys.stderr)
        return 1

    with psycopg.connect(args.database_url) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS public.schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            conn.commit()

            for path in files:
                cur.execute(
                    "SELECT 1 FROM public.schema_migrations WHERE filename = %s",
                    (path.name,),
                )
                if cur.fetchone():
                    print(f"SKIP (already applied): {path.name}")
                    continue

                sql = path.read_text(encoding="utf-8")
                print(f"APPLY: {path.name}")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO public.schema_migrations (filename) VALUES (%s)",
                    (path.name,),
                )
                conn.commit()
                print(f"OK: {path.name}")

    print("All migrations applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
