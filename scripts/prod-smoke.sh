#!/usr/bin/env bash
# Post-deploy smoke checks. Usage: ./scripts/prod-smoke.sh https://api.chipsutra.org
set -euo pipefail

API="${1:-https://api.chipsutra.org}"
API="${API%/}"

echo "==> Health: $API/api/health"
body="$(curl -fsS "$API/api/health")"
echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('status')=='healthy', d; print('  status:', d['status']); print('  verilator:', d.get('verilator')); print('  storage:', d.get('storage'))"

if echo "$body" | grep -q '"verilator": true'; then
  echo "  OK verilator"
else
  echo "  WARN: verilator not true (sim will be mock)"
fi

APP="${2:-https://chipsutra.org}"
echo "==> Frontend: $APP"
code="$(curl -fsS -o /dev/null -w '%{http_code}' "$APP/")"
test "$code" = "200" && echo "  OK HTTP $code" || { echo "  FAIL HTTP $code"; exit 1; }

echo "==> All automated smoke checks passed."
