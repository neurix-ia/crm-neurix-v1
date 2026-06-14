#!/usr/bin/env bash
# Diagnóstico JWT staging — rode: bash scripts/check_jwt_staging.sh
set -euo pipefail

KONG="${KONG:-supabase-staging-319f-kong}"
CRM="${CRM:-crmneurix-crm-qhdg2z-backend-1}"

get_env() {
  local container="$1"
  local var="$2"
  sudo docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | sed -n "s/^${var}=//p" | head -n1
}

echo "=== Containers staging ==="
sudo docker ps --format '{{.Names}}' | grep -E 'supabase-staging|crmneurix-crm-qhdg2z-backend' || true

echo ""
echo "=== JWT_SECRET ==="
JWT_SECRET=""
JWT_CONTAINER=""
JWT_VAR=""
for container in $(sudo docker ps --format '{{.Names}}' | grep 'supabase-staging' || true); do
  for var in JWT_SECRET SUPABASE_JWT_SECRET GOTRUE_JWT_SECRET PGRST_JWT_SECRET; do
    val="$(get_env "$container" "$var")"
    if [ -n "$val" ]; then
      JWT_SECRET="$val"
      JWT_CONTAINER="$container"
      JWT_VAR="$var"
      break 2
    fi
  done
done

if [ -n "$JWT_SECRET" ]; then
  echo "encontrado: container=$JWT_CONTAINER var=$JWT_VAR"
  echo "len=${#JWT_SECRET}  prefix=${JWT_SECRET:0:8}..."
else
  echo "AVISO: JWT_SECRET nao esta nos containers (comum: so no Dokploy)."
  echo "Abra Dokploy -> stack Supabase staging -> Environment -> JWT_SECRET"
  echo ""
  echo "Containers supabase-staging:"
  sudo docker ps --format '{{.Names}}' | grep supabase-staging || true
fi

echo ""
echo "=== Keys (prefixos) ==="
KONG_ANON="$(get_env "$KONG" SUPABASE_ANON_KEY)"
[ -z "$KONG_ANON" ] && KONG_ANON="$(get_env "$KONG" ANON_KEY)"
KONG_SR="$(get_env "$KONG" SUPABASE_SERVICE_ROLE_KEY)"
[ -z "$KONG_SR" ] && KONG_SR="$(get_env "$KONG" SERVICE_ROLE_KEY)"
if [ -z "$KONG_SR" ]; then
  for c in supabase-staging-319f-auth supabase-staging-319f-rest; do
    KONG_SR="$(get_env "$c" SUPABASE_SERVICE_ROLE_KEY)"
    [ -z "$KONG_SR" ] && KONG_SR="$(get_env "$c" SERVICE_ROLE_KEY)"
    [ -n "$KONG_SR" ] && break
  done
fi
CRM_ANON="$(sudo docker exec "$CRM" printenv SUPABASE_ANON_KEY 2>/dev/null || true)"
CRM_SR="$(sudo docker exec "$CRM" printenv SUPABASE_SERVICE_ROLE_KEY 2>/dev/null || true)"

echo "Kong ANON:            ${KONG_ANON:0:36}... (len=${#KONG_ANON})"
echo "Kong SERVICE_ROLE:    ${KONG_SR:0:36}... (len=${#KONG_SR})"
echo "CRM  ANON:            ${CRM_ANON:0:36}... (len=${#CRM_ANON})"
echo "CRM  SERVICE_ROLE:    ${CRM_SR:0:36}... (len=${#CRM_SR})"
echo "Header esperado:      eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

echo ""
echo "=== Iguais? ==="
[ "$KONG_SR" = "$CRM_SR" ] && echo "Kong SR == CRM SR: SIM" || echo "Kong SR == CRM SR: NAO"
[ "$KONG_ANON" = "$CRM_ANON" ] && echo "Kong ANON == CRM ANON: SIM" || echo "Kong ANON == CRM ANON: NAO"

if [ -n "$JWT_SECRET" ] && [ -n "$CRM_SR" ]; then
  echo ""
  echo "=== Assinatura JWT ==="
  sudo docker exec -i -e JWT_SECRET="$JWT_SECRET" -e CRM_SR="$CRM_SR" "$CRM" python <<'PY'
import os
import jwt

secret = os.environ.get("JWT_SECRET", "")
token = os.environ.get("CRM_SR", "")
try:
    jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
    print("OK: assinatura valida")
except Exception as exc:
    print("FALHA:", exc)
PY
fi

echo ""
echo "=== Teste PostgREST ==="
sudo docker exec -i "$CRM" python <<'PY'
from app.config import get_settings
from supabase import create_client

s = get_settings()
c = create_client(s.SUPABASE_URL, s.SUPABASE_SERVICE_ROLE_KEY)
try:
    r = c.table("products").select("id").limit(1).execute()
    print("OK products:", r.data)
except Exception as exc:
    print("ERR:", type(exc).__name__, exc)
PY

echo ""
echo "=== Se FALHA / ERR ==="
echo "1. Dokploy -> Supabase staging -> copie JWT_SECRET"
echo "2. python3 scripts/generate_supabase_jwt_keys.py 'JWT_SECRET'"
echo "3. Cole ANON + SERVICE_ROLE no Supabase staging E no CRM staging"
echo "4. Redeploy Supabase staging, depois CRM backend"
