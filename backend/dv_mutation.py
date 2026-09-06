"""Mutation testing for generated testbenches.

Inject known bugs (mutants) into the DUT RTL and run the TB against each.
A verification-grade TB must FAIL every mutant while PASSing the clean DUT.
Kill rate = killed mutants / applicable mutants. No premium chat model
offers this proof — it is ChipSutra's EDA differentiator.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Dict, List, Optional, Tuple

from dv_verify import verify_testbench, verilator_bin


def _mut_off_by_one(rtl: str) -> Optional[str]:
    """`+ 1` / `+ 1'b1` → `+ 2` (classic off-by-one)."""
    pat = re.compile(r"\+\s*(?:\d+'(?:b0*1|d0*1|h0*1)|1)\b")
    m = pat.search(rtl)
    if not m:
        return None
    return rtl[: m.start()] + "+ 2" + rtl[m.end() :]


def _mut_minus_for_plus(rtl: str) -> Optional[str]:
    """First arithmetic `+` in an assignment RHS → `-`."""
    pat = re.compile(r"(=\s*[\w\[\]']+\s*)\+(\s*[\w\[\]']+)")
    m = pat.search(rtl)
    if not m:
        return None
    return rtl[: m.start()] + m.group(1) + "-" + m.group(2) + rtl[m.end() :]


def _mut_eq_to_neq(rtl: str) -> Optional[str]:
    """First `==` comparison → `!=` (not `===`)."""
    pat = re.compile(r"(?<![=!<>])==(?!=)")
    m = pat.search(rtl)
    if not m:
        return None
    return rtl[: m.start()] + "!=" + rtl[m.end() :]


def _mut_and_to_or(rtl: str) -> Optional[str]:
    """Flip a functionally visible `&&` (handshake/access), not a dead setup wire."""
    for pat in (
        r"\b(?:wr_hs|rd_hs|access|do_wr|do_rd)\b[^=]{0,8}=\s*[^;]+",
        r"\b(?:wr_start|rd_start)\b[^=]{0,8}=\s*[^;]+",
        r"always[\s\S]{0,400}?&&",
        r"&&",
    ):
        m = re.search(pat, rtl)
        if not m:
            continue
        inner = m.group(0)
        pos = inner.rfind("&&")
        if pos < 0:
            continue
        abs_pos = m.start() + pos
        return rtl[:abs_pos] + "||" + rtl[abs_pos + 2 :]
    return None


def _mut_stuck_output(rtl: str) -> Optional[str]:
    """First continuous assign RHS → '0 (stuck-at-zero output)."""
    pat = re.compile(r"(\bassign\s+[A-Za-z_]\w*\s*=\s*)[^;]+;")
    m = pat.search(rtl)
    if not m:
        return None
    return rtl[: m.start()] + m.group(1) + "'0;" + rtl[m.end() :]


def _mut_drop_reset(rtl: str) -> Optional[str]:
    """Disable the active-low reset branch: `if (!rst_n)` / `if (!aresetn)` → `if (1'b0)`."""
    pat = re.compile(
        r"if\s*\(\s*[!~]\s*(?:rst_n|rstn|reset_n|nrst|aresetn|presetn|hresetn)\s*\)",
        re.I,
    )
    m = pat.search(rtl)
    if not m:
        return None
    return rtl[: m.start()] + "if (1'b0)" + rtl[m.end() :]


MUTATORS: List[Tuple[str, Callable[[str], Optional[str]]]] = [
    ("off_by_one", _mut_off_by_one),
    ("minus_for_plus", _mut_minus_for_plus),
    ("eq_to_neq", _mut_eq_to_neq),
    ("and_to_or", _mut_and_to_or),
    ("stuck_output", _mut_stuck_output),
    ("drop_reset", _mut_drop_reset),
]


def generate_mutants(rtl: str) -> List[Tuple[str, str]]:
    """Return [(mutator_name, mutated_rtl)] for every applicable mutator."""
    out: List[Tuple[str, str]] = []
    for name, fn in MUTATORS:
        try:
            mutated = fn(rtl)
        except Exception:
            mutated = None
        if mutated and mutated != rtl:
            out.append((name, mutated))
    return out


