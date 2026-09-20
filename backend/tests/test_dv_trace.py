from coverage_loop import render_hole_sequence
from dv_trace import build_trace_matrix, extract_plan_items


def test_plan_items_and_hits():
    plan = """
# plan
- RST-01: reset then count is zero
- EN-02: enable advances count
"""
    tb = """
class counter_en_test;
  task close_RST_01(); endtask
endclass
"""
    sva = "property p_reset; @(posedge clk) 1; endproperty\nassert property (p_reset);"
    cg = "covergroup g; cp_count: coverpoint count; endgroup"
    m = build_trace_matrix(testplan=plan, tb=tb, sva=sva, covergroups=cg)
    assert m["counts"]["plan"] >= 2
    ids = [r["id"] for r in m["rows"]]
    assert "RST-01" in ids
    rst = next(r for r in m["rows"] if r["id"] == "RST-01")
    assert rst["covered"] is True


def test_extract_plan_skips_headers():
    items = extract_plan_items("- Ports: clk, rst\n- Directed reset walk")
    titles = [i["title"].lower() for i in items]
    assert any("reset" in t for t in titles)
    assert not any(t.startswith("ports:") for t in titles)


def test_hole_sequence_named_and_honest():
    sv = render_hole_sequence("cp_enable", dut="counter_en", ports=["enable", "count"], pct=12.0)
    assert "close_cp_enable" in sv
    assert "cp_enable" in sv
    assert "do not invent" in sv.lower() or "drive enable" in sv
