"""Community sign-off readiness board — never claims vendor sign-off.

Tiles: lint / sim / coverage / CDC / formal / spec. Score is a laptop
readiness hint for a professor or intern mentor, not UCIS/Questa closure.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _tile(name: str, status: str, detail: str = "") -> Dict[str, str]:
    return {"name": name, "status": status, "detail": (detail or "")[:240]}


def _status_from_bool(val: Any, *, missing: str = "missing") -> str:
    if val is True:
        return "pass"
    if val is False:
        return "fail"
    return missing


def _latest(docs: Sequence[dict]) -> Optional[dict]:
    return docs[0] if docs else None


def _cov_pct(run: Optional[dict]) -> Optional[float]:
    if not run:
        return None
    overall = run.get("overall")
    if isinstance(overall, (int, float)):
        return float(overall)
    if isinstance(overall, dict):
        for k in ("percent", "pct", "line", "overall"):
            v = overall.get(k)
            if isinstance(v, (int, float)):
                return float(v)
    metrics = run.get("metrics") or {}
    if isinstance(metrics, dict):
        for k in ("line", "line_pct", "overall"):
            v = metrics.get(k)
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, dict) and isinstance(v.get("percent"), (int, float)):
                return float(v["percent"])
    return None


def build_signoff_board(
    *,
    generations: Optional[Sequence[dict]] = None,
    coverage_runs: Optional[Sequence[dict]] = None,
    cdc_runs: Optional[Sequence[dict]] = None,
    formal_runs: Optional[Sequence[dict]] = None,
    simulations: Optional[Sequence[dict]] = None,
    synth_runs: Optional[Sequence[dict]] = None,
    sta_runs: Optional[Sequence[dict]] = None,
) -> Dict[str, Any]:
    gens = list(generations or [])
    covs = list(coverage_runs or [])
    cdcs = list(cdc_runs or [])
    formals = list(formal_runs or [])
    sims = list(simulations or [])
    synths = list(synth_runs or [])
    stas = list(sta_runs or [])

    tb = next((g for g in gens if g.get("module") == "testbench"), None)
    spec = next((g for g in gens if g.get("module") == "spec2rtl"), None)
    learn = (tb or {}).get("learning") or {}
    spec_learn = (spec or {}).get("learning") or {}

    lint_ok = learn.get("lint_ok")
    lint = _tile(
        "lint",
        _status_from_bool(lint_ok),
        "class/UVM lint on latest TB" if tb else "No testbench generation yet",
    )

    sim_pass = learn.get("sim_pass")
    sim_status = _status_from_bool(sim_pass)
    if sim_pass is None and sims:
        st = str((sims[0] or {}).get("status") or "").lower()
        if st in ("done", "success", "pass", "ok"):
            sim_status = "pass"
        elif st in ("error", "fail", "failed"):
            sim_status = "fail"
        else:
            sim_status = "missing"
    if learn.get("sim_gate") == "skipped":
        sim_status = "skip"
    sim = _tile(
        "sim",
        sim_status,
        "Verilator sim-run on latest TB (Pure SV)" if tb else "No TB sim yet",
    )

    cov_run = _latest(covs)
    pct = _cov_pct(cov_run)
    if cov_run is None:
        cov = _tile("coverage", "missing", "No coverage run uploaded")
    elif pct is None:
        cov = _tile("coverage", "pass" if cov_run else "missing", "Coverage artifact present")
    else:
        cov = _tile(
            "coverage",
            "pass" if pct >= 70 else "fail",
            f"Latest overall {pct:.1f}% (not vendor UCIS)",
        )

    cdc_run = _latest(cdcs)
    if not cdc_run:
        cdc = _tile("cdc", "missing", "No CDC run")
    else:
        nclock = cdc_run.get("clock_count") or cdc_run.get("n_clocks")
        issues = cdc_run.get("issues") or cdc_run.get("crossings") or []
        n_iss = len(issues) if isinstance(issues, list) else 0
        cdc = _tile(
            "cdc",
            "fail" if n_iss else "pass",
            f"clocks={nclock} issues={n_iss}" if nclock is not None else f"issues={n_iss}",
        )

    formal_run = _latest(formals)
    if not formal_run:
        formal = _tile("formal", "missing", "No SBY/formal run")
    else:
        fst = str(formal_run.get("status") or "").lower()
        parsed = formal_run.get("summary") or formal_run.get("result") or {}
        if fst in ("done", "pass", "proven") or parsed.get("pass"):
            formal = _tile("formal", "pass", "Latest formal run finished")
        elif fst in ("error", "fail", "failed"):
            formal = _tile("formal", "fail", "Latest formal run failed")
        else:
            formal = _tile("formal", "skip", fst or "in progress")

    checklist = spec_learn.get("spec_checklist") or {}
    if spec is None and not checklist:
        spec_tile = _tile("spec", "missing", "No Spec→RTL generation")
    else:
        ready = checklist.get("ready")
        grade = checklist.get("grade") or ""
        spec_tile = _tile(
            "spec",
            "pass" if ready else ("fail" if ready is False else "missing"),
            f"grade={grade}" if grade else "spec checklist",
        )

    tiles = [lint, sim, cov, cdc, formal, spec_tile]
    weights = {"pass": 16, "skip": 8, "missing": 0, "fail": 0}
    score = min(100, sum(weights.get(t["status"], 0) for t in tiles))
    mut = learn.get("mutation") or {}
    kr = mut.get("kill_rate")
    if isinstance(kr, (int, float)) and kr >= 0.8:
        score = min(100, score + 4)

    residual: List[str] = [
        "ChipSutra does not claim vendor sign-off (Questa/VCS/Xcelium UCIS).",
    ]
    if lint["status"] != "pass":
        residual.append("Lint not green on latest testbench.")
    if sim["status"] != "pass":
        residual.append("No Verilator sim PASS on latest Pure-SV TB.")
    if cov["status"] == "missing":
        residual.append("No coverage artifact — holes unknown.")
    if cdc["status"] == "missing":
        residual.append("CDC not run — multi-clock residual unknown.")
    if formal["status"] == "missing":
        residual.append("Formal not run — assertions unproven.")
    if isinstance(kr, (int, float)) and kr < 1.0:
        residual.append(f"Mutation kill rate {kr} — survivors remain.")
    if synths and str((synths[0] or {}).get("status") or "").lower() in ("error", "fail"):
        residual.append("Latest synth run failed.")
    if stas and str((stas[0] or {}).get("status") or "").lower() in ("error", "fail"):
        residual.append("Latest STA run failed.")

    return {
        "chipsutra_signoff": "1.0",
        "not_vendor_signoff": True,
        "score": score,
        "tiles": tiles,
        "residual_risk": residual,
        "waivers": [],
        "latest_generation_id": (tb or {}).get("id"),
        "notes": [
            "Community readiness board — laptop evidence, not a tapeout certificate.",
        ],
    }
