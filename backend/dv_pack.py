"""One-click DV pack: Pure SV or UVM TB + SVA + covergroup + testplan (no LLM)."""
from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dv_planner import classify_dut
from formal_pack import render_sva
from rtl_ports import extract_modules
from tb_methodology import normalize_methodology
from tb_skeleton import render_class_sv_tb
from tb_uvm_skeleton import render_uvm_smoke_tb


def _dut(modules: List[dict]) -> dict:
    return modules[0] if modules else {"name": "dut", "ports": []}


def render_covergroup(mod: dict, protocol: str) -> str:
    name = mod.get("name") or "dut"
    ports = mod.get("ports") or []
    bins = []
    for p in ports:
        n = p.get("name") or ""
        if not n or n.lower() in ("clk", "clock", "rst", "rst_n", "reset", "aresetn"):
            continue
        bins.append(f"    cp_{n}: coverpoint {n};")
    if not bins:
        bins.append("    smoke: coverpoint 1'b1 { bins ok = {1}; }")
    body = "\n".join(bins[:16])
    return f"""// ChipSutra covergroup pack — bins from parsed ports ({protocol}).
// Instantiate in the TB and sample after reset. Not a sign-off coverage model.
covergroup {name}_cg;
{body}
endgroup
"""


def render_testplan(mod: dict, protocol: str, methodology: str) -> str:
    name = mod.get("name") or "dut"
    ports = ", ".join(p.get("name") or "?" for p in (mod.get("ports") or [])[:16])
    meth = "UVM source (licensed sim)" if methodology == "uvm" else "Pure SV (Verilator)"
    return f"""# ChipSutra testplan — {name}

- Protocol pack: `{protocol}`
- Methodology: {meth}
- Ports: {ports}
- Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d")}

## Must-run

1. Reset: outputs known after deassert (no X on checked outs).
2. Stimulus: random legal inputs for at least 16 cycles / beats.
3. Checker: protocol golden or no-X smoke (review if protocol is generic).
4. Coverage: sample covergroup `{name}_cg` after reset.
5. Formal (optional): bind `{name}_sva` and run the `.sby` from Formal pack.

## Out of scope (Community)

- UVM compile/run inside ChipSutra Simulate
- Vendor VIP for AXI4 burst / PCIe / CHI / CXL
"""


def build_dv_pack(
    rtl_text: str,
    *,
    methodology: str = "sv",
    cycles: int = 16,
) -> Dict[str, Any]:
    modules = extract_modules(rtl_text or "")
    mod = _dut(modules)
    cls = classify_dut(modules, rtl_text=rtl_text or "")
    proto = cls.get("protocol") or "generic"
    meth = normalize_methodology(methodology)
    if meth == "uvm":
        tb = render_uvm_smoke_tb(mod, cycles=min(cycles, 12))
        tb_name = f"{mod.get('name') or 'dut'}_uvm_tb.sv"
    else:
        tb = render_class_sv_tb(mod, cycles=cycles, seed=1)
        tb_name = f"{mod.get('name') or 'dut'}_tb.sv"
    ir = {
        "clocks": [p["name"] for p in (mod.get("ports") or []) if (p.get("name") or "").lower() in ("clk", "clock", "aclk", "pclk")],
        "resets": [p["name"] for p in (mod.get("ports") or []) if any(x in (p.get("name") or "").lower() for x in ("rst", "reset"))],
        "ports": mod.get("ports") or [],
        "requirements": [],
    }
    sva = render_sva(ir, dut=mod.get("name") or "dut")
    cg = render_covergroup(mod, proto)
    plan = render_testplan(mod, proto, meth)
    files = {
        tb_name: tb,
        f"{mod.get('name') or 'dut'}_sva.sv": sva,
        f"{mod.get('name') or 'dut'}_cg.sv": cg,
        "TESTPLAN.md": plan,
        "README.txt": (
            "ChipSutra DV pack (skeleton, no LLM).\n"
            f"Protocol: {proto}\n"
            f"Methodology: {meth}\n"
            "Review before sign-off. Pure SV TBs run in ChipSutra Simulate; "
            "UVM TBs need the vendor export pack.\n"
        ),
    }
    return {
        "dut": mod.get("name") or "dut",
        "protocol": proto,
        "methodology": meth,
        "files": files,
        "notes": cls.get("tags") or [],
    }


def dv_pack_zip(pack: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in (pack.get("files") or {}).items():
            zf.writestr(str(name).replace("\\", "/"), body or "")
    return buf.getvalue()