_MUTATION_WORKER_CAP = 4


def mutation_worker_count(n_jobs: int, requested: Optional[int] = None) -> int:
    """How many Verilator mutant runs to overlap (1–4).

    Default: min(4, CPU count, n_jobs). Set CHIPSUTRA_MUTATION_WORKERS=1 for serial.
    """
    if n_jobs <= 1:
        return 1
    if requested is None:
        raw = (os.environ.get("CHIPSUTRA_MUTATION_WORKERS") or "").strip()
        if raw:
            try:
                requested = int(raw)
            except ValueError:
                requested = None
        if requested is None:
            requested = min(_MUTATION_WORKER_CAP, os.cpu_count() or 2)
    cap = max(1, min(_MUTATION_WORKER_CAP, int(requested)))
    return max(1, min(cap, n_jobs))


def _classify_mutant_run(mname: str, r: Dict) -> Dict:
    """Killed = TB failed the buggy DUT. Build errors are invalid mutants."""
    if r.get("reason") == "verilator_failed":
        return {"mutant": mname, "status": "invalid_mutant"}
    is_killed = not r.get("ok")
    return {
        "mutant": mname,
        "status": "killed" if is_killed else "survived",
        "sim_log_tail": ("" if is_killed else (r.get("sim_log") or "")[-200:]),
    }


def _run_one_mutant(
    mname: str,
    mutated: str,
    rtl_name: str,
    tb_sv: str,
    tb_name: str,
) -> Dict:
    r = verify_testbench([(rtl_name, mutated)], tb_sv, tb_name=tb_name, mode="run")
    return _classify_mutant_run(mname, r)


def mutation_test(
    rtl: str,
    tb_sv: str,
    *,
    rtl_name: str = "dut.sv",
    tb_name: str = "dut_tb.sv",
    max_mutants: int = 6,
    workers: Optional[int] = None,
) -> Dict:
    """Run the TB against the clean DUT and each mutant.

    Baseline is always serial (need PASS before scoring kills). Mutant sims
    overlap via a thread pool — each Verilator run is a subprocess, so the GIL
    is not the bottleneck.

    Returns {baseline_pass, killed, survived, total, kill_rate, workers, mutants}.
    A mutant is killed when the sim run FAILs (ok=False) against it.
    """
    if not verilator_bin():
        return {"skipped": True, "reason": "verilator_not_on_path"}

    base = verify_testbench([(rtl_name, rtl)], tb_sv, tb_name=tb_name, mode="run")
    if not base.get("ok"):
        return {
            "skipped": False,
            "baseline_pass": False,
            "reason": "baseline_failed",
            "baseline": {
                "reason": base.get("reason"),
                "errors": (base.get("errors") or [])[:5],
                "sim_log_tail": (base.get("sim_log") or "")[-400:],
            },
            "killed": 0,
            "survived": 0,
            "total": 0,
            "kill_rate": None,
            "workers": 1,
        }

    jobs = generate_mutants(rtl)[:max_mutants]
    n_workers = mutation_worker_count(len(jobs), workers)
    if n_workers <= 1:
        results = [
            _run_one_mutant(mname, mutated, rtl_name, tb_sv, tb_name)
            for mname, mutated in jobs
        ]
    else:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = [
                pool.submit(_run_one_mutant, mname, mutated, rtl_name, tb_sv, tb_name)
                for mname, mutated in jobs
            ]
            results = [f.result() for f in futs]

    killed = sum(1 for r in results if r.get("status") == "killed")
    applicable = [r for r in results if r["status"] != "invalid_mutant"]
    total = len(applicable)
    survived = total - killed
    return {
        "skipped": False,
        "baseline_pass": True,
        "killed": killed,
        "survived": survived,
        "total": total,
        "kill_rate": (round(killed / total, 3) if total else None),
        "workers": n_workers,
        "mutants": results,
    }
