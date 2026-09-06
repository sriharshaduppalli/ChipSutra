"""FPGA RTL lint (native)."""
from fpga_lint import lint_fpga, score_fpga


def test_fpga_flags_real_and_initial():
    sv = """
module m;
  real x;
  initial x = 1.0;
endmodule
"""
    ok, issues = lint_fpga(sv)
    assert ok
    assert "fpga_real_type" in issues
    assert "fpga_initial_in_rtl" in issues
    s = score_fpga(sv)
    assert s["score"] < 75


def test_fpga_clean_combo():
    sv = "module m(input a, output y); assign y = a; endmodule"
    ok, issues = lint_fpga(sv)
    assert ok
    assert not issues
    assert score_fpga(sv)["premium_bar"]
