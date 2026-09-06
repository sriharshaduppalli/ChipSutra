"""Spec→RTL checklist guardrails — catch incomplete specs before trusting generation.

Phase-1 of docs/ADVANCED_DV_ARCHITECTURE.md. Incomplete specs can be hard-gated
(`CHIPSUTRA_SPEC_GATE`, default on) to exploratory stub RTL with documented assumptions.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

_CLK_RE = re.compile(
    r"\b(clock|clk|aclk|pclk|sclk|sys_clk|clock\s*domain|posedge)\b",
    re.I,
)
_RST_RE = re.compile(
    r"\b(reset|rst|rst_n|aresetn|async\s*reset|sync\s*reset|reset\s*polarity)\b",
    re.I,
)
_IO_RE = re.compile(
    r"\b(input|output|inout|port|interface|i/?o\b|signal\s+list|pin)\b",
    re.I,
)
_WIDTH_RE = re.compile(
    r"\b(\d+\s*[-–]\s*bit|\d+\s*bits?|width\s*[:=]\s*\d+|\[\s*\d+\s*:\s*\d+\s*\])\b",
    re.I,
)
_PROTOCOL_RE = re.compile(
    r"\b(axi|apb|ahb|uart|spi|i2c|fifo|valid|ready|handshake|wishbone)\b",
    re.I,
)
_TIMING_RE = re.compile(
    r"\b(latency|throughput|frequency|mhz|ns\b|period|timing|cycle)\b",
    re.I,
)


def analyze_spec(text: str = "", *, prompt: str = "") -> Dict[str, Any]:
    """Score a natural-language / structured spec for Spec→RTL readiness."""
    blob = f"{prompt or ''}\n{text or ''}".strip()
    if not blob:
        return {
            "ready": False,
            "score": 0,
            "grade": "empty",
            "checklist": {
                "clock": False,
                "reset": False,
                "io_ports": False,
                "widths": False,
                "protocol": False,
                "timing": False,
            },
            "gaps": ["No specification text provided."],
            "notes": ["Paste a design spec with clocks, resets, and I/O before trusting Spec→RTL."],
        }

    checks = {
        "clock": bool(_CLK_RE.search(blob)),
        "reset": bool(_RST_RE.search(blob)),
        "io_ports": bool(_IO_RE.search(blob)),
        "widths": bool(_WIDTH_RE.search(blob)),
        "protocol": bool(_PROTOCOL_RE.search(blob)),
        "timing": bool(_TIMING_RE.search(blob)),
    }
    # Core triad: clock + reset + I/O — required for ready
    core = ("clock", "reset", "io_ports")
    core_ok = all(checks[k] for k in core)
    bonus = sum(1 for k in ("widths", "protocol", "timing") if checks[k])
    score = (sum(1 for k in core if checks[k]) * 25) + (bonus * 8)
    score = min(100, score)

    gaps: List[str] = []
    if not checks["clock"]:
        gaps.append("Missing clock / clock-domain description.")
    if not checks["reset"]:
        gaps.append("Missing reset name/polarity (e.g. rst_n active-low).")
    if not checks["io_ports"]:
        gaps.append("Missing I/O / port table or signal list.")
    if not checks["widths"]:
        gaps.append("Widths not stated (recommend N-bit fields or [MSB:LSB]).")
    if not checks["protocol"]:
        gaps.append("No protocol/handshake named (optional but improves RTL).")
    if not checks["timing"]:
        gaps.append("No latency/frequency/timing constraints (optional).")

    if core_ok and bonus >= 1:
        grade = "solid"
    elif core_ok:
        grade = "usable"
    elif sum(1 for k in core if checks[k]) >= 2:
        grade = "partial"
    else:
        grade = "weak"

    notes: List[str] = []
    if not core_ok:
        notes.append("Spec incomplete — treat generated RTL as 🧪 exploratory.")
    else:
        notes.append("Core checklist OK (clock/reset/I/O). Review widths and protocol before sign-off.")

    return {
        "ready": core_ok,
        "score": score,
        "grade": grade,
        "checklist": checks,
        "gaps": gaps,
        "notes": notes,
    }


def checklist_prompt_block(analysis: Dict[str, Any]) -> str:
    """Inject into Spec→RTL system/user context."""
    if not analysis:
        return ""
    lines = [
        "--- Spec checklist (ChipSutra) ---",
        f"ready={analysis.get('ready')} grade={analysis.get('grade')} score={analysis.get('score')}",
    ]
    for k, v in (analysis.get("checklist") or {}).items():
        lines.append(f"  [{('x' if v else ' ')}] {k}")
    gaps = analysis.get("gaps") or []
    if gaps:
        lines.append("Gaps:")
        for g in gaps[:6]:
            lines.append(f"  - {g}")
    if not analysis.get("ready"):
        lines.append(
            "INSTRUCTION: Spec incomplete. If the Spec gate is on, ChipSutra emits "
            "exploratory stub RTL with // ASSUMPTION comments instead of free-form LLM RTL. "
            "Set CHIPSUTRA_SPEC_GATE=0 to force LLM anyway."
        )
    return "\n".join(lines)


def spec_gate_enabled() -> bool:
    raw = (os.environ.get("CHIPSUTRA_SPEC_GATE") or "true").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    return True


def spec_gate_blocks(analysis: Optional[Dict[str, Any]]) -> bool:
    if not spec_gate_enabled():
        return False
    if not analysis:
        return True
    return not bool(analysis.get("ready"))


def exploratory_stub_rtl(analysis: Optional[Dict[str, Any]] = None, *, prompt: str = "") -> str:
    """Documented stub when clock/reset/I/O are missing. Not production RTL."""
    a = analysis or {}
    gaps = a.get("gaps") or ["No specification text provided."]
    notes = "\n".join(f"// ASSUMPTION: {g}" for g in gaps[:8])
    hint = (prompt or "").strip().replace("\n", " ")[:120]
    return f"""// ChipSutra Spec→RTL GATE — spec incomplete (grade={a.get('grade') or 'empty'})
// Exploratory stub only. Fill clock / reset / I/O in the spec and regenerate.
// This is not a tapeout-ready design.
{notes}
// prompt_hint: {hint or '(none)'}
module exploratory_stub (
  input  logic       clk,    // assumed
  input  logic       rst_n,  // assumed active-low
  input  logic [7:0] d,      // assumed
  output logic [7:0] q       // assumed
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) q <= '0;
    else        q <= d;
  end
endmodule
"""
