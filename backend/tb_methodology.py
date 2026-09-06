"""Testbench methodology selection: pure SV, UVM, OVM, VMM.

Users pick methodology explicitly; ChipSutra routes skeleton vs LLM and prompt rules.

Pure SV = layered class SystemVerilog (IF/gen/drv/mon/sb/env/test),
NOT the procedural $urandom smoke template (that is gen_mode=skeleton only).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Canonical ids exposed in the UI / API
METHODOLOGIES = ("sv", "uvm", "ovm", "vmm")

_ALIASES = {
    "sv": "sv",
    "systemverilog": "sv",
    "pure_sv": "sv",
    "verilog": "sv",
    "plain": "sv",
    "class_sv": "sv",
    "uvm": "uvm",
    "uvm12": "uvm",
    "uvm1.2": "uvm",
    "ovm": "ovm",
    "vmm": "vmm",
    "vera": "vmm",
}

_PROMPT_HINTS = {
    "uvm": re.compile(r"\b(uvm|uvm_|sequencer|sequence_item|uvm_agent)\b", re.I),
    "ovm": re.compile(r"\bovm(?:_|\b)", re.I),
    "vmm": re.compile(r"\bvmm(?:_|\b)", re.I),
}

LABELS = {
    "sv": "Pure SV (class-based)",
    "uvm": "UVM",
    "ovm": "OVM (legacy)",
    "vmm": "VMM (legacy)",
}


def normalize_methodology(value: Optional[str], *, prompt: str = "") -> str:
    """Return sv|uvm|ovm|vmm. Default sv; auto-detect from prompt when value is auto/empty."""
    raw = (value or "").strip().lower()
    if raw in ("", "auto", "default"):
        for mid, pat in _PROMPT_HINTS.items():
            if pat.search(prompt or ""):
                return mid
        return "sv"
    key = raw.replace("-", "_").replace(" ", "_")
    return _ALIASES.get(key, "sv" if key not in METHODOLOGIES else key)


def is_class_methodology(methodology: str) -> bool:
    """True for UVM/OVM/VMM library methodologies (not Pure SV OOP)."""
    return normalize_methodology(methodology) in ("uvm", "ovm", "vmm")


def wants_oop_tb(methodology: str) -> bool:
    """True when generated TB should use classes (Pure SV OOP or UVM/OVM/VMM)."""
    return normalize_methodology(methodology) in METHODOLOGIES


def methodology_prompt_block(methodology: str) -> str:
    m = normalize_methodology(methodology)
    if m == "sv":
        return (
            "METHODOLOGY: Pure SystemVerilog LAYERED class testbench (NO uvm_*/ovm_*/vmm_*). "
            "Emit ALL of: (1) interface with DUT signals + modports; "
            "(2) txn class with rand + real constraints; "
            "(3) generator (mailbox stimulus); (4) driver; (5) monitor; "
            "(6) scoreboard with independent predict/check; "
            "(7) environment that builds components + fork/join run; "
            "(8) test that resets, post-reset checks, runs env, reports; "
            "(9) top module: clock, IF, DUT via vif, construct test, $dumpfile/$dumpvars/$finish. "
            "Do NOT emit txn+scoreboard-only or bare $urandom smoke unless user asks for procedural smoke."
        )
    if m == "uvm":
        return (
            "METHODOLOGY: UVM 1.2 (IEEE 1800.2). Hierarchy: test→env→agent(sequencer,driver,monitor)→scoreboard. "
            "Emit sequence_item, sequence, driver, monitor, sequencer, agent, scoreboard, env, test, top. "
            "Phases: build (create ONLY) → connect_phase (ALL TLM .connect) → run (phase.raise_objection). "
            "Scoreboard: uvm_analysis_imp + write() — never analysis_port.get / extends uvm_test_top. "
            "Top module: instantiate DUT+IF, uvm_config_db#(virtual if)::set, run_test(\"…\"). "
            "Real APIs only: get_next_item/item_done, start_item/finish_item, analysis_port.write. "
            "Match DUT ports exactly. Never mix ovm_*. Full UVM may need commercial sim — still emit correct UVM."
        )
    if m == "ovm":
        return (
            "METHODOLOGY: OVM (legacy Accellera). Emit compact OVM components: "
            "ovm_sequence_item, sequencer, driver, monitor, agent, env, test, and top that calls run_test(). "
            "Use OVM macros/APIs (not UVM). Match DUT ports exactly. Mark as legacy / commercial-sim oriented."
        )
    # vmm
    return (
        "METHODOLOGY: VMM (legacy Synopsys). Emit compact VMM-style layers: "
        "vmm_data transaction, vmm_channel, atomic generator / xactor driver & monitor, "
        "scoreboard, env, and a top program/module. Use VMM base classes/macros where appropriate. "
        "Match DUT ports exactly. Mark as legacy / VCS-oriented."
    )


def rules_for_methodology(methodology: str) -> str:
    m = normalize_methodology(methodology)
    if m == "sv":
        return """
