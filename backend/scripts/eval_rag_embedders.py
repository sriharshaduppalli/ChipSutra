"""Trial bakeoff: hashed-tfidf vs sentence-transformers embedders on DV queries.

Usage:
  python scripts/eval_rag_embedders.py
  python scripts/eval_rag_embedders.py --models all-MiniLM-L6-v2,BAAI/bge-small-en-v1.5
  python scripts/eval_rag_embedders.py --top-k 3

Writes: storage/rag_embedder_trial.json (+ prints a Markdown table).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Fresh process — import after path
import rag  # noqa: E402
import rag_vector  # noqa: E402

TRIAL_QUERIES = [
    ("datatypes", "SystemVerilog logic vs bit 4-state testbench ports"),
    ("arrays", "FIFO scoreboard queue push_back pop_front dynamic array"),
    ("oop", "Pure SV layered class generator driver monitor scoreboard env test"),
    ("random", "constrained random rand constraint inside dist randomize"),
    ("covergroup", "functional coverage covergroup coverpoint bins cross"),
    ("sva", "assert property disable iff posedge clk concurrent assertion"),
    ("axi", "AXI4-Lite AWVALID WREADY BRESP register model scoreboard"),
    ("mailbox", "mailbox semaphore fork join virtual interface modport"),
]


def _run_backend(name: str, model: str | None, chunks: list, top_k: int) -> dict:
    rag_vector.clear_cache()
    # Reset ST singleton so model switches work in one process
    rag_vector._ST_MODEL = None
    rag_vector._ST_FAILED = False
    rag_vector._NOTE = ""

    os.environ["RAG_VECTOR_ENABLED"] = "true"
    if name == "hashed-tfidf":
        os.environ["RAG_VECTOR_BACKEND"] = "hashed-tfidf"
        os.environ.pop("RAG_VECTOR_MODEL", None)
    else:
        os.environ["RAG_VECTOR_BACKEND"] = "sentence-transformers"
        if model:
            os.environ["RAG_VECTOR_MODEL"] = model

    t0 = time.perf_counter()
    # Force index build once
    index = rag_vector.build_index(chunks)
    build_s = time.perf_counter() - t0

    results = []
    q_times = []
    for qid, query in TRIAL_QUERIES:
        t1 = time.perf_counter()
        hits = rag_vector.search(index, query, top_k=top_k)
        q_times.append(time.perf_counter() - t1)
        results.append(
            {
                "id": qid,
                "query": query,
                "hits": [
                    {
                        "source": h.get("source"),
                        "title": h.get("title"),
                        "score": h.get("score"),
                    }
                    for h in hits
                ],
            }
        )

    status = rag_vector.rag_vector_status()
    return {
        "name": name,
        "model": model,
        "backend": status.get("backend"),
        "dim": status.get("dim"),
        "note": status.get("note"),
        "index_build_s": round(build_s, 3),
        "avg_query_s": round(sum(q_times) / max(1, len(q_times)), 4),
        "results": results,
    }


def _md(report: dict) -> str:
    lines = [
        "# ChipSutra RAG embedder trial",
        "",
        f"Chunks indexed: **{report['chunk_count']}**",
        "",
        "## Backends",
        "",
        "| Backend | Model | Dim | Index build | Avg query |",
        "|---------|-------|-----|-------------|-----------|",
    ]
    for b in report["backends"]:
        lines.append(
            f"| {b['backend']} | {b.get('model') or '—'} | {b.get('dim')} | "
            f"{b['index_build_s']}s | {b['avg_query_s']}s |"
        )
    lines += ["", "## Per-query top hits", ""]
    # Pivot by query
    for i, (qid, query) in enumerate(TRIAL_QUERIES):
        lines.append(f"### `{qid}` — {query}")
        lines.append("")
        for b in report["backends"]:
            hits = b["results"][i]["hits"]
            pretty = ", ".join(
                f"{h['source']}:{h['title'][:40]} ({h['score']})" for h in hits
            ) or "(none)"
            label = b.get("model") or b["backend"]
            lines.append(f"- **{label}**: {pretty}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--models",
        type=str,
        default="all-MiniLM-L6-v2,BAAI/bge-small-en-v1.5",
        help="Comma-separated HF / sentence-transformers model ids",
    )
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument(
        "--out",
        type=str,
        default=str(ROOT / "storage" / "rag_embedder_trial.json"),
    )
    args = ap.parse_args()

    chunks = rag.load_chunks()
    backends = [_run_backend("hashed-tfidf", None, chunks, args.top_k)]

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    for mid in models:
        try:
            backends.append(_run_backend("sentence-transformers", mid, chunks, args.top_k))
        except Exception as e:
            backends.append(
                {
                    "name": "sentence-transformers",
                    "model": mid,
                    "backend": "error",
                    "dim": 0,
                    "note": str(e)[:300],
                    "index_build_s": 0,
                    "avg_query_s": 0,
                    "results": [],
                }
            )

    report = {
        "chunk_count": len(chunks),
        "backends": backends,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out.with_suffix(".md")
    md = _md(report)
    md_path.write_text(md, encoding="utf-8")
    try:
        print(md)
    except UnicodeEncodeError:
        # Windows consoles (cp1252) choke on arrows in knowledge titles
        sys.stdout.buffer.write((md + "\n").encode("utf-8", errors="replace"))
    print(f"\nWrote {out}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
