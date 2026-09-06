# ChipSutra LLM vs premium models (Claude / GPT / OpenAI / Kimi / etc.)

What local `chipsutra-vlsi` still lacks relative to frontier coding models on DV/TB work.

## A. First-pass correctness (biggest quality gap)

| # | Gap | Premium models | ChipSutra today |
|---|-----|----------------|-----------------|
| A1 | **Declare every TB signal** used in port maps / stimulus | Near-perfect | Often omit `logic enable` etc. |
| A2 | **Widths match DUT** (`[3:0] count`) | Usually exact | Sometimes `reg count` / wrong width |
| A3 | **Real constraints** on `rand` fields | Meaningful `inside` / `dist` | Sometimes `{ 1; }` noop |
| A4 | **Init hygiene** (`errors=0`, clk/rst/enable=0) | Consistent | Partial |
| A5 | **Post-reset settle** before stimulus loop | Common | Often skipped |
| A6 | **Compile-clean** first try | High | Lint ≠ compile; undeclared IDs ship |
| A7 | **Semantic golden** (FIFO order, AXI handshakes) | Strong priors | Pattern lint only; wrong math can pass score |
| A8 | **UVM API fidelity** | Strong | Light passthrough; can invent APIs |
| A9 | **Parameterized DUT** `#(.WIDTH,.DEPTH)` | Usually correct | Fragile |
| A10 | **No truncation** mid-`endmodule` | Rare | `num_predict` ceiling |

## B. Knowledge / reasoning

| # | Gap | Premium | ChipSutra |
|---|-----|---------|-----------|
| B1 | Broad pretraining on SV/UVM/corpuses | Huge | Small coder base + Modelfile + RAG |
| B2 | Few-shot diversity | Implicit | Counter + FIFO gold mainly |
| B3 | RAG depth for TB | N/A (weights) | `top_k` thin |
| B4 | Multi-file / SoC reasoning | Strong | Port-list focused |
| B5 | Spec ambiguity handling | Asks / assumes well | Often invents |

## C. Tooling / closed loop

| # | Gap | Premium product UX | ChipSutra |
|---|-----|--------------------|-----------|
| C1 | Compile/sim in the loop | Often (tools/sandbox) | Optional Verilator; off by default |
| C2 | Self-repair from **compiler** errors | Common | Lint-issue strings only |
| C3 | Eval harness vs gold suite | Internal | Competitive score = surface checklist |

## D. Speed / latency (where we can *beat* premium)

| # | Factor | Premium | ChipSutra opportunity |
|---|--------|---------|------------------------|
| D1 | Network + queue | 2–20s+ TTFB | Local Ollama = often faster TTFB |
| D2 | Over-long essays | Sometimes | Constrained to SV-only |
| D3 | Unnecessary 2nd repair pass | Rare | Skip LLM repair when mechanical lint clears |
| D4 | Oversized `num_predict` | Managed | Cap by DUT size / methodology |
| D5 | Cold weight load | N/A | Prewarm 7B on API start |

## E. Product framing

Premium wins on **generalization + first-compile**. ChipSutra wins on **privacy, cost, offline, latency**, and can **match** premium on common DUTs if: port-aware lint/repair + gold few-shots + optional compile gate.

## Fix order (this iteration → v1.4.0)

1. **A1–A5** mechanical lint/repair (undeclared ports, noop constraint, errors=0, settle) ✅
2. **D3–D4** skip redundant LLM repair; tighter predict when clean path ✅
3. Harden Modelfile / HARD RULES ✅
4. Score bar includes declared ports + real constraint ✅
5. **A2 widths** from parsed ports ✅
6. **A7 semantic** golden checks ✅
7. **A8 UVM** lightweight lint ✅
8. **C1 Verilator auto** when installed ✅
9. More gold few-shots (parity, AXI, FIFO) ✅

## Pipeline fixes (v1.4.1)

1. **Circular-golden false positive** — `expected_count = expected_count + 1` (a correct
   independent golden) no longer flags `circular_golden`; true positives like
   `expected = count + 1` still do. Counter eval: 100/100, match premium. ✅
2. **FIFO semantic repair** — `semantic_fifo_no_queue` / `semantic_circular_out` now
   trigger the LLM repair pass, and the repair prompt teaches the queue-golden pattern
   (`q[$]` push/pop, `rd_data===q[0]`, full/empty vs `q.size()`). FIFO eval: 100/100. ✅
3. **A9 class-scope params** — new `class_param_scope:<NAME>` lint catches file-scope
   classes referencing module parameters (compile error); mechanical repair hoists
   `localparam int NAME = <default>;` above the first class. ✅
