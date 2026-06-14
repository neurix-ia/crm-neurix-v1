#!/usr/bin/env bash
# Diagnóstico JWT staging — rode: bash scripts/check_jwt_staging.sh
set -euo pipefail

KONG="${KONG:-supabase-staging-319f-kong}"
CRM="${CRM:-crmneurix-crm-qhdg2z-backend-1}"

echo "=== Containers ==="
sudo docker ps --format '{{.Names}}' | grep -E 'staging-319f-kong|crm.*backend' || true

echo ""
echo "=== JWT_SECRET (staging Kong) ==="
JWT_SECRET="$(sudo docker exec "$KONG" sh -c 'echo "$JWT_SECRET"' 2>/dev/null || true)"
if [ -z "$JWT_SECRET" ]; then
  JWT_SECRET="$(sudo docker exec "$KONG" sh -c 'echo "$SUPABASE_JWT_SECRET"' 2>/dev/null || true)"
fi
if [ -z "$JWT_SECRET" ]; then
  echo "ERRO: JWT_SECRET nao encontrado em $KONG"
  exit 1
fi
echo "len=${#JWT_SECRET}  prefix=${JWT_SECRET:0:8}..."

echo ""
echo "=== Keys (prefixos) ==="
KONG_ANON="$(sudo docker exec "$KONG" sh -c 'echo "$SUPABASE_ANON_KEY"' 2>/dev/null || true)"
KONG_SR="$(sudo docker exec "$KONG" sh -c 'echo "$SUPABASE_SERVICE_ROLE_KEY"' 2>/dev/null || true)"
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

echo ""
echo "=== Assinatura JWT (CRM service_role vs JWT_SECRET do Kong) ==="
sudo docker exec -e JWT_SECRET="$JWT_SECRET" -e TOKEN="$CRM_SR" "$CRM" python <<'PY'
import os
import jwt

secret = os.environ.get("JWT_SECRET", "")
token = os.environ.get("TOKEN", "")
if not secret or not token:
    print("FALHA: JWT_SECRET ou TOKEN vazio")
    raise SystemExit(1)
try:
    jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
    print("OK: assinatura valida — keys batem com JWT_SECRET do Kong staging")
except Exception as exc:
    print("FALHA:", exc)
    print("-> Gere keys com: python3 scripts/generate_supabase_jwt_keys.py SEU_JWT_SECRET")
    print("-> Atualize Supabase staging E CRM staging com as mesmas keys e redeploy.")
PY

echo ""
echo "=== Teste PostgREST (service role) ==="
sudo docker exec "$CRM" python <<'PY'
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
