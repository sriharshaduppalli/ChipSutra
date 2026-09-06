"""DUT-correct UVM smoke skeleton + mechanical repair."""
from rtl_ports import extract_modules
from tb_uvm_lint import lint_uvm_tb, repair_uvm_tb
from tb_uvm_skeleton import render_uvm_smoke_tb
from tb_lint import choose_testbench_output

COUNTER = """
module counter_en (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""

MUX = """
module mux2_8 (
  input wire sel, input wire [7:0] a, input wire [7:0] b, output wire [7:0] y
);
endmodule
"""

FIFO = """
module sync_fifo8 (
  input wire clk, input wire rst_n,
  input wire wr_en, input wire [7:0] wr_data,
  input wire rd_en,
  output wire [7:0] rd_data,
  output wire full, output wire empty
);
endmodule
"""


def test_uvm_skeleton_lints_clean():
    mods = extract_modules(COUNTER)
    sv = render_uvm_smoke_tb(mods[0], cycles=8)
    ok, issues = lint_uvm_tb(sv)
    assert ok, issues
    assert "counter_en dut" in sv or "counter_en" in sv
    assert "uvm_config_db" in sv and "run_test" in sv
    assert "uvm_analysis_imp" in sv
    assert "connect_phase" in sv
    assert "phase.raise_objection" in sv


def test_counter_uvm_has_real_scoreboard():
    mods = extract_modules(COUNTER)
    sv = render_uvm_smoke_tb(mods[0], cycles=8)
    assert "expected" in sv
    assert "count mismatch" in sv or "mismatch" in sv
    assert "seen++" not in sv.replace(" ", "")
    assert "predict/check goes here" not in sv
    assert "t.count = vif.count" in sv
    # Predict-then-check (same as Pure SV): enable updates expected before compare.
    wr = sv.split("function void write", 1)[1].split("endfunction", 1)[0]
    assert wr.find("expected = expected +") < wr.find("t.count !== expected")
    ok, issues = lint_uvm_tb(sv)
    assert ok, issues
    assert "uvm_empty_scoreboard" not in issues


def test_mux_skeleton_no_dut_clk_pin():
    mods = extract_modules(MUX)
    sv = render_uvm_smoke_tb(mods[0])
    import re

    m = re.search(r"mux2_8\s+dut\s*\(([\s\S]*?)\)\s*;", sv)
    assert m, "missing DUT instance"
    dut_map = m.group(1)
    assert ".clk(" not in dut_map
    assert ".sel(" in dut_map
    assert "mux y mismatch" in sv
    ok, issues = lint_uvm_tb(sv)
    assert ok, issues


def test_fifo_uvm_queue_golden():
    mods = extract_modules(FIFO)
    sv = render_uvm_smoke_tb(mods[0], cycles=12)
    assert "q[$]" in sv or "q.push_back" in sv
    assert "rd_data mismatch" in sv
    ok, issues = lint_uvm_tb(sv)
    assert ok, issues


def test_empty_scoreboard_lint_and_fallback():
    empty_sb = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_txn extends uvm_sequence_item;
  `uvm_object_utils(counter_en_txn)
  rand bit enable;
endclass
class counter_en_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(counter_en_scoreboard)
  uvm_analysis_imp #(counter_en_txn, counter_en_scoreboard) imp;
  int unsigned seen;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
  endfunction
  function void write(counter_en_txn t);
    seen++;
    // Independent predict/check goes here (protocol-specific)
  endfunction
endclass
class counter_en_test extends uvm_test;
  `uvm_component_utils(counter_en_test)
endclass
module counter_en_tb;
  logic clk;
  counter_en dut(.clk(clk), .rst_n(1'b1), .enable(1'b0), .count());
  initial run_test("counter_en_test");
endmodule
"""
    ok, issues = lint_uvm_tb(empty_sb)
    assert "uvm_empty_scoreboard" in issues
    mods = extract_modules(COUNTER)
    fixed = repair_uvm_tb(
        empty_sb, dut_name="counter_en", port_specs=mods[0]["ports"]
    )
    assert "expected" in fixed
    assert "predict/check goes here" not in fixed
    ok2, issues2 = lint_uvm_tb(fixed)
    assert ok2, issues2


def test_choose_uvm_falls_back_to_skeleton():
    mods = extract_modules(COUNTER)
    skel = render_uvm_smoke_tb(mods[0])
    junk = "import uvm_pkg::*;\nmodule tb; initial run_test(); endmodule\n"
    out, engine, issues = choose_testbench_output(
        junk,
        skeleton=skel,
        dut_name="counter_en",
        force_uvm=True,
        port_specs=mods[0]["ports"],
    )
    assert engine in ("llm_repaired", "skeleton_fallback")
    assert "counter_en" in out
    assert "run_test" in out
    assert "expected" in out or "scoreboard golden" in out


def test_choose_replaces_llm_placeholder_sb():
    mods = extract_modules(COUNTER)
    skel = render_uvm_smoke_tb(mods[0])
    # Mimic the user's LLM echo of the old empty skeleton
    llm = skel.replace("expected", "seen_unused").replace(
        "count mismatch", "noop"
    )
    # Force placeholder pattern
    llm = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_txn extends uvm_sequence_item;
  `uvm_object_utils(counter_en_txn)
  rand bit enable;
endclass
class counter_en_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(counter_en_scoreboard)
  uvm_analysis_imp #(counter_en_txn, counter_en_scoreboard) imp;
  int unsigned seen;
  function new(string name, uvm_component parent);
    super.new(name, parent); imp = new("imp", this); seen = 0;
  endfunction
  function void write(counter_en_txn t);
    seen++;
    // Independent predict/check goes here (protocol-specific)
  endfunction
endclass
class counter_en_agent extends uvm_agent;
  `uvm_component_utils(counter_en_agent)
