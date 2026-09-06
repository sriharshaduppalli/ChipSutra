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
- Native **SVA / covergroup lint** + optional [AsFigo SVALint / FCOVLint](./ASFIGO_LINTERS.md) PATH wrappers

## Still missing (priority)

Honest leftovers after the Community close-the-loop wave. See **[ADVANCED_DV_ARCHITECTURE.md](./ADVANCED_DV_ARCHITECTURE.md)**.

1. Vendor simulators (Questa/VCS/Xcelium) — Community has **adapter stubs only**; no sign-off claim
2. Publishing a LoRA/GGUF `chipsutra-vlsi:*-ft` weight (docs + Modelfile example exist; training stays on your GPU)
3. Optional 60s screen-recording GIF under `docs/screenshots/` (storyboard is in `docs/screenshots/README.md`)
4. Foundry PDK / Sky130 liberty in-tree — **never**; user supplies `.lib` (see [STA_LIBERTY.md](./STA_LIBERTY.md))

Shipped this wave: GHCR `:edge` pull overlay, demo liberty + STA fallback, RAG index warm at boot, CI diff review worker, UCIS dialect fixtures, first-project wizard, Spec-IR formal pack, sim adapter stubs, multi-revision LEC UI.

## Enterprise-only (by design)

Vendor simulators, LSF/SLURM farms, UCDB/FSDB, SAML/SSO, air-gap bundles, customer LoRA, SLA.

Rule: if it runs on one laptop with OSS tools → Community. If it needs a license, cluster, or auditor → Enterprise.

See also: [SUPPORTED_FEATURES.md](./SUPPORTED_FEATURES.md), [ROADMAP.md](../ROADMAP.md), [ENHANCEMENTS.md](./ENHANCEMENTS.md).
