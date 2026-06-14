#!/usr/bin/env python3
"""
Copia catálogo/config Villadora (prod) → staging, sem dados sensíveis.

Copia: organizations, funnels, pipeline_stages, product_categories, products,
       promotions, promotion_products, settings (filtrados), keyword_rules,
       stage_automations (users remapeados), profile (sem telefones).

Ignora: leads, crm_clients, orders, chat_messages, lead_activity,
        lead_pipeline_positions, inboxes (cria inbox fake vazio opcional).

Uso no servidor (com Docker):

  pip install "psycopg[binary]"

  python scripts/seed_villadora_catalog_staging.py \\
    --prod-container supabase-319f-db \\
    --staging-container supabase-staging-319f-db \\
    --create-staging-user

Ou com URLs explícitas:

  python scripts/seed_villadora_catalog_staging.py \\
    --prod-database-url "postgresql://postgres:PASS@HOST:5432/postgres" \\
    --staging-database-url "postgresql://postgres:PASS@HOST:5432/postgres" \\
    --create-staging-user

Requer acesso de rede aos dois Postgres (IPs dos containers ou portas publicadas).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from typing import Any

SENSITIVE_SETTING_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "uazapi",
    "whatsapp",
    "api_key",
    "webhook",
    "smtp",
)

PROD_SUPABASE_PUBLIC_HOST = "crm-supabase.wbtech.dev"
STAGING_SUPABASE_PUBLIC_HOST = "crm-supabase-staging.wbtech.dev"

CREATE_AUTH_USER_SQL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
DECLARE
  v_user_id uuid := gen_random_uuid();
  v_email text := %(email)s;
BEGIN
  IF EXISTS (SELECT 1 FROM auth.users WHERE lower(trim(email)) = lower(trim(v_email))) THEN
    RETURN;
  END IF;

  INSERT INTO auth.users (
    instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
    raw_app_meta_data, raw_user_meta_data, created_at, updated_at,
    confirmation_token, email_change, email_change_token_new, recovery_token, is_super_admin
  ) VALUES (
    '00000000-0000-0000-0000-000000000000',
    v_user_id, 'authenticated', 'authenticated', v_email,
    crypt(%(password)s, gen_salt('bf')), now(),
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('full_name', %(full_name)s),
    now(), now(), '', '', '', '', false
  );

  INSERT INTO auth.identities (
    id, provider_id, user_id, identity_data, provider, last_sign_in_at, created_at, updated_at
  ) VALUES (
    gen_random_uuid(), v_user_id::text, v_user_id,
    jsonb_build_object(
      'sub', v_user_id::text, 'email', v_email,
      'email_verified', true, 'phone_verified', false
    ),
    'email', now(), now(), now()
  );
END $$;
"""


def _import_psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row

        return psycopg, dict_row
    except ImportError:
        print("Instale: pip install 'psycopg[binary]'", file=sys.stderr)
        raise SystemExit(1)


def docker_argv(use_sudo: bool) -> list[str]:
    if use_sudo:
        return ["sudo", "docker"]
    return ["docker"]


def docker_container_ip(container: str, use_sudo: bool = False) -> str:
    out = subprocess.check_output(
        docker_argv(use_sudo)
        + [
            "inspect",
            "-f",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}",
            container,
        ],
        text=True,
    ).strip()
    ips = [p for p in out.split() if p]
    if not ips:
        raise RuntimeError(f"Sem IP para container {container}")
    return ips[0]


def docker_postgres_password(container: str, use_sudo: bool = False) -> str:
    out = subprocess.check_output(
        docker_argv(use_sudo) + ["exec", container, "printenv", "POSTGRES_PASSWORD"],
        text=True,
    ).strip()
    if not out:
        raise RuntimeError(f"POSTGRES_PASSWORD vazio em {container}")
    return out


def build_url_from_container(container: str, use_sudo: bool = False) -> str:
    password = docker_postgres_password(container, use_sudo)
    ip = docker_container_ip(container, use_sudo)
    return f"postgresql://postgres:{password}@{ip}:5432/postgres"


def connect(url: str):
    psycopg, dict_row = _import_psycopg()
    return psycopg.connect(url, row_factory=dict_row)


