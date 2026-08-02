"""Debug log classifier — map Verilator/UVM/sim errors to ranked fix templates.

Phase-1 of docs/ADVANCED_DV_ARCHITECTURE.md. Used by the debug generate module
and attached to learning when tool_log is present.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# (pattern, category, severity, title, hint)
_RULES: List[Tuple[re.Pattern, str, str, str, str]] = [
    (
        re.compile(r"%Error-MODDUP|Duplicate declaration of module", re.I),
        "parse",
        "error",
        "Duplicate module",
        "Rename TB top or remove duplicate `module` in the same compile unit.",
    ),
    (
        re.compile(r"%Error:.*Unknown module type|Cannot find file containing module", re.I),
        "compile",
        "error",
        "Missing DUT / file",
        "Ensure DUT .sv is on the file list and module name matches the instance.",
    ),
    (
        re.compile(r"Port.*(not found|connection)|(isn't|is not) a port of", re.I),
        "ports",
        "error",
        "Port map mismatch",
        "Regenerate TB from parsed ports; never invent signal names.",
    ),
    (
        re.compile(r"Unsupported.*always|Unsupported.*fork|Unsupported.*class\b|UVM_", re.I),
        "tooling",
        "error",
        "Verilator / UVM unsupported",
        "Prefer pure SV TB (no UVM) for Verilator, or use a UVM-capable simulator.",
    ),
    (
        re.compile(r"\$finish|\$stop", re.I),
        "sim",
        "info",
        "Simulation ended",
        "Check PASS/FAIL messages and error count before $finish.",
    ),
    (
        re.compile(r"\b(X|Z)\b.*(?:propagat|after reset|isunknown)|\$isunknown|Unknowns", re.I),
        "xprop",
        "error",
        "X / unknown on signals",
        "Drive all inputs after reset; check reset polarity and uninitialized regs.",
    ),
    (
        re.compile(r"mismatch|Assertion failed|UVM_ERROR|\$error", re.I),
        "scoreboard",
        "error",
        "Checker / golden mismatch",
        "Compare TB golden vs RTL semantics; fix expected model (not DUT outs).",
    ),
    (
        re.compile(r"timeout|TIMEOUT|deadlock|never ready|hang", re.I),
        "protocol",
        "error",
        "Handshake / ready timeout",
        "Check valid/ready or APB/AXI ready paths; add bounded while-timeouts.",
    ),
    (
        re.compile(r"syntax error|PARSE|expecting|unexpected token", re.I),
        "parse",
        "error",
        "Syntax / parse error",
        "Fix SV syntax near the reported line; avoid mid-block declarations if tool is strict.",
    ),
    (
        re.compile(r"width mismatch|Width mismatch|Truncation|expects.*bits", re.I),
        "width",
        "error",
        "Width mismatch",
        "Cast `$urandom` to port width; match WIDTH/DEPTH parameters on the DUT instance.",
    ),
    (
        re.compile(r"multiple drivers|driven by multiple", re.I),
        "drivers",
        "error",
        "Multiple drivers",
        "Drive each TB output from one procedural block; don't assign wires from always.",
    ),
    (
        re.compile(r"%Warning-UNUSED|Unused|never used", re.I),
        "lint",
        "warning",
        "Unused signal / lint",
        "Often benign in smoke TBs; silence with policy or remove unused decls.",
    ),
]


def classify_log(tool_log: str = "", *, prior_code: str = "") -> Dict[str, Any]:
    """Parse a tool log into ranked categories + actionable templates."""
    text = (tool_log or "").strip()
    if not text:
        return {
            "ok": True,
            "empty": True,
            "findings": [],
            "top_category": None,
            "summary": "No tool log attached.",
            "templates": [],
        }

    findings: List[Dict[str, Any]] = []
    seen = set()
    for pat, category, severity, title, hint in _RULES:
        m = pat.search(text)
        if not m:
            continue
        key = (category, title)
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            {
                "category": category,
                "severity": severity,
                "title": title,
                "hint": hint,
                "match": (m.group(0) or "")[:120],
            }
        )

    # Prefer errors over warnings in ranking
    sev_rank = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: sev_rank.get(f["severity"], 9))

    templates: List[str] = []
    for f in findings[:5]:
        templates.append(f"{f['title']}: {f['hint']}")

    if not findings:
        templates.append(
            "Unrecognized log — paste the first %Error/%Warning lines; "
            "try Fast-random TB skeleton as a known-good baseline."
        )
        top = "unknown"
        summary = "Log present but no known patterns matched."
    else:
        top = findings[0]["category"]
        summary = f"{len(findings)} finding(s); primary: {findings[0]['title']}."

    if prior_code and "module" in prior_code and any(f["category"] == "ports" for f in findings):
        templates.insert(0, "Re-run Generate with gen_mode=skeleton using the same RTL file selection.")

    return {
        "ok": not any(f["severity"] == "error" for f in findings),
        "empty": False,
        "findings": findings,
        "top_category": top,
        "summary": summary,
        "templates": templates[:6],
    }


def debug_prompt_block(analysis: Dict[str, Any]) -> str:
    """Inject ranked fix templates into the debug generate prompt."""
    if not analysis or analysis.get("empty"):
        return ""
    lines = [
        "--- Debug classifier (ChipSutra) ---",
        f"summary: {analysis.get('summary')}",
        f"top_category: {analysis.get('top_category')}",
    ]
    for f in (analysis.get("findings") or [])[:5]:
        lines.append(f"- [{f['severity']}] {f['title']}: {f['hint']}")
    lines.append("INSTRUCTION: Propose a concrete fix ordered by the ranked findings above.")
    return "\n".join(lines)
