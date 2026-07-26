"""
Extract SystemVerilog/Verilog module ports from source text (regex, no EDA deps).

Injected into Generate prompts so the model uses real interface names/widths.
Not a full parser — good enough for typical DUT headers; user RTL still wins on conflict.
"""
from __future__ import annotations

import re
from typing import List, Optional


_DIRECTION = r"(?:input|output|inout)"
_NETTYPE = r"(?:wire|reg|logic|bit|integer|int|signed|unsigned|tri|wand|wor)"
# ANSI port: input wire [7:0] foo, or input foo
_ANSI_PORT = re.compile(
    rf"^\s*({_DIRECTION})\s+"
    rf"(?:(?:{_NETTYPE})\s+)*"
    rf"(?:(signed|unsigned)\s+)?"
    rf"(?:(\[[^\]]+\])\s*)?"
    rf"(\w+)\s*(?:,|$)",
    re.IGNORECASE | re.MULTILINE,
)
_MODULE_HDR = re.compile(
    r"\bmodule\s+(\w+)\s*(?:#\s*\([^;]*?\))?\s*\((.*?)\);",
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


def _clean_port_list(body: str) -> str:
    # Strip // and /* */ comments roughly
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.DOTALL)
    body = re.sub(r"//.*?$", " ", body, flags=re.MULTILINE)
    return body


def extract_modules(rtl: str) -> List[dict]:
    """Return list of {name, ports: [{dir, width, name}, ...]}."""
    if not rtl or not rtl.strip():
        return []
    text = _clean_port_list(rtl)
    modules: List[dict] = []
    for m in _MODULE_HDR.finditer(text):
        name = m.group(1)
        port_body = m.group(2)
        ports: List[dict] = []
        seen: set[str] = set()
        for pm in _ANSI_PORT.finditer(port_body):
            pname = pm.group(4)
            if pname in seen:
                continue
            seen.add(pname)
            ports.append(
                {
                    "direction": pm.group(1).lower(),
                    "width": (pm.group(3) or "").strip(),
                    "name": pname,
                }
            )
        if not ports:
            # Non-ANSI: names in header, decls after
            header_names = [n.strip() for n in port_body.split(",") if n.strip() and re.match(r"^\w+$", n.strip())]
            after = text[m.end() : m.end() + 4000]
            for pm in _LEGACY_PORT.finditer(after):
                width = (pm.group(3) or "").strip()
                direction = pm.group(1).lower()
                for raw in pm.group(4).split(","):
                    pname = raw.strip().split()[-1] if raw.strip() else ""
                    if not pname or not re.match(r"^\w+$", pname):
                        continue
                    if pname in seen:
                        continue
                    seen.add(pname)
                    ports.append({"direction": direction, "width": width, "name": pname})
            # Preserve header order when possible
            if header_names and ports:
                order = {n: i for i, n in enumerate(header_names)}
                ports.sort(key=lambda p: order.get(p["name"], 999))
        modules.append({"name": name, "ports": ports})
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
