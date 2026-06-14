#!/usr/bin/env bash
# Roda seed Villadora em 2 fases: export (rede prod) + import (localhost no container staging).
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
STAGING_PW="$(container_env "$STAGING_CONTAINER" POSTGRES_PASSWORD)"

if [[ -z "$PROD_NET" ]]; then
  echo "ERRO: rede Docker do Postgres prod não encontrada." >&2
  exit 1
fi

mkdir -p "$SEED_DIR"
EXPORT_FILE="$SEED_DIR/catalog.json"

echo "Prod DB:    $PROD_CONTAINER (rede $PROD_NET)"
echo "Staging DB: $STAGING_CONTAINER (import via 127.0.0.1 no namespace do container)"
echo "Repo:       $REPO_DIR"
echo "Seed file:  $EXPORT_FILE"
echo

ARGS_QUOTED=""
for arg in "${EXTRA_ARGS[@]}"; do
  ARGS_QUOTED+=" $(printf '%q' "$arg")"
done

echo "=== Fase 1/2: export prod ==="
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
echo "=== Fase 2/2: import staging ==="
$DOCKER run --rm \
  --network "container:${STAGING_CONTAINER}" \
  -v "$REPO_DIR:/repo" \
  -v "$SEED_DIR:/seed" \
  -w /repo \
  python:3.12-slim \
  bash -c "pip install -q 'psycopg[binary]' && python scripts/seed_villadora_catalog_staging.py \
    --phase import \
    --import-file /seed/catalog.json \
    --staging-database-url 'postgresql://postgres:${STAGING_PW}@127.0.0.1:5432/postgres' \
    --create-staging-user \
    --create-fake-inbox${ARGS_QUOTED}"
