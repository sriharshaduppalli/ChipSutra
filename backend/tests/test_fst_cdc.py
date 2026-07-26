"""Offline tests for FST ingestion and deep CDC checks (no GTKWave / EDA tools)."""
import cdc_deep
from cdc_deep import analyze_deep, merge_deep
from fst_parse import (
    convert_fst_to_vcd,
    fst_available,
    fst_status,
    fst_tool,
    sniff_waveform_format,
)

VCD_TEXT = b"""$date
   Mon Jan 1 00:00:00 2024
$end
$timescale 1ps $end
$var wire 1 ! clk $end
$enddefinitions $end
"""

# FST header block: type byte 0x00 + big-endian uint64 section length 329.
FST_BYTES = b"\x00" + (329).to_bytes(8, "big") + b"\x00" * 64
FST_ZWRAPPER_BYTES = b"\xfe" + (4096).to_bytes(8, "big") + b"\x1f\x8b\x08\x00"


# --------------------------------------------------------------------------- FST


def test_sniff_vcd_text():
    assert sniff_waveform_format(VCD_TEXT) == "vcd"
    assert sniff_waveform_format(b"   \r\n$version Icarus $end\n") == "vcd"
    assert sniff_waveform_format(b"\xef\xbb\xbf$comment hi $end\n") == "vcd"


def test_sniff_fst_magic():
    assert sniff_waveform_format(FST_BYTES) == "fst"
    assert sniff_waveform_format(FST_ZWRAPPER_BYTES) == "fst"


def test_sniff_garbage_and_empty():
    assert sniff_waveform_format(b"\xde\xad\xbe\xef" * 8) == "unknown"
    assert sniff_waveform_format(b"hello world, not a waveform") == "unknown"
    assert sniff_waveform_format(b"") == "unknown"


def test_convert_fst_without_tool(tmp_path):
    src = tmp_path / "wave.fst"
    src.write_bytes(FST_BYTES)
    res = convert_fst_to_vcd(src, tmp_path / "wave.vcd", timeout=5)
    assert set(res) >= {"ok", "vcd_path", "stderr", "note"}
    if fst_tool() is None:
        assert res["ok"] is False
        assert res["vcd_path"] is None
        assert "gtkwave" in str(res["note"]).lower()


def test_convert_fst_missing_input(tmp_path):
    res = convert_fst_to_vcd(tmp_path / "nope.fst", tmp_path / "out.vcd", timeout=5)
    assert res["ok"] is False
    assert res["note"]


def test_fst_status_shape():
    st = fst_status()
    assert set(st) >= {"fst2vcd", "engine", "note"}
    assert st["engine"] == "gtkwave-fst2vcd"
    assert isinstance(st["fst2vcd"], bool)
    assert st["fst2vcd"] == fst_available()
    if not st["fst2vcd"]:
        assert st["note"]


# --------------------------------------------------------------------------- CDC


RECONVERGENCE_RTL = """
module recon(input clk_a, input clk_b, input x, input y, output z);
  reg xa, ya;
  reg x1, x2, y1, y2;
  always @(posedge clk_a) begin
    xa <= x;
    ya <= y;
  end
  always @(posedge clk_b) begin
    x1 <= xa;
    x2 <= x1;
    y1 <= ya;
    y2 <= y1;
  end
  assign z = x2 & y2;
endmodule
"""

MULTIBIT_RTL = """
module mb(input clk_a, input clk_b, input [7:0] din, output [7:0] dout);
  reg [7:0] data_a;
  reg [7:0] d1;
  reg [7:0] d2;
  always @(posedge clk_a) begin
    data_a <= din;
  end
  always @(posedge clk_b) begin
    d1 <= data_a;
    d2 <= d1;
  end
  assign dout = d2;
endmodule
"""

GLITCH_RTL = """
module glitchy(input clk_a, input clk_b, input p, input q, output r);
  reg pa, qa;
  reg g1, g2;
  always @(posedge clk_a) begin
    pa <= p;
    qa <= q;
  end
  always @(posedge clk_b) begin
    g1 <= pa & qa;
    g2 <= g1;
  end
  assign r = g2;
endmodule
"""

ONE_FF_RTL = """
module one_ff(input clk_a, input clk_b, input ctrl, output out);
  reg ctrl_a;
  reg ctrl_b;
  always @(posedge clk_a) begin
    ctrl_a <= ctrl;
  end
  always @(posedge clk_b) begin
    ctrl_b <= ctrl_a;
  end
  assign out = ctrl_b;
endmodule
"""

SCHEME_RTL = """
module async_fifo_ptr(input wclk, input rclk, input [3:0] wptr_bin, output [3:0] rd_wptr);
  reg [3:0] wptr_gray;
  reg [3:0] wptr_gray_s1;
  reg [3:0] wptr_gray_s2;
  always @(posedge wclk) begin
    wptr_gray <= (wptr_bin >> 1) ^ wptr_bin;
  end
  always @(posedge rclk) begin
    wptr_gray_s1 <= wptr_gray;
    wptr_gray_s2 <= wptr_gray_s1;
  end
  assign rd_wptr = wptr_gray_s2;
endmodule
"""


def _kinds(result):
    return {f["kind"] for f in result["findings"]}


def test_deep_result_schema():
    r = analyze_deep([("recon.sv", RECONVERGENCE_RTL)])
    assert set(r) >= {"clocks", "findings", "counts", "engine", "disclaimer", "checks"}
    assert r["engine"] == "chipsutra-cdc-deep"
    assert r["clocks"] == ["clk_a", "clk_b"]
    assert set(r["counts"]) == {"cdc_warn", "cdc_info", "rdc"}
    assert set(r["checks"]) == {"reconvergence", "multibit", "glitch", "sync_depth", "scheme"}
    for f in r["findings"]:
        assert set(f) == {
            "filename", "signal", "from_domain", "to_domain",
            "source", "severity", "kind", "note",
        }


