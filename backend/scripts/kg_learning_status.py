"""Report ChipSutra SV/UVM knowledge-graph learning status.

Usage (from backend/):
  python scripts/kg_learning_status.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rag import load_chunks  # noqa: E402


def main() -> int:
    kg_path = ROOT / "knowledge" / "kg" / "sv_uvm_knowledge_graph.json"
    rag_path = ROOT / "knowledge" / "kg_sv_uvm_learning.txt"
    if not kg_path.is_file() or not rag_path.is_file():
        print("MISSING: kg JSON or kg_sv_uvm_learning.txt")
        return 1

    kg = json.loads(kg_path.read_text(encoding="utf-8"))
    chunks = load_chunks()
    kg_chunks = [c for c in chunks if c["source"] == "kg_sv_uvm_learning.txt"]
    titles = [c["title"] for c in kg_chunks]

    print("=== ChipSutra KG learning status ===")
    print(f"graph_version: {kg.get('version')}")
    print(f"domains: {len(kg.get('domains', []))}")
    print(f"nodes:   {len(kg.get('nodes', []))}")
    print(f"edges:   {len(kg.get('edges', []))}")
    print(f"anti_patterns: {len(kg.get('anti_patterns', []))}")
    print(f"rag_total_chunks: {len(chunks)}")
    print(f"rag_kg_chunks: {len(kg_chunks)}")
    print("rag_kg_titles:")
    for t in titles:
        safe = t.replace("\u2192", "->").replace("\u2014", "-").replace("\u2013", "-")
        print(f"  - {safe}")

    # Coverage: every domain should appear in at least one RAG title/body
    blob = " ".join(f"{c['title']} {c['body']}" for c in kg_chunks).lower()
    missing = []
    for d in kg.get("domains", []):
        label = (d.get("label") or d.get("id") or "").lower()
        did = (d.get("id") or "").lower().replace("_", " ")
        if label not in blob and did not in blob and d.get("id", "") not in blob:
            # soft check on keywords
            key = d["id"].split("_")[0]
            if key not in blob:
                missing.append(d["id"])
    if missing:
        print("WARN domains weakly covered in RAG:", ", ".join(missing))
    else:
        print("domain_coverage: OK (keyword-level)")

    mapping = kg.get("chipsutra_mapping") or {}
    print(f"generate_mappings: {len(mapping)}")
    print("cadence:", (kg.get("learning_cadence") or {}).get("weekly", ""))
    print("STATUS: ready for continuous learning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
