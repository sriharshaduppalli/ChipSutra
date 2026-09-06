"""Module-specific generation constraints for small local LLMs (ChipSutra-VLSI).

Appended to the Generate system prompt so free-form UVM templates and invented
ports are discouraged. User RTL / parsed port blocks still win on conflict.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from tb_methodology import normalize_methodology, rules_for_methodology

# Golden reference TBs injected into the prompt for known protocols.
# RAG only indexes .txt knowledge; these .sv goldens are the strongest signal
# a small local model gets for bus protocols — inject them directly.
_GOLDEN_DIR = Path(__file__).resolve().parent / "knowledge" / "golden"
GOLDEN_REF_BY_PROTOCOL = {
    # Bus protocols only — full gold in the prompt. Simple DUTs (counter/parity/…)
    # rely on Modelfile few-shot; injecting a 200-line gold destroys CPU TTFT.
    "axi_lite": "axi_lite_class_sv_tb.sv",
    "axi4_lite": "axi_lite_class_sv_tb.sv",
    "apb": "apb_smoke_sv_tb.sv",
    "apb3": "apb_smoke_sv_tb.sv",
    "apb4": "apb_smoke_sv_tb.sv",
}

# Protocols that get a short outline instead of a full style-reference dump.
_LIGHT_PROMPT_PROTOCOLS = frozenset(
    {
        "counter",
        "parity",
        "mux",
        "alu",
        "shifter",
        "edge",
        "cdc",
        "encoder",
        "gray",
        "debounce",
        "pwm",
        "generic",
        "riscv",
        "rv32i",
        "switch",
    }
)

LAYERED_SV_OUTLINE = """
Required Pure SV layered shape (NO UVM) — emit ALL of these:
  interface <dut>_if(input logic clk);  // DUT signals + modports
  class <dut>_txn;                      // rand + real constraint
  class <dut>_generator;                // mailbox gen2drv + randomize
  class <dut>_driver;                   // reset + drive via virtual IF
  class <dut>_monitor;                  // sample → mon2sb
  class <dut>_scoreboard;               // predict/check + connect()
  class <dut>_env;                      // build + fork/join run + report
  class <dut>_test;                     // reset, post-reset check, run
  module <dut>_tb;                      // clk, IF, DUT, t=new(vif); t.run(N);
Rules: separate mailbox new(); task→endtask; always #5 clk=~clk; independent golden.
""".strip()


def golden_ref_for_protocol(protocol: str, max_chars: int = 4500) -> str:
    """Golden TB text for a protocol, or "" when none/unavailable."""
    proto = (protocol or "").lower()
    # Skip heavy gold for simple DUTs (latency). Modelfile few-shot covers them.
    if proto in _LIGHT_PROMPT_PROTOCOLS:
        return ""
    fname = GOLDEN_REF_BY_PROTOCOL.get(proto)
    if not fname:
        return ""
    try:
        text = (_GOLDEN_DIR / fname).read_text(encoding="utf-8")
    except Exception:
        return ""
    return text[:max_chars]


# ChipVerify UVM Example 1 topology (ChipSutra wording — not a page dump).
# This is the graph 7B must copy. Concept RAG pages (subscriber, TLM get/put)
# are not a substitute for this end-to-end connect recipe.
UVM_EXAMPLE1_WIRING = """
UVM first-TB wiring (ChipVerify Example 1 shape) — emit ALL of these for THIS DUT:
  class <dut>_txn extends uvm_sequence_item;  // rand DUT inputs; observe outputs
  class <dut>_driver extends uvm_driver#(<dut>_txn);
    run_phase: seq_item_port.get_next_item(req); drive vif; item_done();
  class <dut>_monitor extends uvm_monitor;    // NEVER uvm_subscriber
    uvm_analysis_port#(<dut>_txn) ap;  sample vif; ap.write(t);
  class <dut>_sequencer is uvm_sequencer#(<dut>_txn) inside the agent
  class <dut>_agent extends uvm_agent;
    build: create sqr, drv, mon
    connect_phase: drv.seq_item_port.connect(sqr.seq_item_export);  // ONLY this pull
  class <dut>_scoreboard extends uvm_scoreboard;
    uvm_analysis_imp#(<dut>_txn, <dut>_scoreboard) imp;
    function void write(<dut>_txn t); independent golden (rst_n, not enable==0);
  class <dut>_env extends uvm_env;
    connect_phase: agent.mon.ap.connect(sb.imp);
  class <dut>_seq extends uvm_sequence#(<dut>_txn);
    task body(); start_item; randomize; finish_item;  // NEVER seq = new() of bare uvm_sequence#(T)
  class <dut>_test extends uvm_test;
    raise_objection; reset vif.rst_n; seq.start(env.agent.sqr); drop_objection;
  interface <dut>_if + module top: DUT named ports, config_db::set, run_test("...");
