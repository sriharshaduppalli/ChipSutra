"""Design analysis — understand the DUT before choosing TB shape / protocol pack.

Runs before LLM generate so ChipSutra can explain *what* TB is needed and inject
protocol-version guidance (APB3 vs APB4, AXI4-Lite vs AXI4, …).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from dv_planner import classify_dut
from rtl_ir import extract_rtl_ir, ir_brief_lines
from tb_methodology import normalize_methodology
from tb_skeleton import classify_ports

_KNOW = Path(__file__).resolve().parent / "knowledge"
_GUIDANCE = _KNOW / "protocol_tb_guidance.txt"

_CLK = frozenset({"clk", "clock", "aclk", "pclk", "sclk", "hclk", "clk_i"})
_RST = frozenset(
    {"rst_n", "rst", "reset", "reset_n", "aresetn", "presetn", "hresetn", "rstn"}
)
_ADDR_PORTS = frozenset(
    {
        "paddr",
        "awaddr",
        "araddr",
        "haddr",
        "addr",
        "address",
        "s_axi_awaddr",
        "s_axi_araddr",
    }
)
_BUS_PROTOCOLS = frozenset(
    {"axi_lite", "axi4_lite", "axi4", "apb", "ahb", "axis", "stream"}
)

# Map analysis protocol/variant → VIP knowledge file
_VIP_FILES: dict[str, str] = {
    "axi_lite": "protocol_vip_axi_lite.txt",
    "axi4_lite": "protocol_vip_axi_lite.txt",
    "axi4": "protocol_vip_axi_full.txt",
    "axi4_burst": "protocol_vip_axi_full.txt",
    "ace": "protocol_vip_axi_full.txt",
    "chi": "protocol_vip_axi_full.txt",
    "apb": "protocol_vip_apb.txt",
    "apb3": "protocol_vip_apb.txt",
    "apb4": "protocol_vip_apb.txt",
    "ahb": "protocol_vip_ahb.txt",
    "ahb_lite": "protocol_vip_ahb.txt",
    "ahb5": "protocol_vip_ahb.txt",
    "axis": "protocol_vip_axis.txt",
    "axi4_stream": "protocol_vip_axis.txt",
    "stream": "protocol_vip_axis.txt",
    "spi": "protocol_vip_serial.txt",
    "spi_mode0": "protocol_vip_serial.txt",
    "spi_mode1": "protocol_vip_serial.txt",
    "spi_mode2": "protocol_vip_serial.txt",
    "spi_mode3": "protocol_vip_serial.txt",
    "qspi": "protocol_vip_serial.txt",
    "i2c": "protocol_vip_serial.txt",
    "i2c_7bit": "protocol_vip_serial.txt",
    "i2c_10bit": "protocol_vip_serial.txt",
    "i2c_master": "protocol_vip_serial.txt",
    "uart": "protocol_vip_serial.txt",
    "uart_8n1": "protocol_vip_serial.txt",
    "uart_rx": "protocol_vip_serial.txt",
    "uart_tx": "protocol_vip_serial.txt",
    "can": "protocol_vip_can.txt",
    "canfd": "protocol_vip_can.txt",
    "i3c": "protocol_vip_i3c.txt",
    "processor": "protocol_vip_riscv.txt",
    "ip": "protocol_vip_anatomy.txt",
    "vip": "protocol_vip_anatomy.txt",
    "synopsys_vip": "protocol_vip_commercial.txt",
    "block": "protocol_vip_scale.txt",
    "subsystem": "protocol_vip_scale.txt",
    "soc": "protocol_vip_scale.txt",
    "chiplet": "protocol_vip_scale.txt",
    "pcie": "protocol_vip_offchip.txt",
    "pcie_ep": "protocol_vip_offchip.txt",
    "pcie_rc": "protocol_vip_offchip.txt",
    "cxl": "protocol_vip_offchip.txt",
    "ucie": "protocol_vip_d2d.txt",
    "bow": "protocol_vip_d2d.txt",
    "aib": "protocol_vip_d2d.txt",
    "ddr": "protocol_vip_memory.txt",
    "lpddr": "protocol_vip_memory.txt",
    "hbm": "protocol_vip_memory.txt",
    "dfi": "protocol_vip_memory.txt",
    "sram": "protocol_vip_memory.txt",
    "ethernet": "protocol_vip_netio.txt",
    "usb": "protocol_vip_netio.txt",
    "mipi": "protocol_vip_netio.txt",
    "tilelink": "protocol_vip_onchip.txt",
    "tl_ul": "protocol_vip_onchip.txt",
    "jtag": "protocol_vip_debug.txt",
    "swd": "protocol_vip_debug.txt",
    "dft": "protocol_vip_debug.txt",
    "ral": "protocol_vip_ral.txt",
    "uvm_ral": "protocol_vip_ral.txt",
    "fifo": "protocol_vip_simple.txt",
    "sync_fifo_fwft": "protocol_vip_simple.txt",
    "mux": "protocol_vip_simple.txt",
    "combinational_mux": "protocol_vip_simple.txt",
    "mux4_combinational": "protocol_vip_simple.txt",
    "alu": "protocol_vip_simple.txt",
    "combinational_alu": "protocol_vip_simple.txt",
    "counter": "protocol_vip_simple.txt",
    "enable_counter": "protocol_vip_simple.txt",
    "parity": "protocol_vip_simple.txt",
    "xor_parity": "protocol_vip_simple.txt",
    "switch": "protocol_vip_simple.txt",
    "addr_range_switch": "protocol_vip_simple.txt",
    "riscv": "protocol_vip_riscv.txt",
    "rv32i": "protocol_vip_riscv.txt",
    "rv32i_smoke": "protocol_vip_riscv.txt",
    "wishbone": "protocol_vip_onchip.txt",
    "avalon": "protocol_vip_onchip.txt",
    "avalon_mm": "protocol_vip_onchip.txt",
    "fsm": "protocol_vip_onchip.txt",
    "encoder": "protocol_vip_simple.txt",
    "gray": "protocol_vip_simple.txt",
    "edge": "protocol_vip_simple.txt",
    "cdc": "protocol_vip_simple.txt",
}


def _names(modules: Optional[Sequence[dict]]) -> List[str]:
    out: List[str] = []
    for m in modules or []:
        for p in m.get("ports") or []:
            n = (p.get("name") or "").strip()
            if n:
                out.append(n)
    return out


def detect_protocol_variant(protocol: str, name_set: set, rtl_text: str = "") -> Dict[str, Any]:
    """Version / feature flags on top of coarse protocol pack."""
    proto = (protocol or "generic").lower()
    blob = (rtl_text or "").lower()
    variant = proto
    features: List[str] = []

    if proto in ("axi_lite", "axi4_lite"):
        variant = "axi4_lite"
        features.append("no_burst")
        if "awlen" in name_set or "s_axi_awlen" in name_set:
            variant, features = "axi4", ["burst", "len_size_burst"]
        if "awid" in name_set or "s_axi_awid" in name_set:
            features.append("ids")
    elif proto == "apb":
        variant = "apb3"
        if "pstrb" in name_set or "pprot" in name_set:
            variant = "apb4"
            features.extend([f for f in ("pstrb", "pprot") if f in name_set])
        if "pslverr" in name_set:
            features.append("pslverr")
    elif proto == "ahb":
        variant = "ahb_lite"
        if "hburst" in name_set or "ahb5" in blob:
            variant = "ahb5" if "ahb5" in blob else "ahb_lite"
            features.append("burst")
    elif proto == "axis":
        variant = "axi4_stream"
        for f in ("tlast", "tkeep", "tstrb", "tuser", "tid", "tdest"):
            if f in name_set or f"s_axis_{f}" in name_set:
                features.append(f)
    elif proto == "spi":
        variant = "spi_mode0"  # default assumption; TB must randomize CPOL/CPHA if present
        if "io0" in name_set or "qspi" in blob:
            variant = "qspi"
            features.append("quad")
    elif proto == "i2c":
        variant = "i2c_7bit"
        if "i3c" in blob:
            variant = "i3c"
    elif proto == "i3c":
        variant = "i3c"
        if name_set & {"ccc"}:
            features.append("ccc")
        if name_set & {"ibi", "ibi_req"}:
            features.append("ibi")
    elif proto == "can":
        variant = "canfd" if ("canfd" in blob or "can_fd" in blob or "brs" in name_set) else "can"
    elif proto in ("axi4", "ace", "chi"):
        variant = proto
        features.append("require_user_vip")
    elif proto == "uart":
        variant = "uart_rx" if ({"rx", "rxd"} & name_set and not ({"din", "start", "tx"} <= name_set)) else "uart_8n1"
    elif proto == "fifo":
        variant = "sync_fifo_fwft"
        if "almost_full" in name_set or "afull" in name_set:
            features.append("almost_full")
    elif proto == "mux":
        variant = "combinational_mux"
        if {"d0", "d1", "d2", "d3"} <= name_set:
            variant = "mux4_combinational"
    elif proto == "alu":
        variant = "combinational_alu"
    elif proto == "counter":
        variant = "enable_counter" if "enable" in name_set or "en" in name_set else "counter"
    elif proto == "parity":
        variant = "xor_parity"
    elif proto == "switch":
        variant = "addr_range_switch"
        if "vld" in name_set or "valid" in name_set:
            features.append("vld_pulse")

    return {"protocol_variant": variant, "features": features}


def detect_timing_style(modules: Optional[Sequence[dict]]) -> str:
    """combo | sequential | bus — drives clock/reset expectations in the TB."""
    if not modules:
        return "unknown"
    ports = modules[0].get("ports") or []
    cls = classify_ports(ports)
    names = {(p.get("name") or "").lower() for p in ports}
    busish = bool(
        names
        & {
            "psel",
            "penable",
            "htrans",
            "s_axi_awvalid",
            "s_axis_tvalid",
            "awvalid",
            "tvalid",
        }
    )
    if busish:
        return "bus"
    if cls.get("clk") or (names & _CLK):
        return "sequential"
    return "combo"


def recommend_tb(
    *,
    protocol: str,
    timing_style: str,
    port_count: int,
    tb_methodology: str,
    confidence: float,
) -> Dict[str, Any]:
    """What TB shape to emit given analysis + user methodology choice."""
    meth = normalize_methodology(tb_methodology)
    proto = (protocol or "generic").lower()

    if meth == "uvm":
        shape = "uvm_smoke"
        if proto in ("axi_lite", "apb", "ahb", "axis") or port_count >= 24:
            shape = "uvm_agent_env"
        reason = (
            f"User requested UVM. DUT looks like {proto} ({timing_style}); "
            f"emit {shape} with DUT+IF+config_db+run_test."
        )
        return {
            "methodology": "uvm",
            "tb_shape": shape,
            "needs_clock": timing_style != "combo",
            "needs_reset": timing_style != "combo",
            "reason": reason,
        }

    if meth in ("ovm", "vmm"):
        return {
            "methodology": meth,
            "tb_shape": f"{meth}_compact",
            "needs_clock": timing_style != "combo",
            "needs_reset": timing_style != "combo",
            "reason": f"User requested {meth.upper()}; compact agent/env/top.",
        }

    # Pure SV
    if proto in ("riscv", "rv32i"):
        shape = "procedural_smoke"
    elif timing_style == "combo" and proto in ("mux", "generic", "parity"):
        shape = "class_sv_compact"
    elif proto in ("axi_lite", "apb", "ahb", "axis", "spi", "i2c", "uart", "can", "i3c"):
        shape = "class_sv_layered" if confidence >= 0.7 else "procedural_smoke"
    elif proto in ("axi4", "ace", "chi"):
        shape = "procedural_smoke"
    else:
        shape = "class_sv_layered"
    return {
        "methodology": "sv",
        "tb_shape": shape,
        "needs_clock": timing_style != "combo",
        "needs_reset": timing_style != "combo",
        "reason": (
            f"DUT protocol={proto} timing={timing_style}; "
            f"recommend Pure SV {shape} (Verilator-friendly)."
        ),
    }


def _sections_from_file(path: Path, keys: Sequence[str], *, limit: int = 3) -> List[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    chunks: List[str] = []
    for key in keys:
        if not key:
            continue
        for m in re.finditer(
            rf"(?mi)^##[^\n]*\b{re.escape(key)}\b[^\n]*\n([\s\S]*?)(?=^##|\Z)",
            text,
        ):
            title = text[m.start() : text.find("\n", m.start())]
            body = m.group(1).strip()
            block = f"{title.strip()}\n{body}"
            if body and block not in chunks:
                chunks.append(block)
            if len(chunks) >= limit:
                return chunks
    return chunks


def protocol_guidance_block(protocol: str, variant: str = "") -> str:
    """Pull matching ## sections — VIP file first, then protocol_tb_guidance."""
    keys: List[str] = []
    for k in (variant, protocol, protocol.replace("_", " ")):
        if k and k.lower() not in keys:
            keys.append(k.lower())
    vip_name = ""
    for k in (variant, protocol):
        vip_name = _VIP_FILES.get((k or "").lower(), "")
        if vip_name:
            break
    chunks: List[str] = []
    if vip_name:
        chunks.extend(_sections_from_file(_KNOW / vip_name, keys, limit=3))
        # Also take first non-title ## sections from VIP if key match missed
        if not chunks:
            chunks.extend(_sections_from_file(_KNOW / vip_name, [vip_name.split("_")[-1]], limit=2))
            if not chunks and (_KNOW / vip_name).is_file():
                # whole VIP file truncated
                body = (_KNOW / vip_name).read_text(encoding="utf-8")
                chunks.append(body[:2200])
    if len(chunks) < 2:
        chunks.extend(_sections_from_file(_GUIDANCE, keys, limit=2))
    if not chunks:
        chunks.extend(_sections_from_file(_GUIDANCE, ["generic"], limit=1))
    return "\n\n".join(chunks[:3])


