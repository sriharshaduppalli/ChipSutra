"""FPGA-oriented RTL lint (ChipSutra-native). Optional FPGALint CLI via asfigo_bridge.

AsFigo/FPGALint is currently a stub repo; native heuristics still run.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

_LATCH_KW = re.compile(r"\blatch\b", re.I)
_INITIAL_RTL = re.compile(r"\binitial\b", re.I)
_VENDOR = re.compile(r"\b(?:IBUF|OBUF|BUFG|BUFGCE|MMCME2|PLLE2|ODDR|IDDR|DSP48)\b")
_REAL = re.compile(r"\breal\b", re.I)


def lint_fpga(sv: str, *, required_ports: Optional[Sequence[str]] = None) -> Tuple[bool, List[str]]:
    if not (sv or "").strip():
        return False, ["fpga_empty"]
    issues: List[str] = []
    if _INITIAL_RTL.search(sv) and re.search(r"\bmodule\b", sv, re.I):
        issues.append("fpga_initial_in_rtl")
    if _LATCH_KW.search(sv):
        issues.append("fpga_inferred_latch")
    if _VENDOR.search(sv):
        issues.append("fpga_vendor_primitive")
    if _REAL.search(sv):
        issues.append("fpga_real_type")
    hard = {"fpga_empty"}
    ok = not any(i in hard for i in issues)
    return ok, list(dict.fromkeys(issues))


def score_fpga(sv: str) -> dict:
    ok, issues = lint_fpga(sv)
    checks = {
        "no_initial": "fpga_initial_in_rtl" not in issues,
        "no_latch": "fpga_inferred_latch" not in issues,
        "no_real": "fpga_real_type" not in issues,
    }
    passed = sum(1 for v in checks.values() if v)
    score = int(100 * passed / len(checks)) if checks else 0
    return {"ok": ok, "score": score, "issues": issues, "checks": checks, "premium_bar": score >= 75 and ok}
