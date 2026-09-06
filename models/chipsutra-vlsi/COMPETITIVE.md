# ChipSutra LLM competitiveness roadmap

Goal: local `chipsutra-vlsi` TB generation matches or nearly matches Claude/GPT first-pass quality for Pure SV / UVM on common DUTs.

## Active improvements (v1.4.0)

- Port-width–aware lint/repair from parsed DUT ports
- Semantic golden checks (counter/fifo/parity)
- UVM fake-API lint + hint comments
- Parity + AXI-Lite gold few-shots / RAG goldens
- Verilator lint **auto** when installed (`CHIPSUTRA_VERIFY_TB=auto`)
- TB RAG `top_k=3`; Ollama tags cache for faster `/health`
- Prefer 7B; skip LLM repair when mechanical clears premium bar

## Already in place (v1.3.x+)

1. **Gold few-shot** in Modelfile (counter class-based Pure SV) — teaches shape, not ChipVerify dumps alone.
2. **Class-SV lint + mechanical repair** (`tb_class_lint.py`) — clock, `logic` stimulus, `function bit check`, `new()`, `errors`, NBA→blocking in model.
3. **Generate path** keeps LLM output (no smoke-template replace); stamps `llm` / `llm_repaired`; reports `competitive` score in learning.
4. **RAG curriculum** + methodology routing (SV class / procedural / UVM / OVM / VMM).

## What still moves the needle vs Claude/GPT (v1.8.0)

Status: **20-DUT** eval suite + nightly report (`scripts/run_nightly_bench.py`).
G1–G13 scaffolding shipped through v1.8.0 (LoRA export + 14B Modelfile ready for GPU train/create).

| Priority | Item | Why |
|----------|------|-----|
| P0 | **G1** Compiler-error self-repair ✅ | |
| P0 | **G2** Sim-run PASS gate ✅ | |
| P0 | **G3** Mutation testing ✅ | |
| P1 | **G4** Functional coverage ✅ | |
| P1 | **G5** Protocol packs (AXI-Lite/APB/AXIS/AHB/SPI/I2C/UART) ✅ | Real customer DUT mix |
| P1 | **G6** UVM hard lint (hierarchy + utils) ✅ | Industry default methodology |
| P1 | **G7** SVA lint/repair/score ✅ | Formal + dynamic flows |
| P2 | **G8** QLoRA dataset export + train README ✅ | Run Unsloth/Axolotl on GPU; merge → Ollama |
| P2 | **G9** 14B Modelfile + router tier ✅ | `ollama create chipsutra-vlsi:14b -f Modelfile.14b` |
| P2 | **G10** Stop sequences + adaptive RAG/`num_predict` ✅ | Faster warm decode on simple DUTs |
| P3 | **G11** Multi-module → 14B tier + SoC TB notes ✅ | Full CDC TB body still iterative |
| P3 | **G12** Checker lint + soft-gate spec2rtl/debug ✅ | Mirror SVA path for checkers |
| P3 | **G13** 20-DUT nightly bench + Markdown report ✅ | Grow toward 25+ with customer IP |

India EDA edge to productize: air-gapped on-prem (customer IP never leaves),
flat rupee economics vs dollar-per-token APIs, integration with
Questa/VCS/Xcelium + CI regressions, DV-native features (testplan gen,
regression triage, coverage closure).

## Premium bar (eval)

`score_class_sv_competitive` ≥ 90 and `lint_ok` on gold DUTs. Track in generation `learning.competitive`.

## Commands

```powershell
cd models\chipsutra-vlsi
ollama create chipsutra-vlsi:3b -f Modelfile.3b
ollama create chipsutra-vlsi:7b -f Modelfile.7b
# GPU workstation (pull base first):
# ollama pull qwen2.5-coder:14b
# ollama create chipsutra-vlsi:14b -f Modelfile.14b

cd ..\..\backend
python scripts/export_lora_dataset.py
python scripts/run_nightly_bench.py --skip-llm   # or full LLM nightly
```
