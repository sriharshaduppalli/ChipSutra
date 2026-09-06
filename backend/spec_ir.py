"""Spec IR v0 — requirements graph, ports, SVA stubs from natural-language specs.

Does not replace spec_checklist.py. Checklist = readiness score.
This module extracts a structured IR the LLM can emit against.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

_PORT_LINE = re.compile(
    r"(?im)^\s*(?:[-*]\s+|•\s+|\d+[.)]\s+)?"
    r"(input|output|inout)\s+(?:wire|reg|logic\s+)?"
    r"(?:(\[[^\]]+\])\s+)?"
    r"([A-Za-z_]\w*)",
)
_PORT_KV = re.compile(
    r"(?im)^\s*(?:[-*]\s+)?([A-Za-z_]\w*)\s*[:—-]\s*(input|output|inout|clock|reset)\b"
    r"(?:\s*,?\s*(\[[^\]]+\]|\d+\s*-?\s*bit))?",
)
_REQ = re.compile(
    r"(?im)^\s*(?:(?:REQ[-_]?|R)(\d+)[.:)]\s+|(\d+)[.)]\s+|[-*]\s+(?:The DUT |DUT shall |shall |must ))"
    r"(.+)$",
)
_CLK_NAME = re.compile(r"\b(clk|clock|aclk|pclk|hclk|sclk)\b", re.I)
_RST_NAME = re.compile(r"\b(rst_n|rstn|reset_n|aresetn|presetn|hresetn|rst|reset)\b", re.I)


def extract_spec_ir(text: str = "", *, prompt: str = "") -> Dict[str, Any]:
    blob = f"{prompt or ''}\n{text or ''}".strip()
    ports: List[Dict[str, str]] = []
    seen = set()

    def _add(name: str, direction: str, width: str = "") -> None:
        n = (name or "").strip()
        if not n or n.lower() in seen:
            return
        seen.add(n.lower())
        ports.append({"name": n, "direction": direction.lower(), "width": (width or "").strip()})

    for m in _PORT_LINE.finditer(blob):
        _add(m.group(3), m.group(1), m.group(2) or "")
    for m in _PORT_KV.finditer(blob):
        direction = m.group(2).lower()
        if direction in ("clock",):
            direction = "input"
        if direction in ("reset",):
            direction = "input"
        _add(m.group(1), direction, m.group(3) or "")

    reqs: List[Dict[str, str]] = []
    for m in _REQ.finditer(blob):
        rid = m.group(1) or m.group(2) or str(len(reqs) + 1)
        body = (m.group(3) or "").strip()
        if len(body) < 8:
            continue
        kind = "functional"
        low = body.lower()
        if any(k in low for k in ("assert", "never", "shall not", "must not")):
            kind = "safety"
        elif any(k in low for k in ("cover", "reach")):
            kind = "cover"
        reqs.append({"id": f"REQ-{rid}", "kind": kind, "text": body[:240]})

    clocks = sorted({m.group(0) for m in _CLK_NAME.finditer(blob)}, key=str.lower)
    resets = sorted({m.group(0) for m in _RST_NAME.finditer(blob)}, key=str.lower)
    return {
        "version": "0.1",
        "ports": ports[:32],
        "requirements": reqs[:24],
        "clocks": clocks[:4],
        "resets": resets[:4],
        "port_count": len(ports),
        "requirement_count": len(reqs),
    }


def sva_stubs_from_ir(ir: Dict[str, Any]) -> str:
    """Comment-form SVA stubs — bind to real clocks/ports only."""
    clk = (ir.get("clocks") or ["clk"])[0]
    rst = (ir.get("resets") or ["rst_n"])[0]
    lines = [
        f"// Spec IR SVA stubs (exploratory) — clock {clk}, disable iff (!{rst})",
    ]
    for req in (ir.get("requirements") or [])[:8]:
        rid = req.get("id") or "REQ"
        kind = req.get("kind") or "functional"
        txt = (req.get("text") or "").replace("\n", " ")[:100]
        if kind == "cover":
            lines.append(f"// cover property (@(posedge {clk}) /* {rid}: {txt} */);")
        else:
            lines.append(
                f"// assert property (@(posedge {clk}) disable iff (!{rst}) /* {rid}: {txt} */);"
            )
    if len(lines) == 1:
        lines.append("// (no numbered requirements found — add REQ-1 … in the spec)")
    return "\n".join(lines)


def spec_ir_prompt_block(ir: Dict[str, Any]) -> str:
    if not ir:
        return ""
    lines = [
        "--- Spec IR (ChipSutra) ---",
        f"ports={ir.get('port_count') or 0} requirements={ir.get('requirement_count') or 0}",
    ]
    if ir.get("clocks"):
        lines.append("clocks: " + ", ".join(ir["clocks"]))
    if ir.get("resets"):
        lines.append("resets: " + ", ".join(ir["resets"]))
    if ir.get("ports"):
        lines.append("I/O:")
        for p in ir["ports"][:16]:
            w = (p.get("width") or "").strip()
            lines.append(f"  {p.get('direction')} {w} {p.get('name')}".replace("  ", " "))
    if ir.get("requirements"):
        lines.append("Requirements (implement + comment REQ-id):")
        for r in ir["requirements"][:12]:
            lines.append(f"  {r.get('id')} [{r.get('kind')}]: {r.get('text')}")
    stubs = sva_stubs_from_ir(ir)
    if stubs:
        lines.append("SVA stubs (emit in comments or a bind file, exact port names only):")
        lines.append(stubs)
    lines.append(
        "INSTRUCTION: Use only extracted ports. Do not invent AXI/CSR maps. "
        "If a requirement is ambiguous, implement the conservative case and // TODO it."
    )
    return "\n".join(lines)
