"""Closed-loop coverage: rank holes -> prompt for directed tests -> re-sim plan -> delta.

Pure stdlib and deterministic: the same summary always yields the same seeds so a
coverage-closure run can be reproduced exactly.
"""
from __future__ import annotations

import hashlib
import re
from typing import Dict, List, Optional

HOLE_THRESHOLD = 90.0
_SEED_SPACE = 900000


def _holes_of(summary: dict) -> List[dict]:
    """Holes from the summary, falling back to metrics under the 90% target."""
    summary = summary if isinstance(summary, dict) else {}
    holes = [h for h in (summary.get("holes") or []) if isinstance(h, dict)]
    if not holes:
        holes = [
            m
            for m in (summary.get("metrics") or [])
            if isinstance(m, dict) and isinstance(m.get("pct"), (int, float)) and m["pct"] < HOLE_THRESHOLD
        ]
    out = []
    for hole in holes:
        name = str(hole.get("name") or "").strip()
        pct = hole.get("pct")
        if not name or not isinstance(pct, (int, float)):
            continue
        out.append(hole)
    return out


def _priority(pct: float) -> str:
    if pct < 50:
        return "high"
    if pct < 75:
        return "medium"
    return "low"


def rank_holes(summary: dict, limit: int = 20) -> List[dict]:
    """Coverage holes sorted worst-first, annotated with priority and a short reason."""
    ranked: List[dict] = []
    for hole in sorted(_holes_of(summary), key=lambda h: (float(h["pct"]), str(h.get("name")))):
        pct = round(float(hole["pct"]), 1)
        kind = str(hole.get("kind") or "").strip()
        priority = _priority(pct)
        gap = round(HOLE_THRESHOLD - pct, 1)
        what = f"{kind} " if kind else ""
        reason = (
            f"{what}'{hole['name']}' at {pct}% is {gap} points below the {HOLE_THRESHOLD:.0f}% target"
        )
        if priority == "high":
            reason += "; largely unexercised, needs directed stimulus"
        elif priority == "medium":
            reason += "; partially exercised, needs corner-case stimulus"
        else:
            reason += "; near target, needs a few extra random seeds"
        entry = dict(hole)
        entry.update({"name": str(hole["name"]), "pct": pct, "priority": priority, "reason": reason})
        ranked.append(entry)
        if len(ranked) >= max(0, int(limit)):
            break
    return ranked


def build_closure_prompt(
    summary: dict,
    rtl_names: List[str],
    top_module: Optional[str] = None,
    limit: int = 12,
) -> str:
    """LLM prompt for the ``coverage_holes`` module asking for hole-closing SV tests."""
    holes = rank_holes(summary, limit=limit)
    files = [str(n).strip() for n in (rtl_names or []) if str(n).strip()]
    overall = summary.get("overall") if isinstance(summary, dict) else None
    overall_txt = f"{float(overall):.1f}%" if isinstance(overall, (int, float)) else "unknown"
    source = str((summary or {}).get("source") or "coverage report")

    lines: List[str] = [
        "You are a coverage closure expert working on a SystemVerilog verification project.",
        f"Current overall coverage: {overall_txt} (source: {source}).",
        f"Design under test top module: {top_module or 'unknown (infer from the RTL files)'}.",
        f"RTL files: {', '.join(files) if files else 'none provided'}.",
        "",
        f"Uncovered / under-covered items ({len(holes)} ranked worst-first):",
    ]
    if holes:
        for i, hole in enumerate(holes, 1):
            kind = f" [{hole['kind']}]" if hole.get("kind") else ""
            lines.append(f"{i}. {hole['name']}{kind} — {hole['pct']}% ({hole['priority']} priority)")
    else:
        lines.append("(none reported — propose stress and corner-case stimulus instead)")

    lines += [
        "",
        "Write additional SystemVerilog tests that close these holes:",
        "1. Directed tests for the high-priority items, one task per hole, named after the hole.",
        "2. Constrained-random sequences (with explicit `constraint` blocks) for medium/low items.",
        "3. Covergroups with bins that prove each hole is now hit.",
        "4. Keep the existing top-level port list and clock/reset conventions of "
        f"{top_module or 'the top module'}.",
        "Output compilable SystemVerilog first, then a short bullet rationale mapping each "
        "test back to the hole it closes.",
    ]
    return "\n".join(lines)


