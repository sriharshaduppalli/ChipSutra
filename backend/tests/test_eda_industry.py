"""Unit tests for coverage/formal/CDC helpers (no Verilator required)."""
from coverage_parse import parse_text_report, parse_lcov_info
from formal_parse import parse_sby_log
from cdc import analyze_rtl_texts
from eda_tools import build_manifest


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