Legal SV only: virtual task / virtual function void — NEVER virtual void / endprotected.
""".strip()

UVM_EXAMPLE2_WIRING = """
UVM Example 2 (address switch) — SAME graph as Example 1, different golden:
  txn: rand addr/data; observe addr_a/data_a, addr_b/data_b (not rand)
  driver: pulse vld+addr+data one clk, then vld=0
  monitor extends uvm_monitor (smoke = ONE thread, not dual-thread+semaphore):
    if (rst_n && vld) capture addr/data; next posedge capture A/B outs; ap.write
  scoreboard write(): route by USER addr split (ChipVerify demo [0:'h3F] only if that is the DUT);
    low range → addr_a/data_a === addr/data; else addr_b/data_b === addr/data
  agent/env/test/seq: identical Example 1 TLM (sqr↔drv, mon.ap→sb.imp, seq.body start_item)
NEVER invent addr_a/addr_b if those ports are not on THIS DUT.
""".strip()


def style_ref_for_protocol(
    protocol: str,
    hint_tb: str = "",
    *,
    max_lines: int = 50,
    methodology: str = "sv",
) -> str:
    """Compact style reference — outline for simple DUTs, truncated TB otherwise.

    UVM must never receive the Pure SV mailbox outline. Counter/parity are
    'light' for Pure SV latency; for UVM they still need Example-1 wiring.
    """
    from tb_methodology import normalize_methodology

    meth = normalize_methodology(methodology)
    proto = (protocol or "").lower()
    if meth == "uvm":
        parts = [UVM_EXAMPLE1_WIRING]
        if proto in ("switch", "addr_switch", "addr_range_switch"):
            parts.append(UVM_EXAMPLE2_WIRING)
        if hint_tb:
            parts.append(_uvm_skeleton_connect_excerpt(hint_tb))
        return "\n\n".join(parts)
    if proto in _LIGHT_PROMPT_PROTOCOLS:
        return LAYERED_SV_OUTLINE
    if hint_tb:
        try:
            from tb_skeleton import truncate_tb_reference

            return truncate_tb_reference(hint_tb, max_lines=max_lines)
        except Exception:
            return "\n".join(hint_tb.splitlines()[:max_lines])
    return LAYERED_SV_OUTLINE


def _uvm_skeleton_connect_excerpt(sv: str) -> str:
    """Keep DUT-specific connect_phase + scoreboard write + top (not head/tail chop)."""
    import re

    chunks: list[str] = ["DUT-correct excerpts (keep these connects; adapt names):"]
    for pat, label in (
        (
            r"function void connect_phase\(uvm_phase phase\);[\s\S]*?endfunction",
            "connect",
        ),
        (
            r"function void write\([^)]*\)\s*;[\s\S]*?endfunction",
            "write",
        ),
        (
            r"\bmodule\b[\s\S]*?\bendmodule\b",
            "top",
        ),
    ):
        found = re.findall(pat, sv or "", flags=re.I)
        for block in found[:3]:
            chunks.append(block.strip())
    if len(chunks) == 1:
        return "\n".join((sv or "").splitlines()[:80])
    return "\n\n".join(chunks)

# Hard rules for OSS / Verilator-first procedural smoke TB (gen_mode=skeleton only).
TESTBENCH_SMOKE_RULES = """
HARD RULES for procedural smoke testbench (Fast-random only):
1. Use ONLY the DUT module name and ports from the attached RTL. Never invent signals.
2. Pure SystemVerilog module TB (no classes required). Exact DUT port map.
3. Structure (~50–70 lines): timescale; clock always #5; reset; ONE $urandom loop; independent golden; $dump/$finish.
4. Never drive DUT outputs. Never circular golden (exp = count + 1).
5. Output only SystemVerilog. No essay after endmodule.
""".strip()

# Injected so local models keep SV fundamentals sticky even when RAG top_k is small.
SV_FUNDAMENTALS_BRIEF = """
SV FUNDAMENTALS (must apply): DUT/DUV = user RTL only; logic+exact widths; queues for FIFO gold;
for-loops + === checks; layered OOP — interface (port bundle) + generator (txns) + driver (pin-wiggle)
+ monitor (observe) + scoreboard (independent reference compare, never check() return 1)
+ env (wire/scale) + test (configure knobs); hide pin timing in driver/tasks (abstraction);
rand+real constraints (never {1;}); mailboxes with separate new(); legal task/endfunction.
""".strip()

# Compact map for the generate system prompt (full SV_VS_UVM_BRIEF is curriculum/tests).
SV_VS_UVM_BRIEF_COMPACT = """
PURE SV vs UVM (honor methodology — never mix in one TB):
  interface → same IF + config_db virtual; txn → uvm_sequence_item;
  generator (randomize+mailbox put) → uvm_sequence body() + sequencer + seq.start(sqr) + start_item;
  driver mailbox get → uvm_driver get_next_item then drive then item_done;
  monitor mailbox put → uvm_monitor analysis_port.write (NOT uvm_subscriber);
  scoreboard mailbox get → uvm_scoreboard analysis_imp.write() (function — no @/#);
  env new()+fork/join → uvm_env + uvm_agent; test t.run(N) → uvm_test + raise/drop_objection
    (Pure SV task reset/run/report — no UVM phases).
  Pure SV new(vif, mailbox) → UVM type_id::create in build_phase; TLM only in connect_phase
    (drv.seq_item_port.connect(sqr.seq_item_export); mon.ap.connect(sb.imp) — 1-to-many analysis).
  Factory / config_db knobs; +UVM_TESTNAME; no `uvm_do; no virtual sequencer for one agent.
  Txn/seq = uvm_object; drv/mon/sqr/agent/env/test/sb = uvm_component.
  Top: always #5 clk; module not program. Verilator: Pure SV smoke; no UVM sign-off.
  NEVER mix: uvm_driver+mailbox; class *_generator in UVM; run_test/analysis_port in Pure SV.
""".strip()

SCALE_BRIEF_COMPACT = """
SCALE (honor user scale; RTL ports still win; never invent maps):
  block: one DUT in isolation; pin smoke; highest coverage bar (code AND functional plan).
  ip: still block-stage — VIP four parts (driver+monitor+checker+coverage) for reuse at integration.
  VIP ≠ BFM: a BFM only drives pins; VIP also checks protocol and collects coverage.
  processor: RV32I smoke + user memory/CSR maps as opaque model_reg keys.
  subsystem: reuse block agents on cluster IFs; hunt inter-block/CDC/reset-order bugs; user topology only.
  soc: end-to-end/boot/perf only if user listed them; emu for Linux, not Verilator. SoC PASS ≠ block sign-off.
  chiplet: UCIe/BoW/AIB user VIP; outline mainband/sideband only if those ports exist.
Bug cost rises each stage. ChipSutra does not claim sign-off.
PCIe/CXL/UCIe/DDR/USB/MIPI: still emit VIP four parts as outline; connect commercial VIP for official timings — never invent them.
""".strip()

UVM_BASICS_BRIEF_COMPACT = """
UVM BASICS (methodology=uvm): IEEE 1800.2 — uvm_component (drv/mon/sqr/agent/env/test/sb)
vs uvm_object (txn/seq). import uvm_pkg::*; `include "uvm_macros.svh".
build_phase: type_id::create. connect_phase TLM only:
  drv.seq_item_port.connect(sqr.seq_item_export); mon.ap.connect(sb.imp).
Monitor extends uvm_monitor (never uvm_subscriber). Scoreboard analysis_imp.write().
Test run_phase: raise_objection; reset rst_n; seq.start(sqr); drop_objection.
config_db vif; run_test() in module top; always #5 clk. No class *_generator / mailbox gen2drv.
""".strip()

UVM_BASICS_BRIEF = """
UVM BASICS (methodology=uvm): IEEE 1800.2 — components (uvm_component: drv/mon/sqr/agent/env/test/sb)
process objects (uvm_object/seq_item/sequence); never put txn on uvm_component.
REQUIRED: `interface <dut>_if`; `include "uvm_macros.svh"`; uvm_sequencer#(txn) in agent;
class <dut>_seq extends uvm_sequence#(txn) with task body() (never uvm_sequence#(T) seq = new()).
Hierarchy test->env->agent(sqr,drv,mon)->scoreboard; factory create in build_phase; TLM ONLY in connect_phase:
  drv.seq_item_port.connect(sqr.seq_item_export);  mon.ap.connect(sb.imp);
  NEVER seq_item_port.connect(monitor.analysis_export) or agent.seq_item_port to scoreboard.
Monitor extends uvm_monitor + analysis_port.write (NEVER extends uvm_subscriber; subscriber is SB).
Scoreboard uvm_analysis_imp + write() (never analysis_port.get / seq_item_port.get).
Legal SV only: `virtual function void` / `virtual task` — NEVER `virtual void` or `endprotected`.
NEVER mix Pure SV: no class *_generator, no mailbox gen2drv, no env.t.run(N) — those are methodology=sv.
Txn/seq are uvm_object; drv/mon/sqr/agent/env/test/sb are uvm_component — never txn extends uvm_component.
Smoke: UVM_ACTIVE, seq.start(sqr)+start_item/finish_item (not `uvm_do / default_sequence / virtual sequencer).
Golden math matches Pure SV. No RAL unless user CSR map. Module top, not program.
write() is a function — no @(posedge)/# inside it (time belongs in drv/mon run_phase).
get_next_item then drive then item_done; seq_item_port is on the driver (connect to sqr.seq_item_export).
type_id::create in build_phase with parent this; `uvm_object_utils / `uvm_component_utils; always super.*.
Top still needs always #5 clk and DUT instance. No set_config_int. No fork of a generator in uvm_env.
Pins: driver writes inputs; monitor samples; scoreboard has no virtual if; test starts seq (post-reset peek OK).
Objections only in test run_phase. No phantom `include except uvm_macros.svh. No clocking / analysis_fifo unless asked.
Reset is rst_n (or DUT reset pin) — NEVER treat enable==0 as reset.
Objections: phase.raise_objection(this) in test run_phase; config_db vif; utils macros;
real APIs only (no .put()/.configure(vif)/extends uvm_test_top/build-in-run_phase);
module top: DUT+IF+run_test(); never mix ovm_*; RAL only with user CSR map.
""".strip()

SV_VS_UVM_BRIEF = """
PURE SV vs UVM (honor methodology — never mix in one TB):
Roles (same job, different type):
  interface → same IF + config_db virtual; txn → uvm_sequence_item;
  generator (randomize+mailbox put, fixed N) → uvm_sequence body() + sequencer + seq.start(sqr);
  driver mailbox get → uvm_driver get_next_item/item_done;
  monitor mailbox put → uvm_monitor analysis_port.write (NOT uvm_subscriber);
  scoreboard mailbox get + predict/check → uvm_scoreboard analysis_imp.write();
  env new()+fork/join (holds gen/drv/mon/sb) → uvm_env + uvm_agent(sqr,drv,mon);
  test t.run(N) → uvm_test; top $finish → config_db::set + run_test() (no $finish from sequences).
Construct: Pure SV new(vif, mailbox) → UVM type_id::create; vif via config_db get in build_phase.
Connect: Pure SV mailbox 1-to-1 in env.new → UVM TLM ONLY in connect_phase
  (drv.seq_item_port.connect(sqr.seq_item_export); mon.ap.connect(sb.imp)).
  Analysis TLM is 1-to-many (SB+coverage); never mailbox gen2drv inside UVM.
Phases: Pure SV task reset/run/report → UVM build_phase / connect_phase / run_phase / report_phase
  (never .connect in build; never create children in run).
End/report: Pure SV fixed-N then $display PASS/FAIL + $finish → UVM phase.raise/drop_objection(this)
  and `uvm_info/`uvm_error in report_phase.
Coverage: Pure SV covergroup (`ifndef VERILATOR) → UVM uvm_subscriber on analysis (not the monitor).
Reset: both use driver/test reset on rst_n — never treat enable==0 as reset.
Plusargs: Pure SV +SEED/+N → UVM +UVM_TESTNAME/+UVM_VERBOSITY.
Object vs component: Pure SV all plain classes. UVM txn/seq = uvm_object; drv/mon/sqr/agent/env/test/sb = uvm_component (never txn extends uvm_component). Generator is object-like → sequence, not a UVM component.
Active/passive: Pure SV always drives if generator exists. UVM agent is_active; smoke UVM_ACTIVE. No virtual sequencer for a single-agent TB.
Golden: SAME math both stacks (counter/FIFO/mux/parity/switch); only predict/check vs write() changes.
Sequence API: UVM seq.start(sqr) + start_item/finish_item in body(); no `uvm_do, no default_sequence, no get_response unless DUT returns data. Pure SV has none of these.
Top: both use module (not program). Pure SV $dump+$finish; UVM run_test (no $finish from sequence).
Events/RAL: Pure SV event/semaphore teaching-only; UVM uvm_event. RAL/uvm_reg only with user CSR map (Pure SV uses assoc/model_reg).
Constraints on txn/item, never on the driver. UVM factory override = reuse; Pure SV = copy/adapt.
Time: Pure SV gen/drv/mon tasks + @(posedge); SB run() may mailbox.get. UVM time only in run_phase tasks; write() is a function — no @/# inside write().
Driver order: get then drive (UVM get_next_item → drive → item_done). Never item_done before drive; never seq_item_port.put.
TLM polarity: seq_item_port on driver, seq_item_export on sequencer (drv.seq_item_port.connect(sqr.seq_item_export) — never reverse, never port→monitor).
Create: Pure SV new(vif,mb) in env. UVM type_id::create("name", this) in build_phase; super.new/build/connect; `uvm_object_utils on txn/seq; `uvm_component_utils on components. No set_config_int (OVM).
Preamble: Pure SV timescale. UVM import uvm_pkg::* + `include "uvm_macros.svh" before classes.
Top clock: BOTH always #5 clk=~clk and named DUT map — run_test() does not create clk.
Concurrency: Pure SV env fork gen/drv/mon/sb. UVM components each have run_phase — do not fork a generator inside uvm_env.
Pins: only driver writes DUT inputs; only monitor samples; SB has no virtual if (txn in); test/seq do not pin-wiggle the stimulus loop (post-reset peek OK). Monitor never vif.*=.
Knobs: Pure SV +N/+SEED. UVM config_db + +UVM_TESTNAME (not resource_db / set_config_int). Extra test = extra uvm_test; factory override only if asked.
Objections: raise/drop in test run_phase only (not in body()).
SVA/cover: interface/bind or module `ifndef VERILATOR; never assert property inside write(). UVM coverage = subscriber, not the monitor.
Smoke file: one .sv; `include "uvm_macros.svh" only; no clocking block; no uvm_tlm_analysis_fifo unless asked.
Reuse: Pure SV = copy/adapt this DUT. UVM = factory override, extra sequences/tests, agent-as-VIP.
Scale: Pure SV = Verilator block smoke. UVM = multi-agent / virtual seq / RAL (commercial sim; no Verilator UVM sign-off).
Never mix: uvm_driver+mailbox get; class *_generator in UVM; run_test/analysis_port in Pure SV; monitor extends uvm_subscriber; `uvm_do in Pure SV; program block unless asked.
""".strip()

# Default Pure SV = layered ChipVerify-style OOP (NO UVM).
TESTBENCH_RULES = """
HARD RULES for Pure SV LAYERED class testbench (match premium-model quality):
1. Use ONLY the DUT module name and ports from the attached RTL / parsed port list. Never invent signals.
2. Emit CLASS-BASED SystemVerilog — NO uvm_*, ovm_*, or vmm_* macros/base classes,
   no `include "uvm_macros.svh", no run_test(), no analysis_port (that is methodology=uvm).
3. Required components (ALL of them — this is the default Pure SV template):
   - `interface <dut>_if(input logic clk);` with DUT signals + modports DRV/MON;
   - `class <dut>_txn;` with `rand` fields + REAL constraint (e.g. `enable inside {[0:1]};` — NEVER `{1;}`);
   - `class <dut>_generator;` — randomizes txns into a mailbox (gen2drv);
   - `class <dut>_driver;` — gets txns, drives via `virtual <dut>_if`, reset task;
   - `class <dut>_monitor;` — samples DUT activity into mon2sb mailbox;
   - `class <dut>_scoreboard;` — `function void predict(...)` + `function bit check(...)`
     (NEVER `task check` with `return`; NEVER `expected <=` — use blocking `=`);
     independent golden (FIFO: `q[$]` / count===q.size());
     time lives in gen/drv/mon tasks (`@(posedge)`); predict/check stay functions.
   - `class <dut>_env;` — builds gen/drv/mon/sb + mailboxes; `fork…join` run;
   - `class <dut>_test;` — builds env, calls reset, post-reset output checks, run, report;
   - `module <dut>_tb` (NOT `program` by default — Verilator-first; program only if user asks):
     clock `always #5 clk=~clk;`, instantiate IF + DUT (ports via vif),
     construct test, `t.run(N);`, `$dumpfile`/`$dumpvars`/`$finish`.
4. Scoreboard `errors = 0` in new(); ONE PASS/FAIL $display from env.report().
5. After reset deassert: check key outputs === '0 BEFORE stimulus (e.g. count).
6. Keep ~140–220 lines. Output ONLY SystemVerilog. No markdown essay.
7. Never drive DUT outputs. CLASS SCOPING: methods use only args + own members —
   declare scoreboard fields (`logic […] expected;`) before use; module owns `errors`
   (never `sb.errors++` unless SB declares `errors`).
   Only the driver writes DUT inputs; the monitor samples; the scoreboard uses
   txn fields (no vif); the test starts env.run — it does not pin-wiggle the loop.
8. Combo DUT (no clk/rst ports): do NOT invent DUT `.clk`/`.rst_n` pins; TB may keep a
   local clock for stimulus pacing. No reset assert/deassert when DUT has no reset.
9. FIFO: clamp `txn.wr_en=0` when `sb.q.size()>=DEPTH` and `txn.rd_en=0` when empty
   before drive; predict then check FWFT `rd_data===q[0]` only when `q.size()>0`.
   NEVER check `rd_data==='0` after reset (FWFT mem is X). After the stimulus loop,
   pulse reset and check empty===1 / full===0 (kills drop_reset).
10. ALWAYS close the TB with `endmodule`. Never stop mid-assignment.
11. Sequential DUTs: after stimulus, mid-test reset then check key outputs === '0.
12. Optional: `ifndef VERILATOR` covergroup at module scope.
13. RISC-V-like DUT: directed RV32I smoke (reset, NOP/ADDI, PC+4); never invent Spike/AXI/CSR maps unless those ports exist.
""".strip()

ASSERTIONS_RULES = """
HARD RULES for SVA:
1. Bind or write properties only against ports that exist in the attached RTL.
2. Every concurrent assertion/cover MUST be clocked: @(posedge <clk>) disable iff (!<rst_n>).
3. Prefer assert property / cover property; never invent data_in/data_out.
4. Output only SystemVerilog (assertions/bind). No chat preamble. Keep under ~60 lines.
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

# Token caps: class-based Pure SV needs more room than smoke TB
_MODULE_NUM_PREDICT = {
    "testbench": 1100,
    "assertions": 640,
    "covergroups": 600,
    "checkers": 600,
    "formal_hints": 700,
    "coverage_holes": 800,
    "debug": 720,
    "rtl2spec": 900,
    "testplan": 900,
    "spec2rtl": 900,
}


def rules_for_module(
    module: str,
    *,
    has_ports: bool = False,
    tb_methodology: str = "sv",
) -> str:
    """Return extra system-prompt rules for a generate module."""
    meth = normalize_methodology(tb_methodology)
    if module == "testbench":
        base = rules_for_methodology(meth) if meth != "sv" else TESTBENCH_RULES
        # Always attach methodology prompt intent for TB
        if meth == "sv":
            base = TESTBENCH_RULES
    else:
        base = _MODULE_RULES.get(module or "", "")
    if not base and module != "testbench":
        return ""
    if has_ports and module == "testbench":
        base += (
            "\n8. A parsed port list was provided — treat it as the contract. "
            "If your draft uses any port not in that list, rewrite before answering."
        )
        if meth == "sv":
            base += (
                "\n9. Protocol goldens: counter expected+=enable; FIFO q[$]; parity ^data; "
                "AXI-Lite model_reg + handshakes. Prefer class fields matching these."
            )
    # Compact briefs on the generate path — the full essays destroy 7B TTFT.
    if module in ("testbench", "assertions", "covergroups", "checkers"):
        base = (base + "\n\n" + SV_FUNDAMENTALS_BRIEF).strip()
    if module == "testbench":
        base = (base + "\n\n" + SV_VS_UVM_BRIEF_COMPACT + "\n\n" + SCALE_BRIEF_COMPACT).strip()
    if module == "testbench" and meth == "uvm":
        base = (base + "\n\n" + UVM_BASICS_BRIEF_COMPACT).strip()
    return base


_SIMPLE_TB_PROTOCOLS = frozenset(
    {
        "counter",
        "parity",
        "mux",
        "alu",
        "shifter",
        "edge",
        "cdc",
        "encoder",
        "gray",
        "debounce",
        "pwm",
        "generic",
        "fsm",
    }
)


def num_predict_for_module(
    module: str,
    *,
    tb_methodology: str = "sv",
    protocol: str = "generic",
) -> int:
    """Token budget; class methodologies and Pure SV OOP need more than smoke.

    Simple/combinational protocols use a tighter cap (G10 latency).
    """
    meth = normalize_methodology(tb_methodology)
    if module == "testbench" and meth in ("uvm", "ovm", "vmm"):
        return int(os.environ.get("OLLAMA_NUM_PREDICT_CLASS", "1400"))
    if module == "testbench" and meth == "sv":
        proto = (protocol or "generic").lower()
        # Layered Pure SV needs room, but oversized num_predict burns CPU decode time.
        if proto in _SIMPLE_TB_PROTOCOLS:
            return int(os.environ.get("OLLAMA_NUM_PREDICT_SV_SIMPLE", "1100"))
        return int(os.environ.get("OLLAMA_NUM_PREDICT_SV_CLASS", "1500"))
    return int(_MODULE_NUM_PREDICT.get(module or "", 800))


def default_user_prompt(
    module: str,
    dut_hint: Optional[str] = None,
    *,
    tb_methodology: str = "sv",
) -> str:
    """Fallback user text when the UI prompt is empty."""
    if module == "testbench":
        dut = dut_hint or "the attached DUT"
        meth = normalize_methodology(tb_methodology)
        if meth == "uvm":
            return (
                f"Generate a compact UVM 1.2 testbench for {dut}: sequence_item, sequencer, "
                "driver, monitor, agent, env, test, and top with uvm_config_db + run_test(). "
                "Factory create in build_phase; TLM connect only in connect_phase; "
                "objections in run_phase; analysis_imp.write() scoreboard. "
                "Exact DUT ports. Real UVM APIs only. One sequence with task body(). "
                "Do not emit a Pure SV generator, mailbox gen2drv, or t.run(N)."
            )
        if meth == "ovm":
            return (
                f"Generate a compact OVM (legacy) testbench for {dut} with ovm_* components "
                "and run_test(). Exact DUT ports. Do not use uvm_* macros. "
                "OVM+VMM mix only if the user asked: interconnected adapters, not wrappers."
            )
        if meth == "vmm":
            return (
                f"Generate a compact VMM-style (legacy) testbench for {dut} with vmm_data / "
                "channel / xactor layers and a top. Exact DUT ports. "
                "Do not emit uvm_*. Channel↔TLM adapters only if mixing with OVM was requested."
            )
        return (
            f"Generate a LAYERED Pure SystemVerilog testbench for {dut} (NO UVM). "
            "Required components: interface, generator, driver, monitor, scoreboard, "
            "environment, test, and top module. "
            "Txn class with rand+constraints; mailboxes between gen→drv and mon→sb; "
            "tasks reset/run/report (no UVM phases); independent golden; exact DUT ports; "
            "$dumpfile/$dumpvars/$finish. "
            "Do not emit uvm_*, run_test(), analysis_port, objections, or a bare "
            "$urandom-only procedural TB or txn+scoreboard-only shortcut."
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
            "DUT class: sync FIFO (FWFT). Queue scoreboard q[$]; after randomize clamp "
            "wr_en=0 if sb.q.size()>=DEPTH and rd_en=0 if empty; @(posedge); #1; predict then "
            "check empty/full/count===q.size() and (q.size()==0 || rd_data===q[0]). "
            "Do not check rd_data==='0 after reset (mem may be X). After the stimulus "
            "loop pulse reset and check empty===1/full===0/count===0. Instantiate WIDTH/DEPTH."
        )
    if "s_axi_awvalid" in names and "s_axi_arvalid" in names:
        return (
            "DUT class: AXI4-Lite slave. Prefer class txn+scoreboard with predict_write(sel,data) "
            "taking txn fields as args. Drive s_axi_wstrb=4'hF on every write. "
            "AW+W then B, then AR then R; clock aclk; reset aresetn. "
            "Wait ready/valid with timeout; check BRESP/RRESP===2'b00 and RDATA vs model_reg. "
            "Finish the full module with endmodule — never truncate mid-assignment. "
            "AWVALID without WVALID must not write. After stimulus, reset and read all regs === 0."
        )
    if "parity" in names and ("valid" in names or "data" in names):
        return "DUT class: parity. When valid, check parity === ^data. After reset AND after a mid-test reset pulse check parity/valid_out==='0."
    if {"addr_a", "addr_b"} <= names and {"data_a", "data_b"} <= names:
        return (
            "DUT class: address-range switch. Route {addr,data} to port A vs B by the "
            "USER addr split (do not invent a threshold). UVM: Example 2 golden in "
            "scoreboard write(); same Example 1 TLM graph. Single-thread monitor: "
            "sample in on vld, next clock sample addr_a/data_a and addr_b/data_b."
        )
    if "enable" in names and ("count" in names or "q" in names):
        return (
            "DUT class: enable-counter. Independent expected += enable; never expected = count + 1. "
            "After reset deassert check count==='0 before stimulus."
        )
    if {"psel", "penable", "pwrite", "paddr", "pwdata", "pready", "prdata"} <= names:
        return (
            "DUT class: APB slave. SETUP (PSEL&&!PENABLE) then ACCESS (PSEL&&PENABLE); "
            "model_reg[]; wait PREADY with timeout; check PRDATA. "
            "PENABLE without PSEL must not write. After stimulus, reset and read all regs === 0."
        )
    if {"haddr", "htrans", "hrdata"} <= names:
        return "DUT class: AHB-Lite slave. Nonseq HTRANS=2'b10; wait HREADYOUT; model mem[]; check HRDATA/HRESP."
    if {"s_axis_tvalid", "s_axis_tdata"} <= names or (
        {"tvalid", "tdata"} <= names and ("tready" in names or "s_axis_tready" in names)
    ):
        return "DUT class: AXI-Stream. Drive tvalid/tdata when tready; timeout on handshake; check sink outputs."
    if {"can_rx", "can_tx"} <= names or {"canrx", "cantx"} <= names:
        return (
            "DUT class: CAN. Recessive idle can_rx=1; check can_tx not X. "
            "SOF dominant pulse only if user set can_bit_clocks. Do not invent bit-time/CRC."
        )
    if names & {"ibi", "ccc", "ibi_req"}:
        return (
            "DUT class: I3C. I2C-compatible unless CCC/IBI ports exist. "
            "Do not invent MIPI timings or CCC encodings."
        )
    if {"sclk", "mosi", "miso"} <= names:
        return (
            "DUT class: SPI slave. Assert cs_n, shift MSB-first. "
            "Mode0 default (drive negedge, sample posedge). Honor user spi_mode 0–3."
        )
    if {"scl", "sda_in"} <= names or {"scl", "sda"} <= names:
        return (
            "DUT class: I2C. Default 7-bit slave START+data. "
            "Master/10-bit only if user knobs say so. Stretch time from user only."
        )
    if {"tx", "din", "start"} <= names:
        return "DUT class: UART TX. Pulse start, wait done/busy, sample tx line for 8N1."
    if {"rx", "dout"} <= names or {"rxd", "rx_data"} <= names or {"rx", "rx_valid"} <= names:
        return (
            "DUT class: UART RX. Idle HIGH, start=0, 8 data LSB-first, stop=1. "
            "Hold each bit uart_baud_div clocks (1 if unset). Do not invent baud."
        )
    if (names & {"instr", "instruction", "imem_rdata", "inst", "instr_rdata"}) and (
        names & {"pc", "iaddr", "imem_addr", "instr_addr"}
    ):
        return (
            "DUT class: RISC-V RV32I-like (experimental). Directed smoke only: reset, "
            "drive NOP (`32'h00000013`), check PC +4 if no stall; optional ADDI writeback "
            "IF the DUT exposes wb/rd. Timeout every mem ready. Do not invent Spike, "
            "AXI/TileLink, or a CSR/RAL map."
        )
    if (names & {"sel", "select"}) and (names & {"a", "in0"}) and (names & {"b", "in1"}) and (
        names & {"y", "out", "dout"}
    ):
        return (
            "DUT class: 2:1 mux (combinational). No DUT clk/rst pins — do not connect invented "
            "reset. Scoreboard: declare expected OR check(sel,a,b,y) with y===(sel?b:a). "
            "Real constraint on sel; local TB clock OK for pacing only."
        )
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
