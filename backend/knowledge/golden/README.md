# Golden reference DUTs

Hand-written, known-good RTL used as **fixtures** for ChipSutra's regression and
accuracy checks — not RAG corpus (`rag.py` only chunks `knowledge/*.txt`, so nothing
in this folder is ever injected into a prompt).

They give the pipeline a stable baseline: if lint, simulation, VCD capture, coverage
or synthesis regresses, these files fail first and the cause is the tool wiring, not a
model hallucination. They also serve as the "expected quality bar" when scoring
generated RTL/testbenches.

| File | What it is |
|------|------------|
| `counter.sv` | 8-bit counter — smallest possible lint/sim smoke test |
| `fifo.sv` | Parameterized synchronous FIFO (`WIDTH`, `DEPTH`) with `full`/`empty`/`count`, wrap-around pointers, overflow/underflow protection |
| `fifo_tb.sv` | Self-checking TB: reset state, underflow, fill-to-full, overflow, FIFO-order drain, pointer wrap, interleaved access |
| `axi_lite_slave.sv` | AXI4-Lite slave, four 32-bit registers in a 16-byte aperture, registered AW/W/B/AR/R handshakes, byte strobes, `OKAY` responses |
| `axi_lite_slave_tb.sv` | Self-checking TB: reset values, write-then-read every register, register independence, byte-enable write, `BRESP`/`RRESP` == `OKAY` |

Every testbench calls `$dumpfile("dump.vcd")` / `$dumpvars` so ChipSutra's waveform
path is exercised, prints exactly `TEST PASSED` or `TEST FAILED (<n> errors)`, ends
with `$finish`, and carries a watchdog so a stalled handshake cannot hang a run.

## Running them in ChipSutra

1. Create (or open) a project and upload the DUT **and** its testbench, e.g.
   `fifo.sv` + `fifo_tb.sv`.
2. Open the **Simulate** panel, set the top module to the testbench (`fifo_tb` /
   `axi_lite_slave_tb`), choose mode **run**, and start.
3. The log should end with `TEST PASSED` and a VCD should appear in the waveform
   viewer. Mode **lint** on the DUT alone should report zero warnings.

## Running them from the CLI

```bash
cd backend/knowledge/golden

# Lint the synthesizable DUTs (what CI checks)
verilator --lint-only -Wall fifo.sv
verilator --lint-only -Wall axi_lite_slave.sv

# Simulate the self-checking testbenches
verilator --binary --timing --trace --top-module fifo_tb fifo.sv fifo_tb.sv
./obj_dir/Vfifo_tb

verilator --binary --timing --trace --top-module axi_lite_slave_tb \
          axi_lite_slave.sv axi_lite_slave_tb.sv
./obj_dir/Vaxi_lite_slave_tb
```

Icarus Verilog works too (`iverilog -g2012 -o sim fifo.sv fifo_tb.sv && vvp sim`),
though Verilator is the engine ChipSutra actually invokes.

## Honest scope

These are **block-level** examples, deliberately small enough to lint and simulate in
seconds. They are not silicon-proven IP:

- Single clock domain only — no CDC, no async FIFO, no reset-domain crossing.
- The FIFO is first-word-fall-through with combinational `rd_data`; a real design may
  want a registered output or almost-full/almost-empty flags.
- The AXI4-Lite slave supports one outstanding transaction, always answers `OKAY`
  (no `SLVERR` decode error), ignores `AxPROT`, and is not protocol-checked against a
  VIP — pass here means "handshakes and register semantics behave", not "AXI
  compliant".
- No formal properties, no coverage closure, no timing constraints.

Treat them as regression anchors and style references, not as drop-in IP.
