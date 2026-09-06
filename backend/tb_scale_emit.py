"""Scale-aware TB extras: IP VIP four-parts, topology orchestration.

Block-scale goldens stay unchanged. Extras apply only when dv_config.scale
is ip / processor / subsystem / soc / chiplet. Never invent DUT ports or maps.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dv_user_config import SCALES

_PROTO_HINTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("apb", ("psel", "penable", "pwrite", "paddr", "pwdata", "prdata")),
    ("axi_lite", ("awvalid", "arvalid", "wvalid", "bready", "rready", "awaddr")),
    ("axi", ("awvalid", "wvalid", "awburst", "awlen")),
    ("ahb", ("htrans", "hwrite", "haddr", "hsel")),
    ("uart", ("txd", "rxd", "uart_tx", "uart_rx", "sout", "sin")),
    ("spi", ("sclk", "sck", "mosi", "miso", "ss_n", "cs_n")),
    ("i2c", ("scl", "sda")),
    ("axis", ("tvalid", "tready", "tdata")),
    ("can", ("can_rx", "can_tx")),
    ("jtag", ("tck", "tms", "tdi", "tdo")),
    ("wishbone", ("stb_i", "cyc_i", "we_i", "ack_o")),
)

_PROTO_ALIAS = {
    "apb3": "apb",
    "apb4": "apb",
    "axi4_lite": "axi_lite",
    "axi4-lite": "axi_lite",
    "axi-lite": "axi_lite",
    "axi4lite": "axi_lite",
    "ahb_lite": "ahb",
    "ahb-lite": "ahb",
    "axi4-stream": "axis",
    "axi_stream": "axis",
}


def scale_of(module: Optional[dict]) -> str:
    cfg = (module or {}).get("_dv_knobs") if isinstance(module, dict) else {}
    if not isinstance(cfg, dict):
        return "block"
    s = str(cfg.get("scale") or "block").strip().lower()
    return s if s in SCALES else "block"


def _cfg_of(module: Optional[dict]) -> Dict[str, Any]:
    cfg = (module or {}).get("_dv_knobs") if isinstance(module, dict) else {}
    return cfg if isinstance(cfg, dict) else {}


def _port_names(module: Optional[dict]) -> List[str]:
    out = []
    for p in (module or {}).get("ports") or []:
        n = p.get("name") if isinstance(p, dict) else None
        if n:
            out.append(str(n))
    return out


def protocol_from_port_names(names: Sequence[str]) -> str:
    low = [n.lower() for n in names if n]
    blob = " ".join(low)
    best = "generic"
    best_hits = 0
    for proto, hints in _PROTO_HINTS:
        hits = sum(1 for h in hints if h in blob or any(h in n for n in low))
        need = 2 if proto not in ("i2c", "can", "jtag") else 2
        if hits >= need and hits > best_hits:
            best, best_hits = proto, hits
    return best


def _norm_proto(raw: Any) -> str:
    s = str(raw or "").strip().lower().replace(" ", "_")
    return _PROTO_ALIAS.get(s, s)


def _ident(name: str, fallback: str = "if") -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", (name or "").strip())
    if not s or s[0].isdigit():
        s = f"{fallback}_{s}" if s else fallback
    return s


def match_topology_agents(
    agents: Sequence[Any],
    port_names: Sequence[str],
) -> List[Dict[str, Any]]:
    """Mark each user agent matched if its protocol exists on DUT ports."""
    dut_proto = protocol_from_port_names(port_names)
    low_blob = " ".join(n.lower() for n in port_names)
    out: List[Dict[str, Any]] = []
    for i, raw in enumerate(agents or []):
        if isinstance(raw, dict):
            name = str(raw.get("name") or raw.get("if") or f"agent{i}")
            proto = _norm_proto(raw.get("protocol") or raw.get("if_type") or "")
        else:
            name = str(raw)
            proto = _norm_proto(raw)
        proto = proto or "generic"
        matched = False
        if proto != "generic" and proto == dut_proto:
            matched = True
        elif proto != "generic":
            hints = dict(_PROTO_HINTS).get(proto) or (proto,)
            hits = sum(1 for h in hints if h in low_blob)
            matched = hits >= 2 or (hits >= 1 and proto in low_blob)
        out.append(
            {
                "name": _ident(name, f"agent{i}"),
                "protocol": proto,
                "matched": matched,
            }
        )
    return out


def apply_scale_emit(sv: str, module: Optional[dict]) -> str:
    """Post-process a Pure SV class TB. No-op at block scale."""
    if not sv or not module:
        return sv
    scale = scale_of(module)
    if scale in ("block", ""):
        return sv
    if scale == "ip":
        sv = _apply_ip(sv, module)
    elif scale == "processor":
        sv = _apply_processor(sv, module)
    elif scale in ("subsystem", "soc", "chiplet"):
        sv = _apply_ip(sv, module)
        sv = _apply_topology(sv, module, scale=scale)
    return sv


def apply_uvm_scale_emit(
    sv: str,
    module: Optional[dict],
    *,
    txn: str = "",
    env: str = "",
    ag: str = "",
    if_name: str = "",
    sb: str = "",
) -> str:
    """UVM extras: IP is_active + commercial VIP integration sketch."""
    if not sv or not module:
        return sv
    cfg = _cfg_of(module)
    scale = scale_of(module)
    name = module.get("name") or "dut"
    if scale == "ip" and ag:
        chunk = sv.split(f"class {ag}", 1)
        if len(chunk) == 2 and "is_active" not in chunk[1][:900]:
            needle = f"class {ag} extends uvm_agent;\n  `uvm_component_utils({ag})\n"
            insert = (
                f"class {ag} extends uvm_agent;\n"
                f"  `uvm_component_utils({ag})\n"
                f"  uvm_active_passive_enum is_active = UVM_ACTIVE;\n"
            )
            if needle in sv:
                sv = sv.replace(needle, insert, 1)
            sv = re.sub(
                r"(class "
                + re.escape(ag)
                + r"[\s\S]*?function void build_phase[\s\S]*?)"
                r"(drv = \w+::type_id::create\(\"drv\", this\);)",
                r"\1if (is_active == UVM_ACTIVE)\n      \2",
                sv,
                count=1,
            )
    if cfg.get("require_user_vip") or scale in ("subsystem", "soc", "chiplet", "ip"):
        vip = str((cfg.get("protocol_knobs") or {}).get("vip_name") or "user_vip")
        vip = _ident(vip, "user_vip")
        sketch = (
            f"\n// Commercial VIP integration sketch — integrate {vip}, do not copy vendor source.\n"
            f"// uvm_config_db#(virtual {if_name or (name + '_if')})::set(this, \"{vip}*\", \"vif\", vif);\n"
            f"// {vip}.analysis_port.connect({sb or (name + '_scoreboard')}.imp);\n"
            f"// Project scoreboard stays the consumer; VIP owns protocol checker/coverage.\n"
        )
        if "Commercial VIP integration" not in sv:
            marker = f"class {env} extends uvm_env;" if env else "class "
            idx = sv.find(marker)
            if idx >= 0:
                sv = sv[:idx] + sketch + sv[idx:]
            else:
                sv = sketch + sv
    if scale in ("subsystem", "soc", "chiplet"):
        sv = _apply_topology(sv, module, scale=scale)
    return sv


def _apply_ip(sv: str, module: dict) -> str:
    name = module.get("name") or "dut"
    if f"{name}_agent_cfg" in sv:
        return sv
    cfg_sv = f"""
