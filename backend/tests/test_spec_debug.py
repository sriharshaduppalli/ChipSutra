"""Tests for Spec→RTL checklist and debug log classifier."""
from spec_checklist import analyze_spec, checklist_prompt_block
from debug_classify import classify_log, debug_prompt_block


def test_spec_empty_not_ready():
    a = analyze_spec("")
    assert a["ready"] is False
    assert a["grade"] == "empty"


def test_spec_core_ready():
    text = """
    Design a 8-bit counter with clock clk, active-low reset rst_n,
    input enable, output count[7:0].
    """
    a = analyze_spec(text)
    assert a["checklist"]["clock"]
    assert a["checklist"]["reset"]
    assert a["checklist"]["io_ports"]
    assert a["ready"] is True
    assert a["grade"] in ("usable", "solid")
    block = checklist_prompt_block(a)
    assert "ready=True" in block or "ready=true" in block.lower()


def test_spec_weak_missing_reset():
    a = analyze_spec("Build a UART TX with clock and tx output pin.")
    assert a["checklist"]["clock"]
    assert a["ready"] is False or not a["checklist"]["reset"]
    assert any("reset" in g.lower() for g in a["gaps"])


def test_spec_gate_emits_stub(monkeypatch):
    from spec_checklist import exploratory_stub_rtl, spec_gate_blocks

    monkeypatch.delenv("CHIPSUTRA_SPEC_GATE", raising=False)
    a = analyze_spec("a UART with a tx pin")
    assert spec_gate_blocks(a) is True
    stub = exploratory_stub_rtl(a, prompt="make uart")
    assert "exploratory_stub" in stub
    assert "ASSUMPTION" in stub
    assert "module exploratory_stub" in stub
    monkeypatch.setenv("CHIPSUTRA_SPEC_GATE", "0")
    assert spec_gate_blocks(a) is False


def test_debug_port_error():
    log = "%Error: Port 'data_in' not found in module 'counter'"
    c = classify_log(log)
    assert c["empty"] is False
    assert c["top_category"] == "ports"
    assert any("Port" in t or "port" in t.lower() for t in c["templates"])
    assert "Port map" in debug_prompt_block(c)


def test_debug_verilator_uvm():
    log = "Unsupported: class uvm_object / UVM_ERROR"
    c = classify_log(log)
    assert c["top_category"] in ("tooling", "scoreboard")
    assert c["findings"]


def test_debug_incomplete_module_and_fifo_x():
    truncated = "module tb;\n  initial begin\n    wr_en = 1;\n"
    log = "%Error: tb.sv:40: syntax error, unexpected $end"
    c = classify_log(log, prior_code=truncated)
    titles = {f["title"] for f in c["findings"]}
    assert "Incomplete module" in titles
    assert c["ok"] is False

    xlog = "FAIL after reset: rd_data is X (unknown)"
    cx = classify_log(xlog)
    assert any(f["title"].startswith("FIFO") for f in cx["findings"])


def test_spec_ir_extracts_ports_and_requirements():
    from spec_ir import extract_spec_ir, spec_ir_prompt_block, sva_stubs_from_ir

    spec = """
    Clock clk, active-low reset rst_n.
    input [3:0] enable
    output [3:0] count
    REQ-1: The counter shall increment when enable is high.
    REQ-2: count shall be zero after reset.
    """
    ir = extract_spec_ir(spec)
    names = {p["name"] for p in ir["ports"]}
    assert "enable" in names and "count" in names
    assert ir["requirement_count"] >= 2
    block = spec_ir_prompt_block(ir)
    assert "REQ-1" in block
    stubs = sva_stubs_from_ir(ir)
    assert "posedge" in stubs
    assert "clk" in stubs.lower() or "rst" in stubs.lower()


def test_debug_formal_cex_category():
    c = classify_log("SBY FAIL BMC failed: counterexample at step 7")
    assert c["empty"] is False
    titles = {f["title"] for f in c["findings"]}
    assert "Formal CEX" in titles
    assert c["top_category"] == "formal"
