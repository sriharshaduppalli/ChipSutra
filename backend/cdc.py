"""
Structural CDC / RDC heuristics (v0) — no vendor CDC license.

Parses SystemVerilog/Verilog for clocked processes and flags likely crossings.
Detects simple 2FF synchronizer patterns as mitigated. Not Spyglass-class;
labeled experimental in the UI.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set, Tuple


_MODULE = re.compile(r"\bmodule\s+(\w+)", re.I)
_POSEDGE = re.compile(r"always(?:_ff|_latch)?\s*@\s*\(\s*(?:posedge|negedge)\s+(\w+)", re.I)
_NB_ASSIGN = re.compile(r"(\w+)\s*<=\s*([^;]+);")
_SYNC2 = re.compile(
    r"(\w+)\s*<=\s*(\w+)\s*;[\s\S]{0,120}?(\w+)\s*<=\s*\1\s*;",
    re.I,
)


def analyze_rtl_texts(files: List[Tuple[str, str]]) -> dict:
    """files: list of (filename, text)."""
    findings: List[dict] = []
    clocks: Set[str] = set()
    # signal -> last observed clock domain
    sig_clk: Dict[str, str] = {}
    sync_pairs: Set[Tuple[str, str]] = set()

    for fname, text in files:
        if not text:
            continue
        # 2FF detection across file
        for m in _SYNC2.finditer(text):
            sync_pairs.add((m.group(2), m.group(3)))  # src -> synced out

        blocks = re.split(r"(?=always(?:_ff|_latch)?\s*@)", text, flags=re.I)
        for block in blocks:
            cm = _POSEDGE.search(block)
            if not cm:
                continue
            clk = cm.group(1)
            clocks.add(clk)
            for am in _NB_ASSIGN.finditer(block):
                dst = am.group(1)
                rhs = am.group(2)
                srcs = set(re.findall(r"\b([A-Za-z_]\w*)\b", rhs))
                srcs -= {"posedge", "negedge", "clk", "clock", "rst", "reset", "1", "0"}
                for s in list(srcs):
                    if s == dst:
                        continue
                    prev = sig_clk.get(s)
                    if prev and prev != clk:
                        mitigated = (s, dst) in sync_pairs or any(
                            p[0] == s for p in sync_pairs
                        )
                        findings.append(
                            {
                                "filename": fname,
                                "signal": dst,
                                "from_domain": prev,
                                "to_domain": clk,
                                "source": s,
                                "severity": "info" if mitigated else "warn",
                                "kind": "cdc",
                                "note": "2FF synchronizer pattern detected"
                                if mitigated
                                else "Possible CDC: data from other clock domain without obvious 2FF",
                            }
                        )
                sig_clk[dst] = clk

        # Reset domain: async reset deassert sync hint
        if re.search(r"always\s*@\s*\([^)]*posedge\s+\w+[^)]*or\s+(?:posedge|negedge)\s+(?:rst|reset)", text, re.I):
            if not re.search(r"\brst_sync|reset_sync|synced_rst\b", text, re.I):
                findings.append(
                    {
                        "filename": fname,
                        "signal": "reset",
                        "from_domain": "async",
                        "to_domain": "clk",
                        "source": "rst",
                        "severity": "info",
                        "kind": "rdc",
                        "note": "Async reset present — prefer sync deassert / named reset synchronizer",
                    }
                )

    # Deduplicate
    uniq = []
    seen = set()
    for f in findings:
        key = (f["filename"], f["signal"], f["from_domain"], f["to_domain"], f["kind"], f["note"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)

    return {
        "clocks": sorted(clocks),
        "findings": uniq[:200],
        "counts": {
            "cdc_warn": sum(1 for f in uniq if f["kind"] == "cdc" and f["severity"] == "warn"),
            "cdc_info": sum(1 for f in uniq if f["kind"] == "cdc" and f["severity"] == "info"),
            "rdc": sum(1 for f in uniq if f["kind"] == "rdc"),
        },
        "engine": "chipsutra-cdc-v0",
        "disclaimer": "Heuristic regex CDC — not a sign-off Spyglass/Questa CDC replacement.",
    }
