"""Class-based Pure SV lint/repair + competitive score."""
import re
from pathlib import Path

from tb_class_lint import lint_class_sv_tb, repair_class_sv_tb, score_class_sv_competitive
from tb_lint import choose_testbench_output
from tb_llm_repair import should_llm_repair

GOLD = Path(__file__).resolve().parents[1] / "knowledge" / "golden" / "counter_class_sv_tb.sv"
PORTS = ["clk", "rst_n", "enable", "count"]

# User's 7B sample that omitted `logic enable` and used noop constraint
USER_7B_BROKEN = """
`timescale 1ns / 1ps
class counter_rtl_txn;
  rand bit enable;
  constraint legal_c { 1; }
endclass
class counter_rtl_scoreboard;
  logic [3:0] expected;
  function new(); expected = '0; endfunction
  function void predict(bit enable);
    if (enable) expected = expected + 1'b1;
  endfunction
  function bit check(logic [3:0] actual);
    return (actual === expected);
  endfunction
endclass
module counter_rtl_tb;
  logic clk, rst_n;
  logic [3:0] count;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("counter_rtl_tb.vcd");
    $dumpvars(0, counter_rtl_tb);
    automatic counter_rtl_txn txn = new();
    automatic counter_rtl_scoreboard sb = new();
    int i, errors;
    clk = 0; rst_n = 0; enable = 0;
    repeat (4) @(posedge clk);
    rst_n = 1;
    for (i=0; i<32; i++) begin
      assert(txn.randomize()) else $fatal(1, "randomize failed");
      enable = txn.enable;
      @(posedge clk);
      #1;
      sb.predict(txn.enable);
      if (!sb.check(count)) begin
        $error("mismatch");
        errors++;
      end
    end
    if (errors == 0)
      $display("PASS: counter_rtl_tb class-based Pure SV OK");
    else
      $display("FAIL: counter_rtl_tb - %0d error(s)", errors);
    $finish;
  end
endmodule
"""

BROKEN_3B = """
`timescale 1ns / 1ps
class counter_rtl_txn;
  rand bit enable;
  constraint legal_c { enable inside {[0:1]}; }
endclass
class counter_rtl_scoreboard;
  logic [3:0] expected;
  function new(); expected = '0; endfunction
  function void predict(bit en);
    if (en) expected <= expected + 1'b1;
  endfunction
  task check(logic [3:0] actual);
    return (actual === expected);
  endtask
endclass
module counter_rtl_tb;
  logic clk, rst_n;
  wire enable;
  reg count;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  initial begin
    counter_rtl_txn txn;
    counter_rtl_scoreboard sb;
    $dumpfile("t.vcd"); $dumpvars(0, counter_rtl_tb);
    clk = 0; rst_n = 0; enable = 0;
    repeat (2) @(posedge clk);
    rst_n = 1;
    for (int i = 0; i < 8; i++) begin
      assert(txn.randomize());
      enable = txn.enable;
      @(posedge clk);
      #1;
      sb.predict(txn.enable);
      if (!sb.check(count)) errors = errors + 1;
      if (errors == 0) $display("PASS: ok");
    end
    $finish;
  end
endmodule
"""


def test_gold_passes_premium_bar():
    gold = GOLD.read_text(encoding="utf-8")
    ok, issues = lint_class_sv_tb(
        gold, dut_name="counter_rtl", required_ports=PORTS, dut_outputs=["count"]
    )
    assert ok, issues
    score = score_class_sv_competitive(gold, required_ports=PORTS, dut_outputs=["count"])
    assert score["score"] >= 90
    assert score["premium_bar"] is True


MUX_SPECS = [
    {"name": "sel", "direction": "input", "width": ""},
    {"name": "a", "direction": "input", "width": "[7:0]"},
    {"name": "b", "direction": "input", "width": "[7:0]"},
    {"name": "y", "direction": "output", "width": "[7:0]"},
]

