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


def test_circular_golden_true_positive_still_flagged():
    sv = GOOD_SKEL.replace("if (enable) expected = expected + 1;", "expected = count + 1;")
    ok, issues = lint_testbench(
        sv, dut_name="counter_rtl", required_ports=["clk", "rst_n", "enable", "count"]
    )
    assert "circular_golden" in issues


def test_self_increment_golden_not_flagged_circular():
    """Regression: `expected_count = expected_count + 1` is a valid independent golden."""
    sv = GOOD_SKEL.replace("expected", "expected_count")
    ok, issues = lint_testbench(
        sv, dut_name="counter_rtl", required_ports=["clk", "rst_n", "enable", "count"]
    )
    assert "circular_golden" not in issues, issues


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


def test_lint_rejects_missing_posedge_sync():
    sv = """
module counter_rtl_tb;
  logic clk, rst_n, enable;
  logic [3:0] count, expected;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, counter_rtl_tb);
    void'($urandom(1));
    for (int i = 0; i < 8; i++) begin
      enable = $urandom_range(0, 1);
      #1;
      if (enable) expected = expected + 1;
    end
    $finish;
  end
endmodule
"""
    ok, issues = lint_testbench(
        sv, dut_name="counter_rtl", required_ports=["clk", "rst_n", "enable", "count"]
    )
    assert not ok
    assert "missing_posedge_sync" in issues


def test_lint_rejects_driving_dut_outputs():
    sv = """
module sample_parity_tb;
  logic clk, rst_n, valid;
  logic [7:0] data;
  logic parity, valid_out;
  sample_parity dut (
    .clk(clk), .rst_n(rst_n), .valid(valid), .data(data),
    .parity(parity), .valid_out(valid_out)
  );
  always #5 clk = ~clk;
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, sample_parity_tb);
    void'($urandom(1));
    for (int i = 0; i < 8; i++) begin
      valid = $urandom_range(0, 1);
      data = $urandom();
      @(posedge clk);
      parity = ^data;
      valid_out = valid;
    end
    $finish;
  end
endmodule
"""
    ok, issues = lint_testbench(
        sv,
        dut_name="sample_parity",
        required_ports=["clk", "rst_n", "valid", "data", "parity", "valid_out"],
        dut_outputs=["parity", "valid_out"],
    )
    assert not ok
    assert any(i.startswith("drives_dut_output:") for i in issues)


def test_lint_rejects_undeclared_queue_and_depth():
    sv = """
module sample_fifo_tb;
  logic clk, rst_n, wr_en, rd_en;
  logic [7:0] wr_data, rd_data;
  logic full, empty;
  sample_fifo #(.WIDTH(8), .DEPTH(4)) dut (
    .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data),
    .rd_en(rd_en), .rd_data(rd_data), .full(full), .empty(empty)
  );
  always #5 clk = ~clk;
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, sample_fifo_tb);
    void'($urandom(1));
    for (int i = 0; i < 8; i++) begin
      wr_en = $urandom_range(0, 1);
      @(posedge clk);
      if (wr_en && q.size() >= DEPTH) wr_en = 0;
      void'(q.push_back(wr_data));
    end
    $finish;
  end
endmodule
"""
    ok, issues = lint_testbench(
        sv,
        dut_name="sample_fifo",
        required_ports=["clk", "rst_n", "wr_en", "wr_data", "rd_en", "rd_data", "full", "empty"],
    )
    assert not ok
    assert "undeclared_queue_q" in issues


def test_lint_rejects_wire_stimulus_assign():
    sv = """
module mux_tb;
  wire sel;
  logic [7:0] a, b, y;
  mux2 dut (.sel(sel), .a(a), .b(b), .y(y));
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, mux_tb);
    void'($urandom(1));
    for (int i = 0; i < 4; i++) begin
      sel = $urandom_range(0, 1);
      a = $urandom(); b = $urandom();
      #1;
    end
    $finish;
  end
endmodule
"""
    ok, issues = lint_testbench(
        sv, dut_name="mux2", required_ports=["sel", "a", "b", "y"]
    )
    assert not ok
    assert any(i.startswith("wire_driven_procedurally:") for i in issues)


def test_choose_falls_back_on_semantic_fail():
    bad = """
module sample_parity_tb;
  logic clk, rst_n, valid;
  logic [7:0] data;
  logic parity, valid_out;
  sample_parity dut (
    .clk(clk), .rst_n(rst_n), .valid(valid), .data(data),
    .parity(parity), .valid_out(valid_out)
  );
  always #5 clk = ~clk;
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, sample_parity_tb);
    void'($urandom(1));
    for (int i = 0; i < 4; i++) begin
      valid = $urandom_range(0, 1);
      @(posedge clk);
      parity = ^data;
    end
    $finish;
  end
endmodule
"""
    out, engine, issues = choose_testbench_output(
        bad,
        skeleton=GOOD_SKEL,
        dut_name="sample_parity",
        required_ports=["clk", "rst_n", "valid", "data", "parity", "valid_out"],
        dut_outputs=["parity", "valid_out"],
    )
    assert engine == "skeleton_fallback"
    assert "always #5 clk" in out


def test_stamp_and_truncate_helpers():
    from tb_lint import stamp_tb_header, truncate_tb_reference

    stamped = stamp_tb_header(GOOD_SKEL, engine="skeleton", model="tb_skeleton", protocol="counter")
    assert stamped.startswith("// ChipSutra engine=skeleton")
    stamped2 = stamp_tb_header(stamped, engine="llm", model="chipsutra-vlsi:3b", protocol="counter")
    assert stamped2.startswith("// ChipSutra engine=llm")
    assert stamped2.count("// ChipSutra engine=") == 1
    long_sv = "\n".join([f"// line {i}" for i in range(80)]) + "\nmodule x; endmodule\n"
    trunc = truncate_tb_reference(long_sv, max_lines=40)
    assert "truncated" in trunc.lower()
    assert trunc.count("\n") < 80


def test_incomplete_module_falls_back_to_skeleton():
    from tb_lint import choose_testbench_output, lint_testbench, module_incomplete

    truncated = """
`timescale 1ns / 1ps
class axi_lite_txn;
  rand bit [1:0] sel;
endclass
module axi_lite_smoke_tb;
  logic aclk, aresetn;
  integer errors;
  initial begin
    txn.sel = 2'b10; txn.data =
"""
    assert module_incomplete(truncated)
    ok, issues = lint_testbench(truncated, dut_name="axi_lite_slave")
    assert not ok
    assert "incomplete_module" in issues
    skel = """
module axi_lite_slave_tb;
  logic aclk;
  always #5 aclk = ~aclk;
  initial begin
    $dumpfile("t.vcd"); $dumpvars(0, axi_lite_slave_tb);
    $display("PASS: skeleton");
    $finish;
  end
endmodule
"""
    out, engine, issues = choose_testbench_output(
        truncated, skeleton=skel, dut_name="axi_lite_slave", protocol="axi_lite"
    )
    assert engine == "skeleton_fallback"
    assert "endmodule" in out
    assert "txn.data =" not in out.split("skeleton")[-1] or "PASS: skeleton" in out