def detect_csr_stance(
    name_set: set,
    rtl_text: str = "",
    protocol: str = "",
) -> Dict[str, Any]:
    """Whether RAL / invented CSR maps are allowed."""
    proto = (protocol or "").lower()
    has_addr = bool(name_set & _ADDR_PORTS)
    # Heuristic: named localparam addresses or hex literals in a regs module
    has_map = bool(
        re.search(
            r"\blocalparam\b[^;]*\bADDR\b|\b12'h[0-9a-fA-F]+\b|\b16'h[0-9a-fA-F]+\b",
            rtl_text or "",
            re.I,
        )
    )
    if proto in _BUS_PROTOCOLS or has_addr:
        if has_map:
            return {
                "ral_allowed": False,  # still no auto-RAL; map present but user-owned
                "has_address_ports": has_addr,
                "has_map_hints": True,
                "stance": (
                    "Address ports present with RTL map hints — use opaque model_reg[] "
                    "keyed by observed addresses. Do NOT invent a full RAL block or "
                    "undocumented CSR names."
                ),
            }
        return {
            "ral_allowed": False,
            "has_address_ports": has_addr,
            "has_map_hints": False,
            "stance": (
                "NO RAL / no invented CSR map — front-door random/directed smoke only; "
                "keep an opaque model_reg[] updated from observed writes."
            ),
        }
    return {
        "ral_allowed": False,
        "has_address_ports": False,
        "has_map_hints": False,
        "stance": "Non-CSR DUT — no RAL; independent functional golden only.",
    }


