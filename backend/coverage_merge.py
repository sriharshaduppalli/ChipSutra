"""Real coverage database merging (verilator_coverage) + union-style summary merge.

``merge_metric_lists`` in ``coverage_parse`` averages percentages across runs, which
under-reports merged coverage. The helpers here do the correct thing: merge the actual
``coverage.dat`` databases when Verilator is available, and fall back to a union merge
(covered in ANY run => covered) at the summary level otherwise.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

HOLE_THRESHOLD = 90.0
_MAX_METRICS = 80
_MAX_HOLES = 40

_MISSING_NOTE = (
    "verilator_coverage not found on PATH. Install Verilator (apt install verilator / "
    "brew install verilator) or run the OSS CAD Suite Docker image "
    "(hdlc/sim:osscad) to enable real coverage.dat merging."
)


def verilator_coverage_bin() -> Optional[str]:
    """Absolute path to ``verilator_coverage`` if it is on PATH."""
    return shutil.which("verilator_coverage")


def merge_coverage_dats(dat_paths: List[str], out_path: str, timeout: int = 120) -> dict:
    """Merge Verilator coverage databases: ``verilator_coverage -write <out> <dat...>``.

    Never raises for a missing tool or bad inputs — returns ``ok=False`` with a note.
    """
    paths = [str(p) for p in (dat_paths or []) if str(p).strip()]
    existing = [p for p in paths if Path(p).is_file()]
    result = {"ok": False, "out_path": str(out_path), "note": "", "stderr": ""}

    if not paths:
        result["note"] = "No coverage.dat paths supplied."
        return result
    if not existing:
        result["note"] = f"None of the {len(paths)} coverage.dat path(s) exist on disk."
        return result

    binary = verilator_coverage_bin()
    if not binary:
        result["note"] = _MISSING_NOTE
        return result

    try:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["note"] = f"Cannot create output directory: {exc}"
        return result

    cmd = [binary, "-write", str(out_path), *existing]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        result["note"] = f"verilator_coverage timed out after {timeout}s"
        return result
    except OSError as exc:
        result["note"] = f"verilator_coverage failed to launch: {exc}"
        return result

    result["stderr"] = (proc.stderr or "")[-4000:]
    skipped = len(paths) - len(existing)
    if proc.returncode == 0 and Path(out_path).is_file():
        result["ok"] = True
        result["note"] = f"Merged {len(existing)} coverage database(s)."
        if skipped:
            result["note"] += f" Skipped {skipped} missing path(s)."
    else:
        result["note"] = f"verilator_coverage exited with code {proc.returncode}"
    result["merged_inputs"] = len(existing)
    return result


def annotate_merged(dat_path: str, annotate_dir: str, timeout: int = 120) -> dict:
    """Annotate a coverage database: ``verilator_coverage --annotate <dir> <dat>``."""
    result = {"ok": False, "annotate_dir": str(annotate_dir), "note": "", "stderr": ""}

    if not str(dat_path or "").strip():
        result["note"] = "No coverage.dat path supplied."
        return result
    if not Path(dat_path).is_file():
        result["note"] = f"Coverage database not found: {dat_path}"
        return result

    binary = verilator_coverage_bin()
    if not binary:
        result["note"] = _MISSING_NOTE
        return result

    try:
        Path(annotate_dir).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["note"] = f"Cannot create annotate directory: {exc}"
        return result

    cmd = [binary, "--annotate", str(annotate_dir), str(dat_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        result["note"] = f"verilator_coverage timed out after {timeout}s"
        return result
    except OSError as exc:
        result["note"] = f"verilator_coverage failed to launch: {exc}"
        return result

    result["stderr"] = (proc.stderr or "")[-4000:]
    if proc.returncode == 0:
        result["ok"] = True
        result["note"] = f"Annotated sources written to {annotate_dir}"
    else:
        result["note"] = f"verilator_coverage exited with code {proc.returncode}"
    return result


def merge_summary_points(summaries: List[dict]) -> dict:
    """Union merge of coverage summaries: a point counts as covered if covered in ANY run.

    Uses hit/miss counts when present (max hits, widest total), otherwise the max pct
    across runs — max is correct for merged coverage, averaging is not.
    """
    runs = [s for s in (summaries or []) if isinstance(s, dict)]
    buckets: Dict[str, dict] = {}
    order: List[str] = []

    for summary in runs:
        for metric in summary.get("metrics") or []:
            if not isinstance(metric, dict):
                continue
            name = str(metric.get("name") or "").strip()
            pct = metric.get("pct")
            if not name or not isinstance(pct, (int, float)):
                continue
            key = name.lower()
            entry = buckets.get(key)
            if entry is None:
                entry = {"name": name, "pct": 0.0, "samples": 0}
                buckets[key] = entry
                order.append(key)
            entry["samples"] += 1
            entry["pct"] = max(float(entry["pct"]), float(pct))
            for extra in ("kind", "alias"):
                if extra not in entry and metric.get(extra):
                    entry[extra] = metric[extra]

            hit = metric.get("hit")
            miss = metric.get("miss")
            if isinstance(hit, (int, float)):
                total = int(hit) + int(miss if isinstance(miss, (int, float)) else 0)
                entry["hit"] = max(int(entry.get("hit", 0)), int(hit))
                entry["_total"] = max(int(entry.get("_total", 0)), total)
            if metric.get("covered") is True or (isinstance(hit, (int, float)) and hit > 0):
                entry["covered"] = True

    metrics: List[dict] = []
    agg_hit = agg_total = 0
    for key in order:
        entry = buckets[key]
        total = entry.pop("_total", 0)
        if total > 0:
            hit = min(int(entry.get("hit", 0)), total)
            entry["hit"] = hit
            entry["miss"] = max(0, total - hit)
            entry["pct"] = max(float(entry["pct"]), round(100.0 * hit / total, 1))
            agg_hit += hit
            agg_total += total
        entry["pct"] = round(min(100.0, max(0.0, float(entry["pct"]))), 1)
        metrics.append(entry)

    metrics.sort(key=lambda m: m["name"].lower())
    metrics = metrics[:_MAX_METRICS]
    if agg_total > 0:
        overall = 100.0 * agg_hit / agg_total
    elif metrics:
        overall = sum(m["pct"] for m in metrics) / len(metrics)
    else:
        overall = 0.0
    holes = [m for m in metrics if m["pct"] < HOLE_THRESHOLD]
    return {
        "overall": round(overall, 1),
        "metrics": metrics,
        "holes": sorted(holes, key=lambda x: x["pct"])[:_MAX_HOLES],
        "count": len(metrics),
        "source": "merged_union",
        "merged_from": len(runs),
    }