def test_deep_detects_reconvergence():
    r = analyze_deep([("recon.sv", RECONVERGENCE_RTL)])
    hits = [f for f in r["findings"] if f["kind"] == "cdc_reconvergence"]
    assert hits, r["findings"]
    assert hits[0]["signal"] == "z"
    assert hits[0]["from_domain"] == "clk_a"
    assert hits[0]["to_domain"] == "clk_b"
    assert hits[0]["severity"] == "warn"
    assert "xa" in hits[0]["source"] and "ya" in hits[0]["source"]
    assert r["counts"]["cdc_warn"] >= 1
    assert r["checks"]["reconvergence"]["findings"] >= 1


def test_deep_detects_multibit():
    r = analyze_deep([("mb.sv", MULTIBIT_RTL)])
    hits = [f for f in r["findings"] if f["kind"] == "cdc_multibit"]
    assert hits, r["findings"]
    assert hits[0]["source"] == "data_a"
    assert hits[0]["severity"] == "warn"
    assert "gray" in hits[0]["note"].lower()
    # 2FF is present, so depth is not the complaint here.
    assert "cdc_1ff" not in _kinds(r)


def test_deep_detects_glitch():
    r = analyze_deep([("glitchy.sv", GLITCH_RTL)])
    hits = [f for f in r["findings"] if f["kind"] == "cdc_glitch"]
    assert hits, r["findings"]
    assert hits[0]["signal"] == "g1"
    assert hits[0]["to_domain"] == "clk_b"
    assert hits[0]["severity"] == "warn"


def test_deep_detects_single_flop():
    r = analyze_deep([("one_ff.sv", ONE_FF_RTL)])
    hits = [f for f in r["findings"] if f["kind"] == "cdc_1ff"]
    assert hits, r["findings"]
    assert hits[0]["signal"] == "ctrl_b"
    assert hits[0]["source"] == "ctrl_a"
    assert hits[0]["from_domain"] == "clk_a"
    assert hits[0]["severity"] == "warn"


def test_deep_recognizes_cdc_scheme():
    r = analyze_deep([("afifo.sv", SCHEME_RTL)])
    hits = [f for f in r["findings"] if f["kind"] == "cdc_scheme"]
    assert hits, r["findings"]
    assert all(f["severity"] == "info" for f in hits)
    assert any("gray" in f["source"].lower() for f in hits)
    # A recognized scheme suppresses the generic multi-bit warning.
    assert "cdc_multibit" not in _kinds(r)
    assert r["counts"]["cdc_info"] >= 1


def test_deep_clean_rtl_has_no_warnings():
    rtl = """
module single(input clk, input d, output q);
  reg r1;
  always @(posedge clk) begin
    r1 <= d;
  end
  assign q = r1;
endmodule
"""
    r = analyze_deep([("single.sv", rtl)])
    assert r["counts"]["cdc_warn"] == 0
    assert r["clocks"] == ["clk"]


def test_deep_handles_empty_and_junk_input():
    assert analyze_deep([])["findings"] == []
    assert analyze_deep([("a.sv", "")])["findings"] == []
    assert analyze_deep([("a.sv", "not verilog at all ;;;")])["counts"]["cdc_warn"] == 0


def test_counts_fold_unknown_cdc_kinds():
    findings = [
        {"kind": "cdc_multibit", "severity": "warn"},
        {"kind": "cdc_reconvergence", "severity": "warn"},
        {"kind": "cdc_scheme", "severity": "info"},
        {"kind": "rdc", "severity": "info"},
        {"kind": "lint", "severity": "warn"},
    ]
    counts = cdc_deep._counts(findings)
    assert counts == {"cdc_warn": 2, "cdc_info": 1, "rdc": 1}


def test_merge_deep_dedupes():
    shared = {
        "filename": "a.sv",
        "signal": "d1",
        "from_domain": "clk_a",
        "to_domain": "clk_b",
        "source": "data_a",
        "severity": "warn",
        "kind": "cdc",
        "note": "same note",
    }
    base = {
        "clocks": ["clk_a"],
        "findings": [shared, dict(shared, signal="other", note="base only")],
        "counts": {"cdc_warn": 2, "cdc_info": 0, "rdc": 0},
        "engine": "chipsutra-cdc-v0",
    }
    deep = analyze_deep([("mb.sv", MULTIBIT_RTL)])
    deep["findings"] = [dict(shared)] + deep["findings"]

    merged = merge_deep(base, deep)
    assert merged["engine"] == "chipsutra-cdc-deep-merged"
    assert merged["engines"] == ["chipsutra-cdc-v0", "chipsutra-cdc-deep"]
    assert sum(1 for f in merged["findings"] if f["note"] == "same note") == 1
    assert set(merged["clocks"]) == {"clk_a", "clk_b"}
    assert "cdc_multibit" in {f["kind"] for f in merged["findings"]}
    assert merged["counts"]["cdc_warn"] == len(
        [f for f in merged["findings"] if str(f["kind"]).startswith("cdc") and f["severity"] == "warn"]
    )
    assert "checks" in merged


def test_merge_deep_without_deep_returns_base():
    base = {"findings": [], "engine": "chipsutra-cdc-v0"}
    assert merge_deep(base, None) is base
