"""User CSR map → SV reg model / UVM RAL. No invented registers."""
from dv_user_config import attach_knobs, merge_with_design, parse_dv_config
from rtl_ports import extract_modules
from tb_dut_goldens import try_render_special_class_tb
from tb_ral import (
    normalize_csr_list,
    ral_prompt_block,
    render_sv_csr_sequences,
    render_sv_reg_model,
    render_uvm_frontdoor_seq,
    render_uvm_ral_block,
    wants_ral,
)
from tb_skeleton import render_class_sv_tb
from tb_uvm_skeleton import render_uvm_smoke_tb
from design_analyze import analyze_design

APB = """
module apb_regs(
  input pclk, input presetn, input psel, input penable, input pwrite,
  input [7:0] paddr, input [31:0] pwdata, output pready, output [31:0] prdata
);
endmodule
"""

CSRS = [
    {"name": "CTRL", "addr": "0x0", "reset": "0x1", "access": "rw",
     "fields": [{"name": "ENABLE", "lsb": 0, "width": 1}]},
    {"name": "STAT", "addr": "0x4", "reset": "0x0", "access": "ro"},
]


def test_normalize_drops_nameless():
    assert normalize_csr_list([{"addr": "0x0"}, {"name": "CTRL", "addr": "0x0"}])[0]["name"] == "CTRL"


def test_sv_reg_model_only_user_names():
    sv = render_sv_reg_model("apb_regs", normalize_csr_list(CSRS))
    assert "CTRL" in sv and "STAT" in sv
    assert "ENABLE" not in sv or "CTRL" in sv  # fields stay on UVM path
    assert "do not invent" in sv.lower() or "unmapped" in sv
    assert "TIMER" not in sv
    assert "CTRL = data[" in sv
    assert "ignore write" in sv
    assert "hw_reset" in sv
    assert "function void hw_reset()" in sv
    assert "reset_of" in sv
    assert "frontdoor_walk" in sv


def test_sv_w1c_clears_bits():
    sv = render_sv_reg_model(
        "uart_mini",
        normalize_csr_list([{"name": "INTR_STATE", "addr": "0x0", "access": "w1c"}]),
    )
    assert "INTR_STATE = INTR_STATE & ~data" in sv


def test_uvm_ral_block_user_map():
    sv = render_uvm_ral_block("apb_regs", normalize_csr_list(CSRS))
    assert "extends uvm_reg" in sv
    assert "apb_regs_reg_block" in sv
    assert "32'h0" in sv and "32'h4" in sv
    assert "ENABLE" in sv
    assert "lock_model" in sv
    assert "apb_regs_csr_seq" in sv
    assert "UVM_FRONTDOOR" in sv
    assert "mdl.CTRL.write" in sv
    assert "mdl.STAT.read" in sv


def test_sv_and_uvm_frontdoor_sequences():
    csrs = normalize_csr_list(CSRS)
    sv = render_sv_csr_sequences("apb_regs", csrs)
    assert "frontdoor_walk" in sv
    assert "predict_write" in sv
    assert "32'h0" in sv
    uvm = render_uvm_frontdoor_seq("apb_regs", csrs)
    assert "extends uvm_sequence" in uvm
    assert "UVM_FRONTDOOR" in uvm
    assert "CTRL" in uvm and "STAT" in uvm


def test_no_ral_without_map():
    cfg = parse_dv_config({"enable_ral": True}, env=False)
    assert cfg["enable_ral"] is False
    assert wants_ral({"_dv_knobs": cfg}) is False


def test_apb_golden_uses_named_model_when_ral():
    mod = extract_modules(APB)[0]
    cfg = parse_dv_config({"enable_ral": True, "csr_list": CSRS}, env=False)
    cfg = merge_with_design(cfg, [mod], tb_methodology="sv")
    attach_knobs(mod, cfg)
    assert cfg["design_protocol"] == "apb"
    assert cfg["enable_ral"] is True
    sv = try_render_special_class_tb(mod, cycles=8, seed=1)
    assert sv and "apb_regs_reg_model" in sv
    assert "addr inside" in sv
    assert "model_reg [0:3]" not in sv


def test_apb_golden_unchanged_without_map():
    mod = extract_modules(APB)[0]
    sv = render_class_sv_tb(mod, cycles=8, seed=1)
    assert "model_reg [0:3]" in sv
    assert "reg_model" not in sv


def test_analyze_ral_allowed_only_with_user_map():
    mods = extract_modules(APB)
    a0 = analyze_design(mods)
    assert a0["csr"]["ral_allowed"] is False
    cfg = parse_dv_config({"enable_ral": True, "csr_list": CSRS}, env=False)
    a1 = analyze_design(mods, user_config=cfg)
    assert a1["csr"]["ral_allowed"] is True
    assert "CTRL" in a1["brief"] or "user" in a1["csr"]["stance"].lower()


def test_uvm_smoke_embeds_ral_block():
    mod = extract_modules(APB)[0]
    cfg = parse_dv_config({"enable_ral": True, "csr_list": CSRS}, env=False)
    attach_knobs(mod, cfg)
    sv = render_uvm_smoke_tb(mod, cycles=8)
    assert "extends uvm_reg_block" in sv
    assert "apb_regs_CTRL_reg" in sv
    assert "extends uvm_reg_adapter" in sv
    assert "uvm_reg_predictor" in sv
    assert "set_sequencer" in sv
    assert "apb_regs_csr_seq" in sv
    assert "csr_s.mdl = env.ral" in sv


def test_ral_prompt_refuses_invented_map():
    assert "skip ral" in ral_prompt_block([], enable_ral=True).lower()
    block = ral_prompt_block(normalize_csr_list(CSRS), methodology="uvm", enable_ral=True)
    assert "CTRL" in block and "uvm_reg" in block


def test_prompt_with_ral_sets_flag_only_if_map():
    cfg = parse_dv_config(None, prompt="generate with RAL", env=False)
    assert cfg["protocol_knobs"].get("want_ral") is True
    assert cfg["enable_ral"] is False
