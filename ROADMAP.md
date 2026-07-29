# Public roadmap — ChipSutra

Last updated: 2026-07-29

ChipSutra is an **AI verification copilot** (not a full sign-off EDA replacement). This roadmap splits **Community (open source)** from **Enterprise (commercial, future)**.

## Editions

| | **Community Edition** (this repo) | **Enterprise Edition** (planned) |
|---|-----------------------------------|----------------------------------|
| License | MIT + attribution | Commercial agreement |
| LLM | Local **[ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM)** via Ollama | Same + optional hosted GPU |
| Sim | Verilator lint/run/VCD | Questa/VCS/Xcelium adapters |
| Support | GitHub Issues, community | SLA, on-prem, SSO/SAML |
| Rebrand | “Powered by ChipSutra” required | White-label option |

## Shipped (Community)

- [x] 10 AI modules (testbench, SVA, covergroups, spec2rtl, …)
- [x] Zero-key Ollama path + optional Claude/OpenAI
- [x] Verilator lint + compile/run + VCD
- [x] SymbiYosys formal (best-effort; Yosys version notes)
- [x] Coverage report parser + waveform (VCD) viewer
- [x] Workspaces, roles, notifications, templates, CI template
- [x] **ChipSutra-VLSI** custom Ollama model (default in Docker) — **v1.2.x** protocol index
- [x] Keyword + hybrid vector RAG (`backend/knowledge/`) + RTL port injection + lint/sim fix-loop (`tool_log`)
- [x] Verilator coverage persist + run manifests + formal CEX/property table
- [x] CDC/RDC heuristic analyzer (experimental) + optional Yosys JSON merge
- [x] Seeded multi-test regression matrix (parallel workers 1–4, coverage, trends)
- [x] Project lint policy + owned/reasoned waivers (`chipsutra.lint.json`)
- [x] Yosys synthesis + equivalence sanity + **eqy LEC** (fallback to internal equiv) + synth artifacts
- [x] VCD hierarchy/search/zoom/cursor + **FST** via `fst2vcd` when available
- [x] cocotb project scaffold + **one-click runner** (mock if tools missing)
- [x] Coverage merge/trends; **UCIS / IMC / URG / CSV** adapters; closure plan + delta compare
- [x] **Closed-loop UX**: Generate hole tests + Apply seeds → Regression from Coverage page
- [x] **Auto-attach** Verilator/sim log into Generate `tool_log` after Simulate finishes
- [x] OpenSTA run path (SDC + TCL + liberty upload; mock if `sta`/liberty missing)
- [x] Golden DUT suite: `counter`, `fifo`, `axi_lite_slave` (+ TBs)
- [x] Optional **Redis** rate limiter (`REDIS_URL` + compose `--profile redis`)
- [x] GHCR publish workflow on `main` / `v*` tags (see `.github/workflows/docker-publish.yml`)

## In progress (Community — next 90 days)

- [ ] Default self-host docs/compose to pull GHCR `:edge` / release tags (skip local rebuild)
- [ ] Demo liberty fixture or documented sky130 path for non-mock STA smoke
- [ ] Ollama model pre-warm on backend startup (cut first-token latency)
- [ ] Embedding / `sentence-transformers` optional extra + index warm at boot
- [ ] UCIS fixture corpus in CI for vendor dialect drift
- [ ] CI webhook worker: PR diff → lint → optional AI review comment
- [ ] Screen recording / first-project wizard polish

Industry gap matrix: **[docs/INDUSTRY_EDA_GAPS.md](./docs/INDUSTRY_EDA_GAPS.md)**.

## Enterprise backlog (not in OSS unless contributed)

- Simulator farm integration (LSF/SLURM + vendor runners)
- Air-gapped install bundles + audit logs
- Fine-tuned private weights per customer (on-prem)
- SAML/OIDC, VPC deploy, data residency (India region)

## How to influence the roadmap

1. Open a [GitHub Issue](https://github.com/sriharshaduppalli/ChipSutra/issues) with label `enhancement`
2. For large features, discuss in an issue before opening a PR
3. See [CONTRIBUTOR_GUIDE.md](./docs/CONTRIBUTOR_GUIDE.md)

## Related repos

| Repo | Purpose |
|------|---------|
| [ChipSutra-VLSI-LLM](https://github.com/sriharshaduppalli/ChipSutra-VLSI-LLM) | Local Ollama models — no API credits |
| [UVM_TB_AUTOGEN](https://github.com/sriharshaduppalli/UVM_TB_AUTOGEN) | Legacy TB templates (ideas for datasets) |
