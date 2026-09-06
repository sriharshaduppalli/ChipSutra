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
    """Resolve Verilator: PATH first, then backend/tools shim (WSL bat)."""
    found = shutil.which("verilator")
    if found:
        return found
    tools = Path(__file__).resolve().parent / "tools"
    for name in ("verilator.bat", "verilator.BAT", "verilator.cmd", "verilator"):
        cand = tools / name
        if cand.is_file():
            return str(cand)
    env = (os.environ.get("VERILATOR_ROOT") or "").strip()
    if env:
        for name in ("bin/verilator", "verilator"):
            cand = Path(env) / name
            if cand.is_file():
                return str(cand)
    return None


def _safe_name(name: str, fallback: str) -> str:
    n = re.sub(r"[^A-Za-z0-9_.\-]", "_", name or fallback)
    if not n.endswith((".v", ".sv")):
        n += ".sv"
    return n


def _tb_module_name(sv: str) -> Optional[str]:
    m = re.search(r"\bmodule\s+([A-Za-z_]\w*)", sv or "")
    return m.group(1) if m else None


def _sim_exec_cmd(vbin: str, top: str) -> List[str]:
    """Command to execute the built sim binary from the temp cwd.

    When verilator is the WSL shim (verilator.bat), the binary is a Linux ELF
    and must run inside WSL too; WSL maps the Windows cwd automatically.
    """
    rel = f"obj_dir/V{top}"
    # +verilator+rand+reset+2 pairs with --x-initial unique (random power-up).
    plusargs = ["+verilator+rand+reset+2"]
    if vbin.lower().endswith((".bat", ".cmd")):
        return ["wsl", "-d", "Ubuntu", "-e", f"./{rel}"] + plusargs
    return [os.path.join(".", rel)] + plusargs


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
    mode: "lint" (default), "compile" (--binary build only),
          or "run" (build + execute; ok requires the sim to print PASS,
          never print FAIL, and exit cleanly)
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

    # ignore_cleanup_errors: WSL/Verilator can briefly lock obj_dir on Windows
    with tempfile.TemporaryDirectory(
        prefix="chipsutra_dv_verify_", ignore_cleanup_errors=True
    ) as tmp:
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
        if mode in ("compile", "run"):
            # --assert is REQUIRED: without it Verilator drops assert statements
            # entirely, so the standard `assert(txn.randomize())` idiom never
            # randomizes and the TB silently tests nothing.
            # --x-initial unique: randomize register power-up state so missing
            # resets are observable (2-state sim otherwise hides them as 0).
            cmd = [
                vbin, "--binary", "--timing", "--assert", "--x-initial", "unique",
                "-Wno-fatal", "--top-module", top,
            ] + basenames
        else:
            # --timing: TBs use #delays / @(posedge) — required for lint since Verilator 5.
            cmd = [vbin, "--lint-only", "--timing", "-Wno-fatal", "--top-module", top] + basenames

        try:
            build_timeout = timeout_s if mode == "lint" else max(timeout_s, 180.0)
            proc = subprocess.run(
                cmd,
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=build_timeout,
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

            sim_pass: Optional[bool] = None
            sim_log = ""
            if mode == "run" and ok:
                run_cmd = _sim_exec_cmd(vbin, top)
                try:
                    sproc = subprocess.run(
                        run_cmd,
                        cwd=tmp,
                        capture_output=True,
                        text=True,
                        timeout=60.0,
                        encoding="utf-8",
                        errors="replace",
                    )
                    sim_log = ((sproc.stdout or "") + "\n" + (sproc.stderr or "")).strip()
                    printed_pass = bool(re.search(r"\bPASS\b", sim_log))
                    printed_fail = bool(
                        re.search(r"\bFAIL\b|%Error|\$fatal|mismatch", sim_log, re.I)
                    )
                    sim_pass = sproc.returncode == 0 and printed_pass and not printed_fail
                except subprocess.TimeoutExpired:
                    sim_pass = False
                    sim_log = "simulation timed out (missing $finish?)"
                ok = bool(sim_pass)

            out = {
                "ok": ok,
                "skipped": False,
                "engine": "verilator",
                "mode": mode,
                "reason": "pass" if ok else (
                    "sim_failed" if (mode == "run" and sim_pass is False) else "verilator_failed"
                ),
                "log": log[-6000:],
                "errors": errors,
                "top_module": top,
                "returncode": proc.returncode,
                "command": cmd,
            }
            if mode == "run":
                out["sim_pass"] = sim_pass
                out["sim_log"] = sim_log[-4000:]
            return out
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
    out = {
        "verify_ok": result.get("ok"),
        "verify_skipped": bool(result.get("skipped")),
        "verify_engine": result.get("engine"),
        "verify_reason": result.get("reason"),
        "verify_errors": (result.get("errors") or [])[:8],
        "verify_mode": result.get("mode"),
    }
    if "sim_pass" in result:
        out["sim_pass"] = result.get("sim_pass")
    return out
