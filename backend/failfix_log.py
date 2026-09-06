"""Append fail→fix pairs for later LoRA (JSONL, local disk)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def failfix_path() -> Path:
    raw = (os.environ.get("CHIPSUTRA_FAILFIX_JSONL") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "storage" / "failfix.jsonl"


def append_failfix(record: Dict[str, Any], *, path: Optional[Path] = None) -> Optional[Path]:
    """Best-effort append. Never raises into generate."""
    dest = path or failfix_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        rec = dict(record)
        rec.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        rec.setdefault("source", "chipsutra_closed_loop")
        with dest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")
        return dest
    except Exception:
        return None