MUX_INVENTED_PINS = """
module mux2_8_tb;
  logic clk, rst_n, sel; logic [7:0] a, b, y;
  mux2_8 dut (.clk(clk), .rst_n(rst_n), .sel(sel), .a(a), .b(b), .y(y));
  always #5 clk = ~clk;
  initial begin
    int errors;
    errors = 0; clk = 0; rst_n = 0; sel = 0; a = '0; b = '0;
    repeat (2) @(posedge clk); rst_n = 1; @(posedge clk);
    if (errors == 0) $display("PASS"); else $display("FAIL");
    $dumpfile("t.vcd"); $dumpvars(0, mux2_8_tb); $finish;
  end
endmodule
"""


def test_unknown_dut_pin_lint_and_repair():
    ok, issues = lint_class_sv_tb(
        MUX_INVENTED_PINS,
        dut_name="mux2_8",
        required_ports=["sel", "a", "b", "y"],
        port_specs=MUX_SPECS,
    )
    assert not ok
    assert "unknown_dut_pin:clk" in issues
    assert "unknown_dut_pin:rst_n" in issues
    fixed = repair_class_sv_tb(
        MUX_INVENTED_PINS,
        required_ports=["sel", "a", "b", "y"],
        dut_outputs=["y"],
        port_specs=MUX_SPECS,
        dut_name="mux2_8",
    )
    assert ".clk(" not in fixed.split("dut (")[1].split(");")[0]
    assert ".sel(sel)" in fixed


def test_post_reset_check_inserted():
    sv = """
module counter_en_tb;
  logic clk, rst_n, enable; logic [3:0] count;
  integer errors;
  counter_en dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    errors = 0; clk = 0; rst_n = 0; enable = 0;
    repeat (2) @(posedge clk); rst_n = 1; @(posedge clk);
    for (int i = 0; i < 4; i++) begin enable = 1; @(posedge clk); end
    if (errors == 0) $display("PASS"); else $display("FAIL");
    $dumpfile("t.vcd"); $dumpvars(0, counter_en_tb); $finish;
  end
endmodule
"""
    fixed = repair_class_sv_tb(sv, dut_outputs=["count"], dut_name="counter_en")
    assert "if (count !== '0) errors++;" in fixed


def test_fix_inverted_stuck_active_low_reset():
    """LLM often does rst_n=1 → pulse low and never release — sim would FAIL."""
    from tb_class_lint import lint_class_sv_tb, repair_class_sv_tb
    from tb_semantic import lint_semantic_golden

    sv = """
`timescale 1ns / 1ps
module counter_rtl_tb;
  logic clk, rst_n, enable; logic [3:0] count;
  integer i, errors;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    errors = 0;
    clk = 0; rst_n = 1; enable = 0;
    repeat (4) @(posedge clk);
    rst_n = 0;
    @(posedge clk);
    if (count !== '0) begin $error("Reset failed"); errors++; end
    for (i = 0; i < 32; i++) begin
      enable = 1; @(posedge clk); #1;
    end
    if (errors == 0) $display("PASS"); else $display("FAIL");
    $dumpfile("t.vcd"); $dumpvars(0, counter_rtl_tb); $finish;
  end
endmodule
"""
    ok, issues = lint_class_sv_tb(sv, required_ports=["clk", "rst_n", "enable", "count"])
    assert "stuck_active_low_reset" in issues
    assert "semantic_stuck_active_low_reset" in lint_semantic_golden(sv, protocol="counter")
    fixed = repair_class_sv_tb(
        sv, required_ports=["clk", "rst_n", "enable", "count"], dut_outputs=["count"]
    )
    assert not _reset_stuck(fixed)
    # Canonical: assert then release
    assert re.search(
        r"rst_n\s*=\s*0[\s\S]+?rst_n\s*=\s*1", fixed, re.I
    )
    ok2, issues2 = lint_class_sv_tb(
        fixed, required_ports=["clk", "rst_n", "enable", "count"]
    )
    assert "stuck_active_low_reset" not in issues2


def _reset_stuck(sv: str) -> bool:
    from tb_class_lint import _active_low_reset_stuck

    return _active_low_reset_stuck(sv)