def analyze_design(
    modules: Optional[List[dict]] = None,
    *,
    rtl_text: str = "",
    tb_methodology: str = "sv",
    prompt: str = "",
    user_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full pre-generate design analysis."""
    dut = classify_dut(modules, rtl_text=rtl_text, user_config=user_config)
    name_set = {n.lower() for n in _names(modules)}
    variant_info = detect_protocol_variant(dut["protocol"], name_set, rtl_text)
    knobs = (user_config or {}).get("protocol_knobs") or {}
    if knobs.get("spi_mode") is not None and dut["protocol"] == "spi":
        variant_info["protocol_variant"] = f"spi_mode{int(knobs['spi_mode']) & 3}"
        variant_info["features"] = list(variant_info.get("features") or []) + [f"spi_mode{int(knobs['spi_mode']) & 3}"]
    if knobs.get("i2c_role") == "master" and dut["protocol"] == "i2c":
        variant_info["protocol_variant"] = "i2c_master"
    if knobs.get("i2c_addr_bits") == 10 and dut["protocol"] in ("i2c", "i3c"):
        variant_info["protocol_variant"] = "i2c_10bit"
    if knobs.get("uart_dir") == "rx" and dut["protocol"] == "uart":
        variant_info["protocol_variant"] = "uart_rx"
    if knobs.get("can_variant") and dut["protocol"] == "can":
        variant_info["protocol_variant"] = str(knobs["can_variant"])
    if knobs.get("axi_variant") == "burst":
        variant_info["protocol_variant"] = "axi4_burst"
        variant_info["features"] = list(variant_info.get("features") or []) + ["require_user_vip"]
    timing = detect_timing_style(modules)
    ports = (modules[0].get("ports") if modules else None) or []
    cls = classify_ports(list(ports)) if ports else {}
    rec = recommend_tb(
        protocol=dut["protocol"],
        timing_style=timing,
        port_count=int(dut.get("port_count") or 0),
        tb_methodology=tb_methodology,
        confidence=float(dut.get("confidence") or 0),
    )
    # If user said "uvm" in prompt but methodology auto — already handled by normalize
    guidance = protocol_guidance_block(
        dut["protocol"], variant_info.get("protocol_variant") or ""
    )
    csr = detect_csr_stance(name_set, rtl_text, dut["protocol"])
    if user_config and (user_config.get("csr_list") or user_config.get("memory_map")):
        ral_on = bool(user_config.get("enable_ral") and user_config.get("csr_list"))
        csr = {
            **csr,
            "ral_allowed": ral_on,
            "has_map_hints": True,
            "user_map": True,
            "stance": (
                "User CSR map — emit named reg_model / uvm_reg_block for ONLY these "
                "registers. Do not invent extra CSRs or offsets."
                if ral_on
                else (
                    "User supplied memory_map/csr_list — opaque model_reg keyed by those "
                    "addresses only. RAL off. Do not invent extra CSRs or regions."
                )
            ),
        }
    ir = extract_rtl_ir(rtl_text or "", modules)

    inputs = [p.get("name") for p in (cls.get("inputs") or []) if p.get("name")]
    outputs = [p.get("name") for p in (cls.get("outputs") or []) if p.get("name")]
    clk = (cls.get("clk") or {}).get("name") if cls.get("clk") else None
    rst = (cls.get("rst") or {}).get("name") if cls.get("rst") else None

    confidence = float(dut.get("confidence") or 0)
    proto = (dut.get("protocol") or "generic").lower()
    # Supported tiers for honest product messaging (not a quality score)
    supported = {
        "counter", "fifo", "parity", "mux", "alu", "switch",
        "axi_lite", "axi4_lite", "apb", "apb3", "apb4",
    }
    if proto in supported and confidence >= 0.55:
        support_tier = "supported"
        support_note = (
            f"Protocol `{proto}` is on ChipSutra's supported list — "
            "emit compact Verilator-friendly smoke/class TB."
        )
    elif proto in (
        "ahb", "axis", "spi", "i2c", "uart", "stream", "riscv", "rv32i",
        "can", "i3c", "wishbone", "avalon",
    ) and confidence >= 0.5:
        support_tier = "experimental"
        support_note = (
            f"Protocol `{proto}` is experimental — prefer short smoke TB; "
            "do NOT invent full VIP/RAL or undocumented CSR maps."
        )
    elif proto in ("axi4", "ace", "chi") and confidence >= 0.5:
        support_tier = "experimental"
        support_note = (
            f"Protocol `{proto}` requires user VIP/BFM — outline only; "
            "do not invent burst/snoop/CHI timings."
        )
    else:
        support_tier = "best_effort"
        support_note = (
            "DUT protocol is generic/low-confidence — emit procedural smoke only "
            "(clock/reset if present, drive inputs, check outputs vs simple golden). "
            "Do NOT invent bus agents, RAL, or undocumented ports. "
            "State assumptions in // comments."
        )
        if confidence < 0.55 or proto == "generic":
            rec = {
                **rec,
                "tb_shape": "procedural_smoke",
                "reason": (
                    f"Low-confidence/generic DUT (protocol={proto}, "
                    f"confidence={confidence:.2f}); procedural smoke only."
                ),
            }

    brief_lines = [
        f"DUT module: {dut.get('module_name') or '(unknown)'}",
        f"Protocol pack: {dut['protocol']} (confidence {dut['confidence']:.2f})",
        f"Protocol variant: {variant_info.get('protocol_variant')}",
        f"Timing style: {timing}",
        f"Clocks: {clk or '(none - combinational)'} | Resets: {rst or '(none)'}",
        f"Stimulus inputs: {', '.join(inputs[:16]) or '(none)'}",
        f"Checked outputs: {', '.join(outputs[:16]) or '(none)'}",
        f"Recommended methodology: {rec['methodology']} | TB shape: {rec['tb_shape']}",
        f"Why: {rec['reason']}",
        f"CSR/RAL: {csr['stance']}",
        f"Support tier: {support_tier} — {support_note}",
    ]
    if variant_info.get("features"):
        brief_lines.append("Features: " + ", ".join(variant_info["features"]))
    if user_config:
        scale = user_config.get("scale") or "block"
        if scale == "ip":
            brief_lines.append(
                "User scale: ip — Verification IP (driver, monitor, checker, coverage); "
                "RAL only from user map; one DUT."
            )
        elif scale != "block":
            brief_lines.append(f"User scale: {scale} — orchestrate from topology; do not invent maps.")
        if knobs:
            brief_lines.append(
                "User knobs: "
                + ", ".join(f"{k}={v}" for k, v in knobs.items() if v not in (None, "", []))
            )
    brief_lines.extend(ir_brief_lines(ir))
    if timing == "combo":
        brief_lines.append(
            "COMBO RULE: do NOT connect invented clk/rst pins onto the DUT; "
            "TB may keep a local clock for pacing only."
        )

    if user_config and (user_config.get("scale") or "block") != "block":
        scale_g = protocol_guidance_block(user_config.get("scale") or "subsystem", user_config.get("scale") or "")
        if scale_g:
            guidance = (guidance + "\n\n" + scale_g).strip() if guidance else scale_g

    analysis = {
        "version": "1.4.0",
        "dut": dut,
        "user_config": {
            "scale": (user_config or {}).get("scale") or "block",
            "knobs": knobs,
            "has_memory_map": bool(user_config and user_config.get("memory_map")),
            "has_csr_list": bool(user_config and user_config.get("csr_list")),
            "has_topology": bool(user_config and (user_config.get("topology") or {}).get("agents")),
        },
        "rtl_ir": ir,
        "protocol": dut["protocol"],
        "protocol_variant": variant_info.get("protocol_variant"),
        "features": variant_info.get("features") or [],
        "timing_style": timing,
        "clock": clk,
        "reset": rst,
        "active_low_reset": bool(cls.get("active_low_reset", True)),
        "inputs": inputs,
        "outputs": outputs,
        "recommendation": rec,
        "csr": csr,
        "support_tier": support_tier,
        "support_note": support_note,
        "protocol_guidance": guidance,
        "brief": "\n".join(brief_lines),
        "prompt_block": "",  # filled by build_tb_context_pack
    }
    analysis["prompt_block"] = build_tb_context_pack(analysis)
    return analysis


def build_tb_context_pack(
    analysis: Dict[str, Any],
    *,
    max_chars: int = 4200,
    vip_chars: int = 2200,
) -> str:
    """Tight LLM context: short analysis + CSR stance + one VIP slice (budgeted)."""
    rec = analysis.get("recommendation") or {}
    csr = analysis.get("csr") or {}
    parts = [
        "DESIGN ANALYSIS (follow before coding):",
        analysis.get("brief")
        or f"protocol={analysis.get('protocol')} variant={analysis.get('protocol_variant')}",
        f"Emit TB shape `{rec.get('tb_shape')}` with methodology `{rec.get('methodology')}`.",
    ]
    if analysis.get("support_tier"):
        parts.append(
            f"SUPPORT TIER: {analysis.get('support_tier')} — "
            f"{analysis.get('support_note') or ''}"
        )
    if csr.get("stance"):
        parts.append("CSR/RAL STANCE: " + str(csr["stance"]))
    guidance = (analysis.get("protocol_guidance") or "").strip()
    if (analysis.get("support_tier") or "") == "best_effort":
        # Keep VIP slice tiny for unknown RTL — avoid wrong-protocol hallucination
        vip_chars = min(vip_chars, 800)
        guidance = (
            "GENERIC / UNKNOWN DUT RULES:\n"
            "- Instantiate DUT with exact port names/widths from the analysis.\n"
            "- If combinational: no invented DUT clk/rst pins.\n"
            "- Drive every input; check outputs with an independent golden or "
            "simple directed vectors.\n"
            "- No UVM agents, no RAL, no invented CSR address map.\n"
        ) + (guidance[:400] if guidance else "")
    if not guidance:
        guidance = protocol_guidance_block(
            analysis.get("protocol") or "generic",
            analysis.get("protocol_variant") or "",
        )
    if guidance:
        parts.append("PROTOCOL VIP / VERSION (primary emit rules):")
        parts.append(guidance[:vip_chars])
    text = "\n".join(parts)
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n"
    return text


def analysis_to_learning(analysis: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "protocol": analysis.get("protocol"),
        "protocol_variant": analysis.get("protocol_variant"),
        "timing_style": analysis.get("timing_style"),
        "tb_shape": (analysis.get("recommendation") or {}).get("tb_shape"),
        "methodology": (analysis.get("recommendation") or {}).get("methodology"),
        "confidence": (analysis.get("dut") or {}).get("confidence"),
        "ral_allowed": (analysis.get("csr") or {}).get("ral_allowed"),
        "has_map_hints": (analysis.get("csr") or {}).get("has_map_hints"),
        "support_tier": analysis.get("support_tier"),
        "looks_riscv": bool((analysis.get("rtl_ir") or {}).get("looks_riscv")),
        "rtl_parser": (analysis.get("rtl_ir") or {}).get("parser"),
        "module_count": (analysis.get("rtl_ir") or {}).get("module_count"),
        "cdc_hint": bool((analysis.get("rtl_ir") or {}).get("cdc_hint")),
    }
