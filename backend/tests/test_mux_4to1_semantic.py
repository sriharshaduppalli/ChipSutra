"""mux_4to1 noop-scoreboard lint + mechanical repair + sim gate."""
from pathlib import Path
import re

from dv_verify import verify_testbench
from rtl_ports import extract_modules
from tb_class_lint import repair_class_sv_tb
from tb_semantic import lint_semantic_golden
from tb_skeleton import classify_ports, detect_mux_model, render_class_sv_tb

ROOT = Path(__file__).resolve().parents[1]
DUT = (ROOT / "scripts" / "eval_suite" / "duts" / "mux_4to1.sv").read_text(encoding="utf-8")
BROKEN = (ROOT / "storage" / "sim_mux_4to1" / "mux_4to1_broken_tb.sv").read_text(
    encoding="utf-8"
)


def test_detect_mux_4to1():
    mod = extract_modules(DUT)[0]
    mux = detect_mux_model(classify_ports(mod["ports"]))
    assert mux is not None
    assert mux["kind"] == "nto1"
    assert len(mux["data"]) == 4


def test_noop_scoreboard_flagged():
    issues = lint_semantic_golden(BROKEN, protocol="generic")
    assert "semantic_noop_check" in issues
    assert "semantic_mux_no_select" in issues


def test_repair_replaces_noop_mux_scoreboard():
    mod = extract_modules(DUT)[0]
    fixed = repair_class_sv_tb(
        BROKEN, port_specs=mod["ports"], dut_name=mod["name"], clk_name="clk"
    )
    issues = lint_semantic_golden(fixed, protocol="generic")
    assert "semantic_noop_check" not in issues
    assert "semantic_mux_no_select" not in issues
    assert "case" in fixed.lower() or "?" in fixed
    # Verilator-safe: no virtual-IF handles on combo mux
    assert "virtual mux_" not in fixed


def test_skeleton_mux_has_real_check():
    mod = extract_modules(DUT)[0]
    tb = render_class_sv_tb(mod, cycles=32, seed=1)
    assert "function bit check(); return 1;" not in tb
    assert "case" in tb.lower() or "?" in tb
    assert "interface mux_4to1_if" in tb or "interface mux_4to1" in tb
    assert "class mux_4to1_generator" in tb
    assert "class mux_4to1_driver" in tb
    assert "class mux_4to1_monitor" in tb
    assert "class mux_4to1_env" in tb
    assert "mailbox" in tb
    assert not re.search(r"\bvirtual\s+\w+", tb)


def test_repaired_mux_sim_pass():
    mod = extract_modules(DUT)[0]
    fixed = repair_class_sv_tb(
        BROKEN, port_specs=mod["ports"], dut_name=mod["name"], clk_name="clk"
    )
    r = verify_testbench(
        [("mux_4to1.sv", DUT)], fixed, tb_name="mux_4to1_tb.sv", mode="run"
    )
    assert r.get("sim_pass") is True, r.get("sim_log") or r.get("log")
