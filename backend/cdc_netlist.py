"""Structural CDC heuristics from Yosys JSON netlists (v1)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set, Tuple


_DFF_TYPES = {"$dff", "$_DFF_P_", "$_DFF_N_", "$adff", "$sdff", "$dffe", "$adffe", "$sdffe"}


def _cell_type(cell: dict) -> str:
    return str(cell.get("type") or "")


def _conn_bits(conn: Any) -> List[Any]:
    if isinstance(conn, list):
        return conn
    if conn is None:
        return []
    return [conn]


def analyze_yosys_json(doc: dict | str, *, filename: str = "synth.json") -> dict:
    """Flag data arcs into flops whose Q bits come from another flop's clock domain."""
    if isinstance(doc, str):
        doc = json.loads(doc)
    modules = doc.get("modules") or {}
    findings: List[dict] = []
    clocks: Set[str] = set()
    # bit id -> (flop_name, clock_name)
    bit_owner: Dict[Any, Tuple[str, str]] = {}
    flops: List[Tuple[str, str, List[Any], List[Any]]] = []  # name, clk, d_bits, q_bits

    for mod_name, mod in modules.items():
        cells = mod.get("cells") or {}
        for cell_name, cell in cells.items():
            ctype = _cell_type(cell)
            if ctype not in _DFF_TYPES and not ctype.startswith("$_DFF"):
                continue
            conns = cell.get("connections") or {}
            clk_bits = _conn_bits(conns.get("CLK") or conns.get("C") or conns.get("CLK_BUF"))
            d_bits = _conn_bits(conns.get("D") or conns.get("D_BUF"))
            q_bits = _conn_bits(conns.get("Q") or conns.get("Q_BUF"))
            clk_name = f"{mod_name}.{clk_bits[0]}" if clk_bits else "unknown"
            clocks.add(str(clk_bits[0]) if clk_bits else "unknown")
            flop = f"{mod_name}.{cell_name}"
            for qb in q_bits:
                bit_owner[qb] = (flop, clk_name)
            flops.append((flop, clk_name, d_bits, q_bits))

    sync_chains: Set[Tuple[str, str]] = set()
    for flop, clk, d_bits, _q in flops:
        for db in d_bits:
            owner = bit_owner.get(db)
            if not owner:
                continue
            src_flop, src_clk = owner
            if src_clk == clk:
                continue
            # Look for a second flop in same domain sampling this Q (2FF-ish)
            mitigated = False
            for flop2, clk2, d2, _ in flops:
                if clk2 != clk or flop2 == flop:
                    continue
                if any(bit_owner.get(x, (None, None))[0] == flop for x in d2):
                    mitigated = True
                    sync_chains.add((src_flop, flop2))
                    break
            findings.append(
                {
                    "filename": filename,
                    "signal": flop,
                    "from_domain": src_clk,
                    "to_domain": clk,
                    "source": src_flop,
                    "severity": "info" if mitigated else "warn",
                    "kind": "cdc",
                    "note": "Structural 2FF-like chain on Yosys netlist"
                    if mitigated
                    else "Possible CDC: flop D driven by Q from another clock domain (Yosys JSON)",
                }
            )

    uniq = []
    seen = set()
    for f in findings:
        key = (f["filename"], f["signal"], f["from_domain"], f["to_domain"], f["kind"], f["note"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)

    return {
        "clocks": sorted(str(c) for c in clocks),
        "findings": uniq[:200],
        "counts": {
            "cdc_warn": sum(1 for f in uniq if f["kind"] == "cdc" and f["severity"] == "warn"),
            "cdc_info": sum(1 for f in uniq if f["kind"] == "cdc" and f["severity"] == "info"),
            "rdc": 0,
        },
        "engine": "chipsutra-cdc-v1-yosys",
        "disclaimer": "Structural Yosys-JSON CDC — experimental; not Spyglass/Questa CDC sign-off.",
        "sync_chains": len(sync_chains),
    }


def merge_cdc_results(heuristic: dict, structural: Optional[dict]) -> dict:
    if not structural:
        return heuristic
    findings = list(heuristic.get("findings") or []) + list(structural.get("findings") or [])
    clocks = sorted(set(heuristic.get("clocks") or []) | set(structural.get("clocks") or []))
    uniq = []
    seen = set()
    for f in findings:
        key = (f.get("filename"), f.get("signal"), f.get("from_domain"), f.get("to_domain"), f.get("kind"), f.get("note"))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f)
    return {
        "clocks": clocks,
        "findings": uniq[:200],
        "counts": {
            "cdc_warn": sum(1 for f in uniq if f.get("kind") == "cdc" and f.get("severity") == "warn"),
            "cdc_info": sum(1 for f in uniq if f.get("kind") == "cdc" and f.get("severity") == "info"),
            "rdc": sum(1 for f in uniq if f.get("kind") == "rdc"),
        },
        "engine": "chipsutra-cdc-v1-merged",
        "disclaimer": "Merged heuristic + Yosys-JSON CDC — experimental; not sign-off.",
        "engines": [heuristic.get("engine"), structural.get("engine")],
    }
