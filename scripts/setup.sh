#!/usr/bin/env bash
# ChipSutra setup — bootstrap + Docker check + optional compose
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
INSTALL_DEPS=false
START=false
for arg in "$@"; do
  case "$arg" in
    --install-deps) INSTALL_DEPS=true ;;
    --start) START=true ;;
  esac
done

"$ROOT/scripts/bootstrap.sh"

if ! command -v docker >/dev/null 2>&1; then
  echo "[chipsutra] Docker not found."
  if $INSTALL_DEPS; then
    echo "Install Docker: https://docs.docker.com/get-docker/"
    if command -v apt-get >/dev/null; then
      echo "  sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin"
    elif command -v brew >/dev/null; then
      echo "  brew install --cask docker"
    fi
  else
    echo "Re-run: ./scripts/setup.sh --install-deps"
  fi
  exit 0
fi

if ! docker info >/dev/null 2>&1; then
  echo "[chipsutra] Start the Docker daemon, then: docker compose up --build"
  exit 0
fi

echo "[chipsutra] Docker OK."
if $START; then
  docker compose up --build
else
  echo "Next: ./scripts/setup.sh --start"
fi