4. **D5+ keep-alive** — all Ollama calls send `keep_alive=30m` (env `OLLAMA_KEEP_ALIVE`)
   so 7B weights stay resident between generates; removes cold-reload latency. ✅
5. **C1/A6 compile gate LIVE** — Verilator 5.032 installed (WSL Ubuntu +
   `backend/tools/verilator.bat` shim); `--timing` added to lint mode for TB
   delays/event controls. All 4 eval TBs (counter/FIFO/parity/mux) pass
   `verilator --lint-only` after mechanical repair. `CHIPSUTRA_VERIFY_TB=auto`
   now actually runs on every generate. ✅

## Proof loop (v1.5.0) — G1/G2/G3/G4 shipped

1. **G1 compiler-error self-repair** — when the Verilator gate fails, the server
   now (a) mechanically repairs and RE-verifies, then (b) runs one LLM repair
   pass fed with the actual `%Error` lines (`CHIPSUTRA_COMPILER_REPAIR=true`).
   Validated end-to-end: sim-failing FIFO TB → LLM repair with evidence → sim
   PASS. ✅
2. **G2 sim-run PASS gate** — `dv_verify` mode="run" builds with
   `--binary --timing --assert --x-initial unique` and executes the sim
   (`+verilator+rand+reset+2`); ok requires PASS printed, no FAIL, clean exit.
   Critical finds: without `--assert` Verilator drops `assert(txn.randomize())`
   so TBs silently tested nothing; z3 installed in WSL for constrained
   randomize; random power-up makes missing resets observable. ✅
3. **G3 mutation testing** — `dv_mutation.py` injects 6 bug classes
   (off-by-one, +→−, ==→!=, &&→||, stuck output, dropped reset);
   `scripts/run_mutation_bench.py` reports kill rate. Current suite:
   **10/11 mutants killed (91%)** — counter 3/3, FIFO 6/6, mux 1/1; parity
   misses drop_reset (no post-reset value check — now required by rules). ✅
