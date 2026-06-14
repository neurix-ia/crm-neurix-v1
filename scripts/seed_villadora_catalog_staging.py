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
from decimal import Decimal
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


def staging_connect_urls(password: str, explicit_url: str | None = None) -> list[str]:
    urls: list[str] = []
    if explicit_url:
        urls.append(explicit_url)
    urls.extend(
        [
            f"postgresql://postgres:{password}@/postgres?host=/var/run/postgresql",
            f"postgresql://postgres:{password}@/postgres?host=/var/lib/postgresql",
            f"postgresql://postgres:{password}@127.0.0.1:5432/postgres",
        ]
    )
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def connect_first(urls: list[str]):
    last_err: Exception | None = None
    for url in urls:
        try:
            return connect(url), url
        except Exception as exc:
            last_err = exc
    raise last_err or RuntimeError("Falha ao conectar ao Postgres")


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


def json_serialize(obj: Any) -> Any:
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Não serializável: {type(obj)}")


def build_export_bundle(prod_conn, prod_email: str) -> dict[str, Any]:
    prod_tenant = fetch_user_id(prod_conn, prod_email)
    if not prod_tenant:
        raise RuntimeError(f"Usuário prod não encontrado: {prod_email}")

    profile_rows = fetch_rows(
        prod_conn, "SELECT * FROM public.profiles WHERE id = %s", (prod_tenant,)
    )
    profile = profile_rows[0] if profile_rows else {}
    org_id = profile.get("organization_id")

    organizations: list[dict[str, Any]] = []
    if org_id:
        organizations = fetch_rows(
            prod_conn, "SELECT * FROM public.organizations WHERE id = %s", (org_id,)
        )

    settings_rows = [
        row
        for row in fetch_rows(
            prod_conn,
            "SELECT * FROM public.settings WHERE tenant_id = %s",
            (prod_tenant,),
        )
        if not is_sensitive_setting(str(row.get("key", "")))
    ]

    stage_automations: list[dict[str, Any]] = []
    if org_id:
        stage_automations = fetch_rows(
            prod_conn,
            "SELECT * FROM public.stage_automations WHERE organization_id = %s",
            (org_id,),
        )

    tables = (
        "funnels",
        "pipeline_stages",
        "product_categories",
        "products",
        "promotions",
        "promotion_products",
        "keyword_rules",
    )
    catalog: dict[str, list] = {}
    for table in tables:
        catalog[table] = fetch_rows(
            prod_conn,
            f"SELECT * FROM public.{table} WHERE tenant_id = %s ORDER BY created_at NULLS LAST",
            (prod_tenant,),
        )

    return {
        "version": 1,
        "prod_email": prod_email,
        "prod_tenant_id": str(prod_tenant),
        "org_id": str(org_id) if org_id else None,
        "organizations": organizations,
        "profile_snapshot": profile,
        "settings": settings_rows,
        "stage_automations": stage_automations,
        **catalog,
    }


def print_bundle_summary(bundle: dict[str, Any], prefix: str = "") -> None:
    print(f"{prefix}Prod tenant: {bundle['prod_email']} ({bundle['prod_tenant_id']})")
    for key in (
        "organizations",
        "funnels",
        "pipeline_stages",
        "product_categories",
        "products",
        "promotions",
        "promotion_products",
        "settings",
        "keyword_rules",
        "stage_automations",
    ):
        print(f"{prefix}  {key}: {len(bundle.get(key, []))} linha(s)")


