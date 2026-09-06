"""Functional coverage insert + mutation operators."""
from tb_coverage import build_covergroup, has_covergroup, insert_covergroup
from dv_mutation import generate_mutants

PORTS = [
    {"name": "clk", "direction": "input", "width": ""},
    {"name": "rst_n", "direction": "input", "width": ""},
    {"name": "enable", "direction": "input", "width": ""},
    {"name": "mode", "direction": "input", "width": ""},
    {"name": "count", "direction": "output", "width": "[3:0]"},
]

TB = """
module counter_tb;
  logic clk, rst_n, enable, mode;
  logic [3:0] count;
  counter dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    $finish;
  end
endmodule
"""


def test_build_covergroup_guards_verilator_and_skips_clk_rst():
    cg = build_covergroup("counter", PORTS)
    assert "`ifndef VERILATOR" in cg and "`endif" in cg
    assert "covergroup cg_counter" in cg
    assert "coverpoint enable" in cg and "coverpoint count" in cg
    assert "coverpoint clk" not in cg and "coverpoint rst_n" not in cg
    # Two single-bit inputs → cross
    assert "cross cp_enable, cp_mode" in cg


def test_insert_covergroup_before_endmodule_and_idempotent():
    out = insert_covergroup(TB, "counter", PORTS)
    assert has_covergroup(out)
    assert out.index("covergroup") < out.rindex("endmodule")
    # Idempotent: never insert twice
    again = insert_covergroup(out, "counter", PORTS)
    assert again.count("covergroup") == out.count("covergroup")


RTL = """
module counter_en (
  input  wire clk, rst_n, enable,
  output reg [3:0] count
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) count <= 4'd0;
    else if (enable) count <= count + 4'd1;
  end
endmodule
"""


def test_generate_mutants_apply_and_differ():
    muts = dict(generate_mutants(RTL))
    assert "off_by_one" in muts and "+ 2" in muts["off_by_one"]
    assert "minus_for_plus" in muts and "count - 4'd1" in muts["minus_for_plus"]
    assert "drop_reset" in muts and "if (1'b0)" in muts["drop_reset"]
    for name, mutated in muts.items():
        assert mutated != RTL, name
