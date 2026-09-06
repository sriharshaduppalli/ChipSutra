"""Optional AsFigo BYOL linters and extra packs.

Never vendors those repos. Install locally and point env vars / PATH.
Docs: docs/ASFIGO_LINTERS.md  https://github.com/AsFigo
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asfigo_packs import pack_status

_TOOLS = (
    ("svalint", "CHIPSUTRA_SVALINT", ("svalint.py", "svalint")),
    ("fcovlint", "CHIPSUTRA_FCOVLINT", ("fcovlint.py", "fcovlint")),
    ("pyslint", "CHIPSUTRA_PYSLINT", ("pyslint.py", "pyslint")),
    ("yoyolint", "CHIPSUTRA_YOYOLINT", ("yoyolint.py", "yoyolint")),
    ("svck", "CHIPSUTRA_SVCK", ("svck.py", "svck")),
    ("fpgalint", "CHIPSUTRA_FPGALINT", ("fpgalint.py", "fpgalint")),
)


def _disabled() -> bool:
    raw = (os.environ.get("CHIPSUTRA_ASFIGO") or "1").strip().lower()
    return raw in ("0", "false", "off", "no")


def _resolve(env_key: str, names: Tuple[str, ...]) -> Optional[str]:
    explicit = (os.environ.get(env_key) or "").strip()
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return str(p)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def tool_status() -> Dict[str, Any]:
    found = {}
    for key, env_key, names in _TOOLS:
        path = None if _disabled() else _resolve(env_key, names)
        found[key] = {"available": bool(path), "path": path, "env": env_key}
    found["verible_syntax"] = {
        "available": bool(shutil.which("verible-verilog-syntax")),
        "note": "Required by SVALint / FCOVLint / SVCK; ChipSutra native lint does not need it.",
    }
    found["enabled"] = not _disabled()
    found["vendor"] = "optional PATH wrappers — MIT AsFigo BYOL, not vendored"
    found["packs"] = pack_status()
    return found


def _argv(tool_path: str, sv_path: str) -> List[str]:
    import sys

    if tool_path.lower().endswith(".py"):
        return [sys.executable, tool_path, "-t", sv_path]
    return [tool_path, "-t", sv_path]


def _parse_lines(log: str, engine: str) -> List[Dict[str, str]]:
    findings: List[Dict[str, str]] = []
    for line in (log or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if re.search(r"\b(error|fail|violation|af_)\b", s, re.I) or s.startswith("ERROR"):
            sev = "error" if re.search(r"error|fail", s, re.I) else "warning"
            findings.append({"severity": sev, "title": f"{engine}: {s[:80]}", "hint": s[:240]})
        if len(findings) >= 12:
            break
    return findings


def run_tool(kind: str, sv: str, *, timeout: int = 20) -> Dict[str, Any]:
    """Run one AsFigo CLI if installed. Never executes the SV as a script."""
    if _disabled() or not (sv or "").strip():
        return {"skipped": True, "engine": kind, "findings": []}
    meta = {k: (e, n) for k, e, n in _TOOLS}
    if kind not in meta:
        return {"skipped": True, "engine": kind, "findings": [], "reason": "unknown tool"}
    env_key, names = meta[kind]
    path = _resolve(env_key, names)
    if not path:
        return {"skipped": True, "engine": kind, "findings": [], "reason": "not on PATH"}
    with tempfile.TemporaryDirectory(prefix="chipsutra_asfigo_") as tmp:
        sv_path = Path(tmp) / "dut.sv"
        sv_path.write_text(sv, encoding="utf-8")
        try:
            proc = subprocess.run(
                _argv(path, str(sv_path)),
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=tmp,
            )
        except Exception as e:
            return {"skipped": False, "ok": False, "engine": kind, "findings": [], "log": str(e)[:400]}
        log = ((proc.stderr or "") + "\n" + (proc.stdout or ""))[-4000:]
        findings = _parse_lines(log, kind)
        return {
            "skipped": False,
            "ok": proc.returncode == 0 and not any(f["severity"] == "error" for f in findings),
            "engine": kind,
            "findings": findings,
            "log": log[-1500:],
        }


def merge_into(learning: Dict[str, Any], sv: str, *, kind: str = "svalint") -> None:
    extra = run_tool(kind, sv)
    if extra.get("skipped"):
        return
    bucket = learning.setdefault("asfigo", {})
    if isinstance(bucket, dict) and "engine" in bucket and "findings" in bucket:
        learning["asfigo"] = {"runs": [bucket, extra]}
    elif isinstance(bucket, dict) and "runs" in bucket:
        bucket["runs"].append(extra)
    else:
        learning["asfigo"] = extra


def merge_many(learning: Dict[str, Any], sv: str, kinds: Tuple[str, ...]) -> None:
    for kind in kinds:
        merge_into(learning, sv, kind=kind)