def apply_import_bundle(staging_conn, bundle: dict[str, Any], args) -> uuid.UUID:
    prod_tenant = uuid.UUID(bundle["prod_tenant_id"])
    org_id = uuid.UUID(bundle["org_id"]) if bundle.get("org_id") else None
    profile_snapshot = bundle.get("profile_snapshot") or {}

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
            raise RuntimeError(
                f"{args.staging_email} não existe em staging. Use --create-staging-user."
            )

    print(f"Staging tenant ({args.staging_email}): {staging_tenant}")
    clear_staging_catalog(staging_conn, staging_tenant, org_id, args.dry_run)

    for row in bundle.get("organizations", []):
        if args.dry_run:
            continue
        with staging_conn.cursor() as cur:
            upsert_row(cur, "organizations", row)
    if not args.dry_run and bundle.get("organizations"):
        staging_conn.commit()
    print(f"  organizations: {len(bundle.get('organizations', []))} linha(s)")

    for table in (
        "funnels",
        "pipeline_stages",
        "product_categories",
        "products",
        "promotions",
        "promotion_products",
        "keyword_rules",
    ):
        count = 0
        for row in bundle.get(table, []):
            mapped = remap_row(row, prod_tenant, staging_tenant)
            if args.dry_run:
                count += 1
                continue
            with staging_conn.cursor() as cur:
                upsert_row(cur, table, mapped)
            count += 1
        if not args.dry_run:
            staging_conn.commit()
        print(f"  {table}: {count} linha(s)")

    settings_ok = 0
    for row in bundle.get("settings", []):
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

    auto_rows = bundle.get("stage_automations", [])
    for row in auto_rows:
        mapped = remap_row(row, prod_tenant, staging_tenant, ("target_user_id", "created_by"))
        if mapped.get("target_user_id") not in (staging_tenant, None):
            mapped["target_user_id"] = staging_tenant
        if args.dry_run:
            continue
        with staging_conn.cursor() as cur:
            upsert_row(cur, "stage_automations", mapped)
    if not args.dry_run and auto_rows:
        staging_conn.commit()
    print(f"  stage_automations: {len(auto_rows)} linha(s)")

    profile_patch = {
        "company_name": profile_snapshot.get("company_name") or "Villadora (staging)",
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

    return staging_tenant


def run_phase_export(args) -> int:
    if not args.prod_database_url:
        print("ERRO: --prod-database-url obrigatório na fase export.", file=sys.stderr)
        return 1
    print("Fase export — conectando prod...")
    prod_conn = connect(args.prod_database_url)
    bundle = build_export_bundle(prod_conn, args.prod_email)
    prod_conn.close()

    print_bundle_summary(bundle, prefix="Export: ")
    if args.dry_run:
        print("[dry-run] Nenhum arquivo gravado.")
        return 0
    if not args.export_file:
        print("ERRO: --export-file obrigatório (exceto com --dry-run).", file=sys.stderr)
        return 1
    path = args.export_file
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bundle, f, default=json_serialize, indent=2, ensure_ascii=False)
    print(f"Export salvo em {path}")
    return 0


STAGING_USER_SUBQ = "__STAGING_USER_ID__"


def pg_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def staging_user_sql(email: str) -> str:
    return f"(SELECT id FROM auth.users WHERE lower(trim(email)) = lower({pg_quote(email)}))"


def sql_value(col: str, value: Any, email: str) -> str:
    if value == STAGING_USER_SUBQ:
        return staging_user_sql(email)
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return f"{pg_quote(json.dumps(value, ensure_ascii=False))}::jsonb"
    if col.endswith("_id") or col == "id":
        return f"{pg_quote(str(value))}::uuid"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return pg_quote(str(value))


def remap_row_for_sql(
    row: dict[str, Any],
    prod_tenant: str,
    email: str,
    user_fields: tuple[str, ...] = ("tenant_id",),
) -> dict[str, Any]:
    out = dict(row)
    for field in user_fields:
        if field in out and str(out[field]) == prod_tenant:
            out[field] = STAGING_USER_SUBQ
    if "image_url" in out:
        out["image_url"] = rewrite_storage_url(out.get("image_url"))
    return out


def sql_upsert(table: str, row: dict[str, Any], email: str, conflict_col: str = "id") -> str:
    columns = list(row.keys())
    collist = ", ".join(columns)
    values = ", ".join(sql_value(c, row[c], email) for c in columns)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != conflict_col)
    return (
        f"INSERT INTO public.{table} ({collist}) VALUES ({values}) "
        f"ON CONFLICT ({conflict_col}) DO UPDATE SET {updates};"
    )


