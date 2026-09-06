"""Covergroup / FCOV lint."""
from fcov_lint import lint_fcov, repair_fcov, score_fcov


def test_fcov_flags_missing_covergroup():
    ok, issues = lint_fcov("module m; endmodule")
    assert not ok
    assert "fcov_no_covergroup" in issues


def test_fcov_repair_adds_per_instance():
    sv = """
covergroup cg_fifo @(posedge clk);
  cp_depth: coverpoint depth;
endgroup
"""
    ok, issues = lint_fcov(sv)
    assert "fcov_missing_per_instance" in issues
    fixed = repair_fcov(sv)
    assert "option.per_instance = 1" in fixed
    ok2, issues2 = lint_fcov(fixed)
    assert "fcov_missing_per_instance" not in issues2
    assert ok2


def test_fcov_score_premium():
    sv = """
covergroup cg_cnt @(posedge clk);
  option.per_instance = 1;
  cp_en: coverpoint enable { bins on = {1}; bins off = {0}; }
endgroup
"""
    s = score_fcov(sv, required_ports=["clk", "enable"])
    assert s["ok"]
    assert s["score"] >= 75
    assert s["premium_bar"]
