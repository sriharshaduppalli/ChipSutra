"""DV Planner — route generation intent and DUT class for ChipSutra.

Phase-1 spine of the advanced architecture (see docs/ADVANCED_DV_ARCHITECTURE.md):
classify which engine (skeleton / llm / hybrid) and which protocol pack to prefer.
Does not replace lint gates; it decides strategy before generate.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from rtl_ir import looks_riscv
from tb_methodology import (
    normalize_methodology,
    is_class_methodology,
    intent_from_methodology,
    plan_note_for_methodology,
)

_UVM_RE = re.compile(
    r"\b(uvm|u?vm_|agent|sequencer|driver|monitor|scoreboard|sequence_item|"
    r"full\s+uvm|class\s+\w+_env)\b",
    re.I,
)
_FIFO_PORTS = {"wr_en", "rd_en", "full", "empty"} | {"wr_data", "rd_data"}
_AXI_PORTS = {"s_axi_awvalid", "s_axi_arvalid", "s_axi_wvalid"}
_APB_IN = {"psel", "penable", "pwrite", "paddr", "pwdata"}
_APB_OUT = {"pready", "prdata"}
_AHB_PORTS = {"haddr", "htrans", "hwrite", "hwdata", "hrdata", "hready"}
_AXIS_PORTS = {"s_axis_tvalid", "s_axis_tready", "s_axis_tdata"}
_SPI_PORTS = {"sclk", "mosi", "miso"} | {"cs_n", "css"}
_I2C_PORTS = {"scl", "sda_in", "sda_out"}
_UART_PORTS = {"tx", "din", "start", "busy"}
_STREAM_READY = {"ready", "tready", "in_ready", "s_ready", "s_axis_tready"}
_STREAM_VALID = {"valid", "tvalid", "in_valid", "s_valid", "s_axis_tvalid"}


def _port_names(modules: Optional[List[dict]]) -> List[str]:
    if not modules:
        return []
    names: List[str] = []
    for m in modules:
        for p in m.get("ports") or []:
            n = (p.get("name") or "").strip()
            if n:
                names.append(n)
    return names


def classify_dut(
    modules: Optional[List[dict]] = None,
    *,
    rtl_text: str = "",
    user_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Tag DUT class from parsed ports (+ light text hints).

    Order aligned with ``tb_skeleton`` protocol packs so planner and Fast-random agree.
    """
    names = [n.lower() for n in _port_names(modules)]
    name_set = set(names)
    blob = (rtl_text or "").lower()
    tags: List[str] = []
    protocol = "generic"
    confidence = 0.35

    if _FIFO_PORTS.issubset(name_set) or ({"wr_en", "rd_en", "full", "empty"} <= name_set):
        protocol, confidence, tags = "fifo", 0.92, ["queue_scoreboard", "sync_fifo"]
    elif name_set & {"acvalid", "crvalid", "cdvalid"} or re.search(r"\bace(?:-lite)?\b", blob):
        protocol, confidence, tags = "ace", 0.8, ["ace", "require_user_vip"]
    elif name_set & {"chi_flit", "txnid"} or re.search(r"\bamba\s+chi\b|\bchi\s+flit\b", blob):
        protocol, confidence, tags = "chi", 0.75, ["chi", "require_user_vip"]
    elif _AXI_PORTS.issubset(name_set) or "s_axi_awvalid" in name_set or "awvalid" in name_set:
        if name_set & {"awlen", "s_axi_awlen", "arlen", "s_axi_arlen"}:
            protocol, confidence, tags = "axi4", 0.88, ["axi4_burst", "require_user_vip"]
        else:
            protocol, confidence, tags = "axi_lite", 0.9, ["axi4_lite", "reg_model"]
    elif _APB_IN.issubset(name_set) and _APB_OUT.issubset(name_set):
        protocol, confidence, tags = "apb", 0.88, ["apb_scoreboard"]
    elif _AHB_PORTS.issubset(name_set) or {"haddr", "htrans", "hrdata"} <= name_set:
        protocol, confidence, tags = "ahb", 0.88, ["ahb_lite"]
    elif _AXIS_PORTS.issubset(name_set) or {"s_axis_tvalid", "s_axis_tdata"} <= name_set:
        protocol, confidence, tags = "axis", 0.88, ["axi_stream"]
    elif {"can_rx", "can_tx"} <= name_set or {"canrx", "cantx"} <= name_set:
        protocol, confidence, tags = "can", 0.84, ["can_idle_smoke"]
        if "canfd" in blob or "can_fd" in blob or "brs" in name_set:
            tags = ["canfd", "can_idle_smoke"]
    elif name_set & {"ibi", "ccc", "ibi_req"} or "i3c" in blob:
        protocol, confidence, tags = "i3c", 0.8, ["i3c", "i2c_compatible"]
    elif {"sclk", "mosi", "miso"} <= name_set and (name_set & {"cs_n", "css", "ss_n"}):
        protocol, confidence, tags = "spi", 0.86, ["spi_slave"]
    elif {"scl", "sda_in"} <= name_set or {"scl", "sda"} <= name_set:
        protocol, confidence, tags = "i2c", 0.8, ["i2c_slave"]
    elif {"tx", "din", "start"} <= name_set or {"tx", "busy", "done"} <= name_set:
        protocol, confidence, tags = "uart", 0.82, ["uart_tx"]
    elif {"rx", "rx_valid"} <= name_set or {"rxd", "rx_data"} <= name_set or {"rx", "dout"} <= name_set:
        protocol, confidence, tags = "uart", 0.8, ["uart_rx"]
    elif {"cyc", "stb"} <= name_set and "ack" in name_set:
        protocol, confidence, tags = "wishbone", 0.86, ["wb_classic"]
    elif "waitrequest" in name_set or (
        {"address", "writedata", "readdata"} <= name_set
    ):
        protocol, confidence, tags = "avalon", 0.84, ["avalon_mm"]
    elif name_set & {"a_opcode", "d_opcode", "tl_a_valid", "tl_d_valid"} or re.search(
        r"\btilelink\b|\btl-ul\b|\btl_ul\b", blob
    ):
        protocol, confidence, tags = "tilelink", 0.8, ["tl_ul"]
    elif name_set & {"ltssm", "tlp_valid", "cfg_tlp"} or re.search(
        r"\bpcie\b|\bcfg_tlp\b", blob
    ):
        protocol, confidence, tags = "pcie", 0.78, ["pcie", "require_user_vip"]
    elif re.search(r"\bcxl\.(io|cache|mem)\b|\bcxl_", blob):
        protocol, confidence, tags = "cxl", 0.75, ["cxl", "require_user_vip"]
    elif name_set & {"ucie_mb", "rdi_valid", "fdi_valid"} or re.search(
        r"\bucie\b|\bbow\b|\baib\b", blob
    ):
        protocol, confidence, tags = "ucie", 0.75, ["ucie", "require_user_vip"]
    elif name_set & {"dfi_cke", "dfi_cs_n", "ddr_ck", "ddr_dq"} or re.search(
        r"\bdfi_\w|\bddr[345]\b|\blpddr\b|\bhbm\b", blob
    ):
        protocol, confidence, tags = "ddr", 0.76, ["ddr", "require_user_vip"]
    elif name_set & {"rgmii_txd", "gmii_txd"} or {"mdio", "mdc"} <= name_set or re.search(
        r"\brgmii\b|\bgmii\b", blob
    ):
        protocol, confidence, tags = "ethernet", 0.78, ["ethernet"]
    elif name_set & {"utmi_data", "ulpi_data", "usb_dp"} or re.search(
        r"\butmi\b|\bulpi\b|\busb[23]\b", blob
    ):
        protocol, confidence, tags = "usb", 0.76, ["usb", "require_user_vip"]
    elif name_set & {"dphy_hs", "csi_d0", "dsi_d0"} or re.search(
        r"\bmipi\b|\bcsi-2\b|\bcsi2\b|\bd-phy\b", blob
    ):
        protocol, confidence, tags = "mipi", 0.75, ["mipi", "require_user_vip"]
    elif {"tck", "tms", "tdi", "tdo"} <= name_set:
        protocol, confidence, tags = "jtag", 0.84, ["jtag"]
    elif {"req", "grant"} <= name_set:
        protocol, confidence, tags = "encoder", 0.8, ["prio_enc"]
    elif {"gray", "bin"} <= name_set:
        protocol, confidence, tags = "gray", 0.82, ["gray_code"]
    elif {"rise", "fall"} <= name_set:
        protocol, confidence, tags = "edge", 0.8, ["edge_detect"]
    elif (name_set & {"duty", "compare", "threshold"}) and ("pwm" in name_set):
        protocol, confidence, tags = "pwm", 0.86, ["pwm_compare"]
    elif (name_set & {"noisy", "raw", "bounce"}) and (name_set & {"clean", "debounced"}):
        protocol, confidence, tags = "debounce", 0.84, ["debounce_settle"]
    elif (name_set & {"din", "data"}) and (name_set & {"shamt", "shift", "amt"}) and (
        name_set & {"dout", "out", "q"}
    ):
        protocol, confidence, tags = "shifter", 0.84, ["logical_shift"]
    elif "state" in name_set and not (name_set & {"sel", "op", "opcode"}):
        protocol, confidence, tags = "fsm", 0.72, ["onehot_safety"]
    elif {"async_in", "sync_out"} <= name_set or {"d_async", "q_sync"} <= name_set:
        protocol, confidence, tags = "cdc", 0.8, ["sync_ff"]
    elif (
        (name_set & {"d", "din", "async_in"})
        and (name_set & {"q", "dout", "sync_out"})
        and not (name_set & {"enable", "en", "duty", "pwm", "sel", "op", "opcode"})
        and len(name_set - {"clk", "clock", "rst", "reset", "rst_n", "aresetn"}) <= 3
    ):
        protocol, confidence, tags = "cdc", 0.78, ["sync_ff"]
    elif looks_riscv(name_set, rtl_text):
        protocol, confidence, tags = "riscv", 0.82, ["rv32i_smoke"]
    elif "parity" in name_set and ("valid" in name_set or "data" in name_set):
        protocol, confidence, tags = "parity", 0.85, ["xor_parity"]
    elif (
        {"addr", "data"} <= name_set
        and {"addr_a", "data_a"} <= name_set
        and {"addr_b", "data_b"} <= name_set
    ):
        protocol, confidence, tags = "switch", 0.88, ["addr_range_switch"]
    elif (
        (name_set & {"sel", "select", "s"})
        and (name_set & {"a", "in0", "i0", "din0", "d0"})
        and (name_set & {"b", "in1", "i1", "din1", "d1"})
        and (name_set & {"y", "out", "dout", "z"})
    ):
        protocol, confidence, tags = "mux", 0.86, ["mux2_golden"]
        if {"d0", "d1", "d2", "d3"} <= name_set:
            tags = ["mux4_golden"]
    elif {"d0", "d1", "d2", "d3"} <= name_set and (name_set & {"sel", "select"}) and (
        name_set & {"y", "out", "dout"}
    ):
        protocol, confidence, tags = "mux", 0.88, ["mux4_golden"]
    elif (
        (name_set & {"sel", "select"})
        and (name_set & {"data", "din", "in_bus"})
        and (name_set & {"y", "out", "dout"})
    ):
        protocol, confidence, tags = "mux", 0.8, ["mux_packed"]
    elif (
        (name_set & {"op", "opcode", "alu_op"})
        and (name_set & {"a", "op_a", "operand_a"})
        and (name_set & {"b", "op_b", "operand_b"})
        and (name_set & {"y", "out", "result", "alu_out"})
    ):
        protocol, confidence, tags = "alu", 0.84, ["alu_ops"]
    elif (name_set & _STREAM_VALID) and (name_set & _STREAM_READY) and (
        name_set & {"data", "tdata", "in_data", "s_data", "s_axis_tdata"}
    ):
        protocol, confidence, tags = "stream", 0.8, ["valid_ready"]
    elif name_set & {"enable", "en", "ce"} and name_set & {"count", "cnt", "q"}:
        protocol, confidence, tags = "counter", 0.88, ["enable_counter"]
    elif name_set & {"count", "cnt", "q"} and not (
        name_set - {"clk", "clock", "rst", "reset", "rst_n", "aresetn"} - {"count", "cnt", "q"}
    ):
        protocol, confidence, tags = "counter", 0.75, ["free_running_counter"]
    elif "apb" in blob or {"psel", "penable", "pready"} <= name_set:
        protocol, confidence, tags = "apb", 0.7, ["apb"]
    elif "uart" in blob or {"rx", "tx", "baud"} <= name_set:
        protocol, confidence, tags = "uart", 0.55, ["serial"]

    knobs = (user_config or {}).get("protocol_knobs") or {}
    if knobs.get("can_variant") in ("can", "canfd") and protocol == "generic":
        protocol, confidence, tags = "can", 0.7, [str(knobs["can_variant"])]
    if knobs.get("uart_dir") == "rx" and protocol == "uart":
        tags = list(dict.fromkeys(list(tags) + ["uart_rx"]))
    if knobs.get("i2c_role") == "master" and protocol == "i2c":
        tags = list(dict.fromkeys(list(tags) + ["i2c_master"]))
    if knobs.get("spi_mode") is not None and protocol == "spi":
        tags = list(dict.fromkeys(list(tags) + [f"spi_mode{int(knobs['spi_mode']) & 3}"]))
    if knobs.get("axi_variant") == "burst" and protocol == "axi_lite":
        protocol, confidence, tags = "axi4", 0.85, ["axi4_burst", "require_user_vip"]
    scale = (user_config or {}).get("scale") or "block"
    if scale in ("subsystem", "soc", "chiplet"):
        tags = list(dict.fromkeys(list(tags) + [scale, "require_user_vip"]))
    elif scale == "ip":
        tags = list(dict.fromkeys(list(tags) + ["ip", "reusable_agent"]))
    elif scale == "processor":
        tags = list(dict.fromkeys(list(tags) + ["processor"]))

    clocks = [n for n in names if n in ("clk", "clock", "aclk", "pclk", "sclk", "hclk")]
    resets = [n for n in names if any(x in n for x in ("rst", "reset", "areset"))]
    mod_list = modules or []
    mod_names = [m.get("name") for m in mod_list if m.get("name")]
    multi = len(mod_names) > 1
    if multi:
        tags = list(dict.fromkeys(list(tags) + ["multi_module", "soc"]))
    if len(set(clocks)) > 1:
        tags = list(dict.fromkeys(list(tags) + ["multi_clock", "cdc"]))
    return {
        "protocol": protocol,
        "confidence": confidence,
        "tags": tags,
        "port_count": len(names),
        "clocks": clocks,
        "resets": resets,
        "module_name": (mod_names[0] if mod_names else None),
        "module_names": mod_names,
        "module_count": len(mod_names),
        "multi_module": multi,
        "parameters": (mod_list[0].get("parameters") if mod_list else {}) or {},
    }


