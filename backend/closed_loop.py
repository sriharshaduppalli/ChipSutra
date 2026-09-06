"""Generate closed loop: sim → classify/repair ≤N → skeleton → mutation → evidence.

Keeps LLM generate+repair serial (one stream). Overlaps only mutation Verilator jobs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from debug_classify import classify_log, debug_prompt_block
from dv_verify import verify_status_for_learning, verify_testbench, verilator_bin
from evidence_pack import evidence_document
from failfix_log import append_failfix


def env_enabled(name: str, default: str = "auto", *, tool_present: bool = True) -> bool:
    raw = (os.environ.get(name) or default).strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return bool(tool_present)


def repair_round_limit() -> int:
    try:
        n = int((os.environ.get("CHIPSUTRA_REPAIR_ROUNDS") or "2").strip())
    except ValueError:
        n = 2
    return max(0, min(4, n))


def mutation_max_mutants() -> int:
    try:
        n = int((os.environ.get("CHIPSUTRA_MUTATION_MAX") or "4").strip())
    except ValueError:
        n = 4
    return max(1, min(6, n))


def compact_mutation(mut: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not mut:
        return None
    return {
        "skipped": mut.get("skipped"),
        "reason": mut.get("reason"),
        "baseline_pass": mut.get("baseline_pass"),
        "kill_rate": mut.get("kill_rate"),
        "killed": mut.get("killed"),
        "survived": mut.get("survived"),
        "total": mut.get("total"),
        "workers": mut.get("workers"),
        "mutants": [
            {"mutant": m.get("mutant"), "status": m.get("status")}
            for m in (mut.get("mutants") or [])[:8]
        ],
    }


@dataclass
class ClosedLoopResult:
    tb_sv: str
    engine: Optional[str] = None
    learning: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)


def _progress(stage: str, message: str, **extra: Any) -> Dict[str, Any]:
    ev: Dict[str, Any] = {"type": "progress", "stage": stage, "message": message}
    ev.update(extra)
    return ev


def _replace(content: str, engine: str) -> Dict[str, Any]:
    return {"type": "replace", "content": content, "engine": engine}


def _sim_ok(vres: Dict[str, Any]) -> bool:
    return bool(vres.get("ok")) and not vres.get("skipped")


async def run_closed_loop(
    *,
    tb_sv: str,
    rtl_sources: List[Tuple[str, str]],
    tb_name: str,
    dut_name: str = "dut",
    protocol: str = "generic",
    skeleton_sv: str = "",
    stamp: Optional[Callable[..., str]] = None,
    mechanical_repair: Optional[Callable[[str], str]] = None,
    llm_repair: Optional[Callable[..., Awaitable[Tuple[str, bool]]]] = None,
    verify_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    mutation_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    analysis: Optional[Dict[str, Any]] = None,
    tool_versions: Optional[Dict[str, Any]] = None,
    model: str = "",
) -> ClosedLoopResult:
    """Sim-run gate with bounded repair, then mutation + evidence on PASS."""
    verify = verify_fn or verify_testbench
    has_v = bool(verilator_bin()) if verify_fn is None else True
    if not env_enabled("CHIPSUTRA_SIM_GATE", "auto", tool_present=has_v):
        return ClosedLoopResult(tb_sv=tb_sv, learning={"sim_gate": "disabled"})

    events: List[Dict[str, Any]] = []
    learning: Dict[str, Any] = {}
    engine: Optional[str] = None
    tb = tb_sv
    proto = protocol or "generic"

    def _run(code: str) -> Dict[str, Any]:
        return verify(rtl_sources, code, tb_name=tb_name, mode="run")

    def _stamp(code: str, eng: str) -> str:
        if stamp:
            return stamp(code, engine=eng, model=model or "llm", protocol=proto)
        return code

    events.append(_progress("verify", "Sim-run closed loop…"))
    vrun = _run(tb)
    if vrun.get("skipped"):
        learning["sim_gate"] = "skipped"
        learning.update(verify_status_for_learning(vrun))
        learning["evidence"] = evidence_document(
            dut_name=dut_name or "dut",
            protocol=proto,
            sim_pass=None,
            analysis=analysis,
            tool_versions=tool_versions,
            notes=[
                "Community evidence pack — Verilator skipped (not on PATH or gate off).",
                "Not vendor sign-off.",
            ],
        )
        return ClosedLoopResult(tb_sv=tb, learning=learning, events=events)

    max_rounds = repair_round_limit()
    rounds = 0
    while (not _sim_ok(vrun)) and rounds < max_rounds:
        rounds += 1
        log = ((vrun.get("sim_log") or "") + "\n" + "\n".join(vrun.get("errors") or []))[:8000]
        classified = classify_log(log, prior_code=tb)
        learning["last_debug"] = {
            "top_category": classified.get("top_category"),
            "summary": classified.get("summary"),
        }
        hint = (classified.get("summary") or "sim FAIL")[:120]
        events.append(_progress("repair", f"Repair round {rounds}/{max_rounds}: {hint}"))

        changed = False
        if mechanical_repair:
            try:
                fixed = mechanical_repair(tb)
            except Exception:
                fixed = tb
            if fixed and fixed.strip() and fixed != tb:
                tb = _stamp(fixed, "llm_repaired")
                engine = "llm_repaired"
                changed = True
                events.append(_replace(tb, engine))
                vrun = _run(tb)
                if _sim_ok(vrun):
                    break

        if (not _sim_ok(vrun)) and llm_repair:
            try:
                events.append(_progress("repair", f"LLM repair round {rounds}…"))
                block = debug_prompt_block(classified)
                cand, ok_llm = await llm_repair(
                    tb,
                    classified,
                    vrun,
                    extra_hint=block,
                )
            except Exception:
                cand, ok_llm = tb, False
            if ok_llm and cand and cand.strip():
                if mechanical_repair:
                    try:
                        cand = mechanical_repair(cand)
                    except Exception:
                        pass
                tb = _stamp(cand, "llm_repaired")
                engine = "llm_repaired"
                changed = True
                events.append(_replace(tb, engine))
                vrun = _run(tb)
        if not changed:
            break

    learning["repair_rounds"] = rounds

    if (not _sim_ok(vrun)) and (skeleton_sv or "").strip():
        tb = _stamp(skeleton_sv, "skeleton_fallback")
        engine = "skeleton_fallback"
        learning["skeleton_fallback"] = True
        events.append(_replace(tb, engine))
        events.append(_progress("verify", "Sim FAIL — DUT-correct skeleton fallback"))
        vrun = _run(tb)

    learning.update(verify_status_for_learning(vrun))
    sim_pass = bool(_sim_ok(vrun))
    learning["sim_pass"] = sim_pass
    if sim_pass:
        events.append(_progress("verify", "Sim-run PASS"))
    else:
        events.append(_progress("verify", "Sim-run FAIL (kept best candidate)"))

    mut_compact = None
    want_mut = env_enabled("CHIPSUTRA_MUTATION", "auto", tool_present=has_v)
    if sim_pass and want_mut:
        events.append(_progress("mutation", "Mutation test (parallel Verilator)…"))
        rtl_blob = "\n\n".join(body for _n, body in rtl_sources if body)
        rtl_name = (rtl_sources[0][0] if rtl_sources else "dut.sv") or "dut.sv"
        try:
            if mutation_fn:
                mut = mutation_fn(rtl_blob, tb)
            else:
                from dv_mutation import mutation_test

                mut = mutation_test(
                    rtl_blob,
                    tb,
                    rtl_name=rtl_name,
                    tb_name=tb_name,
                    max_mutants=mutation_max_mutants(),
                )
        except Exception as e:
            mut = {"skipped": True, "reason": str(e)[:200]}
        mut_compact = compact_mutation(mut)
        learning["mutation"] = mut_compact
        kr = (mut_compact or {}).get("kill_rate")
        if kr is not None:
            events.append(
                _progress(
                    "mutation",
                    f"Kill rate {kr} ({(mut_compact or {}).get('killed')}/{(mut_compact or {}).get('total')})",
                    kill_rate=kr,
                )
            )
        elif (mut_compact or {}).get("skipped"):
            events.append(_progress("mutation", "Mutation skipped"))

    evidence = evidence_document(
        dut_name=dut_name or "dut",
        protocol=proto,
        sim_pass=sim_pass,
        mutation=mut_compact,
        analysis=analysis,
        tool_versions=tool_versions,
        notes=[
            "Community evidence pack — Verilator/Yosys/SBY, not vendor sign-off.",
            f"repair_rounds={rounds}",
        ],
    )
    learning["evidence"] = evidence

    if rounds or engine == "skeleton_fallback":
        append_failfix(
            {
                "dut": dut_name,
                "protocol": proto,
                "engine": engine,
                "repair_rounds": rounds,
                "sim_pass": sim_pass,
                "kill_rate": (mut_compact or {}).get("kill_rate"),
                "debug": learning.get("last_debug"),
            }
        )

    return ClosedLoopResult(tb_sv=tb, engine=engine, learning=learning, events=events)
