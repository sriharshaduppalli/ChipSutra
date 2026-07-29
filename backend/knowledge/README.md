# Backend knowledge index (RAG)

Text files here are chunked by `##` headings and injected into **Generate** prompts when `RAG_ENABLED=true` (default).

| File | Source |
|------|--------|
| `vlsi_protocols_compact.txt` | ChipSutra-VLSI-LLM `prompts/` (v1.2+ multi-protocol) |
| `vlsi_soc_dft_power.txt` | ChipSutra-VLSI-LLM — SoC / DFT / UPF / CDC |
| `vlsi_verification_glossary.txt` | ChipSutra-VLSI-LLM — DV/HDL glossary |
| `uvm_patterns.txt` | ChipSutra — UVM / SV TB patterns |
| `sva_patterns.txt` | ChipSutra — SVA patterns |
| `sim_debug_playbook.txt` | ChipSutra — sim triage |
| `covergroup_patterns.txt` | ChipSutra-VLSI-LLM `prompts/` (synced) — bins/cross/closure |

`vlsi_system.txt` (if present) is **ignored by RAG** — SYSTEM text lives inline in Modelfiles.

Refresh LLM-owned files after upstream updates:

```bash
./scripts/sync-vlsi-llm.sh
# or: .\scripts\sync-vlsi-llm.ps1 -SourceRepo <path-to-ChipSutra-VLSI-LLM>
```

`golden/` holds RTL fixtures for tests (not sent to RAG).

**Note:** No model “knows all VLSI” by weights alone. Coverage = Modelfile appendix (v1.2) + this RAG corpus + user RTL. Never invent ports/timing; prefer user specs.