def test_hoist_multi_statement_decl_line():
    sv = """
module t_tb;
  logic clk;
  always #5 clk = ~clk;
  initial begin
    clk = 0;
    int i, errors; $dumpfile("t.vcd"); $dumpvars(0, t_tb);
    errors = 0;
    $finish;
  end
endmodule
"""
    fixed = repair_class_sv_tb(sv)
    body = fixed.split("initial begin")[1]
    assert "int i, errors;" not in body
    assert "$dumpfile" in body
    assert "integer i;" in fixed and "integer errors;" in fixed


def test_user_7b_undeclared_enable_repaired():
    ok, issues = lint_class_sv_tb(
        USER_7B_BROKEN, dut_name="counter_rtl", required_ports=PORTS, dut_outputs=["count"]
    )
    assert not ok
    assert any(i == "undeclared_signal:enable" for i in issues)
    assert "noop_constraint" in issues
    repaired = repair_class_sv_tb(
        USER_7B_BROKEN, required_ports=PORTS, dut_outputs=["count"]
    )
    assert re_search_logic_enable(repaired)
    assert "inside" in repaired
    assert "{ 1; }" not in repaired and "{1;}" not in repaired.replace(" ", "")
    assert "errors = 0" in repaired
    assert "@(posedge clk)" in repaired
    ok2, issues2 = lint_class_sv_tb(
        repaired, dut_name="counter_rtl", required_ports=PORTS, dut_outputs=["count"]
    )
    assert ok2, issues2
    assert not any(i.startswith("undeclared_signal:") for i in issues2)
    assert "noop_constraint" not in issues2
    score = score_class_sv_competitive(repaired, required_ports=PORTS, dut_outputs=["count"])
    # Compact txn+sb repair is no longer premium — layered stack is required.
    assert score["checks"]["has_class_txn"] and score["checks"]["has_scoreboard"]
    assert score["premium_bar"] is False
    assert any(i.startswith("missing_sv_") for i in issues2)
    # Soft layered gaps should trigger LLM repair toward full IF/gen/drv/mon/env/test.
    assert should_llm_repair(
        issues=issues2, competitive_score=score["score"], premium_bar=score["premium_bar"]
    ) is True


def re_search_logic_enable(sv: str) -> bool:
    import re
    return bool(re.search(r"\blogic\s+enable\s*;", sv))


def test_broken_fails_then_repair_improves():
    ok, issues = lint_class_sv_tb(BROKEN_3B, required_ports=PORTS, dut_outputs=["count"])
    assert not ok
    repaired = repair_class_sv_tb(BROKEN_3B, required_ports=PORTS, dut_outputs=["count"])
    assert "always #5 clk" in repaired
    assert "function bit check" in repaired
    assert "logic enable" in repaired
    assert "expected =" in repaired


PARAM_SCOPE_TB = """
`timescale 1ns / 1ps
class fifo_txn;
  rand logic [WIDTH-1:0] wr_data;
endclass
module fifo_tb;
  parameter WIDTH = 8, DEPTH = 16;
  logic clk;
  logic [WIDTH-1:0] wr_data;
  sync_fifo8 #(.WIDTH(WIDTH), .DEPTH(DEPTH)) dut (.clk(clk), .wr_data(wr_data));
  always #5 clk = ~clk;
endmodule
"""


def test_class_param_scope_detected_and_hoisted():
    from tb_class_lint import class_scope_param_gaps

    gaps = class_scope_param_gaps(PARAM_SCOPE_TB)
    assert ("WIDTH", "8") in gaps
    # DEPTH not referenced in any class → no hoist needed
    assert all(n != "DEPTH" for n, _ in gaps)

    ok, issues = lint_class_sv_tb(PARAM_SCOPE_TB, required_ports=["clk", "wr_data"])
    assert "class_param_scope:WIDTH" in issues

    repaired = repair_class_sv_tb(PARAM_SCOPE_TB, required_ports=["clk", "wr_data"])
    assert "localparam int WIDTH = 8;" in repaired
    assert repaired.index("localparam int WIDTH") < repaired.index("class fifo_txn")
    _ok2, issues2 = lint_class_sv_tb(repaired, required_ports=["clk", "wr_data"])
    assert "class_param_scope:WIDTH" not in issues2


