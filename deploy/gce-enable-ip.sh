#!/bin/bash
set -euo pipefail
ROOT=/opt/chipsutra
IP=34.47.145.101
ORIGIN="http://${IP}"

cp "$ROOT/deploy/Caddyfile.ip" "$ROOT/deploy/Caddyfile"

cat > "$ROOT/deploy/.env.prod" <<EOF
PUBLIC_API_URL=${ORIGIN}
PUBLIC_APP_URL=${ORIGIN}
PUBLIC_APP_HOST=${IP}
PUBLIC_API_HOST=${IP}
ACME_EMAIL=ops@chipsutra.ai
OLLAMA_MODEL=chipsutra-vlsi:3b
OLLAMA_BASE_MODEL=qwen2.5-coder:3b
SHOW_CLOUD_MODELS=false
EOF

python3 - <<PY
from pathlib import Path
p = Path("$ROOT/backend/.env")
lines = []
for l in p.read_text().splitlines():
    if l.startswith("CORS_ORIGINS="):
        lines.append("CORS_ORIGINS=${ORIGIN}")
    elif l.startswith("FRONTEND_URL="):
        lines.append("FRONTEND_URL=${ORIGIN}")
    else:
        lines.append(l)
p.write_text("\n".join(lines) + "\n")
print("CORS/FRONTEND_URL -> ${ORIGIN}")
PY

# Give Ollama a moment on next bootstrap
if ! grep -q OLLAMA_HOST "$ROOT/docker-compose.prod.yml"; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/opt/chipsutra/docker-compose.prod.yml")
t = p.read_text()
old = """    environment:
      OLLAMA_MODEL: ${OLLAMA_MODEL:-chipsutra-vlsi:3b}
    entrypoint: ["/bin/sh", "/modelfiles/ollama-bootstrap.sh"]
"""
new = """    environment:
      OLLAMA_MODEL: ${OLLAMA_MODEL:-chipsutra-vlsi:3b}
      OLLAMA_HOST: http://ollama:11434
    entrypoint: ["/bin/sh", "-c", "sleep 8; exec /bin/sh /modelfiles/ollama-bootstrap.sh"]
"""
if old not in t:
    raise SystemExit("compose snippet not found")
p.write_text(t.replace(old, new, 1))
print("patched ollama-bootstrap wait")
PY
fi

cd "$ROOT"
echo "==> compose build/up (long: frontend + 3B pull)"
docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod up -d --build
echo "==> done"
docker compose -f docker-compose.prod.yml --env-file deploy/.env.prod ps
curl -sS -o /dev/null -w "frontend %{http_code}\n" "http://127.0.0.1/" || true
curl -sS -o /dev/null -w "health %{http_code}\n" "http://127.0.0.1/api/health" || true
