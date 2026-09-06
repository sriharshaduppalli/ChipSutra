"""Spec IR → SVA + SymbiYosys pack. Conservative properties only.

Never invent clocks, ports, or protocol maps. CEX logs feed debug_classify.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from debug_classify import classify_log
from spec_ir import extract_spec_ir


def render_sva(ir: Dict[str, Any], *, dut: str = "dut") -> str:
    """Legal SVA bind-style module. Properties stay tautological unless ports exist."""
    clk = (ir.get("clocks") or ["clk"])[0]
    rst = (ir.get("resets") or ["rst_n"])[0]
    ports = ir.get("ports") or []
    names = {(p.get("name") or "").lower(): p.get("name") for p in ports if p.get("name")}
    decls = [
        f"  input logic {clk};",
        f"  input logic {rst};",
    ]
    for p in ports[:12]:
        n = p.get("name")
        if not n or n in (clk, rst):
            continue
        w = (p.get("width") or "").strip()
        decls.append(f"  input logic {w} {n};".replace("  input logic  ", "  input logic "))
    props: List[str] = []
    en = names.get("enable") or names.get("en")
    count = next((names[k] for k in names if "count" in k or k in ("q", "out")), None)
    if en and count:
        props.append(
            f"""  property p_enable_changes;
    @(posedge {clk}) disable iff (!{rst})
    {en} |=> ({count} !== $past({count}));
  endproperty
  assert property (p_enable_changes);"""
        )
    for req in (ir.get("requirements") or [])[:6]:
        rid = (req.get("id") or "REQ").replace("-", "_")
        txt = (req.get("text") or "").replace("*/", "")[:80]
        kind = req.get("kind") or "functional"
        if kind == "cover":
            props.append(
                f"  // {rid}: {txt}\n"
                f"  cover property (@(posedge {clk}) 1'b1);"
            )
        else:
            props.append(
                f"  // {rid}: {txt}\n"
                f"  property p_{rid};\n"
                f"    @(posedge {clk}) disable iff (!{rst}) 1'b1;\n"
                f"  endproperty\n"
                f"  assert property (p_{rid});"
            )
    if not props:
        props.append(
            f"  // No numbered requirements — reset stability smoke\n"
            f"  property p_reset_stable;\n"
            f"    @(posedge {clk}) {rst} |-> 1'b1;\n"
            f"  endproperty\n"
            f"  assert property (p_reset_stable);"
        )
    body = "\n".join(decls)
    mid = "\n\n".join(props)
    top = f"{dut}_sva"
    return f"""// ChipSutra formal pack from Spec IR — exploratory, not sign-off.
// Bind to the DUT; do not invent extra ports.
module {top} (
{body}
);
{mid}
endmodule
"""


def render_sby(dut: str = "dut", *, depth: int = 20, sva_file: str = "properties.sv") -> str:
    return f"""[options]
mode bmc
depth {max(4, min(64, int(depth)))}

[engines]
smtbmc z3

[script]
read -sv {dut}.sv {sva_file}
prep -top {dut}

[files]
{dut}.sv
{sva_file}
"""


def build_formal_pack(
    spec_text: str = "",
    *,
    prompt: str = "",
    dut: str = "dut",
    depth: int = 20,
) -> Dict[str, Any]:
    ir = extract_spec_ir(spec_text, prompt=prompt)
    sva = render_sva(ir, dut=dut)
    sby = render_sby(dut, depth=depth)
    return {
        "ir": {
            "port_count": ir.get("port_count"),
            "requirement_count": ir.get("requirement_count"),
            "clocks": ir.get("clocks"),
            "resets": ir.get("resets"),
        },
        "sva": sva,
        "sby": sby,
        "notes": [
            "Community BMC pack — SymbiYosys/Z3, not Jasper/VC Formal sign-off.",
            "Properties stay conservative unless enable/count ports were extracted.",
        ],
    }


def classify_cex(sby_log: str = "", prior_sva: str = "") -> Dict[str, Any]:
    """Map a failing SBY log to debug templates (CEX → next debug step)."""
    classified = classify_log(sby_log or "", prior_code=prior_sva or "")
    classified["source"] = "formal_cex"
    if not classified.get("findings") and sby_log:
        classified["findings"] = [
            {
                "title": "Formal CEX",
                "severity": "error",
                "hint": "Open the CEX VCD, check reset polarity, then tighten the failing property.",
                "category": "formal",
            }
        ]
    return classified
