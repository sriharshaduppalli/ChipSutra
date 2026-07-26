# ChipSutra-VLSI Ollama models (synced)

Canonical source: **[ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM)**  
**Version:** see `VERSION` (must match upstream release).

## Sync from upstream

```bash
./scripts/sync-vlsi-llm.sh
# or local clone:
CHIPSUTRA_VLSI_LLM_REPO=../ChipSutra-VLSI-LLM ./scripts/sync-vlsi-llm.sh
```

Windows: `.\scripts\sync-vlsi-llm.ps1`

GitHub: Actions → **Sync ChipSutra-VLSI modelfiles** (opens a PR).

## Docker / Compose

`ollama-bootstrap.sh` reads **`OLLAMA_MODEL`** and picks the Modelfile:

| `OLLAMA_MODEL` | Base pull | Modelfile |
|----------------|-----------|-----------|
| `chipsutra-vlsi:1.5b` | qwen2.5-coder:1.5b | Modelfile.1.5b |
| `chipsutra-vlsi:3b` (default) | qwen2.5-coder:3b | Modelfile.3b |
| `chipsutra-vlsi:7b` | qwen2.5-coder:7b | Modelfile.7b |

After changing Modelfiles, recreate the tag:

```bash
ollama create chipsutra-vlsi:3b -f models/chipsutra-vlsi/Modelfile.3b
```

## Accuracy / knowledge

Prompt-only improvements live in the LLM repo. ChipSutra app-level RAG and tool use: [docs/LLM_ACCURACY.md](../docs/LLM_ACCURACY.md).
