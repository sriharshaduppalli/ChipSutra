"""Coverage report parsers (regex .rpt + Verilator annotate / lcov-ish)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


_PCT = re.compile(r"([A-Za-z][A-Za-z _\-]{2,40})\s*[:=]\s*([0-9]{1,3}(?:\.[0-9]+)?)\s*%")


def parse_text_report(text: str) -> dict:
    metrics: List[dict] = []
    for line in (text or "").splitlines():
        for m in _PCT.finditer(line):
            try:
                pct = float(m.group(2))
            except Exception:
                continue
            if 0 <= pct <= 100:
                metrics.append({"name": m.group(1).strip(), "pct": pct})
    seen: Dict[str, dict] = {}
    for m in metrics:
        seen[m["name"].lower()] = m
    metrics = list(seen.values())[:80]
    holes = [m for m in metrics if m["pct"] < 90]
    overall = round(sum(m["pct"] for m in metrics) / len(metrics), 1) if metrics else 0.0
    return {
        "overall": overall,
        "metrics": metrics,
        "holes": sorted(holes, key=lambda x: x["pct"]),
        "count": len(metrics),
        "source": "text_report",
    }


def parse_verilator_annotate(annotate_dir: str | Path) -> dict:
    """Summarize Verilator --annotate output (*.txt with Line Coverage headers)."""
    root = Path(annotate_dir)
    if not root.is_dir():
        return parse_text_report("")
    metrics: List[dict] = []
    total_hit = total_lines = 0
    for path in sorted(root.rglob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        hit = miss = 0
        for line in text.splitlines():
            # Annotate lines often start with count or %000000 for uncovered
            if re.match(r"^%0+", line) or re.match(r"^0\s+", line):
                miss += 1
            elif re.match(r"^[1-9]\d*\s+", line):
                hit += 1
        lines = hit + miss
        if lines == 0:
            continue
        pct = round(100.0 * hit / lines, 1)
        metrics.append({"name": path.name, "pct": pct, "hit": hit, "miss": miss})
        total_hit += hit
        total_lines += lines
    overall = round(100.0 * total_hit / total_lines, 1) if total_lines else 0.0
    if not metrics and total_lines == 0:
        # Fallback: look for coverage.info style
        info = root / "coverage.info"
        if info.is_file():
            return parse_lcov_info(info.read_text(encoding="utf-8", errors="ignore"))
    holes = [m for m in metrics if m["pct"] < 90]
    return {
        "overall": overall,
        "metrics": metrics[:80],
        "holes": sorted(holes, key=lambda x: x["pct"])[:40],
        "count": len(metrics),
        "source": "verilator_annotate",
        "lines_hit": total_hit,
        "lines_total": total_lines,
    }


def parse_lcov_info(text: str) -> dict:
    metrics: List[dict] = []
    cur = None
    lh = lf = 0
    for line in (text or "").splitlines():
        if line.startswith("SF:"):
            cur = line[3:].strip().split("/")[-1]
            lh = lf = 0
        elif line.startswith("LH:"):
            try:
                lh = int(line[3:])
            except Exception:
                pass
        elif line.startswith("LF:"):
            try:
                lf = int(line[3:])
            except Exception:
                pass
        elif line.startswith("end_of_record") and cur and lf:
            pct = round(100.0 * lh / lf, 1)
            metrics.append({"name": cur, "pct": pct, "hit": lh, "miss": max(0, lf - lh)})
            cur = None
    overall = round(sum(m["pct"] for m in metrics) / len(metrics), 1) if metrics else 0.0
    holes = [m for m in metrics if m["pct"] < 90]
    return {
        "overall": overall,
        "metrics": metrics[:80],
        "holes": sorted(holes, key=lambda x: x["pct"])[:40],
        "count": len(metrics),
        "source": "lcov",
    }


def summarize_coverage_dat(work_dir: str | Path) -> Optional[dict]:
    """If coverage.dat exists, try annotate into work_dir/cov_ann and parse."""
    import shutil
    import subprocess

    root = Path(work_dir)
    dat = root / "coverage.dat"
    if not dat.is_file():
        # Verilator sometimes writes under obj_dir
        cands = list(root.rglob("coverage.dat"))
        if not cands:
            return None
        dat = cands[0]
    if not shutil.which("verilator_coverage"):
        return {"overall": 0.0, "metrics": [], "holes": [], "count": 0, "source": "coverage.dat", "note": "verilator_coverage not installed"}
    ann = root / "cov_ann"
    ann.mkdir(exist_ok=True)
    try:
        subprocess.run(
            ["verilator_coverage", "--annotate", str(ann), str(dat)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(root),
        )
    except Exception as e:
        return {"overall": 0.0, "metrics": [], "holes": [], "count": 0, "source": "coverage.dat", "note": str(e)}
    return parse_verilator_annotate(ann)
