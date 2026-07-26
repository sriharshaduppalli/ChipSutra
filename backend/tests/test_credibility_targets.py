"""Offline tests for lint policy, synth flow, cocotb scaffold and VCD UX."""
import pytest

from cocotb_scaffold import render_cocotb_scaffold
from lint_policy import apply_lint_policy, parse_policy, parse_verilator_findings
from yosys_flow import equiv_script, parse_yosys_log, synth_script


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
    assert "equiv_make" in eq and "equiv_status -assert" in eq
    stats = parse_yosys_log("Number of wires: 12\nNumber of memories: 1\nNumber of cells: 7\n")
    assert stats["cells"] == 7 and stats["wires"] == 12


def test_cocotb_scaffold():
    files = render_cocotb_scaffold("counter", "counter.sv")
    assert "Makefile" in files
    assert "TOPLEVEL = counter" in files["Makefile"]
    assert "test_counter.py" in files
    assert "@cocotb.test()" in files["test_counter.py"]