4. **G4 functional coverage** — `tb_coverage.py` builds covergroups from parsed
   ports (skips clk/rst, crosses control bits) wrapped in `ifndef VERILATOR
   (Questa/VCS compile them; our gate skips). Lint flags
   `missing_functional_coverage` (soft); mechanical repair inserts it;
   generation rules ask the model for it natively. ✅
5. **New semantic lint** — `semantic_fifo_count_arith` (queue exists but count
   tracked by +/- arithmetic instead of q.size()) — the exact bug that made the
   FIFO TB fail at runtime; triggers LLM repair. Rules now also require a
   post-reset output-value check (kills dropped-reset mutants). ✅
6. **Eval upgrades** — `sync_fifo8.sv` DUT replaced with a functional FWFT FIFO
   (the old stub was unrunnable); eval script reports `sim_pass` per case and
   uses the production prompt rules. ✅

## Protocol pack: AXI4-Lite (v1.6.0) — G5 started

1. **Functional AXI4-Lite slave DUT** — `eval_suite/duts/axi_lite_slave.sv`
   (4×32-bit regs, WSTRB byte lanes, 1-cycle ready pulses, held RDATA).
   The golden smoke TB passes real Verilator simulation against it. ✅
2. **AXI semantic lints** — `semantic_axi_no_ready_wait` (drives AWVALID,
   never observes AWREADY), `semantic_axi_no_resp_check` (BRESP/RRESP never
   checked), `semantic_axi_no_timeout` (unbounded handshake waits hang sims).
   All trigger the LLM repair pass; procedural TBs get semantic gating too. ✅
3. **Golden-reference prompt injection** — RAG only indexes `.txt` knowledge,
   so the `.sv` goldens never reached the model. For bus protocols the server
   now injects the matching golden TB into the prompt
   (`golden_ref_for_protocol`). AXI eval first-pass: 60 → **93 vs premium 90**.
   Simple DUT classes skip it (already at bar; prompt-eval latency costs). ✅
4. **New generic mechanical repairs** (found via AXI, apply everywhere):
   hoist illegal mid-block declarations out of `initial` to module scope;
   connect empty DUT port maps `.sig()` → `.sig(sig)` and rewrite `dut.sig`
   hierarchical peeks; neutralize hallucinated `.clone()`; qualify class
   members leaked to module scope (`model_reg` → `sb.model_reg`); covergroup
   insert now detects the real clock (aclk/pclk). ✅
5. **Cloud→local fallback restored** — `stream_chat` falls through to local
   ChipSutra-VLSI when a cloud provider is requested but unconfigured. ✅
6. **CPU-only latency profile measured** — prompt eval ~33 tok/s (3k-token
   server prompt ≈ 90–145s TTFT), generation ~5.5 tok/s; a full TB ≈ 4–6 min
   end-to-end including the Verilator gate. Aborted clients leave Ollama
   grinding server-side and queue subsequent requests (observed 15-min
   pileups) — clean-queue runs complete reliably. `OLLAMA_HTTP_TIMEOUT`
   default raised to 900s. ✅

### v1.6.0 status (eval suite, chipsutra-vlsi:7b)

- Score parity: **6/6 cases match/beat premium refs** (avg 97.7–100 vs 96.7).
- Sim-run PASS proof: counter ✅, FIFO ✅, parity ✅, mux ✅; APB ❌ (runs,
  scoreboard FAILs), AXI-Lite ❌ (compiles+runs after class-scoping rules;
  omitted WSTRB stimulus masks writes → FAIL).
- Mutation kill rate: 10/11 on runnable cases (counter 3/3, FIFO 6/6,
  mux 1/1; parity drop_reset survives when the model skips the post-reset
  check).
- Remaining AXI/APB sim-PASS gap = bus-protocol stimulus completeness. The
  known fix ladder: class-scoping + pin-completeness rules (shipped), model
  few-shot for class-based AXI in the Modelfile, then G8 LoRA on
  (broken → repaired) pairs.

### New lint/repair (v1.6.0)

- `unknown_dut_pin:<pin>` (hard) — invented clk/rst pins on combinational
  DUTs; repair drops them. Mux case: compile fail → sim PASS.
- Missing-pin completion — `.pin(pin)` appended for DUT ports absent from
  the port map (unconnected inputs read 0 and silently break protocol TBs).
- DUT-rename fix — instantiation of a nonexistent module (`enable_counter`
  for `counter_en`) is renamed to the parsed DUT name.
- Declaration hoisting handles multi-statement lines
  (`int i, errors; $dumpfile(...);`).
- LLM repair: truncated outputs (no `endmodule`) rejected; repair token
  budget 1200 → 2000; eval iterates up to 2 compile-repair passes and only
  adopts candidates that pass the gate or make real progress.

## Gap-close release (v1.7.0)

1. **Class-based AXI Modelfile few-shot** — WSTRB=4'hF, timeout-guarded
   handshakes, `predict_write(sel,data)` with proper class scoping; golden
   injection switched to `axi_lite_class_sv_tb.sv`. ✅
2. **Functional APB DUT** — register file + SETUP/ACCESS; APB semantic lints
   (`no_access_phase`, `no_pready_wait`, `no_timeout`, `no_model_reg`); APB
   golden smoke injected. ✅
3. **Post-reset mechanical repair** — inserts `if (<out> !== '0) errors++;`
   after reset deassert (parity/counter drop_reset kill). ✅
4. **G5 protocol packs** — AXIS, AHB, SPI, I2C, UART eval DUTs + premium refs
   + planner detection + golden hints (11-case suite). ✅
5. **G6 UVM hardening** — hierarchy/sequencer checks; utils macros hard when
   full env present. ✅
6. **G7 SVA path** — new `sva_lint.py` (property/clock/disable_iff/invented
   ports) wired into `/generate/stream` for `module=assertions`. ✅
7. **Cancel-on-disconnect** — `request.is_disconnected()` aborts Ollama stream
   early (stops 15-min queue pileups from aborted clients). ✅
8. **pytest markers** — `serial` / `verilator` registered for WSL-sensitive tests. ✅

## Scale-out release (v1.8.0) — G8–G13

1. **G13 nightly bench** — `scripts/run_nightly_bench.py` runs eval + mutation and
   writes `eval_suite/reports/latest.{json,md}`. Suite expanded to **20 DUTs**
   (ALU/shifter/edge/CDC/encoder/gray/debounce/PWM + prior 11). ✅
2. **G12 checkers + soft gates** — `checker_lint.py` wired for `module=checkers`;
   spec2rtl/debug report `learning.soft_gate` without hard-failing the stream. ✅
3. **G10 latency** — Ollama `stop` sequences cut post-SV prose; adaptive RAG
   `top_k` + `OLLAMA_NUM_PREDICT_SV_SIMPLE` for simple protocols. ✅
4. **G8 LoRA** — `scripts/export_lora_dataset.py` + `models/chipsutra-vlsi/LORA.md`
   (Unsloth/Axolotl path). Train on GPU workstation; merge → Ollama tag. ✅
5. **G9 14B tier** — `Modelfile.14b`, `CHIPSUTRA_MODEL_14B`, router
   `14b_preferred`. ✅
6. **G11 multi-module** — planner tags SoC/multi-clock, prefers 14B, injects
   multi-DUT TB notes (full CDC stimulus still follow-on). ✅
