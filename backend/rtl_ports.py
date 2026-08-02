"""
Extract SystemVerilog/Verilog module ports from source text (regex, no EDA deps).

Injected into Generate prompts so the model uses real interface names/widths.
Not a full parser — good enough for typical DUT headers; user RTL still wins on conflict.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Tuple


_DIRECTION = r"(?:input|output|inout)"
_NETTYPE = r"(?:wire|reg|logic|bit|integer|int|signed|unsigned|tri|wand|wor)"
# ANSI port declaration start: input wire [7:0] foo
_ANSI_DECL = re.compile(
    rf"^\s*({_DIRECTION})\s+"
    rf"(?:(?:{_NETTYPE})\s+)*"
    rf"(?:(signed|unsigned)\s+)?"
    rf"(?:(\[[^\]]+\])\s*)?"
    rf"(.+?)\s*$",
    re.IGNORECASE,
)
_MODULE_HDR = re.compile(
    r"\bmodule\s+(\w+)\s*(?:#\s*\(([^;]*?)\))?\s*\((.*?)\);",
    re.IGNORECASE | re.DOTALL,
)
# Non-ANSI: module m(a,b); input a; output [7:0] b;
_LEGACY_PORT = re.compile(
    rf"^\s*({_DIRECTION})\s+"
    rf"(?:(?:{_NETTYPE})\s+)*"
    rf"(?:(signed|unsigned)\s+)?"
    rf"(?:(\[[^\]]+\])\s*)?"
    rf"([\w\s,]+);",
    re.IGNORECASE | re.MULTILINE,
)
_PARAM_ASSIGN = re.compile(
    r"parameter\s+(?:(?:int|integer|logic|bit|longint)\s+)?"
    r"(?:\[\s*[^\]]+\s*\]\s+)?"
    r"(\w+)\s*=\s*(\d+)",
    re.IGNORECASE,
)


def _clean_port_list(body: str) -> str:
    # Strip // and /* */ comments roughly
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.DOTALL)
    body = re.sub(r"//.*?$", " ", body, flags=re.MULTILINE)
    return body


def _clog2(n: int) -> int:
    if n <= 1:
        return 0
    return int(math.ceil(math.log2(n)))


def extract_parameters(param_body: str) -> Dict[str, int]:
    """Parse simple numeric `parameter NAME = N` assignments."""
    params: Dict[str, int] = {}
    if not param_body:
        return params
    cleaned = _clean_port_list(param_body)
    for m in _PARAM_ASSIGN.finditer(cleaned):
        params[m.group(1)] = int(m.group(2))
    return params


def resolve_width_expr(width: str, params: Optional[Dict[str, int]] = None) -> Tuple[str, int]:
    """
    Resolve a port width expression to a concrete `[MSB:LSB]` string and bit count.
    Supports `[7:0]`, `[WIDTH-1:0]`, `[$clog2(DEPTH+1)-1:0]`.
    """
    w = (width or "").strip()
    params = params or {}
    if not w:
        return "", 1
    m = re.match(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", w)
    if m:
        bits = abs(int(m.group(1)) - int(m.group(2))) + 1
        return f"[{m.group(1)}:{m.group(2)}]", bits

    # [$clog2(DEPTH+1)-1:0] or [$clog2(DEPTH)-1:0]
    m = re.match(
        r"\[\s*\$clog2\s*\(\s*(\w+)\s*([+-]\s*\d+)?\s*\)\s*-\s*1\s*:\s*0\s*\]",
        w,
        re.I,
    )
    if m:
        base = params.get(m.group(1))
        if base is not None:
            adj = m.group(2) or ""
            adj = adj.replace(" ", "")
            n = base + int(adj) if adj else base
            msb = max(_clog2(n) - 1, 0)
            return f"[{msb}:0]", msb + 1

    # [WIDTH-1:0]
    m = re.match(r"\[\s*(\w+)\s*-\s*1\s*:\s*0\s*\]", w, re.I)
    if m:
        base = params.get(m.group(1))
        if base is not None and base >= 1:
            msb = base - 1
            return f"[{msb}:0]", base

    # Fallbacks for common param names when expression left unresolved
    for key, default in (("WIDTH", 8), ("DATA_WIDTH", 8), ("DW", 8)):
        if key in w.upper() and key in params:
            bits = params[key]
            return f"[{bits - 1}:0]", bits
        if key in w.upper():
            return f"[{default - 1}:0]", default
    return w, 1


def extract_modules(rtl: str) -> List[dict]:
    """Return list of {name, ports: [...], parameters: {NAME: int}}."""
    if not rtl or not rtl.strip():
        return []
    text = _clean_port_list(rtl)
    modules: List[dict] = []
    for m in _MODULE_HDR.finditer(text):
        name = m.group(1)
        param_body = m.group(2) or ""
        port_body = m.group(3) or ""
        params = extract_parameters(param_body)
        ports: List[dict] = []
        seen: set[str] = set()
        # Split on direction keywords so `output logic full, empty` yields both names.
        chunks = re.split(
            rf"(?=(?:^|,)\s*(?:{_DIRECTION})\b)",
            port_body,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        for chunk in chunks:
            chunk = chunk.strip().lstrip(",").strip()
            if not chunk:
                continue
            pm = _ANSI_DECL.match(chunk.rstrip(",").strip())
            if not pm:
                continue
            direction = pm.group(1).lower()
            raw_w = (pm.group(3) or "").strip()
            width, bits = resolve_width_expr(raw_w, params)
            for raw in pm.group(4).split(","):
                pname = raw.strip().split()[-1] if raw.strip() else ""
                if not pname or not re.match(r"^\w+$", pname):
                    continue
                if pname.lower() in ("input", "output", "inout"):
                    continue
                if pname in seen:
                    continue
                seen.add(pname)
                ports.append(
                    {
                        "direction": direction,
                        "width": width,
                        "bits": bits,
                        "name": pname,
                    }
                )
        if not ports:
            # Non-ANSI: names in header, decls after
            header_names = [n.strip() for n in port_body.split(",") if n.strip() and re.match(r"^\w+$", n.strip())]
            after = text[m.end() : m.end() + 4000]
            for pm in _LEGACY_PORT.finditer(after):
                raw_w = (pm.group(3) or "").strip()
                width, bits = resolve_width_expr(raw_w, params)
                direction = pm.group(1).lower()
                for raw in pm.group(4).split(","):
                    pname = raw.strip().split()[-1] if raw.strip() else ""
                    if not pname or not re.match(r"^\w+$", pname):
                        continue
                    if pname in seen:
                        continue
                    seen.add(pname)
                    ports.append(
                        {
                            "direction": direction,
                            "width": width,
                            "bits": bits,
                            "name": pname,
                        }
                    )
            # Preserve header order when possible
            if header_names and ports:
                order = {n: i for i, n in enumerate(header_names)}
                ports.sort(key=lambda p: order.get(p["name"], 999))
        modules.append({"name": name, "ports": ports, "parameters": params})
    return modules


def format_port_context(modules: List[dict], *, max_modules: int = 5) -> str:
    if not modules:
        return ""
    lines = [
        "Parsed DUT interfaces (from user RTL — use these exact names/widths; do not invent ports):"
    ]
    for mod in modules[:max_modules]:
        lines.append(f"module {mod['name']}")
        if not mod["ports"]:
            lines.append("  (ports not parsed — read the RTL header carefully)")
            continue
        for p in mod["ports"]:
            w = f" {p['width']}" if p["width"] else ""
            lines.append(f"  {p['direction']}{w} {p['name']}")
    return "\n".join(lines)


def extract_port_context_from_texts(texts: List[str], *, max_modules: int = 5) -> str:
    """Merge modules from multiple file bodies."""
    all_mods: List[dict] = []
    seen_names: set[str] = set()
    for t in texts:
        for mod in extract_modules(t or ""):
            if mod["name"] in seen_names:
                continue
            seen_names.add(mod["name"])
            all_mods.append(mod)
    return format_port_context(all_mods, max_modules=max_modules)


def rtl_ports_status() -> dict:
    sample = extract_modules(
        "module counter(input wire clk, input wire rst, output reg [7:0] q); endmodule"
    )
    return {
        "enabled": True,
        "parser": "regex_ansi_legacy",
        "sample_ok": bool(sample and sample[0]["ports"] and len(sample[0]["ports"]) == 3),
    }