def load_staging_columns(path: str | None) -> dict[str, set[str]]:
    if not path:
        return {}
    table_cols: dict[str, set[str]] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            table, cols = line.split("\t", 1)
            table_cols[table] = {c.strip() for c in cols.split(",") if c.strip()}
    return table_cols


def filter_row_columns(
    row: dict[str, Any], table: str, staging_columns: dict[str, set[str]]
) -> dict[str, Any]:
    allowed = staging_columns.get(table)
    if not allowed:
        return row
    return {k: v for k, v in row.items() if k in allowed}


    return f"""
DO $create_user$
DECLARE
  v_user_id uuid := gen_random_uuid();
  v_email text := {pg_quote(email)};
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
    crypt({pg_quote(password)}, gen_salt('bf')), now(),
    '{{"provider":"email","providers":["email"]}}'::jsonb,
    jsonb_build_object('full_name', {pg_quote(full_name)}),
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
END $create_user$;
"""


def render_import_sql(
    bundle: dict[str, Any], args, staging_columns: dict[str, set[str]] | None = None
) -> str:
    staging_columns = staging_columns or {}
    skipped_logged: set[tuple[str, str]] = set()
    prod_tenant = bundle["prod_tenant_id"]
    org_id = bundle.get("org_id")
    profile_snapshot = bundle.get("profile_snapshot") or {}
    email = args.staging_email
    lines = [
        "BEGIN;",
        "CREATE EXTENSION IF NOT EXISTS pgcrypto;",
    ]
    if args.create_staging_user:
        lines.append(render_create_staging_user_sql(email, args.staging_password, args.staging_full_name))

    su = staging_user_sql(email)
    org_sql = f"{pg_quote(org_id)}::uuid" if org_id else "NULL"
    lines.append(
        f"""
DO $clear$
DECLARE v_staging uuid;
BEGIN
  SELECT id INTO v_staging FROM auth.users WHERE lower(trim(email)) = lower({pg_quote(email)});
  IF v_staging IS NULL THEN
    RAISE EXCEPTION 'Usuário staging não encontrado: %', {pg_quote(email)};
  END IF;
  IF {org_sql} IS NOT NULL THEN
    DELETE FROM public.stage_automations WHERE organization_id = {org_sql};
  END IF;
  DELETE FROM public.promotion_products WHERE tenant_id = v_staging;
  DELETE FROM public.promotions WHERE tenant_id = v_staging;
  DELETE FROM public.products WHERE tenant_id = v_staging;
  DELETE FROM public.product_categories WHERE tenant_id = v_staging;
  DELETE FROM public.pipeline_stages WHERE tenant_id = v_staging;
  DELETE FROM public.inboxes WHERE tenant_id = v_staging;
  DELETE FROM public.funnels WHERE tenant_id = v_staging;
  DELETE FROM public.keyword_rules WHERE tenant_id = v_staging;
  DELETE FROM public.settings WHERE tenant_id = v_staging;
END $clear$;
"""
    )

    for row in bundle.get("organizations", []):
        row = filter_row_columns(row, "organizations", staging_columns)
        lines.append(sql_upsert("organizations", row, email))

    for table in (
        "funnels",
        "pipeline_stages",
        "product_categories",
        "products",
        "promotions",
        "promotion_products",
        "keyword_rules",
    ):
        for row in bundle.get(table, []):
            filtered = filter_row_columns(row, table, staging_columns)
            if staging_columns.get(table):
                for col in set(row) - set(filtered):
                    key = (table, col)
                    if key not in skipped_logged:
                        print(f"  SQL skip coluna {table}.{col} (ausente no staging)", file=sys.stderr)
                        skipped_logged.add(key)
            mapped = remap_row_for_sql(filtered, prod_tenant, email)
            lines.append(sql_upsert(table, mapped, email))

    for row in bundle.get("settings", []):
        filtered = filter_row_columns(row, "settings", staging_columns)
        mapped = remap_row_for_sql(filtered, prod_tenant, email)
        lines.append(sql_upsert("settings", mapped, email, conflict_col="id"))

    for row in bundle.get("stage_automations", []):
        filtered = filter_row_columns(row, "stage_automations", staging_columns)
        mapped = remap_row_for_sql(filtered, prod_tenant, email, ("target_user_id", "created_by"))
        if mapped.get("target_user_id") != STAGING_USER_SUBQ and mapped.get("target_user_id") is not None:
            mapped["target_user_id"] = STAGING_USER_SUBQ
        lines.append(sql_upsert("stage_automations", mapped, email))

    company = profile_snapshot.get("company_name") or "Villadora (staging)"
    lines.append(
        f"""
UPDATE public.profiles
SET company_name = {pg_quote(company)},
    full_name = {pg_quote(args.staging_full_name)},
    phones = '[]'::jsonb,
    organization_id = {org_sql},
    is_superadmin = false,
    updated_at = now()
WHERE id = {su};
"""
    )

    if org_id:
        lines.append(
            f"""
DELETE FROM public.organization_members WHERE organization_id = {org_sql};
INSERT INTO public.organization_members (organization_id, user_id, role)
VALUES ({org_sql}, {su}, 'admin')
ON CONFLICT (organization_id, user_id)
DO UPDATE SET role = 'admin', assigned_funnel_id = NULL;
"""
        )

    if args.create_fake_inbox:
        lines.append(
            f"""
INSERT INTO public.inboxes (tenant_id, funnel_id, name, uazapi_settings)
SELECT {su}, f.id, 'Inbox teste staging', '{{}}'::jsonb
FROM public.funnels f
WHERE f.tenant_id = {su}
  AND lower(trim(f.name)) IN ('funil-1', 'funil 1', 'default')
  AND NOT EXISTS (
    SELECT 1 FROM public.inboxes i WHERE i.tenant_id = {su} AND i.funnel_id = f.id
  )
ORDER BY f.created_at
LIMIT 1;
"""
        )

    lines.append(
        f"""
SELECT 'products' AS t, count(*)::int AS n FROM public.products WHERE tenant_id = {su}
UNION ALL SELECT 'leads', count(*)::int FROM public.leads WHERE tenant_id = {su}
UNION ALL SELECT 'crm_clients', count(*)::int FROM public.crm_clients WHERE tenant_id = {su};
COMMIT;
"""
    )
    return "\n".join(lines)


