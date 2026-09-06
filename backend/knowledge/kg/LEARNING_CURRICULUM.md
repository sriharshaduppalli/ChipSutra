# SV / UVM Knowledge Graph — continuous learning curriculum

This folder holds the **machine-readable** knowledge graph. RAG text lives in
[`../kg_sv_uvm_learning.txt`](../kg_sv_uvm_learning.txt) (loaded automatically).

## Goals

Teach ChipSutra-VLSI (and gate LLM output) on:

| Pillar | Graph domains |
|--------|----------------|
| Standard SV syntax | `sv_syntax` |
| SV TB constructs | `sv_constructs` |
| Inbuilt functions | `inbuilt` |
| Randomization | `random`, `uvm_rand` |
| Reusable techniques | `reuse` |
| Reusable / extended tests | `testcases` |
| Block protocol goldens | `protocols` (FIFO / parity / AXI-Lite / AHB / APB / counter) |
| Methodologies (SV/UVM/OVM/VMM) | `methodology` |
| UVM syntax | `uvm_syntax` |
| Scalability | `uvm_scale`, `soc_scale` |
| Quality | `quality` |

**External curriculum map:** [ChipVerify SystemVerilog](https://chipverify.com/tutorials/systemverilog) and [UVM](https://chipverify.com/tutorials/uvm) — use as a topic checklist when authoring RAG (original ChipSutra text only; never wholesale-copy tutorials). AMBA bus emit rules cite ARM IHI 0022L (AXI), IHI 0033C (AHB), IHI 0024E (APB) as reference IDs only — do not vendor those PDFs or copy spec chapters into the repo.

Deep pillar files (ChipVerify-aligned):

| Pillar | RAG file | ChipVerify topic |
|--------|----------|------------------|
| **Must-know spine** | `sv_fundamentals_must_know.txt` | All SV pillars → TB checklist |
| Intro / methodologies | `verification_methodologies_curriculum.txt` | [SV tutorial](https://chipverify.com/tutorials/systemverilog) |
| Data types / control | `sv_datatypes_control_patterns.txt` | Data Types, Control Flow |
| Arrays / collections | `sv_arrays_collections_patterns.txt` | Arrays |
| Classes & OOP | `sv_oop_classes_patterns.txt` | Classes & OOP |
| Randomization | `sv_randomization_patterns.txt` | Randomization |
| Constraints / CRV | `sv_constraints_patterns.txt` | [Constraints](https://chipverify.com/systemverilog/systemverilog-constraints) |
| Interfaces | `sv_interfaces_patterns.txt` | [Interface](https://chipverify.com/systemverilog/systemverilog-interface) |
| Threads & IPC | `sv_threads_ipc_patterns.txt` | Threads, IPC |
| Advanced features | `sv_advanced_features_patterns.txt` | Advanced Features |
| Functional coverage | `covergroup_patterns.txt` | [Functional coverage](https://chipverify.com/systemverilog/systemverilog-functional-coverage) |
| Assertions | `sva_patterns.txt` | [Assertions](https://chipverify.com/systemverilog/systemverilog-assertions) |
| UVM | `uvm_patterns.txt` | [UVM](https://chipverify.com/tutorials/uvm) |

Primary overview: [`../verification_methodologies_curriculum.txt`](../verification_methodologies_curriculum.txt).

## Regular improvement loop

```text
Observe failure (sim / lint / user)
    → classify anti_pattern
    → add ## chunk to kg_sv_uvm_learning.txt
    → update JSON node/edge if new concept
    → (optional) Modelfile MESSAGE few-shot
    → bump VERSION + ollama create
    → pytest RAG + tb_lint
    → python scripts/kg_learning_status.py
```

Cadence:

1. **Weekly** — one new reusable pattern (FIFO/AXI/IRQ/…) with short example.
2. **On every TB lint fallback** — ensure the failing motif is listed under anti-patterns.
3. **On new golden DUT** — extract structure into RAG; do not paste huge files.
4. **Monthly** — review `chipsutra_mapping` vs Generate modules.

## How the LLM “keeps learning”

Weights alone will not absorb everything. ChipSutra uses a **compound learner**:

| Layer | Role |
|-------|------|
| `kg_sv_uvm_learning.txt` | Retrieved facts/patterns each Generate |
| `sv_uvm_knowledge_graph.json` | Curriculum map + edges for humans/tools |
| Modelfile SYSTEM + MESSAGE | Sticky priors + few-shots |
| `tb_skeleton` / `tb_lint` | Guaranteed correct SV smoke path |
| Sim fix-loop logs | Operational lessons → `sim_debug_playbook.txt` |

## Authoring rules for new nodes

- Prefer short, imperative bullets (RAG-friendly).
- Always state **forbidden** anti-pattern next to the good pattern.
- Link `from → to` with a clear relation (`requires`, `extends_to`, `maps_to`, …).
- Never invent JEDEC/PHY timings; point to user specs.
