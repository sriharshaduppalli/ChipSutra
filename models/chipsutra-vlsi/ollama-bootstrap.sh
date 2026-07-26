#!/bin/sh
# Pull Qwen base + create ChipSutra-VLSI tag. Used by Docker Compose (models/chipsutra-vlsi mount).
set -eu

OLLAMA_HOST="${OLLAMA_HOST:-http://ollama:11434}"
export OLLAMA_HOST

MODEL="${OLLAMA_MODEL:-chipsutra-vlsi:3b}"
DIR="${MODELFILE_DIR:-/modelfiles}"

case "$MODEL" in
  *1.5b*) BASE="qwen2.5-coder:1.5b"; MF="Modelfile.1.5b" ;;
  *7b*)   BASE="qwen2.5-coder:7b";   MF="Modelfile.7b" ;;
  *)      BASE="qwen2.5-coder:3b";   MF="Modelfile.3b" ;;
esac

echo "[chipsutra-vlsi] target=$MODEL base=$BASE modelfile=$MF"

if ollama show "$MODEL" >/dev/null 2>&1; then
  echo "[chipsutra-vlsi] $MODEL already present"
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
echo "[chipsutra-vlsi] ready: $MODEL (see $DIR/VERSION)"
