"""Lint + light repair for reference-model checkers (module=checkers)."""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

_HAS_MODULE = re.compile(r"\bmodule\b", re.I)
_HAS_CHECK = re.compile(r"\b(?:function|task)\b[\s\S]{0,80}\bcheck\b|\bassert\b", re.I)
_CIRCULAR = re.compile(
    r"\b(?:exp|expected)\w*\s*=\s*(?:count|rd_data|data_out|q)\b", re.I
)
_FAKE = re.compile(r"\b(?:data_in|data_out|chip_sutra)\b", re.I)


def lint_checker(
    sv: str,
    *,
    required_ports: Optional[Sequence[str]] = None,
) -> Tuple[bool, List[str]]:
    if not (sv or "").strip():
        return False, ["checker_empty"]
    issues: List[str] = []
    if not _HAS_MODULE.search(sv) and not re.search(r"\bclass\b", sv, re.I):
        issues.append("checker_no_module")
    if not _HAS_CHECK.search(sv):
        issues.append("checker_no_check")
    if _CIRCULAR.search(sv):
        issues.append("checker_circular_golden")
    if _FAKE.search(sv):
        known = {p.lower() for p in (required_ports or [])}
        if "data_in" not in known and "data_out" not in known:
            issues.append("checker_invented_port")
    hard = {
        "checker_empty",
        "checker_no_module",
        "checker_no_check",
        "checker_circular_golden",
        "checker_invented_port",
    }
    ok = not any(i in hard for i in issues)
    return ok, list(dict.fromkeys(issues))


def repair_checker(sv: str) -> str:
    """Strip invented-port mentions in comments; no structural rewrite."""
    body = sv or ""
    if _FAKE.search(body):
        body = re.sub(r"\bdata_in\b", "/*FIXME_port*/", body)
        body = re.sub(r"\bdata_out\b", "/*FIXME_port*/", body)
    return body


def score_checker(sv: str, *, required_ports: Optional[Sequence[str]] = None) -> dict:
    ok, issues = lint_checker(sv, required_ports=required_ports)
    checks = {
        "has_module_or_class": bool(
            _HAS_MODULE.search(sv or "") or re.search(r"\bclass\b", sv or "", re.I)
        ),
        "has_check": bool(_HAS_CHECK.search(sv or "")),
        "no_circular": "checker_circular_golden" not in issues,
        "no_invented": "checker_invented_port" not in issues,
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
