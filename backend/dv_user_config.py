"""User-configurable DV knobs: protocol variant, scale, maps, topology.

RTL ports still win. Knobs never invent JEDEC / MIPI / PCI-SIG / UCIe timings.
Parse from GenerateIn.dv_config, prompt text, or CHIPSUTRA_DV_CONFIG JSON.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

SCALES = ("block", "ip", "processor", "subsystem", "soc", "chiplet")
_SCALE_ALIAS = {
    "block": "block",
    "module": "block",
    "ip": "ip",
    "vip": "ip",
    "processor": "processor",
    "cpu": "processor",
    "core": "processor",
    "subsystem": "subsystem",
    "ss": "subsystem",
    "soc": "soc",
    "chip": "soc",
    "chiplet": "chiplet",
    "d2d": "chiplet",
    "ucie": "chiplet",
}


def _as_dict(raw: Union[dict, str, None]) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw).strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        try:
            val = json.loads(text)
            return val if isinstance(val, dict) else {"topology": val}
        except json.JSONDecodeError:
            return {}
    p = Path(text)
    if p.is_file():
        try:
            val = json.loads(p.read_text(encoding="utf-8"))
            return val if isinstance(val, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    if isinstance(val, bool):
        return int(val)
    if isinstance(val, int):
        return val
    s = str(val).strip().lower()
    try:
        return int(s, 0)
    except ValueError:
        return None


def _norm_scale(val: Any) -> str:
    s = str(val or "block").strip().lower()
    return _SCALE_ALIAS.get(s, "block" if s not in SCALES else s)


def _parse_memory_map(raw: Any) -> List[Dict[str, str]]:
    if isinstance(raw, list):
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("region") or "").strip()
            if not name:
                continue
            out.append(
                {
                    "name": name,
                    "base": str(item.get("base") or item.get("addr") or ""),
                    "size": str(item.get("size") or item.get("bytes") or ""),
                }
            )
        return out
    if isinstance(raw, str) and raw.strip():
        out = []
        for m in re.finditer(
            r"([A-Za-z_][\w]*)\s*=\s*(0x[0-9a-fA-F]+|\d+)\s*/\s*(0x[0-9a-fA-F]+|\d+)",
            raw,
        ):
            out.append({"name": m.group(1), "base": m.group(2), "size": m.group(3)})
        return out
    return []


def _parse_csr_list(raw: Any) -> List[Dict[str, str]]:
    if isinstance(raw, list):
        out = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            addr = str(item.get("addr") or item.get("address") or "").strip()
            if not name or not addr:
                continue
            rec = {
                "name": name,
                "addr": addr,
                "reset": str(item.get("reset") or item.get("reset_val") or ""),
                "access": str(item.get("access") or "rw"),
            }
            if item.get("width"):
                rec["width"] = item.get("width")
            if item.get("fields"):
                rec["fields"] = item.get("fields")
            out.append(rec)
        return out
    if isinstance(raw, str) and raw.strip():
        out = []
        for m in re.finditer(
            r"([A-Za-z_][\w]*)\s*=\s*(0x[0-9a-fA-F]+|\d+)",
            raw,
        ):
            out.append({"name": m.group(1), "addr": m.group(2), "reset": "", "access": "rw"})
        return out
    return []


def _knobs_from_prompt(prompt: str) -> Dict[str, Any]:
    p = prompt or ""
    knobs: Dict[str, Any] = {}
    m = re.search(r"\bspi\s*mode\s*[=:]?\s*([0-3])\b", p, re.I)
    if m:
        knobs["spi_mode"] = int(m.group(1))
    cpol = re.search(r"\bcpol\s*[=:]\s*([01])\b", p, re.I)
    cpha = re.search(r"\bcpha\s*[=:]\s*([01])\b", p, re.I)
    if cpol and cpha:
        knobs["spi_mode"] = (int(cpol.group(1)) << 1) | int(cpha.group(1))
        knobs["cpol"] = int(cpol.group(1))
        knobs["cpha"] = int(cpha.group(1))
    if re.search(r"\bi2c\s+master\b|\bmaster\s+i2c\b", p, re.I):
        knobs["i2c_role"] = "master"
    if re.search(r"\bi2c\s+slave\b|\bslave\s+i2c\b", p, re.I):
        knobs["i2c_role"] = "slave"
    if re.search(r"\b10[- ]?bit\b", p, re.I) and re.search(r"\bi2c\b", p, re.I):
        knobs["i2c_addr_bits"] = 10
    if re.search(r"\b7[- ]?bit\b", p, re.I) and re.search(r"\bi2c\b", p, re.I):
        knobs["i2c_addr_bits"] = 7
    m = re.search(r"\b(?:i2c[_ ]?)?(?:target[_ ]?addr|slave[_ ]?addr)\s*[=:]\s*(0x[0-9a-fA-F]+|\d+)\b", p, re.I)
    if m:
        knobs["i2c_target_addr"] = _int(m.group(1))
    if re.search(r"\buart\s*rx\b|\brx[- ]only\b", p, re.I):
        knobs["uart_dir"] = "rx"
    elif re.search(r"\buart\s*tx\b|\btx[- ]only\b", p, re.I):
        knobs["uart_dir"] = "tx"
    m = re.search(r"\bbaud[_ ]?div(?:ider)?\s*[=:]\s*(\d+)\b", p, re.I)
    if m:
        knobs["uart_baud_div"] = int(m.group(1))
    if re.search(r"\bcan[- ]?fd\b", p, re.I):
        knobs["can_variant"] = "canfd"
    elif re.search(r"\bcan\b", p, re.I):
        knobs["can_variant"] = "can"
    m = re.search(r"\bbit[_ ]?clocks\s*[=:]\s*(\d+)\b", p, re.I)
    if m:
        knobs["can_bit_clocks"] = int(m.group(1))
    if re.search(r"\baxi4?\s*burst\b|\bawlen\b", p, re.I):
        knobs["axi_variant"] = "burst"
    if re.search(r"\baxi[- ]?lite\b", p, re.I):
        knobs["axi_variant"] = "lite"
    if re.search(r"\b(?:with\s+)?ral\b|\bregister\s+model\b|\buvm_reg\b|\bralgen\b|\breggen\b", p, re.I):
        knobs["want_ral"] = True
    m = re.search(r"\b(?:ip_hjson|ral_hjson|hjson)\s*[=:]\s*(\S+)", p, re.I)
    if m:
        knobs["_ip_hjson"] = m.group(1).strip().strip('"')
    m = re.search(r"\bscale\s*[=:]\s*(\w+)\b", p, re.I)
    if m:
        knobs["_scale"] = _norm_scale(m.group(1))
    mmap = re.search(r"\bmemory[_ ]?map\s*[:]\s*([^\n]+)", p, re.I)
    if mmap:
        knobs["_memory_map"] = mmap.group(1)
    csr = re.search(r"\bcsr(?:_list)?\s*[:]\s*([^\n]+)", p, re.I)
    if csr:
        knobs["_csr_list"] = csr.group(1)
    return knobs


def parse_dv_config(
    raw: Union[dict, str, None] = None,
    *,
    prompt: str = "",
    env: bool = True,
) -> Dict[str, Any]:
    """Normalize user DV config. Missing fields stay empty — never invent timings."""
    data = {}
    if env:
        env_raw = os.environ.get("CHIPSUTRA_DV_CONFIG") or ""
        if env_raw.strip():
            data.update(_as_dict(env_raw))
    data.update(_as_dict(raw))
    prompt_knobs = _knobs_from_prompt(prompt)
    knobs = dict(data.get("protocol_knobs") or data.get("knobs") or {})
    for k, v in prompt_knobs.items():
        if k.startswith("_"):
            continue
        knobs.setdefault(k, v)

    scale = _norm_scale(data.get("scale") or prompt_knobs.get("_scale") or "block")
    memory_map = _parse_memory_map(data.get("memory_map") or prompt_knobs.get("_memory_map"))
    csr_list = _parse_csr_list(data.get("csr_list") or data.get("csrs") or prompt_knobs.get("_csr_list"))
    hjson_meta = ""
    ip_hjson = (
        data.get("ip_hjson")
        or data.get("ral_hjson")
        or data.get("hjson")
        or prompt_knobs.get("_ip_hjson")
    )
    top_hjson = data.get("top_hjson")
    if ip_hjson or top_hjson:
        try:
            from reg_hjson import (
                csr_list_from_hjson_path,
                load_hjson,
                memory_map_from_top_hjson,
                resolve_hjson_path,
            )

            ip_path = resolve_hjson_path(ip_hjson)
            if ip_path and not csr_list:
                csr_list = csr_list_from_hjson_path(ip_path)
                hjson_meta = str(ip_path)
            top_path = resolve_hjson_path(top_hjson)
            if top_path and not memory_map:
                memory_map = memory_map_from_top_hjson(load_hjson(top_path))
        except Exception:
            hjson_meta = ""
    topology = data.get("topology") if isinstance(data.get("topology"), dict) else {}
    if not topology and any(k in data for k in ("agents", "address_map", "clocks", "interconnect")):
        topology = {
            "agents": data.get("agents") or [],
            "address_map": data.get("address_map") or [],
            "clocks": data.get("clocks") or [],
            "interconnect": data.get("interconnect") or "",
        }

    if knobs.get("spi_mode") is not None:
        mode = int(knobs["spi_mode"]) & 3
        knobs["spi_mode"] = mode
        knobs.setdefault("cpol", (mode >> 1) & 1)
        knobs.setdefault("cpha", mode & 1)

    require_vip = bool(data.get("require_user_vip") or knobs.get("require_user_vip"))
    if scale in ("subsystem", "soc", "chiplet"):
        require_vip = True
    if str(data.get("protocol") or "").lower() in (
        "pcie",
        "cxl",
        "ucie",
        "ddr",
        "lpddr",
        "hbm",
        "usb",
        "mipi",
        "ace",
        "chi",
        "axi4",
    ):
        require_vip = True
    if knobs.get("axi_variant") == "burst" or knobs.get("can_variant"):
        # CAN smoke is allowed without VIP; burst AXI is not pin-golden
        if knobs.get("axi_variant") == "burst":
            require_vip = True

    want_ral = data.get("enable_ral")
    if want_ral is None:
        want_ral = data.get("ral")
    if want_ral is None:
        want_ral = knobs.get("want_ral")
    if want_ral is None:
        want_ral = bool(csr_list)  # map present → SV named model; UVM RAL if methodology=uvm
    enable_ral = bool(want_ral) and bool(csr_list)

    cfg = {
        "scale": scale,
        "protocol": str(data.get("protocol") or "").strip().lower(),
        "protocol_knobs": knobs,
        "memory_map": memory_map,
        "csr_list": csr_list,
        "topology": topology,
        "require_user_vip": require_vip,
        "enable_ral": enable_ral,
        "ip_hjson": str(ip_hjson or "") or None,
        "top_hjson": str(top_hjson or "") or None,
        "hjson_imported": hjson_meta or None,
        "source": "user" if (raw or prompt_knobs or topology or memory_map or csr_list) else "default",
    }
    return cfg


def knobs_of(module: Optional[dict]) -> Dict[str, Any]:
    if not module:
        return {}
    cfg = module.get("_dv_knobs") or {}
    if isinstance(cfg, dict) and "protocol_knobs" in cfg:
        return dict(cfg.get("protocol_knobs") or {})
    return dict(cfg) if isinstance(cfg, dict) else {}


def attach_knobs(module: dict, cfg: Optional[Dict[str, Any]]) -> dict:
    if module is not None and cfg:
        module["_dv_knobs"] = cfg
    return module


def prompt_block(cfg: Optional[Dict[str, Any]], *, max_chars: int = 1800) -> str:
    """Tight block injected into generate system prompt."""
    if not cfg or cfg.get("source") == "default" and not (
        cfg.get("protocol_knobs") or cfg.get("memory_map") or cfg.get("csr_list") or cfg.get("topology")
    ):
        if not cfg:
            return ""
        if cfg.get("scale") in ("block", None) and not cfg.get("protocol_knobs"):
            return ""
    knobs = cfg.get("protocol_knobs") or {}
    lines = [
        "USER DV CONFIG (honor these knobs; RTL port names still win; do not invent timings):",
        f"Scale: {cfg.get('scale') or 'block'}",
    ]
    if knobs:
        shown = {k: v for k, v in knobs.items() if v not in (None, "", [])}
        if shown:
            lines.append("Protocol knobs: " + ", ".join(f"{k}={v}" for k, v in shown.items()))
    if cfg.get("design_protocol"):
        lines.append(
            f"Design protocol (from RTL ports): {cfg.get('design_protocol')} — "
            "port names/widths from the selected DUT win over this JSON."
        )
    if cfg.get("hjson_imported"):
        lines.append(f"Register map imported from HJSON (reggen/ralgen-compatible): {cfg['hjson_imported']}")
    if cfg.get("enable_ral"):
        lines.append("RAL: enabled from user csr_list / HJSON only. Do not invent extra CSRs.")
    elif cfg.get("csr_list"):
        lines.append("csr_list present but RAL off — opaque model_reg keys only.")
    if cfg.get("require_user_vip"):
        lines.append(
            "Commercial/in-house protocol VIP required for official timings "
            "(burst/snoop/PHY/D2D). Still emit driver/monitor/checker/coverage outline. "
            "Do not invent JEDEC, MIPI, PCI-SIG, or UCIe numbers."
        )
    mmap = cfg.get("memory_map") or []
    if mmap:
        lines.append(
            "User memory map (model_reg keys only — no invented regions): "
            + "; ".join(f"{m['name']}@{m['base']}/{m['size']}" for m in mmap[:12])
        )
    csrs = cfg.get("csr_list") or []
    if csrs:
        lines.append(
            "User CSR list (opaque model_reg; no auto-RAL): "
            + "; ".join(f"{c['name']}={c['addr']}" for c in csrs[:16])
        )
        lines.append("Do not invent extra CSR names or reset values.")
    topo = cfg.get("topology") or {}
    agents = topo.get("agents") or []
    if agents or cfg.get("scale") in ("ip", "processor", "subsystem", "soc", "chiplet"):
        lines.extend(_orchestration_lines(cfg))
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n"
    return text


def _orchestration_lines(cfg: Dict[str, Any]) -> List[str]:
    topo = cfg.get("topology") or {}
    agents = topo.get("agents") or []
    amap = topo.get("address_map") or []
    clocks = topo.get("clocks") or []
    interconnect = topo.get("interconnect") or ""
    scale = cfg.get("scale") or "subsystem"
    if scale == "ip":
        return [
            "SCALE IP = Verification IP (not block smoke, not subsystem): one DUT.",
            "Emit VIP four parts: driver, monitor, checker (protocol rules), coverage.",
            "Cfg active/passive. RAL only from user csr_list/HJSON. No invented maps or virtual-seq farm.",
        ]
    if scale == "processor":
        return [
            "SCALE PROCESSOR: directed ISA smoke + user memory/CSR maps only.",
            "Opaque model_reg keys. No Spike/riscv-dv unless the user asked.",
            "Bus fabric only if those ports exist.",
        ]
    lines = [
        f"SCALE ORCHESTRATION ({scale}): do not emit a full SoC VIP.",
        "One top TB; one virtual-sequence outline; one scoreboard per agent/IF.",
    ]
    if agents:
        names = []
        for a in agents[:12]:
            if isinstance(a, dict):
                names.append(f"{a.get('name') or 'if'}({a.get('protocol') or '?'})")
            else:
                names.append(str(a))
        lines.append("User agents: " + ", ".join(names))
    else:
        lines.append("No agent list — infer IFs from parsed RTL only; do not invent extra agents.")
    if amap:
        lines.append(
            "User address map: "
            + "; ".join(
                f"{(m.get('name') if isinstance(m, dict) else m)}@"
                f"{(m.get('base') if isinstance(m, dict) else '')}"
                for m in amap[:12]
            )
        )
    else:
        lines.append("No interconnect decode map — do not invent one.")
    if clocks:
        lines.append("User clocks: " + ", ".join(str(c) for c in clocks[:8]) + " — CDC-aware; no single-clock assumption.")
    if interconnect:
        lines.append(f"Interconnect: {interconnect} (user-named).")
    if scale == "chiplet":
        lines.append(
            "Chiplet/D2D: treat UCIe/BoW/AIB as user VIP. Outline sideband + mainband "
            "only if those ports exist. Never invent flit/lane-repair timings."
        )
    return lines


_BUS_FOR_RAL = frozenset(
    {
        "apb",
        "apb3",
        "apb4",
        "axi_lite",
        "axi4_lite",
        "axi4",
        "ahb",
        "wishbone",
        "avalon",
        "riscv",
    }
)


def merge_with_design(
    cfg: Optional[Dict[str, Any]],
    modules: Optional[List[dict]] = None,
    *,
    rtl_text: str = "",
    tb_methodology: str = "sv",
) -> Dict[str, Any]:
    """Bind user knobs to the selected RTL. Port list wins over JSON protocol."""
    from dv_planner import classify_dut

    base = dict(cfg or {})
    dut = classify_dut(modules, rtl_text=rtl_text, user_config=base)
    proto = dut.get("protocol") or "generic"
    user_proto = (base.get("protocol") or "").strip().lower()
    # Explicit user protocol only if it is the same family or RTL is generic
    if user_proto and proto in ("generic", user_proto):
        proto = user_proto
    knobs = dict(base.get("protocol_knobs") or {})
    csrs = base.get("csr_list") or []
    meth = (tb_methodology or "sv").lower()
    enable = bool(base.get("enable_ral")) and bool(csrs)
    if enable and proto not in _BUS_FOR_RAL and proto != "generic":
        # Combo/serial DUT: keep named model_reg keys, skip uvm_reg
        if meth != "uvm":
            enable = True  # SV named model still OK
        else:
            enable = proto in _BUS_FOR_RAL
    if knobs.get("want_ral") and not csrs:
        enable = False
    base["design_protocol"] = proto
    base["design_confidence"] = dut.get("confidence")
    base["enable_ral"] = bool(enable and csrs)
    base["module_name"] = dut.get("module_name")
    return base


def example_config() -> Dict[str, Any]:
    return {
        "scale": "ip",
        "enable_ral": True,
        "ip_hjson": "(optional path to OpenTitan/reggen IP .hjson — imported into csr_list)",
        "protocol_knobs": {"spi_mode": 0},
        "memory_map": [{"name": "REGS", "base": "0x0", "size": "0x1000"}],
        "csr_list": [
            {
                "name": "CTRL",
                "addr": "0x0",
                "reset": "0x0",
                "access": "rw",
                "width": 32,
                "fields": [{"name": "ENABLE", "lsb": 0, "width": 1, "access": "rw"}],
            },
            {"name": "STAT", "addr": "0x4", "reset": "0x0", "access": "ro", "width": 32},
        ],
        "topology": {"agents": [], "address_map": [], "clocks": [], "interconnect": ""},
    }
