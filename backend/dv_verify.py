"""Post-generate Verilator verify for ChipSutra TB outputs.

Runs lint-only by default (fast). Skips cleanly when Verilator is not installed.
See docs/ADVANCED_DV_ARCHITECTURE.md — Verifier loop v0.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def verilator_bin() -> Optional[str]:
    return shutil.which("verilator")


def _safe_name(name: str, fallback: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_.\-]", "_", name or fallback)
    if not n.endswith((".v", ".sv")):
        n += ".sv"
    return n


def _tb_module_name(sv: str) -> Optional[str]:
    m = re.search(r"\bmodule\s+([A-Za-z_]\w*)", sv or "")
    return m.group(1) if m else None


def verify_sv_sources(
    sources: List[Tuple[str, str]],
    *,
    top_module: Optional[str] = None,
    mode: str = "lint",
    timeout_s: float = 45.0,
) -> Dict:
    """
    Verify SystemVerilog sources with Verilator.

    sources: list of (filename, content)
    mode: "lint" (default) or "compile" (--binary without run — heavier)
    """
    if not sources:
        return {
            "ok": False,
            "skipped": False,
            "engine": "verilator",
            "mode": mode,
            "reason": "no_sources",
            "log": "",
            "errors": ["no_sources"],
            "top_module": top_module,
        }

    vbin = verilator_bin()
    if not vbin:
        return {
            "ok": None,
            "skipped": True,
            "engine": "none",
            "mode": mode,
            "reason": "verilator_not_on_path",
            "log": "",
            "errors": [],
            "top_module": top_module,
        }

    with tempfile.TemporaryDirectory(prefix="chipsutra_dv_verify_") as tmp:
        paths: List[str] = []
        for fname, body in sources:
            if not (body or "").strip():
                continue
            local = _safe_name(fname, f"src_{len(paths)}.sv")
            p = os.path.join(tmp, local)
            Path(p).write_text(body, encoding="utf-8")
            paths.append(local)

        if not paths:
            return {
                "ok": False,
                "skipped": False,
                "engine": "verilator",
                "mode": mode,
                "reason": "empty_sources",
                "log": "",
                "errors": ["empty_sources"],
                "top_module": top_module,
            }

        top = top_module or _tb_module_name(sources[-1][1]) or "tb"
        basenames = [os.path.basename(p) for p in paths]
        if mode == "compile":
            cmd = [vbin, "--binary", "--timing", "-Wno-fatal", "--top-module", top] + basenames
        else:
            cmd = [vbin, "--lint-only", "-Wno-fatal", "--top-module", top] + basenames

        try:
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                encoding="utf-8",
                errors="replace",
            )
            log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            errors = [
                ln.strip()
                for ln in log.splitlines()
                if "%Error" in ln or "error:" in ln.lower()
            ][:20]
            ok = proc.returncode == 0
            return {
                "ok": ok,
                "skipped": False,
                "engine": "verilator",
                "mode": mode,
                "reason": "pass" if ok else "verilator_failed",
                "log": log[-6000:],
                "errors": errors,
                "top_module": top,
                "returncode": proc.returncode,
                "command": cmd,
            }
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "skipped": False,
                "engine": "verilator",
                "mode": mode,
                "reason": "timeout",
                "log": f"verilator timed out after {timeout_s}s",
                "errors": ["timeout"],
                "top_module": top,
            }
        except Exception as e:
            return {
                "ok": False,
                "skipped": False,
                "engine": "verilator",
                "mode": mode,
                "reason": "exec_error",
                "log": str(e)[:500],
                "errors": [str(e)[:200]],
                "top_module": top,
            }


def verify_testbench(
    rtl_texts: List[Tuple[str, str]],
    tb_sv: str,
    *,
    tb_name: str = "dut_tb.sv",
    mode: str = "lint",
) -> Dict:
    """Verify TB + DUT RTL together."""
    sources = list(rtl_texts or [])
    sources.append((tb_name, tb_sv or ""))
    top = _tb_module_name(tb_sv)
    return verify_sv_sources(sources, top_module=top, mode=mode)


def verify_status_for_learning(result: Dict) -> Dict:
    """Compact dict for generation.learning."""
    return {
        "verify_ok": result.get("ok"),
        "verify_skipped": bool(result.get("skipped")),
        "verify_engine": result.get("engine"),
        "verify_reason": result.get("reason"),
        "verify_errors": (result.get("errors") or [])[:8],
        "verify_mode": result.get("mode"),
    }