def run_phase_render_sql(args) -> int:
    if not args.import_file:
        print("ERRO: --import-file obrigatório.", file=sys.stderr)
        return 1
    with open(args.import_file, encoding="utf-8") as f:
        bundle = json.load(f)

    if args.dry_run:
        print_bundle_summary(bundle, prefix="Import: ")
        print("[dry-run] Nenhum SQL gravado.")
        return 0
    if not args.sql_out:
        print("ERRO: --sql-out obrigatório na fase render-sql.", file=sys.stderr)
        return 1

    sql = render_import_sql(
        bundle, args, load_staging_columns(args.staging_columns_file)
    )
    with open(args.sql_out, "w", encoding="utf-8") as f:
        f.write(sql)
    print(f"SQL de import salvo em {args.sql_out}")
    return 0


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
        "--phase",
        choices=("export", "render-sql"),
        help="export= prod→JSON; render-sql= JSON→SQL (import via docker exec psql)",
    )
    parser.add_argument("--export-file", help="Arquivo JSON de saída (fase export)")
    parser.add_argument("--import-file", help="Arquivo JSON de entrada (fase render-sql)")
    parser.add_argument("--sql-out", help="Arquivo SQL de saída (fase render-sql)")
    parser.add_argument(
        "--staging-columns-file",
        help="TSV table_name<TAB>col1,col2,... do schema staging (filtra colunas extras de prod)",
    )
    parser.add_argument(
        "--use-sudo-docker",
        action="store_true",
        help="Usa 'sudo docker' (necessário em muitos servidores)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.phase == "export":
        if not args.prod_database_url:
            args.prod_database_url = build_url_from_container(
                args.prod_container, args.use_sudo_docker
            )
        return run_phase_export(args)

    if args.phase == "render-sql":
        return run_phase_render_sql(args)

    print(
        "ERRO: use --phase export ou --phase render-sql, ou rode scripts/run_seed_villadora_staging.sh",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
