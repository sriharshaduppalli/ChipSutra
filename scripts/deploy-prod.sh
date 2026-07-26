#!/usr/bin/env bash
# Idempotent production deploy, run ON the server (by CI or by hand).
#   ./scripts/deploy-prod.sh [git-ref]
set -euo pipefail

REF="${1:-main}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE="deploy/.env.prod"
API_URL="${PUBLIC_API_URL:-https://api.chipsutra.org}"

echo "==> Deploying ref '$REF' from $ROOT"

for required in "backend/.env" "$ENV_FILE" "deploy/Caddyfile"; do
  if [ ! -f "$required" ]; then
    echo "FATAL: missing $required (see deploy/README.md)" >&2
    exit 1
  fi
done

echo "==> Fetching source"
git fetch --all --prune
git checkout "$REF"
git pull --ff-only origin "$REF"
echo "    now at $(git rev-parse --short HEAD)"

echo "==> Building and starting containers"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build --remove-orphans

echo "==> Waiting for backend health"
for attempt in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1/api/health" >/dev/null 2>&1 \
     || docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T backend \
        curl -fsS http://127.0.0.1:8001/api/health >/dev/null 2>&1; then
    echo "    backend healthy after ${attempt} attempt(s)"
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "FATAL: backend did not become healthy; recent logs:" >&2
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" logs --tail 80 backend >&2
    exit 1
  fi
  sleep 10
done

echo "==> Pruning dangling images"
docker image prune -f >/dev/null || true

echo "==> Smoke test"
bash scripts/prod-smoke.sh "$API_URL" || {
  echo "FATAL: smoke test failed after deploy" >&2
  exit 1
}

echo "==> Deploy complete: $(git rev-parse --short HEAD)"
