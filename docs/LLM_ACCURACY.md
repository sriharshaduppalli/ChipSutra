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
| Protocol/debug prompt appendix (**v1.2**) | ChipSutra-VLSI-LLM | **Shipped** — broad AMBA/fabrics/I/O/DFT/CDC/chiplet index in Modelfiles |
| **Keyword RAG** on `backend/knowledge/` | ChipSutra `rag.py` | **Shipped** — expanded protocol + SoC/DFT/glossary + UVM/SVA/debug |
| **RTL port parsing** before generate | ChipSutra `rtl_ports.py` | **Shipped** — ANSI + legacy headers → prompt |
| **Lint/sim feedback** on regenerate | ChipSutra `lint_feedback.py` | **Shipped** — `tool_log` + `prior_output` on `/api/generate/stream` |
| LoRA fine-tune on golden JSONL | ChipSutra-VLSI-LLM | [FINE_TUNING.md](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM/blob/master/docs/FINE_TUNING.md) |
| Golden DUT regression suite | ChipSutra tests | **Started** — counter + RAG/port tests |

Disable RAG: `RAG_ENABLED=false` in `backend/.env`.

### Closed-loop regenerate (API)

```json
{
  "project_id": "...",
  "module": "testbench",
  "tool_log": "%Error: ... Verilator output ...",
  "prior_output": "module tb; ...",
  "file_ids": ["..."]
}
```

Full strategy: **[ACCURACY_AND_KNOWLEDGE.md](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM/blob/master/docs/ACCURACY_AND_KNOWLEDGE.md)** in the LLM repo.

**Note:** Ollama Modelfiles do **not** auto-learn from user sessions. Continuous “learning” requires explicit datasets, RAG indexes, or fine-tune jobs. **Do not rebuild the base LLM** — improve RAG, RTL context, tool loop, then optional LoRA.
