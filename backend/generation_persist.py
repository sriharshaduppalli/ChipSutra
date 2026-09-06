"""Map a Generate module to a project file kind + filename.

Used to auto-save TB/SVA/cover artifacts so Simulate can pick them
without a download + re-upload.
"""
from __future__ import annotations

import re
from typing import Tuple

_ID_RE = re.compile(r"[^A-Za-z0-9_]")

# module id → (kind, suffix)  filename = {dut}{suffix}
_MODULE_META = {
    "testbench": ("tb", "_tb.sv"),
    "assertions": ("sva", "_sva.sv"),
    "covergroups": ("cover", "_cg.sv"),
    "checkers": ("checker", "_chk.sv"),
    "spec2rtl": ("rtl", "_from_spec.sv"),
    "formal_hints": ("sva", "_formal.sv"),
    "coverage_holes": ("tb", "_hole_tests.sv"),
    "rtl2spec": ("doc", "_spec.md"),
    "testplan": ("doc", "_testplan.md"),
    "debug": ("doc", "_debug.md"),
}


def _safe_dut(name: str) -> str:
    s = _ID_RE.sub("_", (name or "dut").strip()) or "dut"
    if s[0].isdigit():
        s = f"d_{s}"
    return s


def generation_artifact_meta(
    module: str,
    dut: str = "dut",
    methodology: str = "sv",
) -> Tuple[str, str]:
    """Return (kind, filename) for a generated artifact."""
    dut_id = _safe_dut(dut)
    key = (module or "").strip().lower()
    kind, suffix = _MODULE_META.get(key, ("artifact", "_gen.txt"))
    if key == "testbench" and (methodology or "sv").lower() == "uvm":
        suffix = "_uvm_tb.sv"
    return kind, f"{dut_id}{suffix}"
