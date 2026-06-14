#!/usr/bin/env bash
# Roda seed Villadora: export (rede prod) + render SQL + psql via docker exec no staging.
# Uso:
#   cd /tmp/crm-neurix-v1 && bash scripts/run_seed_villadora_staging.sh --dry-run
#   cd /tmp/crm-neurix-v1 && bash scripts/run_seed_villadora_staging.sh

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PROD_CONTAINER="${PROD_CONTAINER:-supabase-319f-db}"
STAGING_CONTAINER="${STAGING_CONTAINER:-supabase-staging-319f-db}"
DOCKER="${DOCKER:-sudo docker}"
SEED_DIR="${SEED_DIR:-/tmp/villadora-seed-data}"

EXTRA_ARGS=("$@")
DRY_RUN=false
for arg in "${EXTRA_ARGS[@]}"; do
  if [[ "$arg" == "--dry-run" ]]; then
    DRY_RUN=true
  fi
done

container_env() {
  $DOCKER exec "$1" printenv "$2"
}

primary_stack_network() {
  local container="$1"
  $DOCKER inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$container" \
    | grep -v '^bridge$' \
    | head -1
}

PROD_NET="$(primary_stack_network "$PROD_CONTAINER")"
PROD_PW="$(container_env "$PROD_CONTAINER" POSTGRES_PASSWORD)"

if [[ -z "$PROD_NET" ]]; then
  echo "ERRO: rede Docker do Postgres prod não encontrada." >&2
  exit 1
fi

mkdir -p "$SEED_DIR"
EXPORT_FILE="$SEED_DIR/catalog.json"
IMPORT_SQL="$SEED_DIR/import.sql"

echo "Prod DB:    $PROD_CONTAINER (rede $PROD_NET)"
echo "Staging DB: $STAGING_CONTAINER (import via docker exec psql)"
echo "Repo:       $REPO_DIR"
echo "Seed JSON:  $EXPORT_FILE"
echo "Seed SQL:   $IMPORT_SQL"
echo

ARGS_QUOTED=""
for arg in "${EXTRA_ARGS[@]}"; do
  ARGS_QUOTED+=" $(printf '%q' "$arg")"
done

echo "=== Fase 1/3: export prod ==="
$DOCKER run --rm \
  --network "$PROD_NET" \
  -v "$REPO_DIR:/repo" \
  -v "$SEED_DIR:/seed" \
  -w /repo \
  python:3.12-slim \
  bash -c "pip install -q 'psycopg[binary]' && python scripts/seed_villadora_catalog_staging.py \
    --phase export \
    --export-file /seed/catalog.json \
    --prod-database-url 'postgresql://postgres:${PROD_PW}@${PROD_CONTAINER}:5432/postgres'${ARGS_QUOTED}"

if [[ "$DRY_RUN" == true ]]; then
  echo
  echo "Dry-run concluído (staging não alterado)."
  exit 0
fi

echo
echo "=== Fase 2/3: render SQL ==="
$DOCKER exec "$STAGING_CONTAINER" psql -U postgres -d postgres -At -F $'\t' -c "
SELECT c.table_name, string_agg(c.column_name, ',' ORDER BY c.ordinal_position)
FROM information_schema.columns c
WHERE c.table_schema = 'public'
GROUP BY c.table_name
ORDER BY c.table_name
" > "$SEED_DIR/staging_columns.tsv"

$DOCKER run --rm \
  -v "$REPO_DIR:/repo" \
  -v "$SEED_DIR:/seed" \
  -w /repo \
  python:3.12-slim \
  bash -c "python scripts/seed_villadora_catalog_staging.py \
    --phase render-sql \
    --import-file /seed/catalog.json \
    --sql-out /seed/import.sql \
    --staging-columns-file /seed/staging_columns.tsv \
    --create-staging-user \
    --create-fake-inbox"

echo
echo "=== Fase 3/3: aplicar SQL no staging ==="
$DOCKER exec -i "$STAGING_CONTAINER" psql -U postgres -d postgres -v ON_ERROR_STOP=1 < "$IMPORT_SQL"

echo
echo "Concluído. Login: https://crm-staging.wbtech.dev"
echo "  staging@villadora.com / 123456"
echo "Nota: image_url pode apontar para storage staging vazio — reenvie imagens se necessário."
