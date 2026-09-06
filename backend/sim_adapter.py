"""Simulator adapter interface.

Community: Verilator (default) and optional Icarus (`iverilog`) + IVL_UVM include.
Questa/VCS/Xcelium stay Enterprise stubs — ChipSutra does not claim vendor UVM sign-off.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple


class SimulatorAdapter(Protocol):
    name: str

    def available(self) -> bool: ...
    def lint(self, sources: List[Tuple[str, str]]) -> Dict[str, Any]: ...


class VerilatorAdapter:
    name = "verilator"

    def available(self) -> bool:
        from dv_verify import verilator_bin

        return bool(verilator_bin())

    def lint(self, sources: List[Tuple[str, str]]) -> Dict[str, Any]:
        from dv_verify import verify_testbench

        rtl = sources[:-1] if len(sources) > 1 else sources
        tb = sources[-1][1] if sources else ""
        tb_name = sources[-1][0] if sources else "tb.sv"
        return verify_testbench(rtl, tb, tb_name=tb_name, mode="lint")


def _safe_name(name: str, idx: int) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(name or "").name)
    return cleaned or f"f{idx}.sv"


class IcarusAdapter:
    """Icarus Verilog lint. Optional AsFigo IVL_UVM include — not Accellera UVM."""

    name = "iverilog"

    def available(self) -> bool:
        return bool(shutil.which("iverilog"))

    def lint(self, sources: List[Tuple[str, str]]) -> Dict[str, Any]:
        note = (
            "Icarus lint. IVL_UVM (if set) is messaging/test only — "
            "not Accellera UVM and not Verilator UVM sign-off."
        )
        if not self.available():
            return {"ok": False, "skipped": True, "reason": "iverilog not on PATH", "note": note}
        ivl = (os.environ.get("CHIPSUTRA_IVL_UVM") or os.environ.get("IVL_UVM_HOME") or "").strip()
        cmd = ["iverilog", "-t", "null", "-g2012"]
        if ivl:
            inc = Path(ivl) / "ivl_uvm_src"
            cmd += ["-I", str(inc if inc.is_dir() else ivl)]
        with tempfile.TemporaryDirectory(prefix="chipsutra_iverilog_") as tmp:
            paths: List[str] = []
            for i, (name, body) in enumerate(sources[:16]):
                p = Path(tmp) / _safe_name(name, i)
                p.write_text(body or "", encoding="utf-8")
                paths.append(str(p))
            if not paths:
                return {"ok": True, "skipped": True, "reason": "no sources", "note": note}
            try:
                proc = subprocess.run(
                    cmd + paths, capture_output=True, text=True, timeout=30, cwd=tmp
                )
            except Exception as e:
                return {"ok": False, "engine": self.name, "log": str(e)[:400], "note": note}
            log = ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-2000:]
            return {
                "ok": proc.returncode == 0,
                "engine": self.name,
                "log": log,
                "note": note,
                "ivl_uvm": bool(ivl),
            }


class _EnterpriseStub:
    def __init__(self, name: str):
        self.name = name

    def available(self) -> bool:
        return False

    def lint(self, sources: List[Tuple[str, str]]) -> Dict[str, Any]:
        return {
            "ok": False,
            "skipped": True,
            "reason": (
                f"{self.name} is an Enterprise adapter. Community uses Verilator "
                "(optional Icarus). ChipSutra does not claim Questa/VCS/Xcelium sign-off here."
            ),
        }


ADAPTERS = {
    "verilator": VerilatorAdapter,
    "iverilog": IcarusAdapter,
    "ivl": IcarusAdapter,
    "ivl_uvm": IcarusAdapter,
    "questa": lambda: _EnterpriseStub("questa"),
    "vcs": lambda: _EnterpriseStub("vcs"),
    "xcelium": lambda: _EnterpriseStub("xcelium"),
}


def resolve_adapter(name: Optional[str] = None) -> Any:
    raw = (name or os.environ.get("CHIPSUTRA_SIM_ADAPTER") or "verilator").strip().lower()
    factory = ADAPTERS.get(raw) or ADAPTERS["verilator"]
    return factory() if callable(factory) else factory
