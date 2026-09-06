"""End-to-end RAL cross-check: HJSON import → SV/UVM models → APB/AXI TB lint (+ sim)."""
from __future__ import annotations

from pathlib import Path

from dv_user_config import attach_knobs, merge_with_design, parse_dv_config
from dv_verify import verify_testbench
from rtl_ports import extract_modules
from tb_class_lint import lint_class_sv_tb
from tb_dut_goldens import try_render_special_class_tb
from tb_ral import normalize_csr_list, render_sv_reg_model, render_uvm_ral_block
from tb_skeleton import render_class_sv_tb
from tb_uvm_lint import lint_uvm_tb
from tb_uvm_skeleton import render_uvm_smoke_tb

REPO = Path(__file__).resolve().parents[1]
HJSON = Path(__file__).resolve().parent / "fixtures" / "sample_uart.hjson"
APB_RTL = (REPO / "scripts" / "eval_suite" / "duts" / "apb_regs.sv").read_text(encoding="utf-8")
AXI_RTL = (REPO / "scripts" / "eval_suite" / "duts" / "axi_lite_slave.sv").read_text(encoding="utf-8")

FOUR_REGS = [
    {"name": "REG0", "addr": "0x0", "access": "rw", "reset": "0x0"},
    {"name": "REG1", "addr": "0x4", "access": "rw", "reset": "0x0"},
    {"name": "REG2", "addr": "0x8", "access": "rw", "reset": "0x0"},
    {"name": "REG3", "addr": "0xc", "access": "rw", "reset": "0x0"},
]


def _lint_ok(sv: str, mod: dict) -> None:
    ports = [p["name"] for p in mod["ports"]]
    outs = [
        p["name"]
        for p in mod["ports"]
        if (p.get("direction") or "").lower() in ("output", "out", "inout")
    ]
    ok, issues = lint_class_sv_tb(
        sv,
        dut_name=mod["name"],
        required_ports=ports,
        dut_outputs=outs,
        port_specs=mod["ports"],
    )
    assert ok, issues


def test_hjson_model_access_semantics():
    cfg = parse_dv_config({"ip_hjson": str(HJSON), "enable_ral": True}, env=False)
    csrs = normalize_csr_list(cfg["csr_list"])
    by = {c["name"]: c for c in csrs}
    assert by["INTR_STATE"]["access"] == "W1C"
    assert by["STATUS"]["access"] == "RO"
    assert by["CTRL"]["access"] == "RW"
    sv = render_sv_reg_model("uart_mini", csrs)
    assert "INTR_STATE = INTR_STATE & ~data" in sv
    assert "STATUS" in sv and "ignore write" in sv
    assert "CTRL = data[" in sv
    assert "TIMER" not in sv and "invent" in sv.lower()
    uvm = render_uvm_ral_block("uart_mini", csrs)
    assert '"W1C"' in uvm
    assert "add_reg(STATUS" in uvm and '"RO"' in uvm
    assert "ENABLE" in uvm


def test_apb_axi_ral_tb_lints_and_uses_map():
    for rtl, tag in ((APB_RTL, "apb_ral"), (AXI_RTL, "axi_lite_ral")):
        mod = extract_modules(rtl)[0]
        cfg = parse_dv_config({"enable_ral": True, "csr_list": FOUR_REGS}, env=False)
        cfg = merge_with_design(cfg, [mod], rtl_text=rtl, tb_methodology="sv")
        attach_knobs(mod, cfg)
        sv = try_render_special_class_tb(mod, cycles=8, seed=1)
        assert sv, tag
        assert f"{mod['name']}_reg_model" in sv
        assert "addr inside {32'h0, 32'h4, 32'h8, 32'hc}" in sv
        assert "model_reg [0:3]" not in sv
        _lint_ok(sv, mod)
        default = render_class_sv_tb(extract_modules(rtl)[0], cycles=8, seed=1)
        assert "model_reg [0:3]" in default


def test_uvm_ral_smoke_lints():
    mod = extract_modules(APB_RTL)[0]
    cfg = parse_dv_config({"enable_ral": True, "csr_list": FOUR_REGS}, env=False)
    attach_knobs(mod, cfg)
    sv = render_uvm_smoke_tb(mod, cycles=8)
    assert "extends uvm_reg_block" in sv
    assert "apb_regs_REG0_reg" in sv
    ok, issues = lint_uvm_tb(sv, port_specs=mod["ports"])
    assert ok, issues


def test_apb_axi_ral_verilator_sim_if_present():
    cases = (
        (APB_RTL, "apb_regs.sv", "apb_regs_tb.sv"),
        (AXI_RTL, "axi_lite_slave.sv", "axi_lite_slave_tb.sv"),
    )
    for rtl, rtl_name, tb_name in cases:
        mod = extract_modules(rtl)[0]
        cfg = parse_dv_config({"enable_ral": True, "csr_list": FOUR_REGS}, env=False)
        attach_knobs(mod, cfg)
        sv = try_render_special_class_tb(mod, cycles=8, seed=1)
        assert sv, rtl_name
        result = verify_testbench([(rtl_name, rtl)], sv, tb_name=tb_name, mode="run")
        if result.get("skipped") or result.get("reason") == "verilator_not_on_path":
            return
        assert result.get("ok") is True, (
            rtl_name,
            result.get("sim_log") or result.get("log") or result,
        )
        assert result.get("sim_pass") is True, (
            rtl_name,
            result.get("sim_log") or result.get("log"),
        )
