"""Offline tests for lint policy, synth flow, cocotb scaffold and VCD UX."""
import pytest

from cocotb_scaffold import render_cocotb_scaffold
from cocotb_runner import pick_scaffold_files, parse_cocotb_log, build_make_cmd
from coverage_parse import trend_points, merge_metric_lists
from lint_policy import apply_lint_policy, parse_policy, parse_verilator_findings
from yosys_flow import equiv_script, eqy_config, parse_eqy_log, parse_yosys_log, synth_script, fallback_equiv_note
from cdc_netlist import analyze_yosys_json, merge_cdc_results
from opensta_flow import build_sta_tcl, parse_sta_log, default_sdc_stub


def test_lint_policy_waives_owned_width_warning():
    log = "%Warning-WIDTH: rtl/foo.sv:12:5: Operator expects 8 bits"
    policy = parse_policy(
        """{
          "fatal_warnings": ["WIDTH"],
          "waivers": [{
            "code": "WIDTH", "file_glob": "rtl/*.sv", "line": 12,
            "reason": "Intentional truncation", "owner": "dv-team"
          }]
        }"""
    )
    report = apply_lint_policy(parse_verilator_findings(log), policy)
    assert report["gate_ok"] is True
    assert report["counts"]["waived"] == 1


def test_lint_policy_blocks_fatal_warning():
    findings = parse_verilator_findings("%Warning-CASEINCOMPLETE: foo.sv:4: Missing case")
    report = apply_lint_policy(findings, parse_policy('{"fatal_warnings":["CASEINCOMPLETE"]}'))
    assert report["gate_ok"] is False
    assert report["counts"]["blocking"] == 1


def test_lint_waiver_requires_owner_and_reason():
    with pytest.raises(ValueError):
        parse_policy('{"waivers":[{"code":"UNUSED"}]}')


def test_yosys_scripts_and_stats():
    syn = synth_script("top", ["top.sv"])
    eq = equiv_script("top", ["top.sv"])
    assert "synth -top top" in syn and "write_json synth.json" in syn
    assert "write_verilog" in syn and "synth_netlist.v" in syn
    assert "equiv_make" in eq and "equiv_status -assert" in eq
    stats = parse_yosys_log("Number of wires: 12\nNumber of memories: 1\nNumber of cells: 7\n")
    assert stats["cells"] == 7 and stats["wires"] == 12


def test_eqy_config_and_log_parser():
    cfg = eqy_config("top", ["gold.sv"], ["gate.v"])
    assert "[gold]" in cfg and "[gate]" in cfg
    assert "read_verilog -sv gold.sv" in cfg
    assert "infer_partition" in cfg
    ok = parse_eqy_log("Status: designs are equivalent\n2 partitions proved")
    assert ok["equivalence"] == "pass"
    assert ok["partitions"] == 2
    bad = parse_eqy_log("ERROR: inequivalent partition foo\nFAILED")
    assert bad["equivalence"] == "fail"
    assert fallback_equiv_note(True)


def test_cocotb_scaffold():
    files = render_cocotb_scaffold("counter", "counter.sv")
    assert "Makefile" in files
    assert "TOPLEVEL = counter" in files["Makefile"]
    assert "test_counter.py" in files
    assert "@cocotb.test()" in files["test_counter.py"]


def test_cocotb_runner_helpers():
    docs = [
        {"original_filename": "Makefile", "ext": "", "kind": "tb"},
        {"original_filename": "test_counter.py", "ext": "py", "kind": "tb"},
        {"original_filename": "counter.sv", "ext": "sv", "kind": "rtl"},
    ]
    mf, py, rtl = pick_scaffold_files(docs)
    assert mf and py and rtl
    hint = parse_cocotb_log("PASS smoke\nFAILED other\nERROR boom")
    assert hint["failed_hints"] >= 1
    # build_make_cmd may raise if make missing — that is acceptable
    try:
        cmd = build_make_cmd("verilator")
        assert cmd[-1].startswith("SIM=")
    except RuntimeError as e:
        assert "make" in str(e).lower()


def test_coverage_trend_and_merge():
    runs = [
        {"id": "a", "overall": 80.0, "created_at": "2026-01-02", "metrics": [{"name": "Line", "pct": 80}]},
        {"id": "b", "overall": 90.0, "created_at": "2026-01-01", "metrics": [{"name": "Line", "pct": 90}]},
    ]
    tr = trend_points(runs, limit=10)
    assert tr["count"] == 2
    assert tr["latest"] == 80.0
    merged = merge_metric_lists(runs)
    assert merged["metrics"][0]["pct"] == 85.0
    assert merged["merged_from"] == 2


def test_cdc_yosys_json_synthetic():
    net = {
        "modules": {
            "top": {
                "cells": {
                    "fa": {
                        "type": "$dff",
                        "connections": {"CLK": [1], "D": [10], "Q": [2]},
                    },
                    "fb": {
                        "type": "$dff",
                        "connections": {"CLK": [3], "D": [2], "Q": [4]},
                    },
                }
            }
        }
    }
    r = analyze_yosys_json(net)
    assert r["engine"].startswith("chipsutra-cdc")
    assert r["counts"]["cdc_warn"] + r["counts"]["cdc_info"] >= 1
    merged = merge_cdc_results(
        {"clocks": ["clk_a"], "findings": [], "counts": {"cdc_warn": 0, "cdc_info": 0, "rdc": 0}, "engine": "h"},
        r,
    )
    assert merged["engine"] == "chipsutra-cdc-v1-merged"


def test_opensta_helpers():
    tcl = build_sta_tcl(netlist="synth_netlist.v", sdc="chipsutra.sdc", top="top")
    assert "read_verilog" in tcl and "report_wns" in tcl
    sdc = default_sdc_stub("clk", 5.0)
    assert "create_clock" in sdc and "period 5.0" in sdc
    stats = parse_sta_log("wns -0.12\ntns -1.5\n")
    assert stats["wns"] == -0.12
    assert stats["tns"] == -1.5


def test_regression_models_import():
    """Import RegressionIn and coverage flag via model construction."""
    import os
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "test")
    from server import RegressionIn, RegressionCase
    inp = RegressionIn(
        project_id="p1",
        cases=[RegressionCase(name="t", rtl_file_ids=["a"], seeds=[1], coverage=True)],
        max_workers=99,
    )
    assert inp.cases[0].coverage is True
    # route clamps; model itself accepts int — clamp is in handler
    assert inp.max_workers == 99
