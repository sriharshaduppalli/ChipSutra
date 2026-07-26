# Supported vs experimental features

Use this matrix to set expectations for **Community Edition** users and contributors.

**Legend:** ✅ Supported · 🧪 Experimental · 📋 Planned · ❌ Out of scope (Community)

## AI generation modules

| Module | Status | Notes |
|--------|--------|-------|
| UVM testbench | ✅ | LLM output; human review required for production |
| SVA assertions | ✅ | |
| Checkers / reference models | ✅ | |
| Covergroups | ✅ | |
| Spec → RTL | 🧪 | Quality varies by model size; not sign-off RTL |
| RTL → spec | ✅ | Markdown spec |
| Testplan / coverage plan | ✅ | Markdown |
| Coverage-hole tests | 🧪 | Best with coverage text + RTL context |
| Debug analysis | ✅ | Log/report → ranked hypotheses |
| Formal hints | ✅ | LLM properties; not a proof engine |

**Default LLM (Community):** `chipsutra-vlsi:3b` via Ollama — see [models/chipsutra-vlsi](../models/chipsutra-vlsi/README.md).

Optional cloud LLMs (Anthropic/OpenAI/Emergent) are **supported when configured** but are not required.

## Analysis & debug

| Feature | Status | Notes |
|---------|--------|-------|
| Coverage upload parser | ✅ | Regex on `.rpt/.log/.txt/.csv`; optional project persist |
| Verilator native coverage | 🧪 | Sim “coverage” toggle → `coverage_runs` |
| Coverage heatmap / holes | ✅ | Holes = metrics &lt; 90% |
| VCD waveform viewer | ✅ | Parsed subset; not full Verdi/DVE |
| CDC / RDC analyzer | 🧪 | Heuristic v0 — Project **CDC** button |
| Assertion debug (dedicated) | 📋 | Use **debug** + formal property table |
| Auto test from holes (closed loop) | 📋 | Manual: run module then sim |
| Run manifests | ✅ | Tool versions + argv + input hashes on sim/formal |

## Simulation & formal

| Feature | Status | Notes |
|---------|--------|-------|
| Verilator lint | ✅ | Streaming logs |
| Verilator compile + run + VCD | ✅ | Block-level SV; UVM may need vendor sim |
| Sim seed / coverage flags | ✅ | UI + API |
| SymbiYosys formal | 🧪 | Prefer OSS CAD Suite Yosys ≥ 0.35 in Docker |
| Formal property table + CEX VCD | ✅ | When SBY produces traces |
| Questa / VCS / Xcelium | ❌ | Enterprise roadmap |

## Platform

| Feature | Status | Notes |
|---------|--------|-------|
| Docker Compose self-host | ✅ | Mongo + Ollama + backend + frontend |
| Local disk storage | ✅ | Default |
| Google OAuth | 🧪 | Optional |
| Workspaces / roles | ✅ | |
| GitHub Actions template | ✅ | Webhook AI review = stub |
| Email verification / quotas | ✅ | Off by default (`FREE_DAILY_QUOTA=0`) |

## Design scope claims

| Scope | Community reality |
|-------|-------------------|
| Block / IP | ✅ Strong fit |
| Subsystem / SoC | 🧪 LLM context limits; split designs |
| Chiplet / multi-die | 🧪 Templates + prompts; not full system TB |
| “Any design, zero review” | ❌ Always engineer-in-the-loop |

## Quality tiers (Ollama)

| Model | Status | Typical use |
|-------|--------|-------------|
| `chipsutra-vlsi:1.5b` | ✅ | Fast drafts, low RAM |
| `chipsutra-vlsi:3b` | ✅ **Default** | Daily verification copilot |
| `chipsutra-vlsi:7b` | ✅ | Heavier UVM/SVA |
| Cloud Claude/GPT | ✅ Optional | Higher quality when keys set |

Update this file when a feature moves from 🧪 → ✅ or ships as 📋.