def _stable_seed(name: str, base_seed: int) -> int:
    """Deterministic per-hole seed (sha256, not Python's randomized hash())."""
    digest = hashlib.sha256(str(name).encode("utf-8")).hexdigest()
    return int(base_seed) + (int(digest[:12], 16) % _SEED_SPACE)


def suggest_resim_plan(summary: dict, base_seed: int = 1, max_cases: int = 6) -> dict:
    """Reproducible re-simulation plan derived from the ranked coverage holes."""
    max_cases = max(1, int(max_cases))
    holes = rank_holes(summary, limit=max_cases)
    focus = [h["name"] for h in holes]

    seeds: List[int] = []
    for name in focus:
        seed = _stable_seed(name, base_seed)
        while seed in seeds:
            seed += 1
        seeds.append(seed)
    if not seeds:
        seeds = [int(base_seed)]

    if focus:
        rationale = (
            f"Re-run {len(seeds)} simulation(s) with seeds derived from the {len(focus)} worst "
            f"coverage hole(s) ({', '.join(focus[:3])}"
            f"{'...' if len(focus) > 3 else ''}). Seeds are hashed from the hole names so the "
            "same coverage report always reproduces the same runs."
        )
    else:
        rationale = (
            "No coverage holes reported; re-running once with the base seed to confirm the "
            "result is stable."
        )

    return {
        "seeds": seeds,
        "focus": focus,
        "mode": "run",
        "coverage": True,
        "rationale": rationale,
    }


def closure_status(before: dict, after: dict) -> dict:
    """Compare two coverage summaries and report what closed, what regressed."""

    def overall_of(summary: dict) -> float:
        value = (summary or {}).get("overall") if isinstance(summary, dict) else None
        return round(float(value), 1) if isinstance(value, (int, float)) else 0.0

    def names_of(summary: dict) -> Dict[str, str]:
        return {
            str(h.get("name")).strip().lower(): str(h.get("name")).strip()
            for h in _holes_of(summary if isinstance(summary, dict) else {})
            if str(h.get("name") or "").strip()
        }

    before_holes = names_of(before)
    after_holes = names_of(after)
    overall_before = overall_of(before)
    overall_after = overall_of(after)
    delta = round(overall_after - overall_before, 1)

    closed = [before_holes[k] for k in before_holes if k not in after_holes]
    new = [after_holes[k] for k in after_holes if k not in before_holes]
    improved = delta > 0 or (delta >= 0 and bool(closed) and not new)

    return {
        "overall_before": overall_before,
        "overall_after": overall_after,
        "delta": delta,
        "closed_holes": sorted(closed),
        "new_holes": sorted(new),
        "improved": improved,
    }


def _safe_id(name: str, fallback: str = "hole") -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", (name or fallback).strip()) or fallback
    if s[0].isdigit():
        s = f"h_{s}"
    return s[:48]


def render_hole_sequence(
    hole_name: str,
    *,
    dut: str = "dut",
    ports: Optional[List[str]] = None,
    kind: str = "",
    pct: Optional[float] = None,
) -> str:
    """Named directed sequence/task for one coverage hole. No invented VIP."""
    hid = _safe_id(hole_name)
    dut_id = _safe_id(dut, "dut")
    names = [str(p).strip() for p in (ports or []) if str(p).strip()]
    matched = [n for n in names if n.lower() in hole_name.lower() or hole_name.lower() in n.lower()]
    drive = "\n".join(f"    // drive {n} toward the uncovered bin" for n in matched[:6]) or (
        "    // Hole name did not match a DUT port — keep existing IF; do not invent pins."
    )
    pct_s = f"{float(pct):.1f}%" if isinstance(pct, (int, float)) else "unknown"
    kind_s = kind or "cover"
    return f"""// ChipSutra directed closure — hole `{hole_name}` ({kind_s} @ {pct_s})
// Named sequence/task for Regression / plusarg +plus{hid}
// Not a sign-off UCIS dump. Review bins against the user covergroup.

task automatic close_{hid}();
  $display("[%0t] close_{hid}: targeting hole `{hole_name}`", $time);
{drive}
  repeat (16) @(posedge clk);
endtask

covergroup {dut_id}_{hid}_cg;
  cp_hole: coverpoint 1'b1 {{
    bins {hid} = {{1}};
  }}
endgroup

// Map: this artifact exists to close `{hole_name}`. Bind in the existing TB env/test.
"""