def test_choose_repairs_class_keeps_llm():
    out, engine, issues = choose_testbench_output(
        USER_7B_BROKEN,
        skeleton="// SHOULD_NOT_APPEAR\nmodule smoke; endmodule\n",
        dut_name="counter_rtl",
        required_ports=PORTS,
        dut_outputs=["count"],
        force_uvm=False,
    )
    assert "SHOULD_NOT_APPEAR" not in out
    assert engine in ("llm", "llm_repaired")
    assert "class counter_rtl_txn" in out
    assert "logic enable" in out
    assert "always #5 clk" in out


SB_ERRORS_TB = """
`timescale 1ns / 1ps
class counter_en_txn;
  rand bit enable;
  constraint legal_c { enable inside {[0:1]}; }
endclass
class counter_en_scoreboard;
  logic [3:0] expected;
  function new(); expected = '0; endfunction
  function void predict(bit en); if (en) expected = expected + 1'b1; endfunction
  function bit check(logic [3:0] actual); return (actual === expected); endfunction
endclass
module counter_en_tb;
  logic clk, rst_n, enable; logic [3:0] count;
  counter_en dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    automatic counter_en_txn txn = new();
    automatic counter_en_scoreboard sb = new();
    int i, errors; $dumpfile("t.vcd"); $dumpvars(0, counter_en_tb);
    errors=0; clk=0; rst_n=0; enable=0;
    repeat(4) @(posedge clk); rst_n=1; @(posedge clk);
    if (count !== '0) begin $error("post-reset"); sb.errors++; end
    for (i=0;i<8;i++) begin
      assert(txn.randomize()); enable = txn.enable;
      @(posedge clk); #1; sb.predict(txn.enable);
      if (!sb.check(count)) errors++;
    end
    if (errors==0) $display("PASS"); else $display("FAIL %0d", errors);
    $finish;
  end
endmodule
"""


def test_sb_errors_not_member_lint_and_repair():
    ok, issues = lint_class_sv_tb(
        SB_ERRORS_TB,
        dut_name="counter_en",
        required_ports=["clk", "rst_n", "enable", "count"],
        dut_outputs=["count"],
    )
    assert "sb_errors_not_member" in issues
    assert not ok
    fixed = repair_class_sv_tb(
        SB_ERRORS_TB,
        required_ports=["clk", "rst_n", "enable", "count"],
        dut_outputs=["count"],
        dut_name="counter_en",
    )
    assert "sb.errors++" not in fixed
    assert "errors++" in fixed
    ok2, issues2 = lint_class_sv_tb(
        fixed,
        dut_name="counter_en",
        required_ports=["clk", "rst_n", "enable", "count"],
        dut_outputs=["count"],
    )
    assert "sb_errors_not_member" not in issues2


MUX_UNDECLARED_EXPECTED = """
`timescale 1ns / 1ps
class mux2_8_txn;
  rand bit sel; rand logic [7:0] a, b;
  constraint legal_c { }
endclass
class mux2_8_scoreboard;
  function new(); endfunction
  function void predict(bit s, logic [7:0] a, logic [7:0] b);
    if (s) expected = b; else expected = a;
  endfunction
  function bit check(logic [7:0] y); return (y === expected); endfunction
endclass
module mux2_8_tb;
  integer errors;
  logic clk, rst_n, sel; logic [7:0] a, b, y;
  mux2_8 dut (.sel(sel), .a(a), .b(b), .y(y));
  always #5 clk = ~clk;
  initial begin
    automatic mux2_8_txn txn = new(); automatic mux2_8_scoreboard sb = new();
    errors=0; clk=0; rst_n=0; sel=0; a='0; b='0;
    repeat(4) @(posedge clk); rst_n=1; @(posedge clk);
    for (int i=0;i<4;i++) begin
      assert(txn.randomize()); sel=txn.sel; a=txn.a; b=txn.b;
      @(posedge clk); #1; sb.predict(sel,a,b);
      if (!sb.check(y)) errors++;
    end
    if (errors==0) $display("PASS"); else $display("FAIL"); $finish;
  end
endmodule
"""