endclass
class counter_en_env extends uvm_env;
  `uvm_component_utils(counter_en_env)
endclass
class counter_en_test extends uvm_test;
  `uvm_component_utils(counter_en_test)
  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    phase.drop_objection(this);
  endtask
endclass
module counter_en_tb;
  logic clk; logic rst_n; logic enable; logic [3:0] count;
  counter_en dut(.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  initial begin
    uvm_config_db#(int)::set(null, "*", "x", 0);
    run_test("counter_en_test");
  end
endmodule
"""
    out, engine, issues = choose_testbench_output(
        llm,
        skeleton=skel,
        dut_name="counter_en",
        force_uvm=True,
        port_specs=mods[0]["ports"],
    )
    assert "uvm_empty_scoreboard" in (issues or []) or "expected" in out
    assert "predict/check goes here" not in out
    assert "expected" in out


SWITCH = """
module addr_switch (
  input wire clk,
  input wire rst_n,
  input wire vld,
  input wire [7:0] addr,
  input wire [7:0] data,
  output reg [7:0] addr_a,
  output reg [7:0] data_a,
  output reg [7:0] addr_b,
  output reg [7:0] data_b
);
endmodule
"""


def test_switch_uvm_has_routing_golden():
    mods = extract_modules(SWITCH)
    sv = render_uvm_smoke_tb(mods[0], cycles=8)
    assert "port A mismatch" in sv or "addr_a" in sv
    assert "t.addr_a = vif.addr_a" in sv
    assert "t.addr_b = vif.addr_b" in sv
    assert "seen++" not in sv.replace(" ", "")
    assert "8'h3F" not in sv and "< 63" not in sv
    wr = sv.split("function void write", 1)[1].split("endfunction", 1)[0]
    assert "to_a" in wr
    assert "addr_a" in wr
    assert "< 128" in wr or "< 8'h80" in wr
    ok, issues = lint_uvm_tb(sv)
    assert ok, issues
    assert "uvm_empty_scoreboard" not in issues


def test_repair_strips_truncated_module_stub():
    """LLM often starts `module <dut>` with no endmodule; surgical top must not keep it."""
    mods = extract_modules(COUNTER)
    llm = """
import uvm_pkg::*;
`include "uvm_macros.svh"
interface counter_en_if(input logic clk);
  logic rst_n, enable; logic [3:0] count;
endinterface
class counter_en_txn extends uvm_sequence_item;
  `uvm_object_utils(counter_en_txn)
  rand bit enable; logic [3:0] count;
endclass
class counter_en_driver extends uvm_driver #(counter_en_txn);
  `uvm_component_utils(counter_en_driver)
endclass
class counter_en_monitor extends uvm_monitor;
  `uvm_component_utils(counter_en_monitor)
  uvm_analysis_port #(counter_en_txn) ap;
endclass
class counter_en_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(counter_en_scoreboard)
  uvm_analysis_imp #(counter_en_txn, counter_en_scoreboard) imp;
  logic [3:0] expected;
  function void write(counter_en_txn t);
    if (t.count !== expected) expected = expected + 1;
  endfunction
endclass
class counter_en_agent extends uvm_agent;
  `uvm_component_utils(counter_en_agent)
  uvm_sequencer #(counter_en_txn) sqr;
endclass
class counter_en_env extends uvm_env;
  `uvm_component_utils(counter_en_env)
endclass
class counter_en_test extends uvm_test;
  `uvm_component_utils(counter_en_test)
endclass
module counter_en
"""
    fixed = repair_uvm_tb(
        llm, dut_name="counter_en", port_specs=mods[0]["ports"]
    )
    import re

    mods_found = re.findall(r"\bmodule\s+(\w+)", fixed, re.I)
    assert len(mods_found) == 1, mods_found
    assert "endmodule" in fixed
    assert not re.search(r"\bmodule\s+counter_en\s*$", fixed.strip(), re.I | re.M)


def test_uvm_alu_and_parity_not_seen_plus():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts"
    for fname, needle in (("alu4.sv", "alu y mismatch"), ("sample_parity.sv", "parity mismatch")):
        mods = extract_modules((root / fname).read_text(encoding="utf-8"))
        sv = render_uvm_smoke_tb(mods[0], cycles=8)
        compact = sv.replace(" ", "")
        assert "seen++" not in compact, fname
        assert needle.split()[0] in sv.lower() or needle in sv, fname
        ok, issues = lint_uvm_tb(sv, port_specs=mods[0]["ports"])
        assert ok, (fname, issues)


def test_uvm_axi_has_handshake_driver():
    from pathlib import Path

    rtl = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "eval_suite"
        / "duts"
        / "axi_lite_slave.sv"
    ).read_text(encoding="utf-8")
    mods = extract_modules(rtl)
    sv = render_uvm_smoke_tb(mods[0], cycles=8)
    assert "s_axi_awready" in sv
    assert "model_reg" in sv
    assert "4'hF" in sv or "wstrb" in sv.lower()
    ok, issues = lint_uvm_tb(sv, port_specs=mods[0]["ports"])
    assert ok, issues
