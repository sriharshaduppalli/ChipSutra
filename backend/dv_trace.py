"""Requirement / testplan ↔ TB / SVA / covergroup traceability.

No invented coverage. Items come from user/generated artifacts only.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_PLAN_LINE = re.compile(
    r"^\s*(?:[-*]|\d+\.)\s+(?:`?([A-Z]{2,8}[-_]\d{1,4})`?[:\s]+)?(.+?)\s*$",
    re.M,
)
_REQ_ID = re.compile(r"\b([A-Z]{2,8}[-_]\d{1,4})\b")
_PROP = re.compile(
    r"\b(?:property|assert\s+property|cover\s+property|assume\s+property)\s*(?:\((\w+)\)|(\w+))?",
    re.I,
)
_NAMED_PROP = re.compile(r"\bproperty\s+(\w+)\s*;", re.I)
_COVERPOINT = re.compile(r"\b(?:coverpoint|cp_(\w+))\s+(\w+)?", re.I)
_CP_ID = re.compile(r"\b(cp_\w+)\s*:", re.I)
_SEQ = re.compile(r"\b(?:class|task|function)\s+(?:automatic\s+)?(\w*(?:seq|test|hole|close)\w*)", re.I)
_CLASS_TEST = re.compile(r"\bclass\s+(\w*test\w*)", re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def extract_plan_items(md: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    seen = set()
    for m in _PLAN_LINE.finditer(md or ""):
        rid = (m.group(1) or "").strip()
        title = (m.group(2) or "").strip()
        if len(title) < 4 or title.startswith("#"):
            continue
        if title.lower().startswith(("ports:", "generated:", "protocol", "methodology")):
            continue
        key = rid or title[:80]
        if key in seen:
            continue
        seen.add(key)
        items.append({"id": rid or f"TP{len(items)+1:02d}", "title": title[:160], "source": "testplan"})
        if len(items) >= 40:
            break
    if not items:
        for rid in _REQ_ID.findall(md or ""):
            if rid not in seen:
                seen.add(rid)
                items.append({"id": rid, "title": rid, "source": "testplan"})
    return items


def extract_sva_ids(sv: str) -> List[Dict[str, str]]:
    names = []
    seen = set()
    for m in _NAMED_PROP.finditer(sv or ""):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            names.append({"id": n, "title": n, "source": "sva"})
    return names


def extract_coverpoints(sv: str) -> List[Dict[str, str]]:
    names = []
    seen = set()
    for m in _CP_ID.finditer(sv or ""):
        n = m.group(1)
        if n not in seen:
            seen.add(n)
            names.append({"id": n, "title": n, "source": "covergroup"})
    return names


def extract_tb_stimuli(sv: str) -> List[Dict[str, str]]:
    names = []
    seen = set()
    for rx in (_CLASS_TEST, _SEQ):
        for m in rx.finditer(sv or ""):
            n = m.group(1)
            if not n or n in seen:
                continue
            seen.add(n)
            names.append({"id": n, "title": n, "source": "tb"})
    return names


def _hits(item: Dict[str, str], artifacts: List[Dict[str, str]]) -> List[Dict[str, str]]:
    needle = _norm(item.get("id") or "")
    title = _norm(item.get("title") or "")
    tokens = [t for t in title.split() if len(t) > 3]
    out = []
    for a in artifacts:
        blob = _norm(f"{a.get('id','')} {a.get('title','')}")
        if needle and needle in blob:
            out.append(a)
            continue
        if tokens and sum(1 for t in tokens if t in blob) >= max(1, min(2, len(tokens))):
            out.append(a)
    return out


def build_trace_matrix(
    *,
    testplan: str = "",
    tb: str = "",
    sva: str = "",
    covergroups: str = "",
) -> Dict[str, Any]:
    plan = extract_plan_items(testplan)
    sva_ids = extract_sva_ids(sva)
    cps = extract_coverpoints(covergroups or tb)
    stim = extract_tb_stimuli(tb)
    artifacts = sva_ids + cps + stim
    if not plan:
        # Still show uncovered artifacts so DV can see orphan checkers
        plan = [{"id": "UNPLANNED", "title": "No testplan items parsed", "source": "testplan"}]

    rows = []
    covered = 0
    for item in plan:
        hits = _hits(item, artifacts) if item["id"] != "UNPLANNED" else []
        if hits:
            covered += 1
        rows.append(
            {
                "id": item["id"],
                "title": item["title"],
                "covered": bool(hits),
                "hits": hits[:8],
            }
        )
    orphans = [
        a
        for a in artifacts
        if not any(a["id"] == h["id"] for r in rows for h in r.get("hits") or [])
    ]
    total = max(1, len([r for r in rows if r["id"] != "UNPLANNED"]))
    return {
        "rows": rows,
        "orphans": orphans[:20],
        "counts": {
            "plan": len([r for r in rows if r["id"] != "UNPLANNED"]),
            "covered": covered,
            "sva": len(sva_ids),
            "coverpoints": len(cps),
            "tb": len(stim),
        },
        "coverage_pct": int(100 * covered / total) if plan and plan[0]["id"] != "UNPLANNED" else 0,
    }