def test_undeclared_expected_and_combo_reset_repair():
    ok, issues = lint_class_sv_tb(
        MUX_UNDECLARED_EXPECTED,
        dut_name="mux2_8",
        required_ports=["sel", "a", "b", "y"],
        dut_outputs=["y"],
        port_specs=MUX_SPECS,
        protocol="mux",
    )
    assert "undeclared_expected" in issues
    assert "combo_invented_reset" in issues
    assert "noop_constraint" in issues
    fixed = repair_class_sv_tb(
        MUX_UNDECLARED_EXPECTED,
        required_ports=["sel", "a", "b", "y"],
        dut_outputs=["y"],
        port_specs=MUX_SPECS,
        dut_name="mux2_8",
    )
    assert re.search(r"logic\s*\[7:0\]\s*expected", fixed)
    assert "rst_n =" not in fixed
    ok2, issues2 = lint_class_sv_tb(
        fixed,
        dut_name="mux2_8",
        required_ports=["sel", "a", "b", "y"],
        port_specs=MUX_SPECS,
        protocol="mux",
    )
    assert "undeclared_expected" not in issues2


def test_fifo_clamp_injected():
    fifo = """
class sync_fifo8_txn;
  rand bit wr_en, rd_en; rand logic [7:0] wr_data;
  constraint legal_c { !(wr_en && rd_en); }
endclass
class sync_fifo8_scoreboard;
  logic [7:0] q[$];
  localparam int DEPTH = 8;
  function new(); q.delete(); endfunction
  function void predict(bit wr, bit rd, logic [7:0] wdata);
    if (rd && q.size()>0) void'(q.pop_front());
    if (wr && q.size()<DEPTH) q.push_back(wdata);
  endfunction
  function bit check(logic [7:0] rd_data, bit full, bit empty, logic [3:0] count);
    return (empty===(q.size()==0)) && (full===(q.size()>=DEPTH)) &&
           (count===q.size()) && (q.size()==0 || rd_data===q[0]);
  endfunction
endclass
module sync_fifo8_tb;
  logic clk, rst_n, wr_en, rd_en; logic [7:0] wr_data, rd_data;
  logic full, empty; logic [3:0] count;
  integer errors;
  sync_fifo8 dut (.clk(clk),.rst_n(rst_n),.wr_en(wr_en),.wr_data(wr_data),
    .rd_en(rd_en),.rd_data(rd_data),.full(full),.empty(empty),.count(count));
  always #5 clk = ~clk;
  initial begin
    automatic sync_fifo8_txn txn = new(); automatic sync_fifo8_scoreboard sb = new();
    errors=0; clk=0; rst_n=0; wr_en=0; rd_en=0; wr_data='0;
    repeat(2) @(posedge clk); rst_n=1; @(posedge clk);
    for (int i=0;i<8;i++) begin
      assert(txn.randomize());
      wr_en=txn.wr_en; rd_en=txn.rd_en; wr_data=txn.wr_data;
      @(posedge clk); #1; sb.predict(txn.wr_en, txn.rd_en, txn.wr_data);
      if (!sb.check(rd_data, full, empty, count)) errors++;
    end
    if (errors==0) $display("PASS"); else $display("FAIL"); $finish;
  end
endmodule
"""
    from tb_semantic import lint_semantic_golden

    assert "semantic_fifo_no_clamp" in lint_semantic_golden(fifo, protocol="fifo")
    fixed = repair_class_sv_tb(
        fifo,
        required_ports=["clk", "rst_n", "wr_en", "wr_data", "rd_en", "rd_data", "full", "empty", "count"],
        dut_outputs=["rd_data", "full", "empty", "count"],
        dut_name="sync_fifo8",
    )
    assert "sb.q.size() >= 8" in fixed
    assert "rd_data !== '0" not in fixed  # post-reset skip for rd_data


