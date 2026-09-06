"""SVA lint + light mechanical repair for generated assertions."""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

_HAS_PROPERTY = re.compile(r"\bproperty\b|\bassert\s+property\b|\bcover\s+property\b", re.I)
_HAS_DISABLE_IFF = re.compile(r"\bdisable\s+iff\b", re.I)
_HAS_POSEDGE = re.compile(r"@\s*\(\s*posedge\s+\w+", re.I)
_FAKE_PORT = re.compile(r"\b(?:data_in|data_out|chip_sutra)\b", re.I)
_HAS_MODULE_OR_BIND = re.compile(r"\b(?:module|bind)\b", re.I)
_NAMED_PROPERTY = re.compile(r"\bproperty\s+p_\w+", re.I)
_LABELED_ASSERT = re.compile(r"\b\w+\s*:\s*(?:assert|cover|assume)\s+property\b", re.I)
_BARE_ASSERT_PROP = re.compile(r"(?<![:\w])assert\s+property\s*\(", re.I)
_FAIL_AB = re.compile(r"assert\s+property\s*\([^;]{0,400}\)\s*else\b", re.I | re.S)
_TAUTOLOGY = re.compile(r"\|[=-]>\s*\(?\s*1(?:'b1)?\s*\)?", re.I)
_CONC_IN_FF = re.compile(r"always_ff\b[\s\S]{0,240}assert\s+property\b", re.I)


def lint_sva(
    sv: str,
    *,
    required_ports: Optional[Sequence[str]] = None,
) -> Tuple[bool, List[str]]:
    """Return (ok, issues) for assertion/bind output."""
    if not (sv or "").strip():
        return False, ["sva_empty"]
    issues: List[str] = []
    if not _HAS_PROPERTY.search(sv) and not re.search(r"\bassert\s+", sv, re.I):
        issues.append("sva_no_property")
    if _HAS_PROPERTY.search(sv) and not _HAS_POSEDGE.search(sv):
        issues.append("sva_no_clocked_property")
    if _HAS_PROPERTY.search(sv) and not _HAS_DISABLE_IFF.search(sv):
        # Soft unless reset port exists
        ports = {p.lower() for p in (required_ports or [])}
        if ports & {"rst_n", "rstn", "reset_n", "aresetn", "presetn", "hresetn"}:
            issues.append("sva_missing_disable_iff")
    if _FAKE_PORT.search(sv):
        issues.append("sva_invented_port")
    if required_ports:
        known = {p.lower() for p in required_ports}
        # Flag common invented names not in DUT
        for m in re.finditer(r"\b([a-zA-Z_]\w*)\b", sv):
            n = m.group(1)
            if n.lower() in ("data_in", "data_out", "din", "dout") and n.lower() not in known:
                if n.lower() not in {k.lower() for k in known}:
                    issues.append(f"sva_unknown_signal:{n}")
                    break
    if _BARE_ASSERT_PROP.search(sv) and not _LABELED_ASSERT.search(sv) and not _NAMED_PROPERTY.search(sv):
        issues.append("sva_unlabeled_assert")
    if _BARE_ASSERT_PROP.search(sv) or _LABELED_ASSERT.search(sv):
        if not _FAIL_AB.search(sv) and re.search(r"\bassert\s+property\b", sv, re.I):
            issues.append("sva_missing_fail_ab")
    if _TAUTOLOGY.search(sv):
        issues.append("sva_tautology")
    if _CONC_IN_FF.search(sv):
        issues.append("sva_concurrent_in_always_ff")
    soft = {
        "sva_missing_disable_iff",
        "sva_unlabeled_assert",
        "sva_missing_fail_ab",
        "sva_tautology",
        "sva_concurrent_in_always_ff",
    }
    hard = [i for i in issues if i not in soft]
    return (not hard), list(dict.fromkeys(issues))


def repair_sva(
    sv: str,
    *,
    clk: str = "clk",
    rst_n: str = "rst_n",
    required_ports: Optional[Sequence[str]] = None,
) -> str:
    """Light mechanical fixes: add disable iff when missing; strip invented ports comment."""
    body = sv or ""
    if not body.strip():
        return body
    ports = {p.lower(): p for p in (required_ports or [])}
    clk_use = ports.get("clk") or ports.get("aclk") or ports.get("pclk") or clk
    rst_use = (
        ports.get("rst_n")
        or ports.get("aresetn")
        or ports.get("presetn")
        or ports.get("hresetn")
        or rst_n
    )
    if _HAS_PROPERTY.search(body) and not _HAS_DISABLE_IFF.search(body):
        # Insert disable iff after @(posedge clk)
        body = re.sub(
            rf"(@\s*\(\s*posedge\s+{re.escape(clk_use)}\s*\))",
            rf"\1 disable iff (!{rst_use})",
            body,
            count=1,
            flags=re.I,
        )
    if _BARE_ASSERT_PROP.search(body) and not _LABELED_ASSERT.search(body):
        body = re.sub(
            r"\bassert\s+property\s*\(",
            "a_sva: assert property (",
            body,
            count=1,
            flags=re.I,
        )
    return body


def score_sva(sv: str, *, required_ports: Optional[Sequence[str]] = None) -> dict:
    ok, issues = lint_sva(sv, required_ports=required_ports)
    checks = {
        "has_property": bool(_HAS_PROPERTY.search(sv or "")),
        "has_clock": bool(_HAS_POSEDGE.search(sv or "")),
        "has_disable_iff": bool(_HAS_DISABLE_IFF.search(sv or "")),
        "no_invented": "sva_invented_port" not in issues,
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
