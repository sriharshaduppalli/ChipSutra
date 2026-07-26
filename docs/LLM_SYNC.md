# ChipSutra ↔ ChipSutra-VLSI-LLM sync

## Repos

| Repo | Role |
|------|------|
| [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) | **Canonical** Modelfiles, prompts, VERSION, fine-tune docs |
| ChipSutra (this repo) | **Vendored** `models/chipsutra-vlsi/` + `ollama-bootstrap.sh` for Compose |

## When you change the LLM

1. Edit **ChipSutra-VLSI-LLM** (`modelfiles/`, `prompts/`, bump `VERSION`).
2. Tag upstream e.g. `v1.1.0`.
3. Sync into ChipSutra:
   - **Local:** `./scripts/sync-vlsi-llm.sh` or `.\scripts\sync-vlsi-llm.ps1`
   - **GitHub:** Actions → **Sync ChipSutra-VLSI modelfiles** → merge PR
4. Rebuild Ollama tags on servers (`ollama create …`) or redeploy Compose (bootstrap skips if tag exists — delete tag to force recreate).

## Compose

All compose files use **`ollama-bootstrap`** (not separate pull/create). Set in `.env` or shell:

```env
OLLAMA_MODEL=chipsutra-vlsi:7b
```

## Optional git submodule

For developers who want both repos fixed at a commit:

```bash
git submodule add https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM.git external/ChipSutra-VLSI-LLM
CHIPSUTRA_VLSI_LLM_REPO=external/ChipSutra-VLSI-LLM ./scripts/sync-vlsi-llm.sh
```

Submodule is **optional**; vendored copy keeps single-repo clones simple.
