"""Tests for TB methodology selection (SV / UVM / OVM / VMM)."""
from tb_methodology import normalize_methodology, is_class_methodology, rules_for_methodology
from dv_planner import plan_generation, classify_intent
from tb_skeleton import should_use_tb_skeleton
from rtl_ports import extract_modules
from generation_rules import rules_for_module, num_predict_for_module

COUNTER = """
module counter_rtl (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""


def test_normalize_aliases_and_prompt():
    assert normalize_methodology("UVM") == "uvm"
    assert normalize_methodology("systemverilog") == "sv"
    assert normalize_methodology("auto", prompt="please build full UVM agent") == "uvm"
    assert normalize_methodology("auto", prompt="ovm_env please") == "ovm"
    assert normalize_methodology("auto", prompt="vmm_channel scoreboard") == "vmm"
    assert normalize_methodology("auto", prompt="random SV tb") == "sv"


def test_class_methodologies():
    assert is_class_methodology("uvm")
    assert is_class_methodology("ovm")
    assert is_class_methodology("vmm")
    assert not is_class_methodology("sv")


def test_plan_uvm_forces_llm():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="skeleton", tb_methodology="uvm", modules=mods)
    assert p["engine_preference"] == "llm"
    assert p["tb_methodology"] == "uvm"
    assert p["verify"]["lint"] is False


def test_plan_sv_skeleton_style_still_llm():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="skeleton", tb_methodology="sv", modules=mods)
    assert p["engine_preference"] == "llm"
    assert p["tb_methodology"] == "sv"


def test_plan_sv_auto_uses_llm():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="auto", tb_methodology="sv", modules=mods)
    assert p["engine_preference"] == "llm"
    assert p["tb_methodology"] == "sv"


def test_should_use_skeleton_respects_methodology():
    mods = extract_modules(COUNTER)
    assert should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="skeleton", tb_methodology="sv")
    assert not should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="llm", tb_methodology="sv")
    assert not should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="skeleton", tb_methodology="uvm")
    assert not should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="auto", tb_methodology="vmm")


def test_rules_and_tokens_for_uvm():
    rules = rules_for_module("testbench", has_ports=True, tb_methodology="uvm")
    assert "UVM" in rules
    assert "run_test" in rules.lower() or "uvm" in rules.lower()
    assert "UVM BASICS" in rules
    assert "config_db" in rules
    assert "uvm_component" in rules
    assert "build_phase" in rules or "build/connect" in rules
    uvm_hard = rules_for_methodology("uvm")
    assert "get_next_item" in uvm_hard
    assert "objection" in uvm_hard.lower()
    assert "uvm_component" in uvm_hard
    assert "run_phase" in uvm_hard
    assert num_predict_for_module("testbench", tb_methodology="uvm") >= 1000
    assert num_predict_for_module("testbench", tb_methodology="sv") >= 1000


def test_sv_vs_uvm_map_in_both_methodology_prompts():
    sv = rules_for_module("testbench", tb_methodology="sv")
    uvm = rules_for_module("testbench", tb_methodology="uvm")
    for blob in (sv, uvm):
        assert "generator" in blob.lower()
        assert "uvm_sequence" in blob.lower()
        assert "mailbox" in blob.lower()
        assert "factory" in blob.lower() or "config_db" in blob.lower()
        assert "verilator" in blob.lower()
    assert "NO uvm" in sv or "no uvm" in sv.lower() or "NO uvm_*" in sv
    assert "run_test" in sv.lower() or "analysis_port" in sv.lower()
    assert "generator" in uvm.lower() and "NEVER mix" in uvm
    for blob in (sv, uvm):
        assert "build_phase" in blob.lower() or "connect_phase" in blob.lower()
        assert "objection" in blob.lower()
        assert "1-to-many" in blob.lower() or "analysis" in blob.lower()
        assert "factory" in blob.lower() or "type_id::create" in blob.lower() or "config_db" in blob.lower()
        assert "uvm_object" in blob.lower() or "start_item" in blob.lower()
        assert "item_done" in blob.lower() or "write()" in blob.lower()


def test_intent_marks_class_tb():
    i = classify_intent("testbench", "", tb_methodology="ovm")
    assert i["tb_methodology"] == "ovm"
    assert i["wants_class_tb"] is True


def test_render_class_sv_counter_has_full_layered_stack():
    from tb_skeleton import render_class_sv_tb

    mods = extract_modules(COUNTER)
    sv = render_class_sv_tb(mods[0], cycles=16, seed=1)
    for needle in (
        "interface counter_rtl_if",
        "class counter_rtl_txn",
        "class counter_rtl_generator",
        "class counter_rtl_driver",
        "class counter_rtl_monitor",
        "class counter_rtl_scoreboard",
        "class counter_rtl_env",
        "class counter_rtl_test",
        "module counter_rtl_tb",
    ):
        assert needle in sv, needle
    assert "mailbox" in sv
    assert "uvm_" not in sv.lower()
    assert "layered" in sv.lower()


def test_default_prompt_uvm():
    from generation_rules import default_user_prompt

    p = default_user_prompt("testbench", dut_hint="module counter_rtl", tb_methodology="uvm")
    assert "UVM" in p
    assert "run_test" in p
    assert "objection" in p.lower() or "connect_phase" in p.lower()
    assert "generator" in p.lower()  # banned (do not emit)


def test_rag_retrieves_methodology_curriculum():
    from rag import retrieve

    chunks = retrieve(
        "UVM OVM VMM methodology SystemVerilog testbench agent",
        module="testbench",
        filenames=[],
        top_k=4,
    )
    blob = " ".join(c["title"] + " " + c["body"] for c in chunks).lower()
    assert "methodology" in blob or "uvm" in blob
    sources = {c["source"] for c in chunks}
    assert (
        "verification_methodologies_curriculum.txt" in sources
        or "kg_sv_uvm_learning.txt" in sources
        or "dv_tb_templates.txt" in sources
    )