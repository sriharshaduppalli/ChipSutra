"""Tests for generation_rules (prompt hardening for local LLMs)."""
from generation_rules import rules_for_module, default_user_prompt, TESTBENCH_RULES
from rtl_ports import extract_modules, extract_port_context_from_texts


COUNTER_RTL = """
module counter_rtl (
    input wire clk,
    input wire rst_n,
    input wire enable,
    output reg [3:0] count
);
endmodule
"""


def test_counter_rtl_ports_parse():
    mods = extract_modules(COUNTER_RTL)
    assert mods[0]["name"] == "counter_rtl"
    names = [p["name"] for p in mods[0]["ports"]]
    assert names == ["clk", "rst_n", "enable", "count"]
    assert mods[0]["ports"][3]["width"] == "[3:0]"


def test_testbench_rules_ban_fake_apis_and_invented_ports():
    rules = rules_for_module("testbench", has_ports=True)
    assert "Never invent" in rules or "never invent" in rules.lower() or "Never invent" in TESTBENCH_RULES
    assert "random" in rules.lower()
    assert "Verilator" in rules
    assert "parsed port list" in rules.lower()
    assert "HARD RULES" in rules


def test_default_prompt_prefers_random_compact_sv():
    p = default_user_prompt("testbench", dut_hint="module counter_rtl")
    assert "counter_rtl" in p
    assert "Verilator" in p
    assert "random" in p.lower() or "urandom" in p.lower()
    assert "UVM" in p


def test_num_predict_caps_testbench():
    from generation_rules import num_predict_for_module
    assert 700 <= num_predict_for_module("testbench") <= 1200
    assert num_predict_for_module("assertions") <= num_predict_for_module("testbench")


def test_tb_golden_hint_detects_fifo_and_axi():
    from generation_rules import tb_golden_hint_from_ports
    assert "FIFO" in tb_golden_hint_from_ports(["clk", "wr_en", "wr_data", "rd_en", "rd_data", "full", "empty"])
    assert "AXI" in tb_golden_hint_from_ports(["aclk", "s_axi_awvalid", "s_axi_arvalid", "s_axi_wdata"])
    assert "parity" in tb_golden_hint_from_ports(["valid", "data", "parity"]).lower()


def test_port_context_mentions_counter_rtl():
    ctx = extract_port_context_from_texts([COUNTER_RTL])
    assert "module counter_rtl" in ctx
    assert "enable" in ctx and "count" in ctx
    assert "do not invent" in ctx.lower()
