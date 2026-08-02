"""Tests for dv_verify and llm_router."""
from __future__ import annotations

from dv_verify import verify_testbench, verify_sv_sources, verilator_bin, verify_status_for_learning
from llm_router import resolve_model, model_3b, prewarm_status


RTL = """
module counter_rtl (
  input wire clk, input wire rst_n, input wire enable,
  output reg [3:0] count
);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) count <= 0;
    else if (enable) count <= count + 1;
endmodule
"""

TB = """
`timescale 1ns / 1ps
module counter_rtl_tb;
  logic clk, rst_n, enable;
  logic [3:0] count;
  counter_rtl dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    clk = 0; rst_n = 0; enable = 0;
    #20 rst_n = 1;
    $finish;
  end
endmodule
"""


def test_verilator_bin_is_optional():
    # Just ensure API is callable; machine may or may not have verilator
    b = verilator_bin()
    assert b is None or isinstance(b, str)


def test_verify_skips_without_sources_body():
    r = verify_sv_sources([])
    assert r["ok"] is False
    assert "no_sources" in (r.get("errors") or [r.get("reason")])


def test_verify_testbench_runs_or_skips():
    r = verify_testbench([("counter_rtl.sv", RTL)], TB, tb_name="counter_rtl_tb.sv")
    assert "skipped" in r
    if r["skipped"]:
        assert r["ok"] is None
        assert r["reason"] == "verilator_not_on_path"
    else:
        assert r["engine"] == "verilator"
        assert r["ok"] in (True, False)
    learn = verify_status_for_learning(r)
    assert "verify_ok" in learn


def test_resolve_model_non_ollama_passthrough():
    r = resolve_model(provider="openai", requested_model="gpt-4o", model_tier="7b_preferred")
    assert r["model"] == "gpt-4o"
    assert r["reason"] == "non_ollama_passthrough"


def test_resolve_model_ollama_defaults():
    r = resolve_model(provider="ollama", requested_model="", model_tier="3b", ollama_url="")
    assert r["model"] == model_3b()
    assert "ollama" in r["provider"]


def test_prewarm_status_shape():
    st = prewarm_status()
    assert "attempted" in st
    assert "ok" in st
