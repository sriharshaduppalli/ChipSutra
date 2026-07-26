"""
Format Verilator/sim/lint logs into a re-prompt block for debug / regenerate.

Closed-loop path (app): generate → lint/sim → attach this block → debug or regenerate.
Does not run tools itself — call after you already have a log string.
"""
from __future__ import annotations

import re
from typing import List, Optional


_VERILATOR_LINE = re.compile(
    r"%(?:Error|Warning)[-:].*$|"
    r"%Error\b.*$|"
    r"Unsupported:\s*.*$",
    re.IGNORECASE | re.MULTILINE,
)
_UVM_LINE = re.compile(
    r"UVM_(?:ERROR|FATAL|WARNING).*?$",
    re.IGNORECASE | re.MULTILINE,
)
_ASSERT_LINE = re.compile(
    r"(?:Error|Fatal):\s*.*(?:assert|Assertion|SVA).*?$|"
    r"Offending\s+'.*?$",
    re.IGNORECASE | re.MULTILINE,
)


def summarize_log(log: str, *, max_lines: int = 40) -> List[str]:
    if not (log or "").strip():
        return []
    hits: List[str] = []
    for rx in (_VERILATOR_LINE, _UVM_LINE, _ASSERT_LINE):
        for m in rx.finditer(log):
            line = m.group(0).strip()
            if line and line not in hits:
                hits.append(line)
            if len(hits) >= max_lines:
                return hits
    if not hits:
        # Fallback: last non-empty lines
        for line in reversed(log.strip().splitlines()):
            s = line.strip()
            if s:
                hits.append(s)
            if len(hits) >= min(15, max_lines):
                break
        hits.reverse()
    return hits[:max_lines]


def format_lint_feedback(
    log: str,
    *,
    prior_code: Optional[str] = None,
    max_log_chars: int = 12000,
    max_code_chars: int = 8000,
) -> str:
    """Build user-message appendix for fix/regenerate prompts."""
    clipped = (log or "")[:max_log_chars]
    findings = summarize_log(clipped)
    parts = [
        "--- Tool / simulation feedback (fix these; do not ignore) ---",
    ]
    if findings:
        parts.append("Key findings:")
        parts.extend(f"- {f}" for f in findings)
    else:
        parts.append("(No structured error lines found — see raw log excerpt.)")
    parts.append("\nRaw log excerpt:\n```\n" + clipped.strip() + "\n```")
    if prior_code:
        parts.append(
            "\nPrior generated code to revise:\n```systemverilog\n"
            + prior_code[:max_code_chars]
            + "\n```"
        )
    parts.append(
        "\nInstructions: produce a corrected artifact. Keep DUT port names exact. "
        "Explain root cause briefly in comments only if needed; prefer compilable code."
    )
    return "\n".join(parts)


def lint_feedback_status() -> dict:
    sample = summarize_log("%Error: test.sv:10: syntax error\nUVM_ERROR @ 100: env.sb [CMP] mismatch")
    return {"enabled": True, "sample_findings": len(sample)}
