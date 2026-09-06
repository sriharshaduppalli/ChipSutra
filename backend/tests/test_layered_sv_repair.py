"""Mechanical repair for mangled layered Pure SV TBs."""
from tb_class_lint import (
    lint_class_sv_tb,
    repair_class_sv_tb,
    repair_layered_sv_syntax,
    score_class_sv_competitive,
)

PORTS = ["clk", "rst_n", "enable", "count"]
SPECS = [
    {"name": "clk", "direction": "input", "width": ""},
    {"name": "rst_n", "direction": "input", "width": ""},
    {"name": "enable", "direction": "input", "width": ""},
    {"name": "count", "direction": "output", "width": "[3:0]"},
]

# Condensed from a real llm_repaired counter run (architecture OK, SV mangled)
BROKEN_LAYERED = r"""
`timescale 1ns / 1ps
interface counter_rtl_if(input logic clk);
  logic rst_n; logic enable; logic [3:0] count;
  modport DRV(input clk, output enable, rst_n, input count);
  modport MON(input clk, input rst_n, enable, count);
endinterface
class counter_rtl_txn;
  rand bit enable;
  constraint legal_c { enable inside {[0:1]}; }
endclass
class counter_rtl_mon_pkt;
  logic enable; logic [3:0] count;
endclass
class counter_rtl_generator;
  mailbox #(counter_rtl_txn) gen2drv; int n_txns;
  function new(mailbox #(counter_rtl_txn) mb, int n); gen2drv=mb; n_txns=n; endfunction
  task run();
    counter_rtl_txn t;
    repeat (n_txns) begin t=new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class counter_rtl_driver;
  virtual counter_rtl_if vif;
  mailbox #(counter_rtl_txn) gen2drv, drv2sb;
  function new(virtual counter_rtl_if vif, mailbox #(counter_rtl_txn) g, mailbox #(counter_rtl_txn) d);
    this.vif=vif; gen2drv=g; drv2sb=d;
  endfunction
  task reset(); vif.rst_n=0; vif.enable=0; repeat(4) @(posedge vif.clk); vif.rst_n=1; @(posedge vif.clk); endtask
  task run(int n); counter_rtl_txn t; repeat(n) begin gen2drv.get(t); @(posedge vif.clk); vif.enable=t.enable; drv2sb.put(t); end endtask
endclass
class counter_rtl_monitor;
  virtual counter_rtl_if vif; mailbox #(counter_rtl_mon_pkt) mon2sb;
  function new(virtual counter_rtl_if vif, mailbox #(counter_rtl_mon_pkt) mb); this.vif=vif; mon2sb=mb; endfunction
  task run(int n); counter_rtl_mon_pkt p; repeat(n) begin @(posedge vif.clk); #1; p=new(); p.enable=vif.enable; p.count=vif.count; mon2sb.put(p); end endtask
endclass
class counter_rtl_scoreboard;
  mailbox #(counter_rtl_txn) drv2sb; mailbox #(counter_rtl_mon_pkt) mon2sb;
  logic [3:0] expected; int errors;
  function new(); expected='0; errors=0; endfunction
  function void predict(bit enable); if (enable) expected = expected + 1'b1; endfunction
  function bit check(logic [3:0] actual); return (actual === expected); endfunction
  task run(int n);
    counter_rtl_txn t; counter_rtl_mon_pkt p;
    repeat (n) begin drv2sb.get(t); mon2sb.get(p); predict(t.enable);
      if (!check(p.count)) begin $error("mismatch"); errors++; end
    end
  endfunction
endclass
class counter_rtl_env;
  virtual counter_rtl_if vif;
  mailbox #(counter_rtl_txn) gen2drv, drv2sb, mon2sb;
  counter_rtl_generator gen; counter_rtl_driver drv; counter_rtl_monitor mon; counter_rtl_scoreboard sb;
  function new(virtual counter_rtl_if vif); this.vif=vif; endfunction
  function void build(int n);
    gen2drv=drv2sb=mon2sb=new();
    gen=new(gen2drv,n); drv=new(vif,gen2drv,drv2sb); mon=new(vif,mon2sb); sb=new();
    sb.connect(drv2sb,mon2sb);
  endfunction
  task run(int n); fork gen.run(); drv.run(n); mon.run(n); sb.run(n); join; endtask
  function void report() { if (sb.errors==0) $display("PASS"); else $display("FAIL"); }
endclass
class counter_rtl_test;
  virtual counter_rtl_if vif; counter_rtl_env env;
  function new(virtual counter_rtl_if vif) { this.vif = vif; env=new(vif); }
  task run(int n=32);
    env.build(n); env.drv.reset(); env.run(n); env.report();
  endtask
endclass
module counter_rtl_tb;
  logic clk;
  counter_rtl_if vif(clk);
  counter_rtl_test t(vif);
  counter_rtl dut(.clk(clk), .rst_n(vif.rst_n), .enable(vif.enable), .count(vif.count));
  initial forever #5 clk = ~clk;
  initial begin
    if (count !== '0) errors++;
    t.run(32); $finish;
  end
endmodule
"""


def test_layered_syntax_flags_broken():
    ok, issues = lint_class_sv_tb(
        BROKEN_LAYERED, required_ports=PORTS, dut_outputs=["count"], port_specs=SPECS
    )
    assert "layered_syntax_broken" in issues
    assert not ok


def test_repair_layered_recovers_or_falls_back_to_skeleton():
    fixed = repair_class_sv_tb(
        BROKEN_LAYERED,
        required_ports=PORTS,
        dut_outputs=["count"],
        port_specs=SPECS,
        dut_name="counter_rtl",
    )
    assert "interface counter_rtl_if" in fixed
    assert "class counter_rtl_generator" in fixed
    assert "class counter_rtl_env" in fixed
    assert "class counter_rtl_test" in fixed
    assert not _still_broken(fixed)
    # Must not instantiate class like a module
    assert "counter_rtl_test t(vif)" not in fixed.replace(" ", "")
    score = score_class_sv_competitive(
        fixed, required_ports=PORTS, dut_outputs=["count"], port_specs=SPECS
    )
    assert score["checks"]["has_interface"]
    assert score["checks"]["has_generator"]
    assert score["checks"]["has_env"]
    assert score["score"] >= 85


def test_repair_layered_syntax_fixes_task_endfunction():
    sv = repair_layered_sv_syntax(BROKEN_LAYERED)
    assert "endfunction" not in sv.split("task run(int n);")[1].split("endclass")[0] or (
        "endtask" in sv
    )
    assert "gen2drv = new(); drv2sb = new(); mon2sb = new();" in sv.replace(" ", "") or (
        "gen2drv = new()" in sv and "drv2sb = new()" in sv
    )


def _still_broken(sv: str) -> bool:
    from tb_class_lint import _layered_syntax_broken

    return _layered_syntax_broken(sv)
