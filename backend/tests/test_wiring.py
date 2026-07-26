"""Offline wiring tests: engine modules reachable through the FastAPI app.

No EDA tools, no live Mongo — the server module is imported with test env vars, the
same way test_credibility_targets.py::test_regression_models_import does it.
"""
import asyncio
import os
import sys

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "chipsutra_test")

import rag  # noqa: E402
import rate_limit  # noqa: E402
import server  # noqa: E402

NEW_ROUTES = [
    "/api/sta/stream",
    "/api/projects/{pid}/sta-runs",
    "/api/golden-duts",
    "/api/projects/{pid}/import-golden",
    "/api/projects/{pid}/latest-tool-log",
    "/api/projects/{pid}/coverage/{cov_id}/holes",
    "/api/projects/{pid}/coverage/{cov_id}/closure-plan",
    "/api/projects/{pid}/coverage/closure-status",
]

ENGINE_MODULES = [
    "fst_parse",
    "cdc_deep",
    "ucis_parse",
    "coverage_merge",
    "coverage_loop",
    "rag_vector",
    "rate_limit",
]


def _paths() -> set:
    return {getattr(r, "path", None) for r in server.app.routes}


# =========================
# Routes
# =========================
@pytest.mark.parametrize("path", NEW_ROUTES)
def test_new_route_is_registered(path):
    assert path in _paths()


def test_existing_routes_are_untouched():
    paths = _paths()
    for path in (
        "/api/health",
        "/api/coverage/parse",
        "/api/projects/{pid}/coverage/merge",
        "/api/waveform/parse",
        "/api/waveform/parse-project",
        "/api/synth/stream",
        "/api/cdc/analyze",
    ):
        assert path in paths


# =========================
# Models
# =========================
def test_synth_in_accepts_multi_revision_file_sets():
    inp = server.SynthIn(
        project_id="p1",
        mode="eqy",
        gold_file_ids=["rev-a"],
        gate_file_ids=["rev-b"],
    )
    assert inp.gold_file_ids == ["rev-a"] and inp.gate_file_ids == ["rev-b"]
    # default stays an empty list (today's RTL-vs-netlist behaviour)
    assert server.SynthIn(project_id="p1").gold_file_ids == []


def test_cdc_in_accepts_deep_engine():
    assert server.CdcIn(project_id="p1", rtl_file_ids=["a"], engine="deep").engine == "deep"
    assert server.CdcIn(project_id="p1").engine == "auto"


def test_sta_and_coverage_models_have_expected_defaults():
    sta = server.StaRunIn(project_id="p1")
    assert sta.clock_name == "clk" and sta.period_ns == 10.0 and sta.max_paths == 10
    assert sta.netlist_file_id is None and sta.liberty_file_id is None
    plan = server.CoverageClosureIn()
    assert plan.rtl_file_ids == [] and plan.limit == 12
    assert server.ImportGoldenIn().names is None


# =========================
# Engine module wiring
# =========================
@pytest.mark.parametrize("mod", ENGINE_MODULES)
def test_server_import_pulls_in_engine_module(mod):
    assert mod in sys.modules


def test_server_uses_engine_entry_points():
    assert server.merge_summary_points is not None
    assert server.rank_holes is not None and server.closure_status is not None
    assert server.analyze_deep is not None and server.merge_deep is not None
    assert server.sta_command is not None and server.liberty_is_plausible is not None
    assert server.ucis_parse.detect_and_parse is not None


def test_health_reports_new_subsystems():
    health = asyncio.run(server.health())
    assert set(health["fst"]) >= {"fst2vcd", "vcd2fst", "engine"}
    assert health["rate_limit"]["backend"] in ("redis", "memory")
    assert "opensta" in health


# =========================
# FST ingestion helper
# =========================
def test_vcd_bytes_pass_through_unchanged():
    vcd = b"$timescale 1ns $end\n$var wire 1 ! clk $end\n$enddefinitions $end\n#0\n0!\n"
    assert server._vcd_text_from_waveform(vcd, "dump.vcd") == vcd.decode("utf-8")


@pytest.mark.skipif(
    server.fst_status()["fst2vcd"], reason="fst2vcd installed — real conversion path is exercised"
)
def test_fst_without_converter_returns_actionable_400():
    from fastapi import HTTPException

    fst = b"\x00" + (329).to_bytes(8, "big") + b"\x00" * 64
    with pytest.raises(HTTPException) as exc:
        server._vcd_text_from_waveform(fst, "dump.fst")
    assert exc.value.status_code == 400
    assert "fst2vcd" in str(exc.value.detail).lower()


# =========================
# Golden DUTs
# =========================
def test_golden_entries_are_listed_with_kinds():
    entries = {e["name"]: e for e in server._golden_entries()}
    assert {"counter.sv", "fifo.sv", "fifo_tb.sv", "axi_lite_slave.sv"} <= set(entries)
    assert entries["fifo.sv"]["kind"] == "rtl"
    assert entries["fifo_tb.sv"]["kind"] == "tb"
    assert entries["fifo.sv"]["bytes"] > 0
    assert entries["fifo.sv"]["description"]
    # nothing outside the golden directory is importable
    assert "server.py" not in entries


# =========================
# RAG
# =========================
def test_augment_generation_context_still_returns_a_string():
    ctx = rag.augment_generation_context(
        module="testbench",
        prompt="async fifo gray code pointer synchronizer",
        filenames=["fifo.sv"],
        top_k=3,
    )
    assert isinstance(ctx, str)


def test_rag_status_includes_vector_section():
    status = rag.rag_status()
    assert "vector" in status
    assert status["vector"]["backend"] in ("sentence-transformers", "hashed-tfidf", "disabled")
    assert status["chunk_count"] >= 0


def test_retrieve_falls_back_to_keyword_order_without_vector(monkeypatch):
    monkeypatch.setenv("RAG_VECTOR_ENABLED", "false")
    import rag_vector

    rag_vector.clear_cache()
    hits = rag.retrieve("async fifo gray code pointer", module="testbench", top_k=2)
    assert isinstance(hits, list) and len(hits) <= 2
    rag_vector.clear_cache()


# =========================
# Rate limiting
# =========================
def test_rate_limit_delegates_and_raises_429():
    from fastapi import HTTPException

    key = "test:wiring:_rate_limit"
    rate_limit.reset_rate_limit(key)
    server._rate_limit(key, max_calls=2, window_s=60.0)
    server._rate_limit(key, max_calls=2, window_s=60.0)
    with pytest.raises(HTTPException) as exc:
        server._rate_limit(key, max_calls=2, window_s=60.0)
    assert exc.value.status_code == 429
    rate_limit.reset_rate_limit(key)
