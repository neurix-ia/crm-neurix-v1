#!/usr/bin/env bash
# Diagnóstico rápido do backend CRM staging na VPS (rode como augusto).
# Uso: bash scripts/diag_staging_backend.sh
set -euo pipefail

BACKEND="${BACKEND:-crmneurix-crm-qhdg2z-backend-1}"

echo "=== Container: $BACKEND ==="
if ! sudo docker ps --format '{{.Names}}' | grep -qx "$BACKEND"; then
  echo "Container não encontrado. Liste: sudo docker ps --format '{{.Names}}' | grep crm"
  exit 1
fi

echo ""
echo "=== Env Supabase (prefixos) ==="
sudo docker exec "$BACKEND" printenv SUPABASE_URL || true
SR="$(sudo docker exec "$BACKEND" printenv SUPABASE_SERVICE_ROLE_KEY 2>/dev/null || true)"
AN="$(sudo docker exec "$BACKEND" printenv SUPABASE_ANON_KEY 2>/dev/null || true)"
echo "SERVICE_ROLE_KEY: ${SR:0:30}... (len=${#SR})"
echo "ANON_KEY:         ${AN:0:30}... (len=${#AN})"

echo ""
echo "=== Teste PostgREST via Python (service role) ==="
sudo docker exec "$BACKEND" python -c "
from app.config import get_settings
from supabase import create_client

s = get_settings()
key = s.SUPABASE_SERVICE_ROLE_KEY or s.SUPABASE_ANON_KEY
print('key_mode:', 'service_role' if s.SUPABASE_SERVICE_ROLE_KEY else 'anon_fallback')
print('url:', s.SUPABASE_URL)
c = create_client(s.SUPABASE_URL, key)
for table, cols in [
    ('products', 'id'),
    ('profiles', 'id,is_superadmin,organization_id,role'),
    ('organization_members', 'organization_id,role'),
]:
    try:
        r = c.table(table).select(cols).limit(1).execute()
        print(f'OK {table}:', r.data)
    except Exception as e:
        print(f'ERR {table}:', type(e).__name__, e)
"

echo ""
echo "=== Últimos logs do backend ==="
sudo docker logs "$BACKEND" --tail 40 2>&1

echo ""
echo "=== HTTP /api/health/db (se deploy recente) ==="
curl -sS "https://crm-staging.wbtech.dev/api/health/db" || true
echo ""
