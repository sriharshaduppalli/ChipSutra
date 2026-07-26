"""EDA toolchain helpers: versions, file hashes, run manifests."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _run_version(cmd: List[str]) -> Optional[str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        out = (p.stdout or p.stderr or "").strip().splitlines()
        return out[0][:200] if out else None
    except Exception:
        return None


def tool_versions() -> Dict[str, Optional[str]]:
    return {
        "verilator": _run_version(["verilator", "--version"]),
        "yosys": _run_version(["yosys", "-V"]),
        "sby": _run_version(["sby", "--help"]) or ("present" if shutil.which("sby") else None),
        "z3": _run_version(["z3", "--version"]),
    }


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_paths(paths: Iterable[str | Path]) -> List[Dict[str, str]]:
    out = []
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            out.append({"path": pp.name, "sha256": sha256_file(pp)})
    return out


def build_manifest(
    *,
    engine: str,
    mode: str,
    command: Optional[List[str]] = None,
    top_module: Optional[str] = None,
    file_hashes: Optional[List[Dict[str, str]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    doc: Dict[str, Any] = {
        "engine": engine,
        "mode": mode,
        "top_module": top_module,
        "command": command or [],
        "tool_versions": tool_versions(),
        "inputs": file_hashes or [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        doc.update(extra)
    return doc
