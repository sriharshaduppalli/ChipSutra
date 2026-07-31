"""Tests for TB lint / quality gate."""
from tb_lint import extract_sv, lint_testbench, choose_testbench_output

BAD_LLM = '''
```systemverilog
module counter_rtl_tb;
  reg clk, rst_n, enable;
  wire [3:0] count;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  initial begin
    clk = 0; rst_n = 0; enable = 0;
    for (int i=0; i<10; i++) begin
      enable = $urandom_range(0, 1);
      @(posedge clk);
      int exp;
      exp = count + 1;
      assert(count === exp);
    end
    $finish;
  end
  initial begin
    clk = ~clk;
    #5 forever @(posedge clk);
  end
endmodule
```
This testbench initializes the DUT...
'''

GOOD_SKEL = """
`timescale 1ns / 1ps
module counter_rtl_tb;
  logic clk, rst_n, enable;
  logic [3:0] count;
  logic [3:0] expected;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    $dumpfile(\"t.vcd\"); $dumpvars(0, counter_rtl_tb);
    void'($urandom(1));
    expected = 0;
    for (int i = 0; i < 8; i++) begin
      enable = $urandom_range(0, 1);
      @(posedge clk);
      if (enable) expected = expected + 1;
      if (count !== expected) $error(\"bad\");
    end
    $finish;
  end
endmodule
"""


def test_extract_strips_prose():
    sv = extract_sv(BAD_LLM)
    assert "module counter_rtl_tb" in sv
    assert "This testbench initializes" not in sv
    assert sv.strip().endswith("endmodule")


def test_lint_rejects_broken_llm_tb():
    sv = extract_sv(BAD_LLM)
    ok, issues = lint_testbench(
        sv, dut_name="counter_rtl", required_ports=["clk", "rst_n", "enable", "count"]
    )
    assert not ok
    assert "bad_or_missing_clock" in issues or "circular_golden" in issues


def test_fallback_to_skeleton():
    out, engine, issues = choose_testbench_output(
        BAD_LLM,
        skeleton=GOOD_SKEL,
        dut_name="counter_rtl",
        required_ports=["clk", "rst_n", "enable", "count"],
    )
    assert engine == "skeleton_fallback"
    assert "always #5 clk" in out
    assert "expected = expected + 1" in out or "expected = expected + 1'b1" in out
    assert "exp = count + 1" not in out


def test_soft_repair_adds_finish_and_dump():
    from tb_lint import repair_soft_tb_gaps, choose_testbench_output

    truncated = """
`timescale 1ns / 1ps
module counter_rtl_tb;
  logic clk, rst_n, enable;
  logic [3:0] count, expected;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    void'($urandom(1));
    expected = 0;
    for (int i = 0; i < 8; i++) begin
      enable = $urandom_range(0, 1);
      @(posedge clk);
      if (enable) expected = expected + 1;
    end
  end
endmodule
"""
    repaired = repair_soft_tb_gaps(truncated)
    assert "$finish" in repaired and "$dump" in repaired
    out, engine, issues = choose_testbench_output(
        truncated,
        skeleton=GOOD_SKEL,
        dut_name="counter_rtl",
        required_ports=["clk", "rst_n", "enable", "count"],
    )
    assert engine == "llm_repaired"
    assert "$finish" in out
    assert "skeleton_fallback" not in engine


def test_lint_accepts_parameterized_dut_instance():
    sv = """
module fifo_tb;
  logic clk, rst_n, wr_en, rd_en, full, empty;
  logic [7:0] wr_data, rd_data;
  logic [3:0] count;
  fifo #(.WIDTH(8), .DEPTH(8)) dut (
    .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data),
    .rd_en(rd_en), .rd_data(rd_data), .full(full), .empty(empty), .count(count)
  );
  always #5 clk = ~clk;
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, fifo_tb);
    void'($urandom(1));
    $finish;
  end
endmodule
"""
    ok, issues = lint_testbench(
        sv,
        dut_name="fifo",
        required_ports=["clk", "rst_n", "wr_en", "wr_data", "rd_en", "rd_data", "full", "empty", "count"],
    )
    assert ok, issues
    assert "missing_dut_instance" not in issues
