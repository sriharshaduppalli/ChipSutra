#!/usr/bin/env bash
# Quick open-source readiness checks (no Docker / no live API required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/5] docker compose syntax..."
docker compose config --quiet
docker compose -f docker-compose.atlas.yml config --quiet
docker compose -f docker-compose.backend-verilator.yml config --quiet
docker compose -f docker-compose.prod.yml --env-file deploy/env.prod.example config --quiet

echo "[2/5] backend OSS requirements install..."
pip install -q -r backend/requirements-oss.txt

echo "[3/5] pytest offline (compose, env, llm_provider, rag)..."
cd backend
pytest tests/test_iteration_5.py tests/test_rag_and_golden.py -n 0 \
  -k "docker_compose or env_example or requirements or readme or available_providers or stream_chat or rag or golden"

echo "[4/5] modelfiles..."
test -f ../models/chipsutra-vlsi/Modelfile.3b

echo "[5/5] production templates..."
test -f ../docker-compose.prod.yml
test -f ../backend/.env.production.example
test -f ../deploy/Caddyfile
test -f ../models/chipsutra-vlsi/ollama-bootstrap.sh
test -f ../models/chipsutra-vlsi/VERSION

echo "OK — community validation passed."
