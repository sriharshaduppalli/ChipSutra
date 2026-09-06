"""SVA lint / repair / score."""
from sva_lint import lint_sva, repair_sva, score_sva


def test_sva_flags_missing_property():
    ok, issues = lint_sva("module m; endmodule")
    assert not ok
    assert "sva_no_property" in issues


def test_sva_repair_adds_disable_iff():
    sv = """
module m;
  property p; @(posedge clk) a |-> b; endproperty
  assert property (p);
endmodule
"""
    fixed = repair_sva(sv, clk="clk", rst_n="rst_n", required_ports=["clk", "rst_n", "a", "b"])
    assert "disable iff (!rst_n)" in fixed
    ok, issues = lint_sva(fixed, required_ports=["clk", "rst_n", "a", "b"])
    assert "sva_missing_disable_iff" not in issues


def test_sva_score_premium_bar():
    sv = """
property p_rst; @(posedge clk) disable iff (!rst_n) !rst_n |=> (count == '0); endproperty
assert property (p_rst);
cover property (@(posedge clk) disable iff (!rst_n) enable);
"""
    s = score_sva(sv, required_ports=["clk", "rst_n", "enable", "count"])
    assert s["ok"]
    assert s["score"] >= 75


def test_sva_flags_unlabeled_and_repair_labels():
    sv = "assert property (@(posedge clk) enable |-> 1'b1);"
    ok, issues = lint_sva(sv)
    assert ok
    assert "sva_unlabeled_assert" in issues
    assert "sva_tautology" in issues
    fixed = repair_sva(sv)
    assert "a_sva:" in fixed