class {name}_agent_cfg;
  bit is_active = 1;
  bit en_coverage = 1;
endclass

class {name}_checker;
  int errors;
  function new(); errors = 0; endfunction
  function void protocol_ok();
    // VIP checker: protocol handshake rules (not the data-path scoreboard).
  endfunction
endclass
"""
    txn_end = f"class {name}_txn;"
    idx = sv.find(txn_end)
    if idx >= 0:
        end = sv.find("endclass", idx)
        if end >= 0:
            end = end + len("endclass")
            sv = sv[:end] + "\n" + cfg_sv + sv[end:]
    else:
        sv = cfg_sv + sv

    empty_mon = f"class {name}_monitor;\nendclass"
    if empty_mon in sv:
        sv = sv.replace(
            empty_mon,
            f"""class {name}_monitor;
  virtual {name}_if vif;
  {name}_checker chk;
  function new(); chk = new(); endfunction
  function void sample();
    // Passive observe when cfg.is_active==0; driver owns stimulus when active.
  endfunction
endclass""",
            1,
        )

    try:
        from tb_coverage import build_covergroup, has_covergroup

        if not has_covergroup(sv):
            prefix = "vif." if re.search(r"\bvif\s*\(", sv) or "virtual " in sv else ""
            clk = "vif.clk" if prefix else _clk_name(module)
            block = build_covergroup(
                name,
                module.get("ports") or [],
                clk=clk,
                sample_prefix=prefix,
            )
            if block:
                em = sv.rfind("endmodule")
                if em >= 0:
                    sv = sv[:em] + "\n" + block + "\n\n" + sv[em:]
    except Exception:
        pass

    if f"{name}_reg_model" in sv and "task hw_reset();" not in sv:
        note = (
            f"\n  // RAL frontdoor: driver predict_write is the SV adapter.\n"
            f"  // Passive predictor: monitor.sample() → ral.predict_write (is_active==0).\n"
            f"  // hw_reset / bit-bash: only user csr_list addresses; do not invent CSRs.\n"
        )
        sv = sv.replace(
            f"class {name}_scoreboard;",
            f"class {name}_scoreboard;{note}",
            1,
        )
    return sv


def _apply_processor(sv: str, module: dict) -> str:
    if "SCALE PROCESSOR" in sv:
        return sv
    banner = (
        "// SCALE PROCESSOR: directed ISA smoke + user memory/CSR maps only.\n"
        "// Opaque model_reg keys. No Spike/riscv-dv unless the user asked.\n"
    )
    return banner + sv


def _apply_topology(sv: str, module: dict, *, scale: str) -> str:
    if f"{module.get('name') or 'dut'}_vseq" in sv:
        return sv
    cfg = _cfg_of(module)
    topo = cfg.get("topology") or {}
    agents = match_topology_agents(topo.get("agents") or [], _port_names(module))
    name = module.get("name") or "dut"
    clocks = topo.get("clocks") or []
    interconnect = str(topo.get("interconnect") or "")
    lines = [
        f"// SCALE {scale.upper()}: orchestrate from user topology; do not invent RTL or maps.",
    ]
    if len(clocks) > 1:
        lines.append(
            "// CDC: user clocks "
            + ", ".join(str(c) for c in clocks[:8])
            + " — no single-clock assumption; do not invent synchronizer RTL."
        )
    if interconnect:
        lines.append(f"// Interconnect (user-named): {interconnect}")
    stub_classes = []
    vseq_body = []
    for a in agents:
        if a["matched"]:
            vseq_body.append(
                f"    $display(\"vseq: agent {a['name']} protocol={a['protocol']} matched DUT ports\");"
            )
        else:
            cls = f"{a['name']}_ss_agent"
            stub_classes.append(
                f"""class {cls};
  string protocol = "{a['protocol']}";
  task run();
    $display("SKIP agent {a['name']} ({a['protocol']}): no matching DUT ports — do not invent RTL");
  endtask
