"""Module-specific generation constraints for small local LLMs (ChipSutra-VLSI).

Appended to the Generate system prompt so free-form UVM templates and invented
ports are discouraged. User RTL / parsed port blocks still win on conflict.
"""
from __future__ import annotations

from typing import List, Optional

# Hard rules for OSS / Verilator-first testbench generation (3B-friendly).
TESTBENCH_RULES = """
HARD RULES for testbench generation (follow exactly):
1. Use ONLY the DUT module name and ports from the attached RTL / "Parsed RTL interfaces" block. Never invent signals.
2. Prefer a **Verilator-friendly pure SystemVerilog testbench** (no uvm_* unless user asks). Exact DUT port map is mandatory.
3. Prefer **randomized / constrained-random stimulus** with a golden reference model — NOT long hardcoded directed case lists.
4. Structure (keep ~50–90 lines total): timescale; clk; `reg`/`logic` stimulus; DUT instance; reset once; ONE loop using `$urandom`/`$urandom_range`; update expected model each cycle; `$error` on mismatch; `$dumpfile`/`$dumpvars`; `$finish`.
5. Protocol goldens (pick matching DUT):
   - Counter: independent `expected`; if enable then expected=expected+1; NEVER `exp = count + 1`.
   - Sync FIFO: `logic [W-1:0] q[$]`; clamp wr/rd on full/empty; check empty/full/rd_data vs queue.
   - Parity: when valid, `parity === ^data`.
   - AXI-Lite: model_reg[]; complete AW+W→B then AR→R handshakes (do not randomize all channels every cycle).
   - APB: SETUP then ACCESS; scoreboard on paddr/pwdata/prdata; wait pready with timeout.
   - 2:1 mux: y matches (sel ? b : a) or (sel ? a : b).
   - Valid/ready stream: fire when ready; $isunknown checks on outs.
   - Unknown protocol: random legal stimulus + post-reset / continuous no-X on outputs (universal auto-TB).
6. Output **only** SystemVerilog (brief // comments ok). No "Certainly!", no markdown essay after the code.
7. Name top `<dut>_tb`, instance `dut`. Match reset polarity and widths from RTL. Pass WIDTH/DEPTH if parameterized.
8. Driven signals must be `reg`/`logic` (not `wire`).
9. Clock MUST be `always #5 <clk> = ~<clk>;` (clk or aclk). Forbidden: `clk = ~clk; forever @(posedge clk)`.
10. Include `$dumpfile`/`$dumpvars` AND `$finish` before endmodule (truncation without $finish is a fail).
11. Declare variables at the start of the block (no mid-loop `int` decls if avoidable).
12. If a MANDATORY reference TB is attached, copy its structure (clock/reset/loop/golden); only adapt names/widths.
""".strip()

ASSERTIONS_RULES = """
HARD RULES for SVA:
1. Bind or write properties only against ports that exist in the attached RTL.
2. Clocked properties with disable iff (!rst_n) or the RTL's actual reset.
3. Output only SystemVerilog (assertions/bind). No chat preamble. Keep under ~60 lines.
""".strip()

COVERGROUPS_RULES = """
HARD RULES for covergroups:
1. Coverpoints only on signals present in the RTL (or clearly derived counts/states).
2. Include bins that match width/reset/enable behavior of the DUT.
3. Output only SystemVerilog. No chat preamble. Keep compact.
""".strip()

CHECKERS_RULES = """
HARD RULES for checkers:
1. Reference model must implement the DUT's actual behavior from RTL (e.g. counter increment on enable).
2. Compare only real DUT outputs. Exact port names from RTL.
3. Output only SystemVerilog. No chat preamble. Prefer a small reusable checker + random TB harness.
""".strip()

SPEC2RTL_RULES = """
HARD RULES for Spec→RTL:
1. Honor the Spec checklist: require clock, reset polarity, and an I/O list. If missing, invent a minimal interface and document assumptions in // comments; mark exploratory.
2. Prefer synthesizable RTL (no delays in always_ff; no initial for logic).
3. Name ports clearly; match any table in the spec. Parameterize WIDTH when data width is stated.
4. Output only RTL (SystemVerilog/Verilog as requested). No markdown essay after the code.
5. Include a brief module header comment: clocks, reset, and primary I/O.
""".strip()

DEBUG_RULES = """
HARD RULES for debug:
1. Use the ranked Debug classifier findings first (ports, width, X-prop, handshake timeout, scoreboard).
2. Propose the smallest concrete fix (code snippet or checklist), not a long essay.
3. If Verilator rejects UVM, recommend pure SV Fast-random TB.
4. Never invent DUT ports — regenerate from attached RTL when port-map errors appear.
""".strip()