def test_fifo_post_reset_rd_data_stripped_when_lint_ok():
    from tb_lint import choose_testbench_output
    from tb_class_lint import sanitize_class_sv_tb

    fifo = """
`timescale 1ns / 1ps
class sync_fifo8_txn;
  rand bit wr_en, rd_en; rand logic [7:0] wr_data;
  constraint legal_c { !(wr_en && rd_en); }
endclass
class sync_fifo8_scoreboard;
  logic [7:0] q[$];
  localparam int DEPTH = 8;
  function new(); q.delete(); endfunction
  function void predict(bit wr, bit rd, logic [7:0] wdata);
    if (rd && q.size()>0) void'(q.pop_front());
    if (wr && q.size()<DEPTH) q.push_back(wdata);
  endfunction
  function bit check(logic [7:0] rd_data, bit full, bit empty, logic [3:0] count);
    return (empty===(q.size()==0)) && (full===(q.size()>=DEPTH)) &&
           (count===q.size()) && (q.size()==0 || rd_data===q[0]);
  endfunction
endclass
module sync_fifo8_tb;
  logic clk, rst_n, wr_en, rd_en; logic [7:0] wr_data, rd_data;
  logic full, empty; logic [3:0] count;
  integer errors;
  sync_fifo8 dut (.clk(clk),.rst_n(rst_n),.wr_en(wr_en),.wr_data(wr_data),
    .rd_en(rd_en),.rd_data(rd_data),.full(full),.empty(empty),.count(count));
  always #5 clk = ~clk;
  initial begin
    automatic sync_fifo8_txn txn = new(); automatic sync_fifo8_scoreboard sb = new();
    errors=0; clk=0; rst_n=0; wr_en=0; rd_en=0; wr_data='0;
    repeat(4) @(posedge clk); rst_n=1; @(posedge clk);
    if (rd_data !== '0 || full !== 0 || empty !== 1 || count !== 0) errors++;
    for (int i=0;i<8;i++) begin
      assert(txn.randomize());
      if (sb.q.size()>=8) txn.wr_en=0;
      if (sb.q.size()==0) txn.rd_en=0;
      wr_en=txn.wr_en; rd_en=txn.rd_en; wr_data=txn.wr_data;
      @(posedge clk); #1; sb.predict(txn.wr_en, txn.rd_en, txn.wr_data);
      if (!sb.check(rd_data, full, empty, count)) errors++;
    end
    if (errors==0) $display("PASS"); else $display("FAIL"); $finish;
  end
endmodule
"""
    from tb_semantic import lint_semantic_golden

    assert "semantic_fifo_reset_rd_data" in lint_semantic_golden(fifo, protocol="fifo")
    fixed = sanitize_class_sv_tb(
        fifo,
        dut_outputs=["rd_data", "full", "empty", "count"],
        protocol="fifo",
    )
    assert "rd_data !== '0" not in fixed
    assert "ChipSutra mid-test reset" in fixed
    out, engine, _iss = choose_testbench_output(
        fifo,
        skeleton="// skel\nmodule x; always #5 clk = ~clk; endmodule\n",
        dut_name="sync_fifo8",
        required_ports=["clk", "rst_n", "wr_en", "wr_data", "rd_en", "rd_data", "full", "empty", "count"],
        dut_outputs=["rd_data", "full", "empty", "count"],
        protocol="fifo",
    )
    assert "rd_data !== '0" not in out
    assert engine in ("llm_repaired", "llm")


def test_parity_mid_reset_injected():
    from tb_class_lint import inject_mid_test_reset

    tb = """
module sample_parity_tb;
  logic clk, rst_n, valid, parity, valid_out;
  sample_parity dut (.clk(clk),.rst_n(rst_n),.valid(valid),.parity(parity),.valid_out(valid_out));
  always #5 clk=~clk;
  initial begin
    errors=0; rst_n=0; repeat(2) @(posedge clk); rst_n=1; @(posedge clk);
    if (parity !== '0) errors++;
    for (int i=0;i<4;i++) begin valid=1; @(posedge clk); end
    if (errors==0) $display("PASS");
    $finish;
  end
endmodule
"""
    out = inject_mid_test_reset(tb, ["parity", "valid_out"], protocol="parity")
    assert "ChipSutra mid-test reset" in out
    assert "parity !== '0" in out

