# ChipSutra ↔ ChipSutra-VLSI-LLM sync

## Repos

| Repo | Role |
|------|------|
| [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) | **Canonical** Modelfiles, prompts, VERSION, fine-tune docs |
| ChipSutra (this repo) | **Vendored** `models/chipsutra-vlsi/` + `ollama-bootstrap.sh` for Compose |

## When you change the LLM

1. Edit **ChipSutra-VLSI-LLM** (`modelfiles/` SYSTEM text, `prompts/` RAG files, bump `VERSION`).
2. Tag upstream e.g. `v1.2.0`.
3. Sync into ChipSutra:
   - **Local:** `./scripts/sync-vlsi-llm.sh` or `.\scripts\sync-vlsi-llm.ps1`
   - **GitHub:** Actions → **Sync ChipSutra-VLSI modelfiles** → merge PR
4. Rebuild Ollama tags:
   - Compose `ollama-bootstrap` recreates when `VERSION` changes (or set `OLLAMA_FORCE_RECREATE=1`)
   - Native: `ollama create chipsutra-vlsi:3b -f models/chipsutra-vlsi/Modelfile.3b`

Synced RAG files: `vlsi_protocols_compact.txt`, `vlsi_soc_dft_power.txt`, `vlsi_verification_glossary.txt`, `covergroup_patterns.txt`.

## Compose

All compose files use **`ollama-bootstrap`**. Set in `.env` or shell:

```env
OLLAMA_MODEL=chipsutra-vlsi:7b
```

## Optional git submodule

```bash
git submodule add https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM.git external/ChipSutra-VLSI-LLM
CHIPSUTRA_VLSI_LLM_REPO=external/ChipSutra-VLSI-LLM ./scripts/sync-vlsi-llm.sh
```

Submodule is **optional**; vendored copy keeps single-repo clones simple.

See also: [LLM_ACCURACY.md](./LLM_ACCURACY.md), [ENHANCEMENTS.md](./ENHANCEMENTS.md).
