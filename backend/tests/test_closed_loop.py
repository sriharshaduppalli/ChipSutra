"""Closed-loop sim repair + mutation (no Verilator required)."""
import asyncio

from closed_loop import compact_mutation, env_enabled, repair_round_limit, run_closed_loop


def test_env_enabled_auto_and_off(monkeypatch):
    monkeypatch.delenv("CHIPSUTRA_SIM_GATE", raising=False)
    assert env_enabled("CHIPSUTRA_SIM_GATE", "auto", tool_present=True) is True
    assert env_enabled("CHIPSUTRA_SIM_GATE", "auto", tool_present=False) is False
    monkeypatch.setenv("CHIPSUTRA_SIM_GATE", "0")
    assert env_enabled("CHIPSUTRA_SIM_GATE", "auto", tool_present=True) is False


def test_repair_round_limit_capped(monkeypatch):
    monkeypatch.setenv("CHIPSUTRA_REPAIR_ROUNDS", "99")
    assert repair_round_limit() == 4
    monkeypatch.setenv("CHIPSUTRA_REPAIR_ROUNDS", "2")
    assert repair_round_limit() == 2


def test_compact_mutation_shape():
    c = compact_mutation(
        {
            "kill_rate": 1.0,
            "killed": 2,
            "survived": 0,
            "total": 2,
            "workers": 2,
            "mutants": [{"mutant": "x", "status": "killed", "sim_log_tail": "nope"}],
        }
    )
    assert c["kill_rate"] == 1.0
    assert "sim_log_tail" not in c["mutants"][0]


def test_closed_loop_repairs_then_mutates(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIPSUTRA_SIM_GATE", "true")
    monkeypatch.setenv("CHIPSUTRA_MUTATION", "true")
    monkeypatch.setenv("CHIPSUTRA_REPAIR_ROUNDS", "2")
    monkeypatch.setenv("CHIPSUTRA_FAILFIX_JSONL", str(tmp_path / "failfix.jsonl"))

    def fake_verify(sources, tb, **kwargs):
        if "PASS_ME" in (tb or ""):
            return {"ok": True, "skipped": False, "sim_pass": True}
        return {
            "ok": False,
            "skipped": False,
            "reason": "sim_fail",
            "errors": ["mismatch"],
            "sim_log": "FAIL scoreboard",
        }

    def mech(tb):
        return tb + "\n// PASS_ME\n"

    def mut(rtl, tb, **kwargs):
        return {
            "skipped": False,
            "baseline_pass": True,
            "kill_rate": 1.0,
            "killed": 2,
            "survived": 0,
            "total": 2,
            "workers": 2,
            "mutants": [{"mutant": "drop_reset", "status": "killed"}],
        }

    loop = asyncio.run(
        run_closed_loop(
            tb_sv="module tb; endmodule",
            rtl_sources=[("dut.sv", "module dut; endmodule")],
            tb_name="tb.sv",
            dut_name="dut",
            protocol="counter",
            skeleton_sv="module tb_skel; endmodule",
            mechanical_repair=mech,
            verify_fn=fake_verify,
            mutation_fn=mut,
            analysis={"protocol": "counter", "support_tier": "supported", "timing_style": "sequential"},
        )
    )
    assert loop.learning["sim_pass"] is True
    assert loop.learning["repair_rounds"] >= 1
    assert loop.learning["mutation"]["kill_rate"] == 1.0
    assert loop.learning["evidence"]["chipsutra_evidence"] == "1.0"
    assert any(e.get("type") == "replace" for e in loop.events)
    assert (tmp_path / "failfix.jsonl").is_file()


def test_closed_loop_skeleton_on_persistent_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("CHIPSUTRA_SIM_GATE", "true")
    monkeypatch.setenv("CHIPSUTRA_MUTATION", "0")
    monkeypatch.setenv("CHIPSUTRA_REPAIR_ROUNDS", "1")
    monkeypatch.setenv("CHIPSUTRA_FAILFIX_JSONL", str(tmp_path / "failfix.jsonl"))

    def fake_verify(sources, tb, **kwargs):
        if "skel_ok" in (tb or ""):
            return {"ok": True, "skipped": False, "sim_pass": True}
        return {"ok": False, "skipped": False, "errors": ["FAIL"], "sim_log": "FAIL"}

    loop = asyncio.run(
        run_closed_loop(
            tb_sv="module tb; endmodule",
            rtl_sources=[("dut.sv", "module dut; endmodule")],
            tb_name="tb.sv",
            skeleton_sv="module tb; // skel_ok\nendmodule",
            verify_fn=fake_verify,
            mutation_fn=lambda *a, **k: {"skipped": True},
        )
    )
    assert loop.engine == "skeleton_fallback"
    assert loop.learning["sim_pass"] is True
    assert loop.learning.get("skeleton_fallback") is True


def test_closed_loop_skipped_still_has_evidence(monkeypatch):
    monkeypatch.setenv("CHIPSUTRA_SIM_GATE", "true")

    def fake_verify(sources, tb, **kwargs):
        return {"ok": False, "skipped": True, "reason": "no_verilator"}

    loop = asyncio.run(
        run_closed_loop(
            tb_sv="module tb; endmodule",
            rtl_sources=[("dut.sv", "module dut; endmodule")],
            tb_name="tb.sv",
            verify_fn=fake_verify,
        )
    )
    assert loop.learning["sim_gate"] == "skipped"
    assert loop.learning["evidence"]["chipsutra_evidence"] == "1.0"
    assert loop.learning["evidence"]["sim_pass"] is None
