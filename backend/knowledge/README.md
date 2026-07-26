# Backend knowledge index (RAG)

Text files here are chunked by `##` headings and injected into **Generate** prompts when `RAG_ENABLED=true` (default).

| File | Source |
|------|--------|
| `vlsi_protocols_compact.txt` | [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) `prompts/vlsi_protocols_compact.txt` |

Refresh after LLM repo updates:

```bash
./scripts/sync-vlsi-llm.sh
```

`golden/` holds small RTL fixtures for tests (not sent to RAG).
