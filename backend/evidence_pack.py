"""Build a reproducible verification evidence pack (OSS sign-off lite).

Laptop-friendly: JSON manifest + optional ZIP of RTL, TB, sim log, mutation.
Not a vendor UCIS dump — enough for a professor, intern mentor, or startup review.
"""
from __future__ import annotations

import json
import zipfile
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def evidence_document(
    *,
    dut_name: str = "dut",
    protocol: str = "generic",
    sim_pass: Optional[bool] = None,
    mutation: Optional[Dict[str, Any]] = None,
    analysis: Optional[Dict[str, Any]] = None,
    tool_versions: Optional[Dict[str, Any]] = None,
    notes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    mut = mutation or {}
    return {
        "chipsutra_evidence": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dut_name": dut_name,
        "protocol": protocol,
        "sim_pass": sim_pass,
        "mutation": {
            "kill_rate": mut.get("kill_rate"),
            "killed": mut.get("killed"),
            "survived": mut.get("survived"),
            "total": mut.get("total"),
            "baseline_pass": mut.get("baseline_pass"),
        },
        "analysis": {
            "protocol": (analysis or {}).get("protocol"),
            "support_tier": (analysis or {}).get("support_tier"),
            "timing_style": (analysis or {}).get("timing_style"),
        },
        "tool_versions": tool_versions or {},
        "notes": notes or [
            "Community evidence pack — Verilator/Yosys/SBY, not vendor sign-off.",
        ],
    }


def write_evidence_zip(
    dest: str | Path,
    *,
    document: Dict[str, Any],
    files: Optional[Dict[str, str]] = None,
) -> Path:
    """files: archive_name -> text content."""
    dest_p = Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    dest_p.write_bytes(evidence_zip_bytes(document=document, files=files))
    return dest_p


def evidence_zip_bytes(
    *,
    document: Dict[str, Any],
    files: Optional[Dict[str, str]] = None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("evidence.json", json.dumps(document, indent=2))
        for name, body in (files or {}).items():
            if not name or body is None:
                continue
            zf.writestr(name.replace("\\", "/"), body)
    return buf.getvalue()
