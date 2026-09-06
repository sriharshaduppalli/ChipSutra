# ChipSutra QLoRA fine-tune (G8)

Permanent weight-level fix for recurring TB bugs (class scoping, invented pins,
WSTRB, post-reset checks) using pairs the proof loop already produces.

## Export dataset

```powershell
cd backend
python scripts/export_lora_dataset.py
# → storage/lora/chipsutra_dv.jsonl + dataset_meta.json
```

Each line is a chat triple: system / user / assistant. Sources:
- eval raw→repaired TB pairs
- golden / premium reference TBs
- **SV fundamentals** teaching sections (`sv_fundamentals_must_know.txt`)

## Recommended train stack (GPU workstation)

1. Base: `Qwen/Qwen2.5-Coder-7B-Instruct` (or 14B for the 14B tier).
2. Method: QLoRA 4-bit (Unsloth or Axolotl), r=16, α=32, target `q_proj,v_proj,o_proj,gate_proj`.
3. Data: `chipsutra_dv.jsonl` (≥200 rows recommended; re-run export after each nightly bench).
4. Hyperparams (starting point): lr 2e-4, 1–2 epochs, max seq 4096, packing on.
5. Merge LoRA → GGUF → `ollama create chipsutra-vlsi:7b-lora -f Modelfile.lora`.

## Dataset growth tips

Re-export after each new DUT / repair:

```powershell
python scripts/export_lora_dataset.py
```

Sources now include `storage/sim_*/*_broken_tb.sv` → `*_tb.sv` pairs (e.g. mux_4to1
noop-scoreboard → real select golden). Aim for ≥200 rows before the first GPU run.

## Acceptance

Re-run:

```powershell
python scripts/run_nightly_bench.py
```

Target vs base 7B: higher first-compile rate, AXI/APB/mux sim-PASS ≥ current, no regression on counter/FIFO/parity.

## Ollama tag after merge

```bash
# After LoRA → GGUF merge, wrap it as chipsutra-vlsi:7b-ft (example Modelfile):
ollama create chipsutra-vlsi:7b-ft -f models/chipsutra-vlsi/Modelfile.ft.example
```

Point `FROM` in that Modelfile at your merged GGUF if you are not stacking on `chipsutra-vlsi:7b`. Then set `OLLAMA_MODEL=chipsutra-vlsi:7b-ft`. ChipSutra does not publish fine-tuned weights in this repo.

## Privacy

All training stays on-prem — customer RTL never leaves the air-gapped site when you
substitute golden/eval DUTs with internal IP (same JSONL schema).
