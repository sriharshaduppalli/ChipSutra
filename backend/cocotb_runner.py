"""Helpers for one-click cocotb + Verilator runs."""
from __future__ import annotations

import re
import shutil
from typing import Dict, List, Optional, Tuple


def cocotb_available() -> bool:
    return bool(shutil.which("cocotb-config"))


def pick_scaffold_files(files: List[dict]) -> Tuple[Optional[dict], Optional[dict], List[dict]]:
    """Return (makefile, test_py, rtl_files) from project file docs."""
    makefile = None
    test_py = None
    rtl = []
    for f in files:
        name = (f.get("original_filename") or "").lower()
        ext = (f.get("ext") or "").lower()
        if name == "makefile":
            makefile = f
        elif name.startswith("test_") and ext == "py":
            test_py = test_py or f
        elif ext in ("v", "sv") and f.get("kind") != "tb":
            rtl.append(f)
        elif ext in ("v", "sv") and not re.search(r"(^|[_-])(tb|test)", name):
            rtl.append(f)
    if not rtl:
        rtl = [f for f in files if (f.get("ext") or "").lower() in ("v", "sv")]
    return makefile, test_py, rtl


def build_make_cmd(sim: str = "verilator") -> List[str]:
    make = shutil.which("make") or shutil.which("mingw32-make")
    if not make:
        raise RuntimeError("make not found on PATH")
    return [make, f"SIM={sim}"]


def parse_cocotb_log(log: str) -> Dict[str, object]:
    passed = len(re.findall(r"\bPASS\b|\bPASSED\b", log or "", flags=re.I))
    failed = len(re.findall(r"\bFAIL(?:ED)?\b|\bERROR\b", log or "", flags=re.I))
    status = "done"
    if failed and failed >= passed:
        status = "error"
    elif "Traceback" in (log or ""):
        status = "error"
    return {"passed_hints": passed, "failed_hints": failed, "status_hint": status}
