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


def test_debug_empty():
    c = classify_log("")
    assert c["empty"] is True
    assert debug_prompt_block(c) == ""
