# Industry EDA gaps — ChipSutra vs sign-off tools

ChipSutra is an **AI verification copilot** with a growing OSS EDA engine layer — not a replacement for Synopsys/Cadence/Siemens sign-off suites.

## Positioning

| Layer | ChipSutra Community | Industry sign-off |
|-------|---------------------|-------------------|
| AI generation (UVM/SVA/debug) | ✅ Differentiator | Emerging (Verisium / Synopsys.ai) |
| Lint / cycle sim | ✅ Verilator | VCS / Xcelium / Questa |
| Formal | 🧪 SymbiYosys (+ Yosys via OSS CAD Suite in Docker) | Jasper / VC Formal / Questa Formal |
| Synthesis / LEC / STA | 🧪 Yosys synth + equiv + eqy LEC; OpenSTA with liberty (mock otherwise) | DC / Genus / Formality / PT |
| Coverage | ✅ Parser + UCIS/IMC/URG + Verilator persist + closure loop UX | IMC / URG / UCIS |
| Waveform | ✅ VCD + FST (via fst2vcd) | Verdi / DVE / Surfer |
| Vendor adapters / farm / SSO | ❌ Enterprise | Native |

## Shipped toward industry credibility (this wave)

- Verilator **coverage** flag + persisted `coverage_runs`
- **Run manifests** (tool versions, argv, input hashes) on sim/formal
- Formal **property table** + **CEX VCD** harvest
- Sim **seed** + coverage toggle in UI
- **CDC/RDC** heuristic + optional Yosys-JSON merge (`POST /cdc/analyze`)
- Docker optional **OSS CAD Suite** for newer Yosys/SBY
- Seeded **regression matrix** with **parallel workers (1–4)**, coverage, and trends
- Verilator **lint policy/waiver gate** (`chipsutra.lint.json`)
- Yosys **synthesis + equivalence** + **eqy LEC** (RTL vs auto-synth netlist; falls back to internal equiv) + artifact export
- VCD **hierarchy/search/zoom/cursor** and direct project-file loading
- **cocotb scaffold** + **one-click runner** (`POST /api/cocotb/stream`; mock if tools missing)
- Coverage **trends/merge** endpoints; OpenSTA **run path** (liberty upload; mock without `sta`)
- **FST** via `fst2vcd`; **UCIS/IMC/URG/CSV** coverage adapters
- **Closed-loop UX**: Generate hole tests + Apply seeds → Regression; sim log **auto-attach** to `tool_log`
- Optional **Redis** rate limiter (`REDIS_URL`, compose `--profile redis`)

## Still missing (priority)

1. Default self-host path that pulls GHCR images (skip local rebuild)
2. Demo liberty / sky130 path so STA smoke is non-mock by default
3. Ollama pre-warm + optional sentence-transformers packaging
4. CI webhook worker: PR diff → lint → optional AI review
5. Multi-revision LEC (UI currently compares RTL vs auto-synth netlist)
6. Richer first-project wizard / screen recording

## Enterprise-only (by design)

Vendor simulators, LSF/SLURM farms, UCDB/FSDB, SAML/SSO, air-gap bundles, customer LoRA, SLA.

Rule: if it runs on one laptop with OSS tools → Community. If it needs a license, cluster, or auditor → Enterprise.

See also: [SUPPORTED_FEATURES.md](./SUPPORTED_FEATURES.md), [ROADMAP.md](../ROADMAP.md), [ENHANCEMENTS.md](./ENHANCEMENTS.md).
