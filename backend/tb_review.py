"""Automatic quality review of a generated testbench (no LLM).

Goes beyond architecture boxes: fake goldens, noop constraints, missing
clock/reset, DUT ports that never appear in the TB.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from tb_architecture import analyze_tb_architecture

_SEEN = re.compile(r"\bseen\s*\+\+", re.I)
_BEATS = re.compile(r"\bbeats\s*\+\+", re.I)
_NOOP_CHECK = re.compile(r"function\s+bit\s+check\s*\(\s*\)\s*;\s*return\s+1\s*;", re.I)
_NOOP_CONSTRAINT = re.compile(r"constraint\s+\w+\s*\{\s*1\s*;\s*\}", re.I)
_CLK = re.compile(r"\b(clk|clock|aclk|pclk|sclk|hclk)\b", re.I)
_RST = re.compile(r"\b(rst_n|rstn|reset_n|aresetn|presetn|hresetn|rst|reset)\b", re.I)


def _port_names(ports: Optional[Sequence[dict]]) -> List[str]:
    out = []
    for p in ports or []:
        n = str((p or {}).get("name") or "").strip()
        if n:
            out.append(n)
    return out


def review_generated_tb(
    sv: str,
    *,
    ports: Optional[Sequence[dict]] = None,
    methodology_hint: str = "",
) -> Dict[str, Any]:
    body = sv or ""
    arch = analyze_tb_architecture(body, methodology_hint=methodology_hint)
    findings: List[dict] = list(arch.get("findings") or [])

    if _SEEN.search(body) or _BEATS.search(body):
        findings.append(
            {
                "severity": "error",
                "title": "Traffic counter, not a golden",
                "hint": "seen++ / beats++ is not a checker. Need an independent expected-value model.",
            }
        )
    if _NOOP_CHECK.search(body):
        findings.append(
            {
                "severity": "error",
                "title": "No-op scoreboard check()",
                "hint": "check() that returns 1 always will pass a broken DUT.",
            }
        )
    if _NOOP_CONSTRAINT.search(body):
        findings.append(
            {
                "severity": "error",
                "title": "Illegal / noop constraint `{ 1; }`",
                "hint": "Use a real legal_c on DUT inputs. `{ 1; }` is not a constraint.",
            }
        )
    if not _CLK.search(body):
        findings.append(
            {
                "severity": "warn",
                "title": "No clock ident in TB",
                "hint": "Combo-only TBs may omit a clock; sequential DUTs must toggle clk.",
            }
        )
    if not _RST.search(body):
        findings.append(
            {
                "severity": "warn",
                "title": "No reset ident in TB",
                "hint": "Sequential goldens should assert then deassert the DUT reset pin.",
            }
        )

    missing_ports = []
    for n in _port_names(ports):
        if n.lower() in ("clk", "clock", "aclk", "pclk"):
            continue
        if not re.search(rf"\b{re.escape(n)}\b", body):
            missing_ports.append(n)
    if missing_ports:
        findings.append(
            {
                "severity": "error",
                "title": f"DUT ports missing from TB: {', '.join(missing_ports[:8])}",
                "hint": "User RTL names win — do not invent data_in/data_out.",
            }
        )

    errors = sum(1 for f in findings if f.get("severity") == "error")
    warns = sum(1 for f in findings if f.get("severity") == "warn")
    score = max(0, 100 - errors * 18 - warns * 6)
    if errors:
        verdict = "reject"
    elif warns:
        verdict = "review"
    else:
        verdict = "ok"
    return {
        "score": score,
        "verdict": verdict,
        "findings": findings,
        "architecture": arch,
        "missing_ports": missing_ports,
        "fake_golden": bool(_SEEN.search(body) or _BEATS.search(body) or _NOOP_CHECK.search(body)),
    }
