#!/bin/bash
set -euo pipefail
ENV=/opt/chipsutra/backend/.env
test -f "$ENV"

echo "--- mongo host ---"
grep '^MONGO_URL=' "$ENV" | sed -E 's#mongodb\+srv://[^@]+@#mongodb+srv://***@#'

if grep -q 'JWT_SECRET=REPLACE_WITH' "$ENV"; then
  JWT=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  python3 - "$ENV" "$JWT" <<'PY'
from pathlib import Path
import sys
p, jwt = Path(sys.argv[1]), sys.argv[2]
lines = [("JWT_SECRET=" + jwt) if l.startswith("JWT_SECRET=") else l for l in p.read_text().splitlines()]
p.write_text("\n".join(lines) + "\n")
print("JWT_SECRET set")
PY
else
  echo "JWT_SECRET already set"
fi

if grep -q 'ADMIN_PASSWORD=REPLACE_WITH' "$ENV"; then
  ADMIN=$(python3 -c 'import secrets,string; a=string.ascii_letters+string.digits; print("".join(secrets.choice(a) for _ in range(20)))')
  python3 - "$ENV" "$ADMIN" <<'PY'
from pathlib import Path
import sys
p, pw = Path(sys.argv[1]), sys.argv[2]
lines = [("ADMIN_PASSWORD=" + pw) if l.startswith("ADMIN_PASSWORD=") else l for l in p.read_text().splitlines()]
p.write_text("\n".join(lines) + "\n")
print("ADMIN_PASSWORD set")
PY
  echo "ADMIN_PASSWORD_GENERATED=$ADMIN"
else
  echo "ADMIN_PASSWORD already set"
fi

python3 - "$ENV" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = [("OLLAMA_MODEL=chipsutra-vlsi:3b" if l.startswith("OLLAMA_MODEL=") else l) for l in p.read_text().splitlines()]
p.write_text("\n".join(lines) + "\n")
print("OLLAMA_MODEL=chipsutra-vlsi:3b")
PY

cp /opt/chipsutra/deploy/env.prod.example /opt/chipsutra/deploy/.env.prod
cp /opt/chipsutra/deploy/Caddyfile.example /opt/chipsutra/deploy/Caddyfile
echo "--- keys ---"
grep -E '^[A-Z_]+=' "$ENV" | sed -E 's/=.*/=***/'
ls -l /opt/chipsutra/deploy/.env.prod /opt/chipsutra/deploy/Caddyfile
