"""Extract a reviewable TB architecture graph from generated SystemVerilog.

No LLM. Used so a DV engineer can see whether the layered / UVM stack
is complete before they trust Simulate or a vendor export.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_CLASS = re.compile(r"\bclass\s+(\w+)", re.I)
_IFACE = re.compile(r"\binterface\s+(\w+)", re.I)
_MODULE = re.compile(r"\bmodule\s+(\w+)", re.I)
_MAILBOX = re.compile(r"\bmailbox\s*(?:#\s*\([^)]+\))?\s+(\w+)", re.I)
_ANALYSIS = re.compile(r"\buvm_analysis_(?:port|imp|export)\b", re.I)
_VIRTUAL_IF = re.compile(r"\bvirtual\s+\w+", re.I)
_RUN_TEST = re.compile(r"\brun_test\s*\(", re.I)
_CONFIG_DB = re.compile(r"\buvm_config_db\s*#", re.I)
_DUT_INST = re.compile(
    r"\b(\w+)\s*(?:#\s*\([^;]*\))?\s+(dut|u_dut|i_dut)\s*[\(\n]",
    re.I,
)
_UVM = re.compile(r"\b(uvm_pkg|uvm_component|`uvm_|run_test\s*\()", re.I)
_OVM = re.compile(r"\b(ovm_pkg|ovm_component|`ovm_)", re.I)
_VMM = re.compile(r"\b(vmm_|`vmm_)", re.I)
_VIP = re.compile(r"require_user_vip|attach user vip|no invented pin", re.I)
_RAL = re.compile(r"\b(uvm_reg_block|frontdoor_walk|UVM_FRONTDOOR)\b", re.I)


def _role_of(name: str) -> str:
    n = (name or "").lower()
    if "scoreboard" in n or n.endswith("_sb"):
        return "scoreboard"
    if "generator" in n or n.endswith("_gen"):
        return "generator"
    if "driver" in n:
        return "driver"
    if "monitor" in n:
        return "monitor"
    if "sequencer" in n or n.endswith("_sqr"):
        return "sequencer"
    if "agent" in n:
        return "agent"
    if n.endswith("_env") or "environment" in n or n.endswith("_env_c"):
        return "env"
    if n.endswith("_test") or n.endswith("_test_c"):
        return "test"
    if "adapter" in n:
        return "ral_adapter"
    if "csr_seq" in n or n.endswith("_reg_block") or "ral" in n:
        return "ral"
    if "txn" in n or "seq_item" in n or "transaction" in n or n.endswith("_item"):
        return "txn"
    return "class"


def _first(names: List[str], role: str) -> Optional[str]:
    for n in names:
        if _role_of(n) == role:
            return n
    return None


def _node(nid: str, label: str, role: str, present: bool, note: str = "") -> dict:
    return {
        "id": nid,
        "label": label if present else f"(missing {role})",
        "role": role,
        "present": bool(present),
        "note": note,
    }


def analyze_tb_architecture(sv: str, *, methodology_hint: str = "") -> Dict[str, Any]:
    """Return nodes/edges/findings for a generated TB."""
    body = sv or ""
    classes = _CLASS.findall(body)
    ifaces = _IFACE.findall(body)
    modules = _MODULE.findall(body)
    mailboxes = _MAILBOX.findall(body)

    uvm = bool(_UVM.search(body))
    ovm = bool(_OVM.search(body)) and not uvm
    vmm = bool(_VMM.search(body)) and not uvm
    hint = (methodology_hint or "").lower()
    if uvm or hint == "uvm":
        methodology = "uvm"
    elif ovm or hint == "ovm":
        methodology = "ovm"
    elif vmm or hint == "vmm":
        methodology = "vmm"
    elif classes or ifaces:
        methodology = "sv"
    else:
        methodology = "procedural"

    dut = None
    m_dut = _DUT_INST.search(body)
    if m_dut:
        dut = m_dut.group(1)
    if not dut:
        tb_mods = [m for m in modules if m.lower().endswith("_tb") or m.lower().endswith("_top")]
        others = [m for m in modules if m not in tb_mods]
        if others:
            dut = others[0]
        elif modules:
            dut = modules[0]
    dut = dut or "dut"
    top = next((m for m in modules if m.lower().endswith("_tb")), modules[-1] if modules else "tb")

    by_role = {
        "interface": ifaces[0] if ifaces else None,
        "txn": _first(classes, "txn"),
        "generator": _first(classes, "generator"),
        "driver": _first(classes, "driver"),
        "monitor": _first(classes, "monitor"),
        "scoreboard": _first(classes, "scoreboard"),
        "sequencer": _first(classes, "sequencer"),
        "agent": _first(classes, "agent"),
        "env": _first(classes, "env"),
        "test": _first(classes, "test"),
        "ral": _first(classes, "ral") or ("reg_block" if _RAL.search(body) else None),
    }
    has_vif = bool(_VIRTUAL_IF.search(body))
    has_ap = bool(_ANALYSIS.search(body))
    has_run = bool(_RUN_TEST.search(body))
    has_cfg = bool(_CONFIG_DB.search(body))
    vip = bool(_VIP.search(body))
    ral = bool(_RAL.search(body) or by_role["ral"])

    if methodology == "uvm":
        expected = [
            ("test", "test"),
            ("env", "env"),
            ("agent", "agent"),
            ("sequencer", "sequencer"),
            ("driver", "driver"),
            ("monitor", "monitor"),
            ("scoreboard", "scoreboard"),
            ("txn", "sequence item"),
            ("if", "interface"),
            ("dut", "DUT instance"),
            ("top", "TB top"),
        ]
    elif methodology == "sv":
        expected = [
            ("test", "test"),
            ("env", "env"),
            ("generator", "generator"),
            ("driver", "driver"),
            ("monitor", "monitor"),
            ("scoreboard", "scoreboard"),
            ("txn", "transaction"),
            ("if", "interface"),
            ("dut", "DUT instance"),
            ("top", "TB top"),
        ]
    else:
        expected = [("dut", "DUT instance"), ("top", "TB top")]

    present_map = {
        "test": bool(by_role["test"]),
        "env": bool(by_role["env"]),
        "agent": bool(by_role["agent"]),
        "sequencer": bool(by_role["sequencer"] or (methodology == "uvm" and "seq_item_port" in body)),
        "generator": bool(by_role["generator"]),
        "driver": bool(by_role["driver"]),
        "monitor": bool(by_role["monitor"]),
        "scoreboard": bool(by_role["scoreboard"] or re.search(r"\berrors\s*\+\+", body)),
        "txn": bool(by_role["txn"]),
        "if": bool(by_role["interface"]),
        "dut": bool(m_dut or dut),
        "top": bool(modules),
        "ral": ral,
    }

    labels = {
        "test": by_role["test"] or "test",
        "env": by_role["env"] or "env",
        "agent": by_role["agent"] or "agent",
        "sequencer": by_role["sequencer"] or "sequencer",
        "generator": by_role["generator"] or "generator",
        "driver": by_role["driver"] or "driver",
        "monitor": by_role["monitor"] or "monitor",
        "scoreboard": by_role["scoreboard"] or "scoreboard",
        "txn": by_role["txn"] or "txn",
        "if": by_role["interface"] or f"{dut}_if",
        "dut": dut,
        "top": top,
        "ral": by_role["ral"] or "reg_block",
        "vip": "user VIP",
    }

    nodes: List[dict] = []
    shown = [eid for eid, _ in expected]
    if ral:
        shown.append("ral")
    if vip:
        shown.append("vip")
    for eid in shown:
        note = ""
        if eid == "if" and methodology == "sv" and present_map["if"] and not has_vif:
            note = "combo / no virtual IF (OK for some DUTs)"
        if eid == "vip":
            note = "Attach licensed VIP — ChipSutra stub only"
        if eid == "sequencer" and not by_role["sequencer"] and present_map["sequencer"]:
            note = "seq_item_port present (implicit sequencer)"
        nodes.append(_node(eid, labels[eid], eid, present_map.get(eid, True), note))

    edges: List[dict] = []

    def edge(src: str, dst: str, label: str, present: bool) -> None:
        edges.append({"from": src, "to": dst, "label": label, "present": bool(present)})

    if methodology == "uvm":
        edge("test", "env", "contains", present_map["test"] and present_map["env"])
        edge("env", "agent", "contains", present_map["env"] and present_map["agent"])
        edge("agent", "sequencer", "sqr", present_map["agent"] and present_map["sequencer"])
        edge("agent", "driver", "drv", present_map["agent"] and present_map["driver"])
        edge("sequencer", "driver", "seq_item", present_map["sequencer"] and present_map["driver"])
        edge("driver", "if", "vif" if has_vif else "pins", present_map["driver"] and present_map["if"])
        edge("if", "dut", "ports", present_map["if"] and present_map["dut"])
        edge("agent", "monitor", "mon", present_map["agent"] and present_map["monitor"])
        edge(
            "monitor",
            "scoreboard",
            "analysis" if has_ap else "txn",
            present_map["monitor"] and present_map["scoreboard"],
        )
        if ral:
            edge("env", "ral", "map", True)
            edge("ral", "driver", "frontdoor", True)
    elif methodology == "sv":
        edge("test", "env", "run", present_map["test"] and present_map["env"])
        edge("env", "generator", "contains", present_map["env"] and present_map["generator"])
        edge(
            "generator",
            "driver",
            mailboxes[0] if mailboxes else "mailbox",
            present_map["generator"] and present_map["driver"],
        )
        edge("driver", "if" if present_map["if"] else "dut", "drive", present_map["driver"])
        if present_map["if"]:
            edge("if", "dut", "ports", present_map["dut"])
        edge("env", "monitor", "contains", present_map["env"] and present_map["monitor"])
        edge(
            "monitor",
            "scoreboard",
            mailboxes[1] if len(mailboxes) > 1 else "compare",
            present_map["monitor"] and present_map["scoreboard"],
        )
    else:
        edge("top", "dut", "instance", present_map["top"] and present_map["dut"])

    if vip:
        edge("monitor", "vip", "analysis stub", True)
        edge("vip", "scoreboard", "user connect", False)

    findings: List[dict] = []
    missing = [label for eid, label in expected if not present_map.get(eid)]
    if not present_map["dut"]:
        findings.append(
            {
                "severity": "error",
                "title": "No DUT instance",
                "hint": "Top should instantiate the user RTL by its real module name.",
            }
        )
    if methodology in ("sv", "uvm") and not present_map["scoreboard"]:
        findings.append(
            {
                "severity": "error",
                "title": "No scoreboard",
                "hint": "Without a checker the TB can compile and still prove nothing.",
            }
        )
    if methodology == "sv" and not present_map["generator"]:
        findings.append(
            {
                "severity": "warn",
                "title": "No generator",
                "hint": "Layered Pure SV normally has a generator feeding the driver via mailbox.",
            }
        )
    if methodology == "uvm" and not has_run:
        findings.append(
            {
                "severity": "error",
                "title": "No run_test()",
                "hint": "UVM top must call run_test(\"...\") — ChipSutra Simulate will not execute this.",
            }
        )
    if methodology == "uvm" and not has_cfg:
        findings.append(
            {
                "severity": "warn",
                "title": "No uvm_config_db vif",
                "hint": "Driver/monitor usually get the virtual interface from config_db.",
            }
        )
    if vip:
        findings.append(
            {
                "severity": "warn",
                "title": "VIP stub — no pin golden",
                "hint": "AXI4/PCIe/CHI-class protocol: attach your licensed VIP before sign-off.",
            }
        )
    if ral:
        findings.append(
            {
                "severity": "ok",
                "title": "RAL / CSR map present",
                "hint": "Frontdoor sequence uses the user map only — review offsets before vendor sim.",
            }
        )
    if methodology == "sv" and present_map["if"] and not has_vif:
        findings.append(
            {
                "severity": "ok",
                "title": "No virtual interface",
                "hint": "Combo goldens may bind hierarchically — that is intentional for Verilator.",
            }
        )
    if not missing and not any(f["severity"] == "error" for f in findings):
        findings.insert(
            0,
            {
                "severity": "ok",
                "title": "Architecture complete",
                "hint": f"{methodology.upper()} stack is present. Review the scoreboard golden against the DUT.",
            },
        )
    elif missing:
        findings.append(
            {
                "severity": "warn",
                "title": f"Missing: {', '.join(missing)}",
                "hint": "Regenerate or repair before treating this as a reviewable TB.",
            }
        )

    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    if errors:
        verdict = "incomplete"
        summary = findings[0]["title"] if findings else "Incomplete architecture"
    elif warns:
        verdict = "gaps"
        summary = f"{len(shown) - len(missing)}/{len(expected)} layers present — review gaps"
    else:
        verdict = "ok"
        summary = f"{methodology.upper()} layered stack looks complete"

    mermaid = _to_mermaid(methodology, dut, nodes, edges)
    return {
        "methodology": methodology,
        "dut": dut,
        "top": top,
        "title": f"{methodology.upper()} TB — {dut}",
        "verdict": verdict,
        "summary": summary,
        "nodes": nodes,
        "edges": edges,
        "findings": findings,
        "has_virtual_if": has_vif,
        "has_mailbox": bool(mailboxes),
        "has_analysis_port": has_ap,
        "has_ral": ral,
        "require_user_vip": vip,
        "mermaid": mermaid,
        "classes": classes,
        "interfaces": ifaces,
    }


def _to_mermaid(methodology: str, dut: str, nodes: List[dict], edges: List[dict]) -> str:
    lines = ["flowchart TB", f"  subgraph TB[{methodology.upper()} / {dut}]"]
    for n in nodes:
        shape = f'{n["id"]}["{n["label"]}"]' if n["present"] else f'{n["id"]}("{n["label"]}")'
        lines.append(f"    {shape}")
    lines.append("  end")
    for e in edges:
        arrow = "-->" if e["present"] else "-.->"
        lab = f'|"{e["label"]}"|' if e.get("label") else ""
        lines.append(f'  {e["from"]} {arrow}{lab} {e["to"]}')
    return "\n".join(lines)
