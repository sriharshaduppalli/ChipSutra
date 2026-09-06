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
| Cold Ollama load | ✅ Pre-warm model in `ollama-create` or backend startup |
| 3B latency on CPU | ✅ GPU compose overlay `docker-compose.gpu.yml`; default `7b` only on GPU hosts |
| Large RTL context | Chunk files + summarize before LLM; raise `num_ctx` in Modelfile |

## P2 — Industry completeness

| Gap | Direction |
|-----|-----------|
| Coverage: regex only | UCIS/IMC parsers, merge across regressions — 🧪 trends/merge helpers shipped |
| No Questa/VCS/Xcelium | ✅ Adapter interface + Enterprise stubs (`sim_adapter.py`); real runners stay licensed |
| Formal tool age | ✅ OSS CAD Suite path; keep pinned/reproducible |
| No regression matrix | ✅ Parallel workers 1–4 + coverage + trend summary |
| No synthesis sanity | ✅ Yosys synth/equiv + eqy LEC (fallback) + OpenSTA scaffold |
| Weak lint governance | ✅ Project policy + owned waivers; native SVA/FCOV lint; optional [AsFigo](https://github.com/AsFigo/SVALint) PATH adapters |
| Basic waveform | ✅ VCD hierarchy/search/zoom/cursor; FST via fst2vcd when available |
| Python TB path | ✅ cocotb scaffold + one-click runner (mock without tools) |
| CI webhook stub | ✅ Worker: PR diff → lint → optional GitHub comment (`ci_review.py`) |
| Closed-loop coverage | ✅ Plan + one-click Generate hole tests + Apply seeds → Regression |
| Auto-attach sim → `tool_log` | ✅ SimulationPanel fills Generate fix-loop on run complete |
| Redis multi-replica limits | ✅ Optional `redis` dep + compose `--profile redis` + `REDIS_URL` |
| RAG cold start | ✅ Optional `requirements-rag.txt`; hashed-TFIDF fallback; `warm_index()` at API boot |

## P2 — README & onboarding

| Done / next |
|-------------|
| ✅ Troubleshooting table, bootstrap, OPEN_SOURCE checklist |
| ✅ First-project wizard: `counter.sv` → testbench → simulate (`POST /projects/quickstart`) |
| Optional 60s GIF under `docs/screenshots/` — storyboard in that folder's README |
| Hindi/Telugu one-pager for universities (optional) |

## ChipSutra-VLSI-LLM positioning (honest)

- **Best at:** zero marginal cost, privacy, VLSI-flavored prompts, offline/air-gapped with Ollama only.
- **Not yet best at:** beating frontier cloud models on arbitrary multi-million-gate SoCs without fine-tuning.
- **Path to “best for DV”:** domain LoRA + RTL-aware tooling + user feedback loop — not bigger marketing claims.

Update this doc as items ship.
