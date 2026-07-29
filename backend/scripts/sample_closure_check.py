"""Sample verification for coverage closure + covergroup RAG (no live LLM)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from coverage_loop import rank_holes, build_closure_prompt, suggest_resim_plan, closure_status
from rag import retrieve, rag_status


def main() -> int:
    sample = {
        "overall": 62.5,
        "source": "sample_fifo_axi.rpt",
        "holes": [
            {"name": "cg_fifo.depth_full", "pct": 12.0, "kind": "bin"},
            {"name": "cg_fifo.empty_to_full", "pct": 40.0, "kind": "cross"},
            {"name": "stmt_push_when_full", "pct": 55.0, "kind": "statement"},
            {"name": "cg_axi.wstrb_sparse", "pct": 70.0, "kind": "bin"},
            {"name": "toggle_almost_full", "pct": 88.0, "kind": "toggle"},
        ],
        "metrics": [],
    }

    ranked = rank_holes(sample, limit=5)
    assert ranked[0]["name"] == "cg_fifo.depth_full"
    assert ranked[0]["priority"] == "high"

    prompt = build_closure_prompt(
        sample,
        rtl_names=["fifo.sv", "axi_lite_slave.sv"],
        top_module="fifo",
        limit=5,
    )
    assert "cg_fifo.depth_full" in prompt
    assert "Directed tests" in prompt

    plan = suggest_resim_plan(sample, base_seed=1, max_cases=4)
    assert len(plan["seeds"]) == 4
    assert plan["mode"] == "run"
    assert plan["coverage"] is True
    assert plan["seeds"] == suggest_resim_plan(sample, base_seed=1, max_cases=4)["seeds"]

    after = {
        "overall": 78.0,
        "holes": [
            {"name": "cg_axi.wstrb_sparse", "pct": 72.0, "kind": "bin"},
            {"name": "toggle_almost_full", "pct": 88.0, "kind": "toggle"},
        ],
    }
    delta = closure_status(sample, after)
    assert delta["improved"] is True
    assert "cg_fifo.depth_full" in delta["closed_holes"]
    assert delta["delta"] == 15.5

    st = rag_status()
    assert "covergroup_patterns.txt" in st["sources"]
    hits = retrieve(
        "close coverage holes with covergroup bins and crosses for FIFO",
        module="coverage_holes",
        top_k=5,
    )
    blob = " ".join((h.get("body") or "") + (h.get("title") or "") for h in hits).lower()
    assert "cover" in blob or "bin" in blob

    golden = ROOT / "knowledge" / "golden"
    for name in [
        "counter.sv",
        "fifo.sv",
        "fifo_tb.sv",
        "axi_lite_slave.sv",
        "axi_lite_slave_tb.sv",
    ]:
        assert (golden / name).is_file(), name

    # Mimic Coverage UI handoff payload
    handoff_generate = {
        "module": "coverage_holes",
        "prompt": prompt,
        "fileIds": ["fifo-id", "axi-id"],
        "autoGenerate": True,
    }
    handoff_resim = {
        "openRegression": True,
        "seeds": plan["seeds"],
        "coverage": True,
    }
    assert len(handoff_generate["prompt"]) > 200
    assert all(isinstance(s, int) for s in handoff_resim["seeds"])

    report = {
        "ranked": [(h["name"], h["pct"], h["priority"]) for h in ranked],
        "seeds": plan["seeds"],
        "focus": plan["focus"],
        "closure": {
            "before": delta["overall_before"],
            "after": delta["overall_after"],
            "closed": delta["closed_holes"],
        },
        "rag_sources": [h.get("source") or h.get("file") for h in hits[:3]],
        "prompt_chars": len(prompt),
        "golden_ok": True,
        "handoff_ok": True,
    }
    print(json.dumps(report, indent=2))
    print("SAMPLE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
