"""Skeleton goldens for eval-suite DUTs: real checks, combo has no virtual IF."""
from __future__ import annotations

from pathlib import Path

from dv_planner import classify_dut
from rtl_ports import extract_modules
from tb_class_lint import lint_class_sv_tb
from tb_skeleton import render_class_sv_tb
from tb_uvm_lint import lint_uvm_tb
from tb_uvm_skeleton import render_uvm_smoke_tb

DUTS = Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts"

COMBO = ("alu4.sv", "prio_enc4.sv", "shifter8.sv", "gray2bin4.sv", "bin2gray4.sv")
SEQ = (
    "sample_parity.sv",
    "edge_detect.sv",
    "pwm8.sv",
    "debounce.sv",
    "sync_ff.sv",
    "axis_sink.sv",
)
BUS = ("apb_regs.sv", "axi_lite_slave.sv", "ahb_slave.sv", "spi_slave.sv", "uart_tx.sv", "i2c_slave.sv")


def _mod(name: str) -> dict:
    return extract_modules((DUTS / name).read_text(encoding="utf-8"))[0]


def test_combo_class_sv_no_virtual_and_real_check():
    for name in COMBO:
        mod = _mod(name)
        sv = render_class_sv_tb(mod, cycles=16, seed=1)
        assert "virtual " not in sv, name
        assert "beats++" not in sv.replace(" ", ""), name
        assert "function bit check(); return 1;" not in sv, name
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
        assert ok, (name, issues)


def test_seq_and_bus_class_sv_not_noop():
    for name in SEQ + BUS:
        mod = _mod(name)
        sv = render_class_sv_tb(mod, cycles=16, seed=1)
        assert "beats++" not in sv.replace(" ", ""), name
        assert "function bit check(); return 1;" not in sv, name
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
        assert ok, (name, issues)


def test_uvm_kinds_not_generic_seen():
    for name in COMBO + SEQ + BUS:
        mod = _mod(name)
        sv = render_uvm_smoke_tb(mod, cycles=8)
        assert "seen++" not in sv.replace(" ", ""), name
        ok, issues = lint_uvm_tb(sv, port_specs=mod["ports"])
        assert ok, (name, issues)
        if name == "spi_slave.sv":
            assert "spi rx mismatch" in sv
        if name == "uart_tx.sv":
            assert "uart last_byte" in sv or "uart golden" in sv
        if name == "i2c_slave.sv":
            assert "i2c last_data" in sv


def test_planner_tags_pwm_debounce_shifter_sync():
    expect = {
        "pwm8.sv": "pwm",
        "debounce.sv": "debounce",
        "shifter8.sv": "shifter",
        "sync_ff.sv": "cdc",
    }
    for name, proto in expect.items():
        rtl = (DUTS / name).read_text(encoding="utf-8")
        got = classify_dut(extract_modules(rtl), rtl_text=rtl)["protocol"]
        assert got == proto, (name, got)
