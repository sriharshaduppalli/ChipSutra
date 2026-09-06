"""Functional-coverage lint + light repair for generated covergroups.

ChipSutra-native regex heuristics (not a copy of AsFigo FCOVLint). Optional
Verible FCOVLint stays behind asfigo_bridge when the user installs it.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

_HAS_CG = re.compile(r"\bcovergroup\b", re.I)
_HAS_CP = re.compile(r"\bcoverpoint\b", re.I)
_HAS_CROSS = re.compile(r"\bcross\b", re.I)
_CG_NAMED = re.compile(r"\bcovergroup\s+cg_\w+", re.I)
_PER_INSTANCE = re.compile(r"option\s*\.\s*per_instance\s*=\s*1", re.I)
_FAKE = re.compile(r"\b(?:data_in|data_out|chip_sutra)\b", re.I)
_BINS = re.compile(r"\bbins\b|\billegal_bins\b|\bignore_bins\b", re.I)


def lint_fcov(
    sv: str,
    *,
    required_ports: Optional[Sequence[str]] = None,
) -> Tuple[bool, List[str]]:
    if not (sv or "").strip():
        return False, ["fcov_empty"]
    issues: List[str] = []
    if not _HAS_CG.search(sv):
        issues.append("fcov_no_covergroup")
    if _HAS_CG.search(sv) and not _HAS_CP.search(sv):
        issues.append("fcov_no_coverpoint")
    if _HAS_CG.search(sv) and not _CG_NAMED.search(sv):
        issues.append("fcov_cg_prefix")
    if _HAS_CG.search(sv) and not _PER_INSTANCE.search(sv):
        issues.append("fcov_missing_per_instance")
    if _HAS_CG.search(sv) and not _BINS.search(sv):
        issues.append("fcov_no_bins")
    crosses = len(_HAS_CROSS.findall(sv))
    if crosses > 4:
        issues.append("fcov_too_many_cross")
    if _FAKE.search(sv):
        known = {p.lower() for p in (required_ports or [])}
        if "data_in" not in known and "data_out" not in known:
            issues.append("fcov_invented_port")
    hard = {"fcov_empty", "fcov_no_covergroup", "fcov_invented_port"}
    ok = not any(i in hard for i in issues)
    return ok, list(dict.fromkeys(issues))


def repair_fcov(sv: str) -> str:
    """Insert option.per_instance = 1 on the first covergroup when missing."""
    body = sv or ""
    if not _HAS_CG.search(body) or _PER_INSTANCE.search(body):
        return body
    return re.sub(
        r"(covergroup\s+\w+\s*(?:\([^;]*\))?\s*(?:@\s*\([^;]*\))?\s*;)",
        r"\1\n    option.per_instance = 1;",
        body,
        count=1,
        flags=re.I,
    )


def score_fcov(sv: str, *, required_ports: Optional[Sequence[str]] = None) -> dict:
    ok, issues = lint_fcov(sv, required_ports=required_ports)
    checks = {
        "has_covergroup": bool(_HAS_CG.search(sv or "")),
        "has_coverpoint": bool(_HAS_CP.search(sv or "")),
        "has_per_instance": bool(_PER_INSTANCE.search(sv or "")),
        "no_invented": "fcov_invented_port" not in issues,
    }
    passed = sum(1 for v in checks.values() if v)
    score = int(100 * passed / len(checks)) if checks else 0
    return {
        "ok": ok,
        "score": score,
        "issues": issues,
        "checks": checks,
        "premium_bar": score >= 75 and ok,
    }
