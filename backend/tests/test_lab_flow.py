"""Unit tests for one-click Lab pipeline helpers."""
from lab_flow import (
    classify_hdl_files,
    looks_like_tb,
    plan_lab_stages,
    pipeline_status,
    stage_failed,
)


def test_looks_like_tb():
    assert looks_like_tb("counter_tb.sv")
    assert looks_like_tb("mux_tb.v")
    assert not looks_like_tb("counter.sv")
    assert not looks_like_tb("synth_netlist.v")


def test_classify_hdl_files():
    files = [
        {"id": "1", "original_filename": "dut.sv", "ext": "sv", "kind": "rtl"},
        {"id": "2", "original_filename": "dut_tb.sv", "ext": "sv", "kind": "tb"},
        {"id": "3", "original_filename": "synth_netlist.v", "ext": "v", "kind": "artifact"},
        {"id": "4", "original_filename": "sky130.lib", "ext": "lib"},
        {"id": "5", "original_filename": "chipsutra.sdc", "ext": "sdc"},
        {"id": "6", "original_filename": "gone.sv", "ext": "sv", "is_deleted": True},
    ]
    b = classify_hdl_files(files)
    assert [f["id"] for f in b["rtl"]] == ["1"]
    assert [f["id"] for f in b["tb"]] == ["2"]
    assert [f["id"] for f in b["liberty"]] == ["4"]
    assert [f["id"] for f in b["sdc"]] == ["5"]


def test_plan_skips_sim_without_tb():
    stages = plan_lab_stages(has_rtl=True, has_tb=False)
    assert [s["id"] for s in stages] == ["lint", "synth", "sta"]


def test_plan_includes_sim_with_tb():
    stages = plan_lab_stages(has_rtl=True, has_tb=True)
    assert [s["id"] for s in stages] == ["lint", "sim", "synth", "sta"]


def test_plan_includes_optional_verible():
    stages = plan_lab_stages(has_rtl=True, has_tb=True, has_verible=True)
    assert [s["id"] for s in stages] == ["verible", "lint", "sim", "synth", "sta"]
    from lab_flow import run_verible_lint

    mock = run_verible_lint([("dut.sv", "module d; endmodule")])
    assert mock["status"] in ("mock", "done", "error")


def test_plan_skip_sim_flag():
    stages = plan_lab_stages(has_rtl=True, has_tb=True, skip_sim=True)
    assert [s["id"] for s in stages] == ["lint", "synth", "sta"]


def test_plan_empty_without_rtl():
    assert plan_lab_stages(has_rtl=False, has_tb=True) == []


def test_stage_failed():
    assert not stage_failed("lint", "done")
    assert not stage_failed("sta", "mock")
    assert stage_failed("sim", "error")
    assert stage_failed("synth", None)


def test_pipeline_status():
    assert pipeline_status([]) == "error"
    assert pipeline_status([{"status": "done", "failed": False}, {"status": "done", "failed": False}]) == "done"
    assert pipeline_status([{"status": "done", "failed": False}, {"status": "mock", "failed": False}]) == "partial"
    assert pipeline_status([{"status": "error", "failed": True}]) == "error"
