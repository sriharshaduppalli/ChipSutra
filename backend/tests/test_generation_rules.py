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
    assert "class" in rules.lower()
    assert "random" in rules.lower() or "rand" in rules.lower()
    assert "parsed port list" in rules.lower()
    assert "HARD RULES" in rules
    assert "uvm_" in rules.lower() or "UVM" in rules
    assert "SCALE" in rules
    assert "chiplet" in rules.lower()


def test_default_prompt_prefers_class_based_sv():
    p = default_user_prompt("testbench", dut_hint="module counter_rtl")
    assert "counter_rtl" in p
    assert "LAYERED" in p or "interface" in p.lower()
    assert "generator" in p.lower() and "environment" in p.lower()
    assert "UVM" in p  # says NO UVM
    assert "mailbox" in p.lower()
    assert "run_test" in p.lower() or "uvm_*" in p.lower()


def test_num_predict_caps_testbench():
    from generation_rules import num_predict_for_module
    assert 700 <= num_predict_for_module("testbench") <= 1800
    assert num_predict_for_module("assertions") <= num_predict_for_module("testbench")
    # Layered Pure SV: bus protocols still get the larger class budget
    assert num_predict_for_module("testbench", protocol="counter") <= num_predict_for_module(
        "testbench", protocol="axi_lite"
    )


def test_tb_golden_hint_detects_fifo_and_axi():
    from generation_rules import tb_golden_hint_from_ports
    assert "FIFO" in tb_golden_hint_from_ports(["clk", "wr_en", "wr_data", "rd_en", "rd_data", "full", "empty"])
    assert "AXI" in tb_golden_hint_from_ports(["aclk", "s_axi_awvalid", "s_axi_arvalid", "s_axi_wdata"])
    assert "parity" in tb_golden_hint_from_ports(["valid", "data", "parity"]).lower()
    assert "RISC-V" in tb_golden_hint_from_ports(["clk", "rst_n", "pc", "instr", "mem_addr", "mem_rdata"])


def test_port_context_mentions_counter_rtl():
    ctx = extract_port_context_from_texts([COUNTER_RTL])
    assert "module counter_rtl" in ctx
    assert "enable" in ctx and "count" in ctx
    assert "do not invent" in ctx.lower()


def test_uvm_style_ref_is_example1_wiring_not_pure_sv_outline():
    """Counter is a 'light' Pure SV protocol; UVM must still get Example 1 connects."""
    from generation_rules import LAYERED_SV_OUTLINE, style_ref_for_protocol
    from rtl_ports import extract_modules
    from tb_uvm_skeleton import render_uvm_smoke_tb

    sv = style_ref_for_protocol("counter", methodology="sv")
    assert "generator" in sv.lower()
    assert sv == LAYERED_SV_OUTLINE or "mailbox" in sv.lower() or "NO UVM" in sv

    mods = extract_modules(COUNTER_RTL)
    hint = render_uvm_smoke_tb(mods[0], cycles=8)
    uvm = style_ref_for_protocol(
        "counter", hint, methodology="uvm"
    )
    assert "get_next_item" in uvm
    assert "seq_item_port.connect" in uvm
    assert "analysis_imp" in uvm or "ap.connect" in uvm
    assert "NEVER uvm_subscriber" in uvm
    assert "class counter_rtl_generator" not in uvm
    assert "mailbox gen2drv" not in uvm
    assert "function void write" in uvm or "write(" in uvm
    assert "counter_rtl dut" in uvm or ".enable(" in uvm


def test_uvm_style_ref_switch_adds_example2_golden():
    from generation_rules import style_ref_for_protocol, tb_golden_hint_from_ports

    uvm = style_ref_for_protocol("switch", methodology="uvm")
    assert "Example 2" in uvm or "address switch" in uvm.lower()
    assert "addr_a" in uvm and "addr_b" in uvm
    assert "seq_item_port.connect" in uvm
    assert "dual-thread" in uvm.lower() or "semaphore" in uvm.lower()
    hint = tb_golden_hint_from_ports(
        ["clk", "rstn", "vld", "addr", "data", "addr_a", "data_a", "addr_b", "data_b"]
    )
    assert "switch" in hint.lower()
    assert "Example 1" in hint or "TLM" in hint


def test_sv_vs_uvm_brief_covers_phases_tlm_objections():
    from generation_rules import SV_VS_UVM_BRIEF, rules_for_module

    b = SV_VS_UVM_BRIEF.lower()
    for needle in (
        "generator",
        "uvm_sequence",
        "get_next_item",
        "analysis_port",
        "analysis_imp",
        "connect_phase",
        "build_phase",
        "objection",
        "1-to-many",
        "factory",
        "covergroup",
        "uvm_subscriber",
        "uvm_testname",
        "uvm_object",
        "uvm_component",
        "is_active",
        "start_item",
        "virtual sequencer",
        "uvm_do",
        "csr map",
        "write() is a function",
        "seq_item_export",
        "item_done",
        "type_id::create",
        "always #5",
        "virtual if",
        "pin-wiggle",
        "analysis_fifo",
        "clocking",
    ):
        assert needle in b, needle
    sv = rules_for_module("testbench", tb_methodology="sv")
    uvm = rules_for_module("testbench", tb_methodology="uvm")
    assert "task reset/run/report" in sv or "no uvm phases" in sv.lower()
    assert "connect_phase" in uvm.lower()
    assert "class *_generator" in uvm or "no class *_generator" in uvm.lower() or "generator" in uvm.lower()
