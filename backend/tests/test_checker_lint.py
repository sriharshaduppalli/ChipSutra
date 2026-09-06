"""Checker lint / repair / score."""
from checker_lint import lint_checker, repair_checker, score_checker


def test_checker_flags_empty():
    ok, issues = lint_checker("")
    assert not ok
    assert "checker_empty" in issues


def test_checker_flags_no_check():
    ok, issues = lint_checker("module m; endmodule")
    assert not ok
    assert "checker_no_check" in issues


def test_checker_flags_circular_golden():
    sv = """
module chk;
  function bit check(logic [3:0] count);
    logic [3:0] expected;
    expected = count;
    return 1;
  endfunction
endmodule
"""
    ok, issues = lint_checker(sv)
    assert not ok
    assert "checker_circular_golden" in issues


def test_checker_repair_invented_ports():
    sv = "module chk; function void check(); data_in = 1; endfunction endmodule"
    fixed = repair_checker(sv)
    assert "data_in" not in fixed or "FIXME_port" in fixed
    ok, issues = lint_checker(fixed, required_ports=["clk"])
    assert "checker_invented_port" not in issues


def test_checker_score_premium_bar():
    sv = """
class ref_model;
  function bit check(logic [3:0] actual, logic [3:0] exp);
    assert (actual === exp);
    return actual === exp;
  endfunction
endclass
"""
    s = score_checker(sv, required_ports=["clk", "count"])
    assert s["ok"]
    assert s["score"] >= 75
    assert s["premium_bar"]
