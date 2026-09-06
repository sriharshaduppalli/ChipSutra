"""ChipSutra nightly / marketing benchmark.

Runs the full eval suite (score + sim_pass) and mutation kill-rate, then writes
a publishable JSON + Markdown report under eval_suite/reports/.

Usage:
  python scripts/run_nightly_bench.py
  python scripts/run_nightly_bench.py --skip-llm   # reuse chipsutra_out TBs
  python scripts/run_nightly_bench.py --only counter_en,axi_lite_slave
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITE = Path(__file__).resolve().parent / "eval_suite"
REPORTS = SUITE / "reports"
sys.path.insert(0, str(ROOT))


def _run(cmd: list[str], env: dict | None = None) -> int:
    print("+", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT), env=env or os.environ.copy())
    return p.returncode


def _load_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _summarize(cmp: list, mut: list) -> dict:
    rows = [r for r in (cmp or []) if isinstance(r, dict) and "chipsutra" in r]
    n = len(rows)
    match = sum(1 for r in rows if r.get("verdict") == "match_or_beat")
    sim_ok = sum(1 for r in rows if r.get("sim_pass") is True)
    sim_known = sum(1 for r in rows if r.get("sim_pass") is not None)
    avg_cs = round(sum(r["chipsutra"].get("score") or 0 for r in rows) / n, 1) if n else 0
    avg_prem = (
        round(sum(r["premium_ref"].get("score") or 0 for r in rows) / n, 1) if n else 0
    )
    avg_lat = round(sum(r.get("latency_s") or 0 for r in rows) / n, 1) if n else 0

    mut_rows = [r for r in (mut or []) if isinstance(r, dict) and r.get("baseline_pass")]
    killed = sum(r.get("killed") or 0 for r in mut_rows)
    total = sum(r.get("total") or 0 for r in mut_rows)
    kill_rate = round(killed / total, 3) if total else None

    return {
        "designs": n,
        "match_or_beat": match,
        "sim_pass": sim_ok,
        "sim_known": sim_known,
        "avg_chipsutra_score": avg_cs,
        "avg_premium_score": avg_prem,
        "avg_latency_s": avg_lat,
        "mutation_killed": killed,
        "mutation_total": total,
        "mutation_kill_rate": kill_rate,
    }


def _markdown(summary: dict, cmp: list, mut: list, when: str) -> str:
    lines = [
        f"# ChipSutra nightly benchmark — {when}",
        "",
        "## Headline",
        "",
        f"- Designs evaluated: **{summary['designs']}**",
        f"- Match/beat premium score: **{summary['match_or_beat']}/{summary['designs']}**",
        f"- Sim-PASS: **{summary['sim_pass']}/{summary['sim_known']}** (known runs)",
        f"- Avg ChipSutra score: **{summary['avg_chipsutra_score']}** "
        f"(premium {summary['avg_premium_score']})",
        f"- Avg latency: **{summary['avg_latency_s']}s**",
        f"- Mutation kill rate: **{summary['mutation_kill_rate']}** "
        f"({summary['mutation_killed']}/{summary['mutation_total']})",
        "",
        "## Per-design score / sim",
        "",
        "| Design | Protocol | CS score | Prem | sim_pass | latency | verdict |",
        "|--------|----------|----------|------|----------|---------|---------|",
    ]
    for r in cmp or []:
        if "chipsutra" not in r:
            continue
        lines.append(
            f"| {r.get('design')} | {r.get('protocol')} | "
            f"{r['chipsutra'].get('score')} | {r['premium_ref'].get('score')} | "
            f"{r.get('sim_pass')} | {r.get('latency_s')}s | {r.get('verdict')} |"
        )
    lines += ["", "## Mutation kill rates", ""]
    for r in mut or []:
        if not isinstance(r, dict):
            continue
        if r.get("skipped"):
            lines.append(f"- `{r.get('design')}`: skipped ({r.get('reason')})")
        elif not r.get("baseline_pass"):
            lines.append(f"- `{r.get('design')}`: baseline FAILED")
        else:
            lines.append(
                f"- `{r.get('design')}`: kill_rate={r.get('kill_rate')} "
                f"({r.get('killed')}/{r.get('total')})"
            )
    lines += [
        "",
        "## India EDA positioning",
        "",
        "On-prem ChipSutra-VLSI (no cloud API), compile + sim-PASS + mutation proof —",
        "metrics premium chat models do not publish for DV testbenches.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-llm", action="store_true", help="reuse existing chipsutra_out")
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--skip-mutation", action="store_true")
    args = ap.parse_args()

    env = os.environ.copy()
    tools = str(ROOT / "tools")
    env["PATH"] = tools + os.pathsep + env.get("PATH", "")

    if not args.skip_llm:
        cmd = [sys.executable, "scripts/eval_llm_vs_premium.py"]
        if args.only:
            cmd += ["--only", args.only]
        rc = _run(cmd, env)
        if rc != 0:
            print("eval suite exited", rc, flush=True)

    if not args.skip_mutation:
        _run([sys.executable, "scripts/run_mutation_bench.py"], env)

    cmp = _load_json(SUITE / "comparison_results.json")
    if isinstance(cmp, dict):
        cmp = cmp.get("results") or cmp.get("cases") or []
    mut = _load_json(SUITE / "mutation_results.json")
    if isinstance(mut, dict):
        mut = mut.get("results") or mut.get("cases") or []

    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    summary = _summarize(cmp if isinstance(cmp, list) else [], mut if isinstance(mut, list) else [])
    REPORTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": when,
        "summary": summary,
        "comparison": cmp,
        "mutation": mut,
    }
    (REPORTS / f"nightly_{stamp}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (REPORTS / f"nightly_{stamp}.md").write_text(
        _markdown(summary, cmp if isinstance(cmp, list) else [], mut if isinstance(mut, list) else [], when),
        encoding="utf-8",
    )
    (REPORTS / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (REPORTS / "latest.md").write_text(
        _markdown(summary, cmp if isinstance(cmp, list) else [], mut if isinstance(mut, list) else [], when),
        encoding="utf-8",
    )
    print("\n=== NIGHTLY SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Wrote {REPORTS / 'latest.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
