# LLM accuracy & knowledge (ChipSutra app)

ChipSutra-VLSI runs **locally via Ollama**. Accuracy comes from:

1. **Modelfile + prompts** — [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) (`VERSION` synced to `models/chipsutra-vlsi/VERSION`)
2. **Module prompts** in `backend/server.py` (testbench, SVA, debug, …)
3. **User context** — uploaded RTL, specs, logs (always prefer over model memory)

## Sync workflow

See [docs/LLM_SYNC.md](./LLM_SYNC.md).

## Improving accuracy (roadmap)

| Approach | Owner repo | Status |
|----------|------------|--------|
| Protocol/debug prompt appendix (v1.1) | ChipSutra-VLSI-LLM | Shipped in Modelfiles |
| **Keyword RAG** on `backend/knowledge/` | ChipSutra `rag.py` | **Shipped** — `/api/health` → `rag` |
| RTL port parsing before generate | ChipSutra backend | Planned |
| LoRA fine-tune on golden JSONL | ChipSutra-VLSI-LLM | [FINE_TUNING.md](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM/blob/master/docs/FINE_TUNING.md) |
| Golden DUT regression suite | ChipSutra tests | **Started** — `test_rag_and_golden.py`, `knowledge/golden/counter.sv` |

Disable RAG: `RAG_ENABLED=false` in `backend/.env`.

Full strategy (knowledge graphs vs RAG vs training):  
**[ACCURACY_AND_KNOWLEDGE.md](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM/blob/master/docs/ACCURACY_AND_KNOWLEDGE.md)** in the LLM repo.

**Note:** Ollama Modelfiles do **not** auto-learn from user sessions. Continuous “learning” requires explicit datasets, RAG indexes, or fine-tune jobs.
