#!/bin/sh
# Pull Qwen base + create ChipSutra-VLSI tag. Used by Docker Compose (models/chipsutra-vlsi mount).
# Recreates the tag when mounted VERSION differs from last bootstrap (Modelfile upgrades).
set -eu

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
export OLLAMA_HOST

MODEL="${OLLAMA_MODEL:-chipsutra-vlsi:3b}"
DIR="${MODELFILE_DIR:-/modelfiles}"
FORCE="${OLLAMA_FORCE_RECREATE:-0}"
MARKER="/root/.ollama/chipsutra-vlsi.bootstrap-version"

case "$MODEL" in
  *1.5b*) BASE="qwen2.5-coder:1.5b"; MF="Modelfile.1.5b" ;;
  *7b*)   BASE="qwen2.5-coder:7b";   MF="Modelfile.7b" ;;
  *)      BASE="qwen2.5-coder:3b";   MF="Modelfile.3b" ;;
esac

WANT_VER="unknown"
if [ -f "$DIR/VERSION" ]; then
  WANT_VER="$(tr -d '[:space:]' < "$DIR/VERSION")"
fi

HAVE_VER=""
if [ -f "$MARKER" ]; then
  HAVE_VER="$(tr -d '[:space:]' < "$MARKER")"
fi

echo "[chipsutra-vlsi] target=$MODEL base=$BASE modelfile=$MF version=$WANT_VER"

NEED_CREATE=0
if [ "$FORCE" = "1" ] || [ "$FORCE" = "true" ]; then
  echo "[chipsutra-vlsi] OLLAMA_FORCE_RECREATE set — rebuilding"
  NEED_CREATE=1
elif ! ollama show "$MODEL" >/dev/null 2>&1; then
  NEED_CREATE=1
elif [ -n "$WANT_VER" ] && [ "$WANT_VER" != "unknown" ] && [ "$WANT_VER" != "$HAVE_VER" ]; then
  echo "[chipsutra-vlsi] VERSION changed ($HAVE_VER -> $WANT_VER) — recreating $MODEL"
  NEED_CREATE=1
else
  echo "[chipsutra-vlsi] $MODEL already present (VERSION=$HAVE_VER)"
  exit 0
fi

echo "[chipsutra-vlsi] pulling $BASE ..."
ollama pull "$BASE"

if [ ! -f "$DIR/$MF" ]; then
  echo "[chipsutra-vlsi] ERROR: missing $DIR/$MF" >&2
  exit 1
fi

echo "[chipsutra-vlsi] creating $MODEL from $MF ..."
ollama create "$MODEL" -f "$DIR/$MF"
mkdir -p "$(dirname "$MARKER")"
echo "$WANT_VER" > "$MARKER"
echo "[chipsutra-vlsi] ready: $MODEL (VERSION=$WANT_VER)"
