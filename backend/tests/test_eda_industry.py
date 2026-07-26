"""Unit tests for coverage/formal/CDC helpers (no Verilator required)."""
from coverage_parse import parse_text_report, parse_lcov_info, trend_points, merge_metric_lists
from formal_parse import parse_sby_log
from cdc import analyze_rtl_texts
from cdc_netlist import analyze_yosys_json
from eda_tools import build_manifest, tool_versions
from opensta_flow import parse_sta_log
from yosys_flow import eqy_config, parse_eqy_log


def test_parse_text_coverage_report():
    text = "Line coverage: 92.5%\nToggle coverage: 80%\n"
    r = parse_text_report(text)
    assert r["count"] >= 2
    assert r["overall"] > 0
    assert any(h["pct"] < 90 for h in r["holes"])


def test_parse_lcov_info():
    text = """SF:foo.sv
LH:8
LF:10
end_of_record
"""
    r = parse_lcov_info(text)
    assert r["metrics"][0]["pct"] == 80.0


def test_parse_sby_pass_fail():
    log = "Status: PASS assert_reset\nFAIL assert_handshake\n"
    props = parse_sby_log(log)
    assert any(p["status"] == "PASS" for p in props)
    assert any(p["status"] == "FAIL" for p in props)


def test_cdc_detects_crossing_and_2ff():
    rtl = """
module m(input clk_a, input clk_b, input din, output dout);
  reg a_meta, a_sync;
  always @(posedge clk_a) a_meta <= din;
  always @(posedge clk_b) begin
    a_meta <= din; // crossing without sync name on this path
    a_sync <= a_meta;
  end
  assign dout = a_sync;
endmodule
"""
    # clearer fixture
    rtl2 = """
module sync2(input clk, input async_in, output sync_out);
  reg s1, s2;
  always @(posedge clk) begin
    s1 <= async_in;
    s2 <= s1;
  end
  assign sync_out = s2;
endmodule

module cross(input clk_a, input clk_b, input d, output q);
  reg ra, rb;
  always @(posedge clk_a) ra <= d;
  always @(posedge clk_b) rb <= ra;
  assign q = rb;
endmodule
"""
    r = analyze_rtl_texts([("x.sv", rtl2)])
    assert "clk_a" in r["clocks"] or "clk" in r["clocks"]
    assert r["counts"]["cdc_warn"] >= 1 or r["counts"]["cdc_info"] >= 1


def test_build_manifest_shape():
    m = build_manifest(engine="verilator", mode="lint", command=["verilator", "--lint-only"], top_module="top")
    assert m["engine"] == "verilator"
    assert "tool_versions" in m
    assert "created_at" in m
    versions = tool_versions()
    assert "eqy" in versions and "opensta" in versions and "cocotb" in versions


def test_eqy_and_coverage_helpers_smoke():
    cfg = eqy_config("dut", ["a.sv"], ["b.v"])
    assert "[strategy simple]" in cfg
    assert parse_eqy_log("equivalent")["equivalence"] == "pass"
    tr = trend_points([{"id": "1", "overall": 70.0, "created_at": "t"}], limit=5)
    assert tr["latest"] == 70.0
    merged = merge_metric_lists([
        {"metrics": [{"name": "Line", "pct": 70}]},
        {"metrics": [{"name": "Line", "pct": 90}]},
    ])
    assert merged["overall"] == 80.0


def test_opensta_log_and_cdc_json_smoke():
    assert parse_sta_log("worst slack = 0.25")["wns"] == 0.25
    empty = analyze_yosys_json({"modules": {}})
    assert empty["findings"] == []
