# Sync vendored Modelfiles from ChipSutra-VLSI-LLM (canonical repo).
# Usage:
#   ./scripts/sync-vlsi-llm.sh
#   ./scripts/sync-vlsi-llm.sh /path/to/ChipSutra-VLSI-LLM
#
# Or set CHIPSUTRA_VLSI_LLM_REPO to a local clone.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/models/chipsutra-vlsi"
SRC="${1:-${CHIPSUTRA_VLSI_LLM_REPO:-}}"

if [ -z "$SRC" ]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  git clone --depth 1 https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM.git "$TMP/llm"
  SRC="$TMP/llm"
  echo "[sync] cloned upstream into temp dir"
fi

if [ ! -d "$SRC/modelfiles" ]; then
  echo "ERROR: $SRC/modelfiles not found" >&2
  exit 1
fi

cp "$SRC/modelfiles/Modelfile."* "$DEST/"
if [ -f "$SRC/VERSION" ]; then
  cp "$SRC/VERSION" "$DEST/VERSION"
fi
KNOW="$ROOT/backend/knowledge"
mkdir -p "$KNOW"
if [ -f "$SRC/prompts/vlsi_protocols_compact.txt" ]; then
  cp "$SRC/prompts/vlsi_protocols_compact.txt" "$KNOW/vlsi_protocols_compact.txt"
  echo "[sync] updated $KNOW/vlsi_protocols_compact.txt"
fi
# Keep bootstrap script in ChipSutra (not overwritten)
echo "[sync] updated $DEST from $SRC"
echo "[sync] VERSION=$(cat "$DEST/VERSION" 2>/dev/null || echo unknown)"
echo "[sync] commit both repos if you changed Modelfiles upstream."
