# Industry EDA gaps — ChipSutra vs sign-off tools

ChipSutra is an **AI verification copilot** with a growing OSS EDA engine layer — not a replacement for Synopsys/Cadence/Siemens sign-off suites.

## Positioning

| Layer | ChipSutra Community | Industry sign-off |
|-------|---------------------|-------------------|
| AI generation (UVM/SVA/debug) | ✅ Differentiator | Emerging (Verisium / Synopsys.ai) |
| Lint / cycle sim | ✅ Verilator | VCS / Xcelium / Questa |
| Formal | 🧪 SymbiYosys (+ Yosys via OSS CAD Suite in Docker) | Jasper / VC Formal / Questa Formal |
| Coverage | ✅ Upload parser + 🧪 Verilator `--coverage` persist | IMC / URG / UCIS |
| CDC / RDC | 🧪 Heuristic + optional Yosys JSON | Spyglass CDC / Questa CDC |
| Waveform | ✅ VCD hierarchy/search/zoom/cursor | Verdi / DVE / Surfer |
| Synthesis / LEC / STA | 🧪 Yosys synth + equiv + eqy LEC (fallback); OpenSTA scaffold only | DC / Genus / Formality / PT |
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
- Coverage **trends/merge** endpoints; OpenSTA **SDC/TCL scaffold** (not full STA without liberty)

## Still missing (priority)

1. **FST** ingestion and deeper waveform debug
2. Full OpenSTA timing **with liberty** (scaffold only today)
3. UCIS / industry coverage format adapters
4. Closed-loop coverage → holes → re-sim
5. Richer regression dashboard UX beyond SSE + trend summary
6. Multi-revision LEC (UI currently compares RTL vs auto-synth netlist)

## Enterprise-only (by design)

Vendor simulators, LSF/SLURM farms, UCDB/FSDB, SAML/SSO, air-gap bundles, customer LoRA, SLA.

Rule: if it runs on one laptop with OSS tools → Community. If it needs a license, cluster, or auditor → Enterprise.

See also: [SUPPORTED_FEATURES.md](./SUPPORTED_FEATURES.md), [ROADMAP.md](../ROADMAP.md), [ENHANCEMENTS.md](./ENHANCEMENTS.md).
