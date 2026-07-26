"""Yosys synthesis, internal equivalence, and eqy LEC helpers."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


def quote_ys(value: str) -> str:
    return value.replace("\\", "/").replace(" ", "\\ ")


def synth_script(top: str, sources: Iterable[str], *, write_verilog: bool = True) -> str:
    files = " ".join(quote_ys(f) for f in sources)
    lines = [
        f"read_verilog -sv {files}",
        f"hierarchy -check -top {top}",
        "proc; opt; check",
        f"synth -top {top}",
        "stat",
        "write_json synth.json",
    ]
    if write_verilog:
        lines.append("write_verilog -noattr synth_netlist.v")
    return "\n".join(lines)


def equiv_script(top: str, sources: Iterable[str]) -> str:
    files = " ".join(quote_ys(f) for f in sources)
    # Compare the elaborated design against an optimized copy. This is an
    # OSS sanity check, not a replacement for Formality/Conformal.
    return "\n".join(
        [
            f"read_verilog -sv {files}",
            f"hierarchy -check -top {top}",
            "proc; opt_clean",
            "design -stash gold",
            f"read_verilog -sv {files}",
            f"hierarchy -check -top {top}",
            "proc; opt; memory; opt",
            "design -stash gate",
            "design -copy-from gold -as gold " + top,
            "design -copy-from gate -as gate " + top,
            "equiv_make gold gate equiv",
            "hierarchy -top equiv",
            "equiv_simple",
            "equiv_status -assert",
            "stat",
        ]
    )


def eqy_config(
    top: str,
    gold_sources: Iterable[str],
    gate_sources: Iterable[str],
    *,
    gold_label: str = "gold",
    gate_label: str = "gate",
) -> str:
    """Minimal .eqy config for gold vs gate RTL/netlist LEC."""
    gold = " ".join(quote_ys(f) for f in gold_sources)
    gate = " ".join(quote_ys(f) for f in gate_sources)
    return "\n".join(
        [
            f"[{gold_label}]",
            f"read_verilog -sv {gold}",
            f"prep -top {top}",
            "",
            f"[{gate_label}]",
            f"read_verilog -sv {gate}",
            f"prep -top {top}",
            "",
            "[script]",
            f"gold on; hierarchy -top {top}",
            f"gate on; hierarchy -top {top}",
            "",
            "[collect]",
            f"infer_partition -module {top}",
            "",
            "[strategy simple]",
            "use sat",
            "depth 10",
        ]
    ) + "\n"


def parse_yosys_log(log: str) -> Dict[str, Any]:
    cells = wires = memories = None
    for line in (log or "").splitlines():
        m = re.search(r"Number of wires:\s+(\d+)", line)
        if m:
            wires = int(m.group(1))
        m = re.search(r"Number of cells:\s+(\d+)", line)
        if m:
            cells = int(m.group(1))
        m = re.search(r"Number of memories:\s+(\d+)", line)
        if m:
            memories = int(m.group(1))
    low = (log or "").lower()
    equivalence = None
    if "equiv_status" in low or "equivalence" in low:
        equivalence = "fail" if "failed" in low or "unproven" in low or "error:" in low else "pass"
    return {
        "cells": cells,
        "wires": wires,
        "memories": memories,
        "equivalence": equivalence,
        "errors": [line.strip() for line in (log or "").splitlines() if "error:" in line.lower()][:20],
    }


def parse_eqy_log(log: str) -> Dict[str, Any]:
    low = (log or "").lower()
    equivalence = "pass"
    if any(tok in low for tok in ("failed", "unproven", "inequivalent", "error:", "assert failed")):
        equivalence = "fail"
    if "equivalent" in low and equivalence != "fail":
        equivalence = "pass"
    partitions = None
    m = re.search(r"(\d+)\s+partitions?", log or "", re.I)
    if m:
        partitions = int(m.group(1))
    return {
        "equivalence": equivalence,
        "partitions": partitions,
        "errors": [line.strip() for line in (log or "").splitlines() if "error" in line.lower()][:20],
        "engine": "eqy",
    }


def fallback_equiv_note(eqy_missing: bool) -> Optional[str]:
    if eqy_missing:
        return "eqy not on PATH — fell back to Yosys internal pre/post optimization equivalence"
    return None
