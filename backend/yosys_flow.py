"""Yosys synthesis and pre/post optimization equivalence helpers."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


def quote_ys(value: str) -> str:
    return value.replace("\\", "/").replace(" ", "\\ ")


def synth_script(top: str, sources: Iterable[str]) -> str:
    files = " ".join(quote_ys(f) for f in sources)
    return "\n".join(
        [
            f"read_verilog -sv {files}",
            f"hierarchy -check -top {top}",
            "proc; opt; check",
            f"synth -top {top}",
            "stat",
            "write_json synth.json",
        ]
    )


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
