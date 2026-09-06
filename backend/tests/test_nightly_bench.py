"""Nightly bench summarizer (no LLM / Verilator)."""
import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "run_nightly_bench", _ROOT / "scripts" / "run_nightly_bench.py"
)
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_mod)
_summarize = _mod._summarize


def test_summarize_empty():
    s = _summarize([], [])
    assert s["designs"] == 0
    assert s["mutation_kill_rate"] is None


def test_summarize_scores():
    cmp = [
        {
            "verdict": "match_or_beat",
            "sim_pass": True,
            "latency_s": 10,
            "chipsutra": {"score": 100},
            "premium_ref": {"score": 90},
        },
        {
            "verdict": "behind",
            "sim_pass": False,
            "latency_s": 20,
            "chipsutra": {"score": 80},
            "premium_ref": {"score": 95},
        },
    ]
    mut = [
        {"baseline_pass": True, "killed": 3, "total": 3},
        {"baseline_pass": False, "killed": 0, "total": 2},
    ]
    s = _summarize(cmp, mut)
    assert s["designs"] == 2
    assert s["match_or_beat"] == 1
    assert s["sim_pass"] == 1
    assert s["avg_chipsutra_score"] == 90.0
    assert s["mutation_killed"] == 3
    assert s["mutation_total"] == 3
    assert s["mutation_kill_rate"] == 1.0
