"""DV Planner — route generation intent and DUT class for ChipSutra.

Phase-1 spine of the advanced architecture (see docs/ADVANCED_DV_ARCHITECTURE.md):
classify which engine (skeleton / llm / hybrid) and which protocol pack to prefer.
Does not replace lint gates; it decides strategy before generate.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


_UVM_RE = re.compile(
    r"\b(uvm|u?vm_|agent|sequencer|driver|monitor|scoreboard|sequence_item|"
    r"full\s+uvm|class\s+\w+_env)\b",
    re.I,
)
_FIFO_PORTS = {"wr_en", "rd_en", "full", "empty"} | {"wr_data", "rd_data"}
_AXI_PORTS = {"s_axi_awvalid", "s_axi_arvalid", "s_axi_wvalid"}
_APB_IN = {"psel", "penable", "pwrite", "paddr", "pwdata"}
_APB_OUT = {"pready", "prdata"}
_STREAM_READY = {"ready", "tready", "in_ready", "s_ready"}
_STREAM_VALID = {"valid", "tvalid", "in_valid", "s_valid"}


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


def classify_dut(modules: Optional[List[dict]] = None, *, rtl_text: str = "") -> Dict[str, Any]:
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
    elif _AXI_PORTS.issubset(name_set) or "s_axi_awvalid" in name_set:
        protocol, confidence, tags = "axi_lite", 0.9, ["axi4_lite", "reg_model"]
    elif _APB_IN.issubset(name_set) and _APB_OUT.issubset(name_set):
        protocol, confidence, tags = "apb", 0.88, ["apb_scoreboard"]
    elif "parity" in name_set and ("valid" in name_set or "data" in name_set):
        protocol, confidence, tags = "parity", 0.85, ["xor_parity"]
    elif (
        (name_set & {"sel", "select", "s"})
        and (name_set & {"a", "in0", "i0", "din0"})
        and (name_set & {"b", "in1", "i1", "din1"})
        and (name_set & {"y", "out", "dout", "z"})
    ):
        protocol, confidence, tags = "mux", 0.86, ["mux2_golden"]
    elif (name_set & _STREAM_VALID) and (name_set & _STREAM_READY) and (
        name_set & {"data", "tdata", "in_data", "s_data"}
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

    clocks = [n for n in names if n in ("clk", "clock", "aclk", "pclk", "sclk")]
    resets = [n for n in names if any(x in n for x in ("rst", "reset", "areset"))]
    return {
        "protocol": protocol,
        "confidence": confidence,
        "tags": tags,
        "port_count": len(names),
        "clocks": clocks,
        "resets": resets,
        "module_name": (modules[0].get("name") if modules else None),
        "parameters": (modules[0].get("parameters") if modules else {}) or {},
    }


def classify_intent(module: str, prompt: str = "", *, tool_log: str = "", gen_mode: str = "auto") -> Dict[str, Any]:
    """What the user is asking the product to do."""
    mod = (module or "").lower().strip()
    mode = (gen_mode or "auto").lower().strip()
    wants_uvm = bool(_UVM_RE.search(prompt or ""))
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
        "wants_uvm": wants_uvm,
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
    modules: Optional[List[dict]] = None,
    rtl_text: str = "",
) -> Dict[str, Any]:
    """
    Return a routing plan for generate/stream.

    engine_preference:
      - skeleton: deterministic template (fast, preferred for smoke SV)
      - llm: call local/cloud model
      - hybrid: LLM with mandatory skeleton reference (production LLM TB path)
    """
    intent = classify_intent(module, prompt, tool_log=tool_log, gen_mode=gen_mode)
    dut = classify_dut(modules, rtl_text=rtl_text)
    mode = intent["gen_mode"]

    engine = "llm"
    reason = "default_llm"

    if intent["module"] == "testbench":
        if mode in ("skeleton", "fast", "template"):
            engine, reason = "skeleton", "user_fast_random"
        elif mode in ("llm", "model"):
            engine, reason = "hybrid", "user_llm_mode"
        elif mode == "auto":
            if intent["has_tool_log"] or intent["wants_uvm"]:
                engine, reason = "hybrid", "auto_uvm_or_fixloop"
            elif modules and modules[0].get("ports"):
                engine, reason = "skeleton", "auto_ports_known"
            else:
                engine, reason = "hybrid", "auto_no_ports"
        # Unknown protocol still uses skeleton stimulus; LLM only if user asked
        if engine == "skeleton" and dut["protocol"] == "generic" and intent["wants_uvm"]:
            engine, reason = "hybrid", "generic_dut_uvm"

    elif intent["module"] == "debug" or intent["has_tool_log"]:
        engine, reason = "llm", "debug_or_tool_log"
    elif intent["module"] == "spec2rtl":
        engine, reason = "llm", "spec2rtl_requires_model"
    else:
        engine, reason = "llm", f"module_{intent['module']}"

    model_tier = "3b"
    if intent["wants_uvm"] or intent["module"] in ("spec2rtl", "debug") or dut["port_count"] > 24:
        model_tier = "7b_preferred"

    verify = {
        "lint": True,
        "compile": intent["module"] == "testbench",
        "sim": False,  # enable when dv_verify sim loop ships
    }

    return {
        "version": "1.0.0",
        "intent": intent,
        "dut": dut,
        "engine_preference": engine,
        "reason": reason,
        "model_tier": model_tier,
        "protocol_pack": dut["protocol"],
        "verify": verify,
        "notes": _notes(intent, dut, engine),
    }


def _notes(intent: Dict[str, Any], dut: Dict[str, Any], engine: str) -> List[str]:
    notes: List[str] = []
    if engine == "skeleton":
        notes.append("Use Fast-random template for latency and golden accuracy.")
    if dut["protocol"] == "generic" and intent["module"] == "testbench":
        notes.append(
            "Unknown protocol: universal auto-TB (random + no-X). "
            "Promote to golden when ports match FIFO/AXI/APB/mux/stream/…"
        )
    elif intent["module"] == "testbench" and dut["protocol"] in (
        "fifo",
        "axi_lite",
        "apb",
        "parity",
        "mux",
        "stream",
        "counter",
    ):
        notes.append(f"Protocol pack: {dut['protocol']} (Fast-random golden when skeleton).")
    if intent["wants_uvm"]:
        notes.append("UVM requested: offer Verilator-friendly SV fallback if UVM will not compile.")
    if intent["module"] == "spec2rtl":
        notes.append("Require clocks/reset/I/O checklist before trusting Spec→RTL.")
    if intent["module"] == "debug":
        notes.append("Classify tool_log into ranked fix templates before free-form advice.")
    return notes


def plan_to_learning(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Compact dict stored on generation.learning for KG / eval."""
    return {
        "planner_version": plan.get("version"),
        "engine_preference": plan.get("engine_preference"),
        "protocol_pack": plan.get("protocol_pack"),
        "dut_confidence": (plan.get("dut") or {}).get("confidence"),
        "model_tier": plan.get("model_tier"),
        "reason": plan.get("reason"),
    }