def classify_intent(
    module: str,
    prompt: str = "",
    *,
    tool_log: str = "",
    gen_mode: str = "auto",
    tb_methodology: str = "sv",
) -> Dict[str, Any]:
    """What the user is asking the product to do."""
    mod = (module or "").lower().strip()
    mode = (gen_mode or "auto").lower().strip()
    meth = intent_from_methodology(normalize_methodology(tb_methodology, prompt=prompt or ""))
    wants_uvm = meth["methodology"] == "uvm" or bool(_UVM_RE.search(prompt or ""))
    wants_class_tb = meth["class_based"] or wants_uvm
    has_log = bool((tool_log or "").strip())

    family = {
        "testbench": "stimulus_check",
        "assertions": "checking",
        "checkers": "checking",
        "covergroups": "coverage",
        "coverage_holes": "coverage_closure",
        "spec2rtl": "spec_impl",
        "rtl2spec": "spec_extract",
        "testplan": "planning",
        "debug": "debug",
        "formal_hints": "formal",
    }.get(mod, "general")

    return {
        "module": mod,
        "family": family,
        "gen_mode": mode,
        "tb_methodology": meth["methodology"],
        "methodology_label": meth["label"],
        "wants_uvm": wants_uvm,
        "wants_class_tb": wants_class_tb,
        "has_tool_log": has_log,
        "signoff_relevant": mod
        in ("testbench", "assertions", "covergroups", "coverage_holes", "debug", "formal_hints", "checkers"),
    }


