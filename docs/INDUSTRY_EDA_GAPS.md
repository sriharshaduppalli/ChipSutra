# Industry EDA gaps — ChipSutra vs sign-off tools

ChipSutra is an **AI verification copilot** with a growing OSS EDA engine layer — not a replacement for Synopsys/Cadence/Siemens sign-off suites.

## Positioning

| Layer | ChipSutra Community | Industry sign-off |
|-------|---------------------|-------------------|
| AI generation (UVM/SVA/debug) | ✅ Differentiator | Emerging (Verisium / Synopsys.ai) |
| Lint / cycle sim | ✅ Verilator | VCS / Xcelium / Questa |
| Formal | 🧪 SymbiYosys (+ Yosys via OSS CAD Suite in Docker) | Jasper / VC Formal / Questa Formal |
| Coverage | ✅ Upload parser + 🧪 Verilator `--coverage` persist | IMC / URG / UCIS |
| CDC / RDC | 🧪 Heuristic v0 | Spyglass CDC / Questa CDC |
| Waveform | ✅ VCD hierarchy/search/zoom/cursor | Verdi / DVE / Surfer |
| Synthesis / LEC / STA | 🧪 Yosys synth + internal equivalence; no STA | DC / Genus / Formality / PT |
| Vendor adapters / farm / SSO | ❌ Enterprise | Native |

## Shipped toward industry credibility (this wave)

- Verilator **coverage** flag + persisted `coverage_runs`
- **Run manifests** (tool versions, argv, input hashes) on sim/formal
- Formal **property table** + **CEX VCD** harvest
- Sim **seed** + coverage toggle in UI
- **CDC/RDC v0** panel (`POST /cdc/analyze`)
- Docker optional **OSS CAD Suite** for newer Yosys/SBY
- Seeded **regression matrix** persisted in Mongo
- Verilator **lint policy/waiver gate** (`chipsutra.lint.json`)
- Yosys **synthesis + equivalence sanity**
- VCD **hierarchy/search/zoom/cursor** and direct project-file loading
- **cocotb scaffold** generation

## Still missing (priority)

1. Regression **trend/dashboard** and parallel workers
2. **FST** ingestion and deeper waveform debug
3. Full **eqy** LEC and synthesis artifact export
4. One-click **cocotb runner** (scaffold shipped)
5. Coverage **merge/trend** charts
6. Structural CDC via Yosys JSON netlist (upgrade v0)
7. SDC/STA sanity via OpenSTA

## Enterprise-only (by design)

Vendor simulators, LSF/SLURM farms, UCDB/FSDB, SAML/SSO, air-gap bundles, customer LoRA, SLA.

Rule: if it runs on one laptop with OSS tools → Community. If it needs a license, cluster, or auditor → Enterprise.

See also: [SUPPORTED_FEATURES.md](./SUPPORTED_FEATURES.md), [ROADMAP.md](../ROADMAP.md), [ENHANCEMENTS.md](./ENHANCEMENTS.md).