endclass"""
            )
            vseq_body.append(f"    {cls} {a['name']}_stub; {a['name']}_stub = new(); {a['name']}_stub.run();")
    if not agents:
        vseq_body.append(
            "    $display(\"vseq: no user agents — single DUT IF only; do not invent extra agents\");"
        )
    stubs = "\n\n".join(stub_classes)
    vseq = f"""
class {name}_vseq;
  task run();
{chr(10).join(vseq_body) if vseq_body else "    ;"}
  endtask
endclass
"""
    block = "\n".join(lines) + "\n" + (stubs + "\n" if stubs else "") + vseq
    m = re.search(rf"\bmodule\s+{re.escape(name)}_tb\b", sv)
    if m:
        sv = sv[: m.start()] + block + "\n" + sv[m.start() :]
    else:
        sv = block + sv
    # Run vseq after env.report so stimulus (and eval PASS) is unchanged.
    report = f"    env.report();"
    hook = f"    env.report();\n    begin {name}_vseq vseq; vseq = new(); vseq.run(); end"
    if report in sv and f"{name}_vseq vseq" not in sv:
        sv = sv.replace(report, hook, 1)
    return sv


def _clk_name(module: dict) -> str:
    for p in module.get("ports") or []:
        n = (p.get("name") or "").lower()
        if n in ("clk", "clock", "pclk", "aclk", "hclk", "clk_i", "clk_in"):
            return p["name"]
    return "clk"
