#!/usr/bin/env bash
# Compara SERVICE_ROLE_KEY do backend CRM staging com a stack Supabase staging.
# Rode no servidor: bash scripts/verify_staging_service_role.sh
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

jwt_header_ok() {
  local jwt="$1"
  local hdr
  hdr="$(printf '%s' "$jwt" | cut -d. -f1 | tr '_-' '/+' | awk '{ while (length($0) % 4) $0 = $0 "="; print }' | base64 -d 2>/dev/null || true)"
  [[ "$hdr" == *'"alg"'* && "$hdr" == *'"typ"'* ]]
}

env_from_container() {
  local name="$1"
  shift
  local var
  for var in "$@"; do
    local val
    val="$(sudo docker inspect "$name" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
      | sed -n "s/^${var}=//p" | head -n1)"
    if [[ -n "$val" ]]; then
      printf '%s' "$val"
      return 0
    fi
  done
  printf ''
}

echo "=== CRM backend ($CRM_BACKEND) ==="
CRM_SR="$(sudo docker exec "$CRM_BACKEND" printenv SUPABASE_SERVICE_ROLE_KEY 2>/dev/null || true)"
CRM_ANON="$(sudo docker exec "$CRM_BACKEND" printenv SUPABASE_ANON_KEY 2>/dev/null || true)"
CRM_URL="$(sudo docker exec "$CRM_BACKEND" printenv SUPABASE_URL 2>/dev/null || true)"
echo "SUPABASE_URL=$CRM_URL"
echo "SUPABASE_ANON_KEY=$(prefix "$CRM_ANON")"
echo "SUPABASE_SERVICE_ROLE_KEY=$(prefix "$CRM_SR")"
if [[ -n "$CRM_SR" ]]; then
  jwt_header_ok "$CRM_SR" && echo "CRM service_role JWT header: OK" || echo "CRM service_role JWT header: INVALIDO"
fi
if [[ -n "$CRM_ANON" ]]; then
  jwt_header_ok "$CRM_ANON" && echo "CRM anon JWT header: OK" || echo "CRM anon JWT header: INVALIDO"
fi

echo ""
echo "=== Supabase Kong ($SUPABASE_KONG) ==="
KONG_SR="$(env_from_container "$SUPABASE_KONG" SERVICE_ROLE_KEY SUPABASE_SERVICE_ROLE_KEY)"
KONG_ANON="$(env_from_container "$SUPABASE_KONG" ANON_KEY SUPABASE_ANON_KEY)"
KONG_JWT="$(env_from_container "$SUPABASE_KONG" JWT_SECRET SUPABASE_JWT_SECRET)"
echo "ANON_KEY=$(prefix "$KONG_ANON")"
echo "SERVICE_ROLE_KEY=$(prefix "$KONG_SR")"
echo "JWT_SECRET=$(prefix "$KONG_JWT")"
if [[ -n "$KONG_SR" ]]; then
  jwt_header_ok "$KONG_SR" && echo "Kong service_role JWT header: OK" || echo "Kong service_role JWT header: INVALIDO"
fi
if [[ -n "$KONG_ANON" ]]; then
  jwt_header_ok "$KONG_ANON" && echo "Kong anon JWT header: OK" || echo "Kong anon JWT header: INVALIDO"
fi

echo ""
echo "Header esperado (inicio): eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
if [[ -n "$KONG_ANON" ]]; then
  echo "Header Kong anon (inicio):  ${KONG_ANON:0:36}"
fi

echo ""
if [[ -n "$CRM_SR" && -n "$KONG_SR" && "$CRM_SR" == "$KONG_SR" ]]; then
  echo "OK: SERVICE_ROLE_KEY do CRM == Kong staging"
elif [[ -z "$KONG_SR" ]]; then
  echo "AVISO: SERVICE_ROLE_KEY nao encontrada no Kong."
  echo "Liste env da stack Supabase staging:"
  echo "  sudo docker inspect $SUPABASE_KONG --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -E 'ANON|SERVICE|JWT'"
else
  echo "ERRO: SERVICE_ROLE_KEY do CRM difere do Supabase staging."
  echo "Corrija no Dokploy (app neurix-crm-staging) e redeploy o backend."
fi

echo ""
echo "=== Probe HTTP /api/health/db (apos redeploy) ==="
curl -sS "https://crm-staging.wbtech.dev/api/health/db" || true
echo ""
