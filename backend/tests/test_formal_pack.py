"""Spec IR → SVA pack + CEX classify (offline)."""
from formal_pack import build_formal_pack, classify_cex, render_sby


def test_formal_pack_emits_module_and_sby():
    pack = build_formal_pack(
        "Clock clk, active-low reset rst_n, input enable, output count[7:0]. "
        "REQ-1: increment when enable is high.",
        dut="counter",
        depth=12,
    )
    assert "module" in pack["sva"]
    assert "counter_sva" in pack["sva"]
    assert "smtbmc" in pack["sby"]
    assert "depth 12" in pack["sby"]


def test_render_sby_has_bmc_engine():
    sby = render_sby("fifo", depth=8, sva_file="props.sv")
    assert "mode bmc" in sby
    assert "smtbmc" in sby
    assert "fifo.sv" in sby


def test_classify_cex_from_sby_fail():
    cex = classify_cex("SBY FAIL BMC failed: counterexample found")
    assert cex["source"] == "formal_cex"
    titles = {f["title"] for f in cex.get("findings") or []}
    assert "Formal CEX" in titles