def plan_generation(
    *,
    module: str,
    prompt: str = "",
    tool_log: str = "",
    gen_mode: str = "auto",
    tb_methodology: str = "sv",
    modules: Optional[List[dict]] = None,
    rtl_text: str = "",
    user_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Return a routing plan for generate/stream.

    engine_preference:
      - skeleton: deterministic template (fast, preferred for smoke SV)
      - llm: call local/cloud model
      - hybrid: LLM with mandatory skeleton reference (production LLM TB path)
    """
    intent = classify_intent(
        module, prompt, tool_log=tool_log, gen_mode=gen_mode, tb_methodology=tb_methodology
    )
    dut = classify_dut(modules, rtl_text=rtl_text, user_config=user_config)
    mode = intent["gen_mode"]
    meth = intent["tb_methodology"]

    engine = "llm"
    reason = "default_llm"

    if intent["module"] == "testbench":
        # Product intent: always LLM for TB (templates are prompt hints only).
        if is_class_methodology(meth):
            engine, reason = "llm", f"methodology_{meth}"
        elif mode in ("skeleton", "fast", "template", "smoke"):
            engine, reason = "llm", "llm_procedural_smoke_style"
        else:
            engine, reason = "llm", "llm_class_sv"

    elif intent["module"] == "debug" or intent["has_tool_log"]:
        engine, reason = "llm", "debug_or_tool_log"
    elif intent["module"] == "spec2rtl":
        engine, reason = "llm", "spec2rtl_requires_model"
    else:
        engine, reason = "llm", f"module_{intent['module']}"

    # 3B for simple combo/seq smoke; 7B for bus/UVM; 14B for multi-module/SoC.
    _SIMPLE = frozenset(
        {
            "mux",
            "alu",
            "encoder",
            "gray",
            "shifter",
            "parity",
            "counter",
            "edge",
            "pwm",
            "debounce",
            "cdc",
            "fsm",
        }
    )
    model_tier = "3b"
    multi = bool(dut.get("multi_module"))
    multi_clk = len(set(dut.get("clocks") or [])) > 1
    if multi or (intent.get("wants_uvm") and dut["port_count"] > 40) or (
        multi_clk and intent["module"] == "testbench"
    ):
        model_tier = "14b_preferred"
    elif intent.get("wants_uvm") or meth in ("uvm", "ovm", "vmm"):
        model_tier = "7b_preferred"
    elif intent["module"] == "testbench" and dut.get("protocol") in _SIMPLE:
        model_tier = "3b"
    elif intent["module"] == "testbench" or intent["module"] in (
        "spec2rtl",
        "debug",
        "assertions",
        "checkers",
    ):
        model_tier = "7b_preferred"
    elif intent["wants_class_tb"] or dut["port_count"] > 24:
        model_tier = "7b_preferred"

    verify = {
        "lint": meth == "sv",
        "compile": intent["module"] == "testbench" and meth == "sv",
        "sim": False,
    }

    notes = _notes(intent, dut, engine, user_config=user_config)
    return {
        "version": "1.2.0",
        "intent": intent,
        "dut": dut,
        "engine_preference": engine,
        "reason": reason,
        "model_tier": model_tier,
        "protocol_pack": dut["protocol"],
        "tb_methodology": meth,
        "verify": verify,
        "notes": notes,
        "scale": (user_config or {}).get("scale") or "block",
        "user_config": bool(user_config and user_config.get("source") != "default"),
    }


def _notes(
    intent: Dict[str, Any],
    dut: Dict[str, Any],
    engine: str,
    user_config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    notes: List[str] = []
    if engine == "skeleton":
        notes.append("Use Fast-random template for latency and golden accuracy.")
    notes.append(plan_note_for_methodology(intent.get("tb_methodology") or "sv"))
    if dut["protocol"] == "generic" and intent["module"] == "testbench" and intent.get("tb_methodology") == "sv":
        notes.append(
            "Unknown protocol: universal auto-TB (random + no-X). "
            "Promote to golden when ports match FIFO/AXI/APB/mux/stream/…"
        )
    elif intent["module"] == "testbench" and dut["protocol"] in (
        "fifo",
        "axi_lite",
        "apb",
        "ahb",
        "axis",
        "spi",
        "i2c",
        "uart",
        "parity",
        "mux",
        "stream",
        "counter",
        "riscv",
        "wishbone",
        "avalon",
        "fsm",
        "encoder",
        "gray",
        "edge",
        "cdc",
        "pwm",
        "debounce",
        "shifter",
        "can",
        "i3c",
        "axi4",
        "ace",
        "chi",
    ):
        notes.append(f"Protocol pack: {dut['protocol']} (Fast-random golden when skeleton).")
    if dut["protocol"] in ("axi4", "ace", "chi"):
        notes.append("Burst/snoop/CHI: require user VIP — do not invent pin-level timing.")
    if dut["protocol"] == "can":
        notes.append("CAN smoke: recessive idle; SOF only if user set can_bit_clocks.")
    if dut["protocol"] == "i3c":
        notes.append("I3C: I2C-compatible smoke unless CCC/IBI ports exist.")
    if intent.get("wants_class_tb"):
        notes.append("Class-based methodology: commercial simulator; SV Fast-random remains Verilator smoke path.")
    if intent["module"] == "spec2rtl":
        notes.append("Require clocks/reset/I/O checklist before trusting Spec→RTL.")
    if intent["module"] == "debug":
        notes.append("Classify tool_log into ranked fix templates before free-form advice.")
    if dut.get("multi_module"):
        notes.append(
            "Multi-module/SoC: one top TB, instantiate all DUTs, shared clocks/resets, "
            "per-block scoreboards."
        )
    if len(set(dut.get("clocks") or [])) > 1:
        notes.append("Multi-clock: CDC-aware stimulus; never drive async domains with one clock only.")
    cfg = user_config or {}
    if cfg.get("scale") == "ip":
        notes.append(
            "Scale=ip: Verification IP — driver, monitor, checker, coverage + cfg. "
            "One DUT — not a subsystem virtual-seq."
        )
    elif cfg.get("scale") == "processor":
        notes.append("Scale=processor: ISA smoke + user memory/CSR maps only.")
    elif cfg.get("scale") in ("subsystem", "soc", "chiplet"):
        notes.append(
            f"Scale={cfg['scale']}: orchestrate from user topology only "
            "(virtual-seq outline, per-agent scoreboard). Do not invent maps."
        )
    if cfg.get("memory_map") or cfg.get("csr_list"):
        notes.append("User memory/CSR map present — opaque model_reg keys only; no auto-RAL.")
    knobs = cfg.get("protocol_knobs") or {}
    if knobs:
        notes.append(
            "User protocol knobs: "
            + ", ".join(f"{k}={v}" for k, v in knobs.items() if v not in (None, "", []))
        )
    return notes


def plan_to_learning(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Compact dict stored on generation.learning for KG / eval."""
    out = {
        "planner_version": plan.get("version"),
        "engine_preference": plan.get("engine_preference"),
        "protocol_pack": plan.get("protocol_pack"),
        "tb_methodology": plan.get("tb_methodology"),
        "dut_confidence": (plan.get("dut") or {}).get("confidence"),
        "model_tier": plan.get("model_tier"),
        "reason": plan.get("reason"),
    }
    if plan.get("protocol_variant"):
        out["protocol_variant"] = plan["protocol_variant"]
    if plan.get("design_analysis"):
        out["design_analysis"] = plan["design_analysis"]
    if plan.get("scale"):
        out["scale"] = plan["scale"]
    return out
