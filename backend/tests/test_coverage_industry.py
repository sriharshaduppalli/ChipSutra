"""Offline tests for UCIS/IMC adapters, coverage.dat merging and the closure loop."""
import pytest

from coverage_loop import (
    build_closure_prompt,
    closure_status,
    rank_holes,
    suggest_resim_plan,
)
from coverage_merge import (
    annotate_merged,
    merge_coverage_dats,
    merge_summary_points,
    verilator_coverage_bin,
)
from ucis_parse import (
    detect_and_parse,
    parse_coverage_csv,
    parse_imc_urg_text,
    parse_ucis_xml,
)


UCIS_XML = """<?xml version="1.0"?>
<ucis xmlns="urn:ucis">
  <coverageInstance name="top.u_fifo">
    <covergroup name="cg_fifo" coveredBins="6" totalBins="10"/>
    <coverpoint name="cp_depth" coveredBins="9" totalBins="10"/>
    <cross name="cx_rw" coveredBins="2" totalBins="8"/>
    <toggle name="tg_data" pct="95.0"/>
  </coverageInstance>
</ucis>
"""


def test_parse_ucis_xml_metrics_and_holes():
    r = parse_ucis_xml(UCIS_XML)
    assert r["source"] == "ucis_xml"
    names = {m["name"] for m in r["metrics"]}
    assert {"cg_fifo", "cp_depth", "cx_rw"} <= names
    by_name = {m["name"]: m["pct"] for m in r["metrics"]}
    assert by_name["cx_rw"] == 25.0
    assert any(h["name"] == "cx_rw" for h in r["holes"])
    assert 0 < r["overall"] <= 100


def test_parse_ucis_xml_rejects_malformed():
    with pytest.raises(ValueError):
        parse_ucis_xml("<ucis><covergroup></ucis>")
    with pytest.raises(ValueError):
        parse_ucis_xml("   ")


def test_parse_imc_urg_label_and_total():
    text = """
    Line Coverage: 92.5%
    Toggle Coverage: 61.0%
    TOTAL COVERAGE: 78.30%
    """
    r = parse_imc_urg_text(text)
    assert r["source"] == "imc_urg"
    assert r["count"] >= 2
    assert any(h["pct"] < 90 for h in r["holes"])


def test_parse_coverage_csv_autodetects_columns():
    csv_text = "instance,score\nu_fifo,88.5\nu_axi,99.0\n"
    r = parse_coverage_csv(csv_text)
    assert r["source"] == "csv"
    assert {m["name"] for m in r["metrics"]} == {"u_fifo", "u_axi"}
    assert [h["name"] for h in r["holes"]] == ["u_fifo"]


def test_detect_and_parse_routes_formats():
    assert detect_and_parse(UCIS_XML, "run.ucis")["detected"] == "ucis_xml"
    assert detect_and_parse("module,coverage\na,50\n", "cov.csv")["detected"] == "csv"
    assert detect_and_parse("Line Coverage: 40%", "urg.log")["detected"] == "imc_urg"
    with pytest.raises(ValueError):
        detect_and_parse("no coverage data here", "x.log")


def test_merge_summary_points_is_union_not_average():
    runs = [
        {"metrics": [{"name": "line", "pct": 40.0}, {"name": "toggle", "pct": 90.0}]},
        {"metrics": [{"name": "line", "pct": 80.0}]},
    ]
    merged = merge_summary_points(runs)
    by_name = {m["name"]: m["pct"] for m in merged["metrics"]}
    assert by_name["line"] == 80.0  # max, not the 60.0 average
    assert merged["source"] == "merged_union"
    assert merged["merged_from"] == 2


def test_merge_summary_points_prefers_hit_counts():
    runs = [
        {"metrics": [{"name": "line", "pct": 25.0, "hit": 1, "miss": 3}]},
        {"metrics": [{"name": "line", "pct": 75.0, "hit": 3, "miss": 1}]},
    ]
    merged = merge_summary_points(runs)
    metric = merged["metrics"][0]
    assert metric["hit"] == 3 and metric["miss"] == 1
    assert merged["overall"] == 75.0


def test_coverage_dat_merge_handles_missing_inputs(tmp_path):
    out = tmp_path / "merged.dat"
    assert merge_coverage_dats([], str(out))["ok"] is False
    ghost = merge_coverage_dats([str(tmp_path / "nope.dat")], str(out))
    assert ghost["ok"] is False and ghost["note"]

    if verilator_coverage_bin() is None:
        dat = tmp_path / "a.dat"
        dat.write_text("# fake\n", encoding="utf-8")
        res = merge_coverage_dats([str(dat)], str(out))
        assert res["ok"] is False
        assert "verilator" in res["note"].lower()

        ann = annotate_merged(str(dat), str(tmp_path / "ann"))
        assert ann["ok"] is False and "verilator" in ann["note"].lower()


def test_rank_holes_orders_and_prioritizes():
    summary = {
        "overall": 60.0,
        "holes": [
            {"name": "cross_rw", "pct": 20.0},
            {"name": "line_cov", "pct": 70.0},
            {"name": "toggle", "pct": 88.0},
        ],
    }
    ranked = rank_holes(summary)
    assert [h["name"] for h in ranked] == ["cross_rw", "line_cov", "toggle"]
    assert [h["priority"] for h in ranked] == ["high", "medium", "low"]
    assert all(h["reason"] for h in ranked)
    assert len(rank_holes(summary, limit=2)) == 2


def test_build_closure_prompt_mentions_context():
    summary = {"overall": 61.5, "holes": [{"name": "cross_rw", "pct": 20.0}]}
    prompt = build_closure_prompt(summary, ["fifo.sv", "fifo_tb.sv"], top_module="fifo")
    assert "fifo.sv" in prompt and "fifo" in prompt
    assert "cross_rw" in prompt and "20.0" in prompt
    assert "constraint" in prompt.lower()


def test_suggest_resim_plan_is_deterministic():
    summary = {"holes": [{"name": "cross_rw", "pct": 20.0}, {"name": "line", "pct": 55.0}]}
    a = suggest_resim_plan(summary, base_seed=1, max_cases=4)
    b = suggest_resim_plan(summary, base_seed=1, max_cases=4)
    assert a["seeds"] == b["seeds"]
    assert len(a["seeds"]) == len(set(a["seeds"])) == 2
    assert a["coverage"] is True and a["mode"] == "run"
    assert a["focus"] == ["cross_rw", "line"]

    empty = suggest_resim_plan({"holes": []}, base_seed=7)
    assert empty["seeds"] == [7] and empty["focus"] == []


def test_closure_status_reports_delta_and_closed_holes():
    before = {"overall": 60.0, "holes": [{"name": "cross_rw", "pct": 20.0}, {"name": "line", "pct": 70.0}]}
    after = {"overall": 82.0, "holes": [{"name": "line", "pct": 80.0}, {"name": "fsm", "pct": 40.0}]}
    st = closure_status(before, after)
    assert st["delta"] == 22.0
    assert st["closed_holes"] == ["cross_rw"]
    assert st["new_holes"] == ["fsm"]
    assert st["improved"] is True

    flat = closure_status(before, before)
    assert flat["delta"] == 0.0 and flat["improved"] is False
