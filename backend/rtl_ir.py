"""Soft RTL IR — clocks, params, FSM hints, RISC-V tags (no EDA deps).

Optional: if `slang` or `verible-verilog-syntax` is on PATH, record that a
real parser is available. Generate still uses this regex IR so ChipSutra
stays laptop-only; slang is a capability flag, not a hard dependency.
"""
from __future__ import annotations

import re
import shutil
from typing import Any, Dict, List, Optional, Sequence

from rtl_ports import extract_modules

_FSM_ENUM = re.compile(
    r"\btypedef\s+enum\b[^;]*?\{([^}]+)\}",
    re.I | re.S,
)
_FSM_LOCAL = re.compile(
    r"\blocalparam\s+(?:\w+\s+)?(S(?:TATE)?_\w+|IDLE|FETCH|DECODE|EXECUTE|WAIT)\s*=",
    re.I,
)
_ALWAYS_FF = re.compile(r"\balways_ff\b|\balways\s+@\s*\(\s*posedge", re.I)
_ALWAYS_COMB = re.compile(r"\balways_comb\b|\balways\s+@\s*\(\s*\*", re.I)
_CASE_OP = re.compile(r"\bcase\s*\(\s*(?:op(?:code)?|funct3|instr)", re.I)

_RV_PORTS = {
    "instr",
    "instruction",
    "imem_rdata",
    "inst",
    "i_imem_rdata",
    "mem_rdata",
    "instr_rdata",
}
_RV_ADDR = {"pc", "iaddr", "imem_addr", "instr_addr", "mem_addr", "daddr"}
_RV_DECODE = {"opcode", "funct3", "funct7", "rs1", "rs2", "rd"}


def oss_parser_available() -> Dict[str, bool]:
    return {
        "slang": bool(shutil.which("slang")),
        "verible_syntax": bool(shutil.which("verible-verilog-syntax")),
        "verible_lint": bool(shutil.which("verible-verilog-lint")),
    }


def _fsm_states(rtl: str) -> List[str]:
    names: List[str] = []
    for m in _FSM_ENUM.finditer(rtl or ""):
        for part in m.group(1).split(","):
            tok = re.split(r"[=/]", part.strip())[0].strip()
            tok = re.sub(r"\W+", "", tok)
            if tok and tok not in names:
                names.append(tok)
    for m in _FSM_LOCAL.finditer(rtl or ""):
        n = m.group(1)
        if n and n not in names:
            names.append(n)
    return names[:16]


def looks_riscv(name_set: set, rtl_text: str = "") -> bool:
    blob = (rtl_text or "").lower()
    if re.search(r"\b(riscv|rv32i|rv32e|rv64i|ibex|vexriscv|picorv)\b", blob):
        return True
    if name_set & _RV_PORTS and name_set & _RV_ADDR:
        return True
    if len(name_set & _RV_DECODE) >= 3:
        return True
    return False


def extract_rtl_ir(
    rtl_text: str = "",
    modules: Optional[Sequence[dict]] = None,
) -> Dict[str, Any]:
    """Return a compact IR dict for analysis / LLM context."""
    mods = list(modules or []) or extract_modules(rtl_text or "")
    ports = (mods[0].get("ports") if mods else None) or []
    params = dict((mods[0].get("parameters") or {}) if mods else {})
    names = {(p.get("name") or "").lower() for p in ports if p.get("name")}
    rtl = rtl_text or ""
    parsers = oss_parser_available()
    engine = "regex"
    if parsers.get("slang"):
        engine = "regex+slang_available"
    elif parsers.get("verible_syntax"):
        engine = "regex+verible_available"

    iface = _interface_map(mods)
    clocks = sorted({c for m in iface for c in (m.get("clocks") or [])})
    ir = {
        "parser": engine,
        "module_name": (mods[0].get("name") if mods else None),
        "module_count": len(mods),
        "modules": [
            {
                "name": m.get("name"),
                "port_count": len(m.get("ports") or []),
                "ports": [p.get("name") for p in (m.get("ports") or [])[:24] if p.get("name")],
            }
            for m in mods[:16]
        ],
        "parameters": params,
        "port_count": len(ports),
        "always_ff": len(_ALWAYS_FF.findall(rtl)),
        "always_comb": len(_ALWAYS_COMB.findall(rtl)),
        "has_case_opcode": bool(_CASE_OP.search(rtl)),
        "fsm_states": _fsm_states(rtl),
        "looks_riscv": looks_riscv(names, rtl),
        "oss_parsers": parsers,
        "interface_map": iface,
        "clocks": clocks,
        "cdc_hint": len(clocks) > 1,
    }
    return ir


_CLK_NAME = re.compile(r"clk|clock", re.I)


def _clocks_of(ports: Sequence[dict]) -> List[str]:
    out: List[str] = []
    for p in ports or []:
        n = p.get("name") or ""
        if n and _CLK_NAME.search(n) and n not in out:
            out.append(n)
    return out


def _interface_map(mods: Sequence[dict]) -> List[Dict[str, Any]]:
    """Per-module protocol/clock sketch from port names (no invented maps)."""
    try:
        from tb_scale_emit import protocol_from_port_names
    except Exception:
        protocol_from_port_names = None  # type: ignore
    out: List[Dict[str, Any]] = []
    for m in mods[:16]:
        ports = m.get("ports") or []
        names = [p.get("name") for p in ports if p.get("name")]
        proto = "generic"
        if protocol_from_port_names:
            proto = protocol_from_port_names(names)
        out.append(
            {
                "module": m.get("name"),
                "protocol": proto,
                "clocks": _clocks_of(ports),
                "port_count": len(ports),
            }
        )
    return out


def ir_brief_lines(ir: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    params = ir.get("parameters") or {}
    if params:
        shown = ", ".join(f"{k}={v}" for k, v in list(params.items())[:8])
        lines.append(f"Parameters: {shown}")
    if ir.get("fsm_states"):
        lines.append("FSM states: " + ", ".join(ir["fsm_states"][:10]))
    lines.append(
        f"Processes: always_ff/posedge={ir.get('always_ff') or 0} "
        f"always_comb={ir.get('always_comb') or 0}"
    )
    if ir.get("looks_riscv"):
        lines.append(
            "RISC-V-like DUT — emit RV32I directed smoke (reset, fetch NOP/ADDI, "
            "check PC/wb); do not invent a full ISA VIP."
        )
    if ir.get("parser"):
        lines.append(f"RTL IR parser: {ir['parser']}")
    nmod = ir.get("module_count") or 0
    if nmod > 1:
        names = ", ".join(
            str(m.get("name")) for m in (ir.get("modules") or [])[:8] if m.get("name")
        )
        lines.append(f"Hierarchy: {nmod} modules ({names})")
    if ir.get("cdc_hint"):
        clocks = ", ".join(str(c) for c in (ir.get("clocks") or [])[:8])
        lines.append(
            f"CDC hint: multiple clocks ({clocks}) — do not assume a single domain; "
            "do not invent synchronizer RTL."
        )
    imap = ir.get("interface_map") or []
    if len(imap) > 1:
        bits = [
            f"{m.get('module')}={m.get('protocol')}"
            for m in imap[:8]
            if m.get("module")
        ]
        if bits:
            lines.append("Interface map: " + ", ".join(bits))
    return lines
