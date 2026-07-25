#!/usr/bin/env bash
# Quick open-source readiness checks (no Docker / no live API required).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/4] docker compose syntax..."
docker compose config --quiet

echo "[2/4] backend OSS requirements install..."
pip install -q -r backend/requirements-oss.txt

echo "[3/4] pytest offline (compose, env, llm_provider)..."
cd backend
pytest tests/test_iteration_5.py -n 0 \
  -k "docker_compose or env_example or requirements or readme or available_providers or stream_chat"

echo "[4/4] modelfiles..."
test -f ../models/chipsutra-vlsi/Modelfile.3b

echo "OK — community validation passed."
