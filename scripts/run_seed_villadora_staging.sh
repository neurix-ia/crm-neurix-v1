#!/usr/bin/env bash
# Roda seed_villadora_catalog_staging.py via container Python (sem pip no host).
# Uso no servidor:
#   cd /tmp/crm-neurix-v1 && bash scripts/run_seed_villadora_staging.sh --dry-run
#   cd /tmp/crm-neurix-v1 && bash scripts/run_seed_villadora_staging.sh

set -euo pipefail

REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
PROD_CONTAINER="${PROD_CONTAINER:-supabase-319f-db}"
STAGING_CONTAINER="${STAGING_CONTAINER:-supabase-staging-319f-db}"
DOCKER="${DOCKER:-sudo docker}"

EXTRA_ARGS=("$@")

container_env() {
  $DOCKER exec "$1" printenv "$2"
}

# Rede Docker do stack (ignora bridge default do container).
primary_stack_network() {
  local container="$1"
  $DOCKER inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{println $k}}{{end}}' "$container" \
    | grep -v '^bridge$' \
    | head -1
}

PROD_NET="$(primary_stack_network "$PROD_CONTAINER")"
STAGING_NET="$(primary_stack_network "$STAGING_CONTAINER")"
PROD_PW="$(container_env "$PROD_CONTAINER" POSTGRES_PASSWORD)"
STAGING_PW="$(container_env "$STAGING_CONTAINER" POSTGRES_PASSWORD)"

if [[ -z "$PROD_NET" || -z "$STAGING_NET" ]]; then
  echo "ERRO: não foi possível detectar redes Docker dos Postgres." >&2
  exit 1
fi

echo "Prod DB:    $PROD_CONTAINER (rede $PROD_NET)"
echo "Staging DB: $STAGING_CONTAINER (rede $STAGING_NET)"
echo "Repo:       $REPO_DIR"
echo

ARGS_QUOTED=""
for arg in "${EXTRA_ARGS[@]}"; do
  ARGS_QUOTED+=" $(printf '%q' "$arg")"
done

RUNNER="seed-villadora-$$"
cleanup() {
  $DOCKER rm -f "$RUNNER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Container efêmero nas duas redes Supabase (hostnames = nomes dos containers).
$DOCKER run -d --name "$RUNNER" --network "$PROD_NET" \
  -v "$REPO_DIR:/repo" -w /repo \
  python:3.12-slim sleep 600 >/dev/null

if [[ "$PROD_NET" != "$STAGING_NET" ]]; then
  $DOCKER network connect "$STAGING_NET" "$RUNNER" >/dev/null
fi

$DOCKER exec "$RUNNER" bash -c "pip install -q 'psycopg[binary]' && python scripts/seed_villadora_catalog_staging.py \
  --prod-database-url 'postgresql://postgres:${PROD_PW}@${PROD_CONTAINER}:5432/postgres' \
  --staging-database-url 'postgresql://postgres:${STAGING_PW}@${STAGING_CONTAINER}:5432/postgres' \
  --create-staging-user \
  --create-fake-inbox${ARGS_QUOTED}"
