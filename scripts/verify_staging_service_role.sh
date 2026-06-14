#!/usr/bin/env bash
# Compara SERVICE_ROLE_KEY do backend CRM staging com a stack Supabase staging.
# Rode no servidor (Hostinger): bash scripts/verify_staging_service_role.sh
set -euo pipefail

CRM_BACKEND="${CRM_BACKEND:-crmneurix-crm-qhdg2z-backend-1}"
SUPABASE_KONG="${SUPABASE_KONG:-supabase-staging-319f-kong}"

prefix() {
  local v="$1"
  if [[ -z "$v" ]]; then
    echo "(vazio)"
  else
    echo "${v:0:24}... (len=${#v})"
  fi
}

echo "=== CRM backend ($CRM_BACKEND) ==="
CRM_SR="$(sudo docker exec "$CRM_BACKEND" printenv SUPABASE_SERVICE_ROLE_KEY 2>/dev/null || true)"
CRM_ANON="$(sudo docker exec "$CRM_BACKEND" printenv SUPABASE_ANON_KEY 2>/dev/null || true)"
CRM_URL="$(sudo docker exec "$CRM_BACKEND" printenv SUPABASE_URL 2>/dev/null || true)"
echo "SUPABASE_URL=$CRM_URL"
echo "SUPABASE_ANON_KEY=$(prefix "$CRM_ANON")"
echo "SUPABASE_SERVICE_ROLE_KEY=$(prefix "$CRM_SR")"

echo ""
echo "=== Supabase Kong ($SUPABASE_KONG) ==="
KONG_SR="$(sudo docker exec "$SUPABASE_KONG" printenv SERVICE_ROLE_KEY 2>/dev/null || true)"
KONG_ANON="$(sudo docker exec "$SUPABASE_KONG" printenv ANON_KEY 2>/dev/null || true)"
echo "ANON_KEY=$(prefix "$KONG_ANON")"
echo "SERVICE_ROLE_KEY=$(prefix "$KONG_SR")"

echo ""
if [[ -n "$CRM_SR" && -n "$KONG_SR" && "$CRM_SR" == "$KONG_SR" ]]; then
  echo "OK: SERVICE_ROLE_KEY do CRM == Kong staging"
else
  echo "ERRO: SERVICE_ROLE_KEY do CRM difere do Supabase staging."
  echo "Corrija no Dokploy (app neurix-crm-staging) e redeploy o backend."
fi

echo ""
echo "=== Probe HTTP /api/health/db ==="
curl -fsS "https://crm-staging.wbtech.dev/api/health/db" || true
echo ""