HARD RULES for Pure SV layered class testbench (NO UVM):
1. Output SystemVerilog only. No uvm_*, ovm_*, vmm_* macros or base classes.
2. Exact DUT module name and ports from RTL. Named port map only.
3. Required structure (all components):
   - interface <dut>_if; class <dut>_txn; class <dut>_generator;
   - class <dut>_driver; class <dut>_monitor; class <dut>_scoreboard;
   - class <dut>_env; class <dut>_test; module <dut>_tb.
4. Mailboxes connect gen→drv and mon→sb (1-to-1 put/get). Independent golden (never exp = dut_out + 1).
5. Use task reset/run/report and fork/join — no UVM phases, no objections, no run_test(), no analysis_port.
6. Include $dumpfile/$dumpvars and $finish. Keep ~140–220 lines.
7. Clock: always #5 clk = ~clk. Drive via virtual interface. Never drive DUT outputs.
""".strip()
    if m == "uvm":
        return """
HARD RULES for UVM testbench (IEEE 1800.2 / UVM 1.2 style):
1. Output UVM SystemVerilog only (classes + top). No chat essay after endmodule.
2. Exact DUT port names from RTL. MUST emit `interface <dut>_if` (virtual if is not a type without it)
   + uvm_config_db set/get (fatal if missing). `include "uvm_macros.svh"`.
3. Components (`uvm_component`) vs objects (`uvm_sequence_item`/`uvm_sequence`/`uvm_object`) —
   never extend a transaction from uvm_component; never build children in run_phase.
4. Required: seq_item (`uvm_object_utils`), class <dut>_seq extends uvm_sequence#(txn) with task body()
   (NEVER `uvm_sequence#(T) seq = new()`), uvm_sequencer#(txn), driver (`get_next_item`/`item_done`),
   monitor extends uvm_monitor (`analysis_port.write` — NEVER extends uvm_subscriber),
   agent, scoreboard (independent predict; rst_n is reset — NEVER enable==0 as reset), env, test, top `run_test()`.
5. Construct in build_phase via factory `type_id::create`; TLM `.connect` ONLY in connect_phase; always `super.*`.
   Legal: drv.seq_item_port.connect(sqr.seq_item_export); mon.ap.connect(sb.imp).
   Illegal: seq_item_port.connect(monitor.*) or agent.seq_item_port to scoreboard.
6. Raise/drop via `phase.raise_objection(this)` in test run_phase around seq.start(sqr). Use `uvm_info`/`uvm_error`/`uvm_fatal`.
7. Real UVM APIs only — never invent `.put()`, `.configure(vif)`, `driver.start(this)`, `extends uvm_test_top`,
   `run_phase.raise_objection`, scoreboard `analysis_port.get` / `seq_item_port.get`.
8. Legal SV: `virtual function void foo();` / `virtual task foo();` — NEVER `virtual void` or `endprotected`.
9. Keep compact (~120–220 lines). One random sequence; no invented RAL maps. Never mix ovm_*.
""".strip()
    if m == "ovm":
        return """
HARD RULES for OVM testbench:
1. Output OVM SystemVerilog only. Use ovm_* base classes/macros (not uvm_*).
2. Exact DUT ports. Compact agent/env/test/top with run_test().
3. Mark top comment: // ChipSutra methodology=ovm (legacy).
4. Keep compact; one sequence driving legal stimulus.
""".strip()
    return """
HARD RULES for VMM testbench:
1. Output VMM-style SystemVerilog only (vmm_data / channel / xactor patterns).
2. Exact DUT ports. Compact env + top.
3. Mark top comment: // ChipSutra methodology=vmm (legacy).
4. Keep compact; legal randomized stimulus.
""".strip()


def plan_note_for_methodology(methodology: str) -> str:
    m = normalize_methodology(methodology)
    return {
        "sv": "Pure SV: always LLM (class-based by default; smoke style optional).",
        "uvm": "UVM: always LLM.",
        "ovm": "OVM: always LLM (legacy).",
        "vmm": "VMM: always LLM (legacy).",
    }[m]


def intent_from_methodology(methodology: str) -> Dict[str, Any]:
    m = normalize_methodology(methodology)
    return {
        "methodology": m,
        "label": LABELS[m],
        "class_based": is_class_methodology(m),
        "oop_tb": True,
        "allows_skeleton": m == "sv",
    }