_MODULE_RULES = {
    "testbench": TESTBENCH_RULES,
    "assertions": ASSERTIONS_RULES,
    "covergroups": COVERGROUPS_RULES,
    "checkers": CHECKERS_RULES,
    "spec2rtl": SPEC2RTL_RULES,
    "debug": DEBUG_RULES,
}

# Token caps: TB needs room for dump/finish + golden (3B often truncates at 640)
_MODULE_NUM_PREDICT = {
    "testbench": 960,
    "assertions": 700,
    "covergroups": 640,
    "checkers": 640,
    "formal_hints": 700,
    "coverage_holes": 800,
    "debug": 800,
    "rtl2spec": 900,
    "testplan": 900,
    "spec2rtl": 900,
}


def rules_for_module(module: str, *, has_ports: bool = False) -> str:
    """Return extra system-prompt rules for a generate module."""
    base = _MODULE_RULES.get(module or "", "")
    if not base:
        return ""
    if has_ports and module == "testbench":
        base += (
            "\n13. A parsed port list was provided — treat it as the contract. "
            "If your draft uses any port not in that list, rewrite before answering."
        )
    return base


def num_predict_for_module(module: str) -> int:
    """Default Ollama num_predict by module (overridable via OLLAMA_NUM_PREDICT)."""
    return int(_MODULE_NUM_PREDICT.get(module or "", 800))


def default_user_prompt(module: str, dut_hint: Optional[str] = None) -> str:
    """Fallback user text when the UI prompt is empty."""
    if module == "testbench":
        dut = dut_hint or "the attached DUT"
        return (
            f"Generate a compact (~50–90 line) Verilator-friendly SystemVerilog testbench for {dut}. "
            "Exact DUT port map. Use randomized stimulus ($urandom_range) in ONE loop with an independent "
            "golden/scoreboard — do not hardcode many directed testcases. Include VCD dump and $finish. "
            "No UVM unless I ask."
        )
    if module == "assertions":
        return "Generate compact SVA for the attached RTL using only its real ports."
    if module == "covergroups":
        return "Generate compact covergroups for the attached RTL using only its real ports/behavior."
    if module == "checkers":
        return "Generate a compact reference-model checker for the attached RTL."
    return "Please generate the requested artifact based on the attached files."


def tb_golden_hint_from_ports(port_names: Optional[List[str]] = None) -> str:
    """Short DUT-class hint injected into the LLM user prompt."""
    names = {n.lower() for n in (port_names or [])}
    if {"wr_en", "rd_en", "full", "empty"} <= names or {"wr_data", "rd_data", "full", "empty"} <= names:
        return (
            "DUT class: sync FIFO. Use queue scoreboard q[$]; check full/empty/rd_data; "
            "instantiate with WIDTH/DEPTH if parameters exist."
        )
    if "s_axi_awvalid" in names and "s_axi_arvalid" in names:
        return (
            "DUT class: AXI4-Lite slave. Use model_reg[]; AW+W then B, then AR then R; "
            "clock is aclk; reset aresetn."
        )
    if "parity" in names and ("valid" in names or "data" in names):
        return "DUT class: parity. When valid, check parity === ^data."
    if "enable" in names and ("count" in names or "q" in names):
        return "DUT class: enable-counter. Independent expected += enable; never expected = count + 1."
    if {"psel", "penable", "pwrite", "paddr", "pwdata", "pready", "prdata"} <= names:
        return "DUT class: APB slave. SETUP+ACCESS; scoreboard regs; wait pready with timeout."
    if (names & {"sel", "select"}) and (names & {"a", "in0"}) and (names & {"b", "in1"}) and (
        names & {"y", "out", "dout"}
    ):
        return "DUT class: 2:1 mux. Check y against (sel?b:a) or (sel?a:b)."
    if (names & {"valid", "tvalid", "in_valid"}) and (names & {"ready", "tready", "in_ready"}) and (
        names & {"data", "tdata", "in_data"}
    ):
        return "DUT class: valid/ready stream. Drive valid/data when ready; $isunknown on outputs."
    if "count" in names or "q" in names:
        return "DUT class: counter. Independent expected model; never circular golden from DUT outs."
    return (
        "Unknown protocol: universal auto-TB — randomize inputs, check $isunknown on outputs after reset; "
        "add a golden only when semantics are clear."
    )
