"""Trial: generate TBs for sample DUTs via ChipSutra skeleton (+ optional LLM) and score them."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rtl_ports import extract_modules
from tb_skeleton import (
    render_randomized_tb,
    detect_counter_model,
    detect_fifo_model,
    detect_parity_model,
    detect_axi_lite_model,
    classify_ports,
)
from tb_lint import lint_testbench, choose_testbench_output, extract_sv
from kg_rating import auto_score_testbench

GOLDEN = ROOT / "knowledge" / "golden"

SAMPLES = {
    "counter_enable": """
module counter_rtl (
    input wire clk,
    input wire rst_n,
    input wire enable,
    output reg [3:0] count
);
endmodule
""",
    "counter_free": (GOLDEN / "counter.sv").read_text(encoding="utf-8") if (GOLDEN / "counter.sv").is_file() else "",
    "fifo": (GOLDEN / "fifo.sv").read_text(encoding="utf-8") if (GOLDEN / "fifo.sv").is_file() else "",
    "axi_lite_slave": (GOLDEN / "axi_lite_slave.sv").read_text(encoding="utf-8") if (GOLDEN / "axi_lite_slave.sv").is_file() else "",
    "parity_byte": """
module parity_byte (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       valid,
    input  wire [7:0] data,
    output reg        parity,
    output reg        valid_out
);
endmodule
""",
}


def review_skeleton(name: str, rtl: str) -> dict:
    mods = extract_modules(rtl)
    if not mods or not mods[0].get("ports"):
        return {"design": name, "ok": False, "error": "parse_failed"}
    mod = mods[0]
    roles = classify_ports(mod["ports"])
    params = mod.get("parameters") or {}
    fifo = detect_fifo_model(roles, params)
    axi = None if fifo else detect_axi_lite_model(roles)
    parity = None if (fifo or axi) else detect_parity_model(roles)
    counter = None if (fifo or axi or parity) else detect_counter_model(roles)
    sv = render_randomized_tb(mod, cycles=32, seed=7)
    ports = [p["name"] for p in mod["ports"]]
    lint_ok, issues = lint_testbench(sv, dut_name=mod["name"], required_ports=ports)
    score = auto_score_testbench(sv, "skeleton", lint_ok, issues)
    has_golden = (
        (bool(counter) and "expected = expected +" in sv)
        or (bool(fifo) and "q[$]" in sv and "empty mismatch" in sv)
        or (bool(parity) and ("^data" in sv or "!== ^" in sv))
        or (bool(axi) and "model_reg" in sv)
    )
    checks = {
        "has_dut": f"{mod['name']} dut" in sv or f"{mod['name']} #" in sv,
        "has_good_clock": "always #" in sv and "~" in sv,
        "has_dump": "$dump" in sv,
        "has_finish": "$finish" in sv,
        "has_urandom": "urandom" in sv,
        "has_independent_golden": has_golden,
        "model": (
            "fifo"
            if fifo
            else "axi_lite"
            if axi
            else "parity"
            if parity
            else "counter"
            if counter
            else "generic"
        ),
        "generic_stimulus_only": not has_golden,
    }
    # Verification readiness rubric
    if lint_ok and checks["has_independent_golden"]:
        verdict = "SOLID"
        note = f"Self-checking randomized TB ({checks['model']} golden) suitable for smoke verification."
    elif lint_ok and checks["generic_stimulus_only"]:
        verdict = "PARTIAL"
        note = "Ports/clock/random OK but no protocol golden — needs model/scoreboard for real verify."
    else:
        verdict = "WEAK"
        note = "Lint/structural gaps — do not use as-is."
    return {
        "design": name,
        "dut": mod["name"],
        "ports": ports,
        "engine": "skeleton",
        "verdict": verdict,
        "note": note,
        "lint_ok": lint_ok,
        "lint_issues": issues,
        "score": score["auto_score"],
        "checks": checks,
        "lines": sv.count("\n") + 1,
        "tb_preview": "\n".join(sv.splitlines()[:25]),
    }


async def review_llm(name: str, rtl: str) -> dict:
    """Optional: ask local Ollama, then quality-gate like production."""
    from generation_rules import (
        rules_for_module,
        default_user_prompt,
        tb_golden_hint_from_ports,
        num_predict_for_module,
    )
    from llm_provider import stream_chat

    mods = extract_modules(rtl)
    if not mods or not mods[0].get("ports"):
        return {"design": name, "engine": "llm", "ok": False, "error": "parse_failed"}
    mod = mods[0]
    ports = [p["name"] for p in mod["ports"]]
    skeleton = render_randomized_tb(mod, cycles=32, seed=7)
    system = (
        "You are ChipSutra-VLSI. Output ONLY SystemVerilog testbench.\n"
        + rules_for_module("testbench", has_ports=True)
    )
    user = default_user_prompt("testbench", dut_hint=f"module {mod['name']}")
    user += f"\n\n--- FILE ---\n{rtl}\n"
    user = (
        "MANDATORY reference (copy structure):\n"
        + skeleton
        + f"\n\nGolden hint: {tb_golden_hint_from_ports(ports)}\n\n"
        + "User request:\n"
        + user
    )
    chunks: list[str] = []
    try:
        async for d in stream_chat(
            "ollama",
            os.environ.get("OLLAMA_MODEL", "chipsutra-vlsi:3b"),
            system,
            user,
            session_id=f"trial-{name}",
            num_predict=num_predict_for_module("testbench"),
        ):
            chunks.append(d)
    except Exception as e:
        return {
            "design": name,
            "dut": mod["name"],
            "engine": "llm",
            "verdict": "ERROR",
            "note": f"Ollama failed: {e}",
            "score": 0,
        }
    raw = "".join(chunks)
    final, engine, issues = choose_testbench_output(
        raw,
        skeleton=skeleton,
        dut_name=mod["name"],
        required_ports=ports,
        force_uvm=False,
    )
    lint_ok, lint_issues = lint_testbench(extract_sv(final) or final, dut_name=mod["name"], required_ports=ports)
    score = auto_score_testbench(final, engine, lint_ok, lint_issues)
    has_golden = (
        "expected = expected +" in final
        or ("q[$]" in final and "empty" in final)
        or "model_reg" in final
        or "!== ^" in final
        or "=== ^" in final
    )
    if engine == "skeleton_fallback":
        note = "LLM failed lint; production gate replaced with template (good for user)."
        verdict = "SOLID" if lint_ok else "PARTIAL"
    elif lint_ok and has_golden and score["auto_score"] >= 80:
        verdict = "SOLID"
        note = f"LLM TB accepted ({engine}) with independent golden."
    elif lint_ok:
        verdict = "PARTIAL"
        note = "LLM lint-ok but weak/missing golden or mid score."
    else:
        verdict = "WEAK"
        note = "LLM output weak."
    return {
        "design": name,
        "dut": mod["name"],
        "engine": engine,
        "verdict": verdict,
        "note": note,
        "lint_ok": lint_ok,
        "lint_issues": lint_issues or issues,
        "score": score["auto_score"],
        "raw_had_circular": "count +" in raw and "expected = expected" not in raw,
        "raw_issues_before_gate": issues if engine != "llm" else [],
        "lines": final.count("\n") + 1,
    }


async def main() -> int:
    os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")
    os.environ.setdefault("OLLAMA_MODEL", "chipsutra-vlsi:3b")
    os.environ.setdefault("OLLAMA_HTTP_TIMEOUT", "120")

    results = []
    print("=== ChipSutra TB trial — SKELETON path (Fast random / Auto) ===\n")
    for name, rtl in SAMPLES.items():
        if not rtl.strip():
            continue
        r = review_skeleton(name, rtl)
        results.append(r)
        print(f"[{r['verdict']}] {name} ({r.get('dut')}) score={r.get('score')} lines={r.get('lines')}")
        print(f"  ports={r.get('ports')}")
        print(f"  {r.get('note')}")
        if r.get("lint_issues"):
            print(f"  lint={r['lint_issues']}")
        print()

    # LLM trials on 2 designs (time-bounded)
    llm_targets = ["counter_enable", "parity_byte"]
    print("=== ChipSutra TB trial — LLM path + quality gate ===\n")
    for name in llm_targets:
        rtl = SAMPLES.get(name) or ""
        if not rtl.strip():
            continue
        r = await review_llm(name, rtl)
        results.append({**r, "path": "llm"})
        print(f"[{r.get('verdict')}] {name} engine={r.get('engine')} score={r.get('score')}")
        print(f"  {r.get('note')}")
        if r.get("lint_issues"):
            print(f"  lint={r['lint_issues']}")
        print()

    solid = sum(1 for r in results if r.get("verdict") == "SOLID")
    partial = sum(1 for r in results if r.get("verdict") == "PARTIAL")
    weak = sum(1 for r in results if r.get("verdict") in ("WEAK", "ERROR"))
    summary = {
        "solid": solid,
        "partial": partial,
        "weak_or_error": weak,
        "total": len(results),
        "results": results,
    }
    out = Path(os.environ.get("TEMP", ".")) / "chipsutra_tb_trial.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("=== SUMMARY ===")
    print(json.dumps({k: summary[k] for k in ("solid", "partial", "weak_or_error", "total")}, indent=2))
    print(f"wrote {out}")
    # Exit 0 even with partials — this is a review harness
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
