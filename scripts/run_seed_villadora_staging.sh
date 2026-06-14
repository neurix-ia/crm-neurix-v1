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

container_ip() {
  $DOCKER inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' "$1" | awk '{print $1}'
}

container_env() {
  $DOCKER exec "$1" printenv "$2"
}

PROD_IP="$(container_ip "$PROD_CONTAINER")"
STAGING_IP="$(container_ip "$STAGING_CONTAINER")"
PROD_PW="$(container_env "$PROD_CONTAINER" POSTGRES_PASSWORD)"
STAGING_PW="$(container_env "$STAGING_CONTAINER" POSTGRES_PASSWORD)"

if [[ -z "$PROD_IP" || -z "$STAGING_IP" ]]; then
  echo "ERRO: não foi possível obter IP dos containers Postgres." >&2
  exit 1
fi

echo "Prod DB:    $PROD_CONTAINER ($PROD_IP)"
echo "Staging DB: $STAGING_CONTAINER ($STAGING_IP)"
echo "Repo:       $REPO_DIR"
echo

ARGS_QUOTED=""
for arg in "${EXTRA_ARGS[@]}"; do
  ARGS_QUOTED+=" $(printf '%q' "$arg")"
done

# Com --network host o container enxerga os IPs dos Postgres no host Linux.
$DOCKER run --rm \
  --network host \
  -v "$REPO_DIR:/repo" \
  -w /repo \
  python:3.12-slim \
  bash -c "pip install -q 'psycopg[binary]' && python scripts/seed_villadora_catalog_staging.py \
    --prod-database-url 'postgresql://postgres:${PROD_PW}@${PROD_IP}:5432/postgres' \
    --staging-database-url 'postgresql://postgres:${STAGING_PW}@${STAGING_IP}:5432/postgres' \
    --create-staging-user \
    --create-fake-inbox${ARGS_QUOTED}"