def fetch_user_id(conn, email: str) -> uuid.UUID | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM auth.users WHERE lower(trim(email)) = lower(trim(%s))",
            (email,),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def ensure_staging_user(conn, email: str, password: str, full_name: str, dry_run: bool) -> uuid.UUID:
    existing = fetch_user_id(conn, email)
    if existing:
        print(f"Usuário staging já existe: {email} ({existing})")
        return existing
    if dry_run:
        print(f"[dry-run] Criaria usuário {email}")
        return uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            CREATE_AUTH_USER_SQL,
            {"email": email, "password": password, "full_name": full_name},
        )
    conn.commit()
    user_id = fetch_user_id(conn, email)
    if not user_id:
        raise RuntimeError(f"Falha ao criar usuário {email}")
    print(f"Usuário criado: {email} ({user_id})")
    return user_id


def is_sensitive_setting(key: str) -> bool:
    lower = key.lower()
    return any(fragment in lower for fragment in SENSITIVE_SETTING_FRAGMENTS)


def rewrite_storage_url(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace(PROD_SUPABASE_PUBLIC_HOST, STAGING_SUPABASE_PUBLIC_HOST)
    return value


def remap_row(
    row: dict[str, Any],
    prod_tenant: uuid.UUID,
    staging_tenant: uuid.UUID,
    uuid_user_fields: tuple[str, ...] = ("tenant_id",),
) -> dict[str, Any]:
    out = dict(row)
    for field in uuid_user_fields:
        if field in out and out[field] == prod_tenant:
            out[field] = staging_tenant
    if "image_url" in out:
        out["image_url"] = rewrite_storage_url(out.get("image_url"))
    return out


def upsert_row(cur, table: str, row: dict[str, Any], conflict_col: str = "id") -> None:
    columns = list(row.keys())
    placeholders = ", ".join(f"%({c})s" for c in columns)
    collist = ", ".join(columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != conflict_col)
    sql = (
        f"INSERT INTO public.{table} ({collist}) VALUES ({placeholders}) "
        f"ON CONFLICT ({conflict_col}) DO UPDATE SET {updates}"
    )
    cur.execute(sql, row)


def fetch_rows(conn, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return list(cur.fetchall())


def clear_staging_catalog(conn, staging_tenant: uuid.UUID, org_id: uuid.UUID | None, dry_run: bool) -> None:
    org_filter = org_id or uuid.UUID(int=0)
    statements = [
        (
            "DELETE FROM public.stage_automations WHERE organization_id = %s",
            (org_filter,),
        ),
        ("DELETE FROM public.promotion_products WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.promotions WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.products WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.product_categories WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.pipeline_stages WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.inboxes WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.funnels WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.keyword_rules WHERE tenant_id = %s", (staging_tenant,)),
        ("DELETE FROM public.settings WHERE tenant_id = %s", (staging_tenant,)),
    ]
    if dry_run:
        print("[dry-run] Limparia catálogo existente do tenant staging")
        return
    with conn.cursor() as cur:
        for sql, params in statements:
            if "stage_automations" in sql and org_id is None:
                continue
            cur.execute(sql, params)
    conn.commit()
    print("Catálogo anterior do tenant staging removido.")


def copy_table_by_tenant(
    prod_conn,
    staging_conn,
    table: str,
    prod_tenant: uuid.UUID,
    staging_tenant: uuid.UUID,
    dry_run: bool,
    extra_remap_fields: tuple[str, ...] = (),
    row_filter=None,
) -> int:
    rows = fetch_rows(
        prod_conn,
        f"SELECT * FROM public.{table} WHERE tenant_id = %s ORDER BY created_at NULLS LAST",
        (prod_tenant,),
    )
    if row_filter:
        rows = [r for r in rows if row_filter(r)]
    count = 0
    for row in rows:
        mapped = remap_row(row, prod_tenant, staging_tenant, ("tenant_id",) + extra_remap_fields)
        if dry_run:
            count += 1
            continue
        with staging_conn.cursor() as cur:
            upsert_row(cur, table, mapped)
        count += 1
    if not dry_run:
        staging_conn.commit()
    print(f"  {table}: {count} linha(s)")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed catálogo Villadora prod → staging.")
    parser.add_argument("--prod-database-url", help="URL Postgres produção")
    parser.add_argument("--staging-database-url", help="URL Postgres staging")
    parser.add_argument("--prod-container", default="supabase-319f-db", help="Container Postgres prod")
    parser.add_argument(
        "--staging-container",
        default="supabase-staging-319f-db",
        help="Container Postgres staging",
    )
    parser.add_argument("--prod-email", default="admin@villadora.com")
    parser.add_argument("--staging-email", default="staging@villadora.com")
    parser.add_argument("--staging-password", default="123456")
    parser.add_argument("--staging-full-name", default="Villadora Staging")
    parser.add_argument(
        "--create-staging-user",
        action="store_true",
        help="Cria staging@villadora.com no Auth se não existir",
    )
    parser.add_argument(
        "--create-fake-inbox",
        action="store_true",
        help="Cria inbox de teste com uazapi_settings vazio no funil-1",
    )
    parser.add_argument(
        "--use-sudo-docker",
        action="store_true",
        help="Usa 'sudo docker' (necessário em muitos servidores)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    prod_url = args.prod_database_url or build_url_from_container(
        args.prod_container, args.use_sudo_docker
    )
    staging_url = args.staging_database_url or build_url_from_container(
        args.staging_container, args.use_sudo_docker
    )

    print("Conectando prod...")
    prod_conn = connect(prod_url)
    print("Conectando staging...")
    staging_conn = connect(staging_url)

    prod_tenant = fetch_user_id(prod_conn, args.prod_email)
    if not prod_tenant:
        print(f"ERRO: usuário prod não encontrado: {args.prod_email}", file=sys.stderr)
        return 1

    staging_tenant = fetch_user_id(staging_conn, args.staging_email)
    if not staging_tenant:
        if args.create_staging_user:
            staging_tenant = ensure_staging_user(
                staging_conn,
                args.staging_email,
                args.staging_password,
                args.staging_full_name,
                args.dry_run,
            )
        else:
            print(
                f"ERRO: {args.staging_email} não existe em staging. "
                "Use --create-staging-user ou crie o usuário antes.",
                file=sys.stderr,
            )
            return 1

    print(f"Prod tenant ({args.prod_email}): {prod_tenant}")
    print(f"Staging tenant ({args.staging_email}): {staging_tenant}")

    prod_profile = fetch_rows(
        prod_conn,
        "SELECT * FROM public.profiles WHERE id = %s",
        (prod_tenant,),
    )
    prod_profile_row = prod_profile[0] if prod_profile else {}
    org_id = prod_profile_row.get("organization_id")

    clear_staging_catalog(staging_conn, staging_tenant, org_id, args.dry_run)

    # --- organizations ---
    if org_id:
        org_rows = fetch_rows(
            prod_conn,
            "SELECT * FROM public.organizations WHERE id = %s",
            (org_id,),
        )
        for row in org_rows:
            if args.dry_run:
                print(f"  organizations: 1 (dry-run) — {row.get('name')}")
            else:
                with staging_conn.cursor() as cur:
                    upsert_row(cur, "organizations", row)
                staging_conn.commit()
        print(f"  organizations: {len(org_rows)} linha(s)")
    else:
        print("  organizations: 0 (tenant sem organization_id)")

    # --- catálogo (ordem FK) ---
    copy_table_by_tenant(prod_conn, staging_conn, "funnels", prod_tenant, staging_tenant, args.dry_run)
    copy_table_by_tenant(
        prod_conn, staging_conn, "pipeline_stages", prod_tenant, staging_tenant, args.dry_run
    )
    copy_table_by_tenant(
        prod_conn, staging_conn, "product_categories", prod_tenant, staging_tenant, args.dry_run
    )
    copy_table_by_tenant(prod_conn, staging_conn, "products", prod_tenant, staging_tenant, args.dry_run)
    copy_table_by_tenant(prod_conn, staging_conn, "promotions", prod_tenant, staging_tenant, args.dry_run)
    copy_table_by_tenant(
        prod_conn, staging_conn, "promotion_products", prod_tenant, staging_tenant, args.dry_run
    )

    # settings (filtrados)
    settings_rows = fetch_rows(
        prod_conn,
        "SELECT * FROM public.settings WHERE tenant_id = %s",
        (prod_tenant,),
    )
    settings_ok = 0
    for row in settings_rows:
        if is_sensitive_setting(str(row.get("key", ""))):
            print(f"  settings: SKIP sensível — {row.get('key')}")
            continue
        mapped = remap_row(row, prod_tenant, staging_tenant)
        if args.dry_run:
            settings_ok += 1
            continue
        with staging_conn.cursor() as cur:
            upsert_row(cur, "settings", mapped, conflict_col="id")
        settings_ok += 1
    if not args.dry_run:
        staging_conn.commit()
    print(f"  settings: {settings_ok} linha(s)")

    copy_table_by_tenant(
        prod_conn, staging_conn, "keyword_rules", prod_tenant, staging_tenant, args.dry_run
    )

    # stage_automations (por org)
    if org_id:
        auto_rows = fetch_rows(
            prod_conn,
            "SELECT * FROM public.stage_automations WHERE organization_id = %s",
            (org_id,),
        )
        for row in auto_rows:
            mapped = remap_row(
                row,
                prod_tenant,
                staging_tenant,
                ("target_user_id", "created_by"),
            )
            if mapped.get("target_user_id") not in (staging_tenant, None):
                mapped["target_user_id"] = staging_tenant
            if args.dry_run:
                continue
            with staging_conn.cursor() as cur:
                upsert_row(cur, "stage_automations", mapped)
        if not args.dry_run:
            staging_conn.commit()
        print(f"  stage_automations: {len(auto_rows)} linha(s)")
    else:
        print("  stage_automations: 0")

    # profile staging (sem telefones)
    profile_patch = {
        "company_name": prod_profile_row.get("company_name") or "Villadora (staging)",
        "full_name": args.staging_full_name,
        "phones": [],
        "organization_id": org_id,
        "is_superadmin": False,
    }
    if args.dry_run:
        print(f"  profiles: atualizaria {args.staging_email} — {profile_patch}")
    else:
        with staging_conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.profiles
                SET company_name = %(company_name)s,
                    full_name = %(full_name)s,
                    phones = %(phones)s::jsonb,
                    organization_id = %(organization_id)s,
                    is_superadmin = %(is_superadmin)s,
                    updated_at = now()
                WHERE id = %(id)s
                """,
                {**profile_patch, "id": staging_tenant, "phones": json.dumps([])},
            )
        staging_conn.commit()
        print("  profiles: staging atualizado")

    # organization_members — só o usuário staging como admin
    if org_id:
        if args.dry_run:
            print(f"  organization_members: admin {args.staging_email}")
        else:
            with staging_conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM public.organization_members WHERE organization_id = %s",
                    (org_id,),
                )
                cur.execute(
                    """
                    INSERT INTO public.organization_members (organization_id, user_id, role)
                    VALUES (%s, %s, 'admin')
                    ON CONFLICT (organization_id, user_id)
                    DO UPDATE SET role = 'admin', assigned_funnel_id = NULL
                    """,
                    (org_id, staging_tenant),
                )
            staging_conn.commit()
            print("  organization_members: admin staging configurado")

    # inbox fake opcional
    if args.create_fake_inbox:
        funnels = fetch_rows(
            staging_conn,
            """
            SELECT id, name FROM public.funnels
            WHERE tenant_id = %s AND lower(trim(name)) IN ('funil-1', 'funil 1', 'default')
            ORDER BY created_at
            LIMIT 1
            """,
            (staging_tenant,),
        )
        if funnels and not args.dry_run:
            with staging_conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM public.inboxes
                    WHERE tenant_id = %s AND funnel_id = %s
                    """,
                    (staging_tenant, funnels[0]["id"]),
                )
                if not cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO public.inboxes (tenant_id, funnel_id, name, uazapi_settings)
                        VALUES (%s, %s, 'Inbox teste staging', '{}'::jsonb)
                        """,
                        (staging_tenant, funnels[0]["id"]),
                    )
            staging_conn.commit()
            print("  inboxes: inbox teste criado")
        elif args.dry_run:
            print("  inboxes: criaria inbox teste (dry-run)")

    # resumo
    counts = fetch_rows(
        staging_conn,
        """
        SELECT 'products' AS t, count(*)::int AS n FROM public.products WHERE tenant_id = %s
        UNION ALL SELECT 'leads', count(*)::int FROM public.leads WHERE tenant_id = %s
        UNION ALL SELECT 'crm_clients', count(*)::int FROM public.crm_clients WHERE tenant_id = %s
        """,
        (staging_tenant, staging_tenant, staging_tenant),
    )
    print("\nResumo staging:")
    for row in counts:
        print(f"  {row['t']}: {row['n']}")

    prod_conn.close()
    staging_conn.close()
    print("\nConcluído. Login: https://crm-staging.wbtech.dev")
    print(f"  {args.staging_email} / (senha informada)")
    if not args.dry_run:
        print(
            "Nota: image_url pode apontar para storage staging vazio — "
            "reenvie imagens se necessário."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
