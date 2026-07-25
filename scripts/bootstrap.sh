#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -f backend/.env ]]; then
  cp backend/.env.example backend/.env
  echo "[chipsutra] Created backend/.env — set JWT_SECRET and ADMIN_PASSWORD before a public deploy."
else
  echo "[chipsutra] backend/.env already exists."
fi
echo "Next: docker compose up --build"
