"""Functional coverage for generated TBs: detect + mechanically insert covergroups.

Covergroups are wrapped in `ifndef VERILATOR so the Verilator gate still
compiles (Verilator does not support covergroups); Questa/VCS/Xcelium use them.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence

_HAS_COVERGROUP = re.compile(r"\bcovergroup\b", re.I)
_CLK_NAMES = frozenset({"clk", "clock", "clk_i", "clk_in", "aclk", "pclk", "sclk"})
_RST_NAMES = frozenset({"rst", "rst_n", "rstn", "reset", "reset_n", "nrst", "aresetn", "presetn"})


def has_covergroup(sv: str) -> bool:
    return bool(_HAS_COVERGROUP.search(sv or ""))


def _coverable_ports(port_specs: Optional[Sequence[dict]], max_points: int = 6) -> List[dict]:
    out: List[dict] = []
    for p in port_specs or []:
        n = (p.get("name") or "").strip()
        if not n or n.lower() in _CLK_NAMES or n.lower() in _RST_NAMES:
            continue
        out.append(p)
        if len(out) >= max_points:
            break
    return out


def build_covergroup(
    dut_name: str,
    port_specs: Optional[Sequence[dict]],
    *,
    clk: str = "clk",
    sample_prefix: str = "",
) -> str:
    """Return a module-scope covergroup block, or "" when nothing to cover."""
    ports = _coverable_ports(port_specs)
    if not ports:
        return ""
    dut = re.sub(r"\W", "_", dut_name or "dut")
    prefix = sample_prefix or ""
    lines = [
        "`ifndef VERILATOR",
        "  // Functional coverage (compiled by Questa/VCS/Xcelium; Verilator skips)",
        f"  covergroup cg_{dut} @(posedge {clk});",
        "    option.per_instance = 1;",
    ]
    single_bit_ins: List[str] = []
    for p in ports:
        n = p["name"]
        w = (p.get("width") or "").strip()
        d = (p.get("direction") or "").lower()
        lines.append(f"    cp_{n}: coverpoint {prefix}{n};")
        if not w or w in ("[0:0]",):
            if d in ("input", "in"):
                single_bit_ins.append(n)
    if len(single_bit_ins) >= 2:
        a, b = single_bit_ins[0], single_bit_ins[1]
        lines.append(f"    cx_{a}_{b}: cross cp_{a}, cp_{b};")
    lines.append("  endgroup")
    lines.append(f"  cg_{dut} cov_{dut} = new();")
    lines.append("`endif")
    return "\n".join(lines)


def insert_covergroup(
    sv: str,
    dut_name: str,
    port_specs: Optional[Sequence[dict]],
    *,
    clk: str = "clk",
    sample_prefix: str = "",
) -> str:
    """Insert a covergroup at TB module scope (before the final endmodule)."""
    if not sv or has_covergroup(sv):
        return sv
    block = build_covergroup(dut_name, port_specs, clk=clk, sample_prefix=sample_prefix)
    if not block:
        return sv
    idx = sv.rfind("endmodule")
    if idx < 0:
        return sv
    return sv[:idx] + "\n" + block + "\n\n" + sv[idx:]
