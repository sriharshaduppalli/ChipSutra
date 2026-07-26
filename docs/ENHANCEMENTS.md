# Enhancements & gaps (accuracy, speed, reliability, UX)

Prioritized for an India-first open-source EDA verification startup.

## P0 — Reliability & “it just works”

| Gap | Impact | Direction |
|-----|--------|-----------|
| No full Docker E2E in CI | Regressions slip through | Add compose smoke job (health + one Ollama chat) on GH runners |
| `backend/.env` required | Compose fails for newcomers | ✅ `scripts/bootstrap.sh` / `.ps1` |
| UI implied Claude by default | Confusing for OSS users | ✅ Engine picker reads `/api/health`, ChipSutra-VLSI first |
| Weak Ollama error messages | Hard to debug | ✅ Actionable errors in `llm_provider` |
| Live hosted demo vs OSS drift | Trust gap | Pin demo to same compose + model tags as `main` |

## P1 — Accuracy (verification quality)

| Gap | Direction |
|-----|-----------|
| LLM-only generation | ✅ Parse RTL ports (`rtl_ports.py`) → inject into Generate; richer AST later |
| Generic system prompts | ChipSutra-VLSI-LLM **v1.2** protocol index + expanded RAG — [LLM_ACCURACY.md](./LLM_ACCURACY.md) |
| No golden regression suite | Curated DUTs (Ibex, counters, FIFO) + expected SVA/TB snippets |
| Spec→RTL oversold | Mark 🧪 in UI; require spec checklist before generate |
| No closed tool loop | ✅ `tool_log` / `prior_output` API + Project UI paste-log field |

## P1 — Speed

| Gap | Direction |
|-----|-----------|
| Cold Ollama load | Pre-warm model in `ollama-create` or backend startup |
| 3B latency on CPU | Document GPU compose snippet; default `7b` only on GPU profiles |
| Large RTL context | Chunk files + summarize before LLM; raise `num_ctx` in Modelfile |

## P2 — Industry completeness

| Gap | Direction |
|-----|-----------|
| Coverage: regex only | UCIS/IMC parsers, merge across regressions |
| No Questa/VCS/Xcelium | Enterprise adapters + job queue |
| Formal tool age | ✅ OSS CAD Suite path; keep pinned/reproducible |
| No regression matrix | ✅ Sequential tests × seeds; parallel workers/trends next |
| No synthesis sanity | ✅ Yosys synth + internal equivalence; eqy/OpenSTA next |
| Weak lint governance | ✅ Project policy + owned waivers |
| Basic waveform | ✅ VCD hierarchy/search/zoom/cursor; FST next |
| Python TB path | ✅ cocotb scaffold; integrated runner next |
| CI webhook stub | Worker: PR diff → lint → optional AI comment |
| Closed-loop coverage | Upload → holes → auto `coverage_holes` → suggest re-run |

## P2 — README & onboarding

| Done / next |
|-------------|
| ✅ Troubleshooting table, bootstrap, OPEN_SOURCE checklist |
| Add 60s screen recording GIF under `docs/screenshots/` |
| “First project” wizard: upload `counter.sv` → testbench → simulate |
| Hindi/Telugu one-pager for universities (optional) |

## ChipSutra-VLSI-LLM positioning (honest)

- **Best at:** zero marginal cost, privacy, VLSI-flavored prompts, offline/air-gapped with Ollama only.
- **Not yet best at:** beating frontier cloud models on arbitrary multi-million-gate SoCs without fine-tuning.
- **Path to “best for DV”:** domain LoRA + RTL-aware tooling + user feedback loop — not bigger marketing claims.

Update this doc as items ship.
