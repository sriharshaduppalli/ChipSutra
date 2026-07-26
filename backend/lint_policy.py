"""Verilator finding parser and project lint-policy/waiver gate."""
from __future__ import annotations

import fnmatch
import json
import re
from typing import Any, Dict, List, Optional


_FINDING = re.compile(
    r"%(?P<severity>Warning|Error)(?:-(?P<code>[A-Z0-9_]+))?:\s*"
    r"(?:(?P<file>[^:\r\n]+):(?P<line>\d+)(?::\d+)?:\s*)?"
    r"(?P<message>.*)",
    re.IGNORECASE,
)

DEFAULT_POLICY: Dict[str, Any] = {
    "fail_on_warning": False,
    "fatal_warnings": [],
    "waivers": [],
}


def parse_policy(text: str) -> Dict[str, Any]:
    raw = json.loads(text or "{}")
    if not isinstance(raw, dict):
        raise ValueError("lint policy must be a JSON object")
    policy = {**DEFAULT_POLICY, **raw}
    if not isinstance(policy["fatal_warnings"], list) or not isinstance(policy["waivers"], list):
        raise ValueError("fatal_warnings and waivers must be arrays")
    for waiver in policy["waivers"]:
        if not isinstance(waiver, dict):
            raise ValueError("each waiver must be an object")
        if not waiver.get("reason") or not waiver.get("owner"):
            raise ValueError("each waiver requires reason and owner")
    return policy


def parse_verilator_findings(log: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in (log or "").splitlines():
        m = _FINDING.search(line)
        if not m:
            continue
        out.append(
            {
                "severity": m.group("severity").lower(),
                "code": (m.group("code") or m.group("severity")).upper(),
                "file": (m.group("file") or "").strip(),
                "line": int(m.group("line")) if m.group("line") else None,
                "message": m.group("message").strip(),
                "raw": line.strip(),
            }
        )
    return out


def _waiver_matches(finding: Dict[str, Any], waiver: Dict[str, Any]) -> bool:
    code = str(waiver.get("code") or "*").upper()
    if not fnmatch.fnmatch(finding["code"], code):
        return False
    file_glob = str(waiver.get("file_glob") or "*")
    if finding.get("file") and not fnmatch.fnmatch(finding["file"].replace("\\", "/"), file_glob):
        return False
    line = waiver.get("line")
    if line is not None and finding.get("line") != int(line):
        return False
    contains = str(waiver.get("message_contains") or "").lower()
    return not contains or contains in finding.get("message", "").lower()


def apply_lint_policy(findings: List[Dict[str, Any]], policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    p = policy or DEFAULT_POLICY
    active: List[Dict[str, Any]] = []
    waived: List[Dict[str, Any]] = []
    for finding in findings:
        matched = next((w for w in p.get("waivers", []) if _waiver_matches(finding, w)), None)
        if matched:
            waived.append({**finding, "waiver": matched})
        else:
            active.append(finding)
    fatal_codes = {str(x).upper() for x in p.get("fatal_warnings", [])}
    blocking = [
        f
        for f in active
        if f["severity"] == "error"
        or bool(p.get("fail_on_warning"))
        or f["code"] in fatal_codes
    ]
    return {
        "gate_ok": not blocking,
        "active": active,
        "waived": waived,
        "blocking": blocking,
        "counts": {
            "active": len(active),
            "waived": len(waived),
            "blocking": len(blocking),
        },
        "policy": p,
    }
