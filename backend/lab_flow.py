"""One-click Lab pipeline: lint → sim → synth → STA.

Pure helpers for stage planning and file classification. The HTTP stream
in server.py composes existing simulate/synth/sta SSE endpoints.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


def looks_like_tb(filename: str) -> bool:
    low = (filename or "").lower()
    return low.endswith("_tb.sv") or low.endswith("_tb.v") or low.endswith("_tb.svh")


def classify_hdl_files(files: List[dict]) -> Dict[str, List[dict]]:
    """Split project files into RTL / TB / liberty / SDC buckets."""
    rtl: List[dict] = []
    tb: List[dict] = []
    liberty: List[dict] = []
    sdc: List[dict] = []
    for f in files or []:
        if f.get("is_deleted"):
            continue
        name = f.get("original_filename") or ""
        ext = (f.get("ext") or "").lower()
        kind = (f.get("kind") or "").lower()
        low = name.lower()
        if ext == "lib" or low.endswith(".lib"):
            liberty.append(f)
            continue
        if ext == "sdc" or low.endswith(".sdc"):
            sdc.append(f)
            continue
        if ext not in ("v", "sv", "svh"):
            continue
        if low.startswith("synth_netlist"):
            continue
        if kind == "tb" or looks_like_tb(name):
            tb.append(f)
        else:
            rtl.append(f)
    return {"rtl": rtl, "tb": tb, "liberty": liberty, "sdc": sdc}


def plan_lab_stages(
    *,
    has_rtl: bool,
    has_tb: bool,
    skip_sim: bool = False,
    has_verible: bool = False,
) -> List[Dict[str, Any]]:
    """Ordered Lab stages. Sim is skipped when no TB or skip_sim=True."""
    if not has_rtl:
        return []
    stages: List[Dict[str, Any]] = []
    if has_verible:
        stages.append(
            {
                "id": "verible",
                "label": "Verible lint",
                "tool": "verible-verilog-lint",
                "required": False,
                "description": "Optional OSS style lint (mock if binary missing)",
            }
        )
    stages.append(
        {
            "id": "lint",
            "label": "Lint",
            "tool": "verilator",
            "required": True,
            "description": "Verilator --lint-only on RTL (+ TB if present)",
        },
    )
    if has_tb and not skip_sim:
        stages.append(
            {
                "id": "sim",
                "label": "Simulate",
                "tool": "verilator",
                "required": True,
                "description": "Verilator compile + run",
            }
        )
    stages.append(
        {
            "id": "synth",
            "label": "Synthesize",
            "tool": "yosys",
            "required": True,
            "description": "Yosys synth → synth_netlist.v",
        }
    )
    stages.append(
        {
            "id": "sta",
            "label": "STA",
            "tool": "opensta",
            "required": False,
            "description": "OpenSTA timing (mock without sta + liberty)",
        }
    )
    return stages


def stage_failed(stage_id: str, status: Optional[str]) -> bool:
    """Hard fail that should abort the pipeline when stop_on_fail is set.

    `mock` is not a hard fail — tools missing still let the chain finish with notes.
    """
    if status in ("done", "mock"):
        return False
    return True


def pipeline_status(stage_results: List[Dict[str, Any]]) -> str:
    """Overall Lab status from per-stage results."""
    if not stage_results:
        return "error"
    if any(r.get("failed") for r in stage_results):
        return "error"
    if any(r.get("status") == "mock" for r in stage_results):
        return "partial"
    if all(r.get("status") == "done" for r in stage_results):
        return "done"
    return "partial"


def run_verible_lint(
    named_sources: Sequence[Tuple[str, str]],
    *,
    timeout_s: float = 20,
) -> Dict[str, Any]:
    """Optional Verible lint. Mock when the binary is not installed."""
    exe = shutil.which("verible-verilog-lint")
    if not exe:
        return {
            "status": "mock",
            "ok": True,
            "note": "verible-verilog-lint not on PATH",
            "log": "",
        }
    sources = [(n, t) for n, t in (named_sources or []) if t]
    if not sources:
        return {"status": "done", "ok": True, "note": "no RTL text", "log": ""}
    with tempfile.TemporaryDirectory(prefix="chipsutra_verible_") as td:
        root = Path(td)
        paths: List[str] = []
        for name, text in sources[:12]:
            safe = Path(name or "dut.sv").name or "dut.sv"
            fp = root / safe
            fp.write_text(text, encoding="utf-8")
            paths.append(str(fp))
        try:
            p = subprocess.run(
                [exe, *paths],
                capture_output=True,
                text=True,
                timeout=timeout_s,
            )
        except Exception as e:
            return {"status": "error", "ok": False, "note": str(e)[:200], "log": ""}
        log = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
        ok = p.returncode == 0
        return {
            "status": "done" if ok else "error",
            "ok": ok,
            "note": None if ok else "verible-verilog-lint reported issues",
            "log": log[:8000],
        }
