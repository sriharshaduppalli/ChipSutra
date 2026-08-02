"""Generate + review TBs for knowledge/samples designs (skeleton + LLM).

Usage:
  python scripts/review_sample_designs.py
  python scripts/review_sample_designs.py --llm-only mux,alu
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rtl_ports import extract_modules
from tb_skeleton import render_randomized_tb
from tb_lint import lint_testbench, choose_testbench_output, extract_sv
from kg_rating import auto_score_testbench
from dv_planner import plan_generation

SAMPLES_DIR = ROOT / "knowledge" / "samples"
OUT_DIR = ROOT / "storage" / "sample_tb_review"


def _has_golden(sv: str) -> bool:
    return any(
        x in sv
        for x in (
            "expected = expected +",
            "q[$]",
            "model_reg",
            "apb_model",
            "mux mismatch",
            "!== ^",
            "=== ^",
        )
    )


def review_sv(name: str, rtl: str, sv: str, engine: str, extra: dict | None = None) -> dict:
    mods = extract_modules(rtl)
    mod = mods[0]
    ports = [p["name"] for p in mod["ports"]]
    plan = plan_generation(module="testbench", gen_mode="skeleton", modules=mods, rtl_text=rtl)
    lint_ok, issues = lint_testbench(extract_sv(sv) or sv, dut_name=mod["name"], required_ports=ports)
    score = auto_score_testbench(sv, engine, lint_ok, issues)
    golden = _has_golden(sv)
    proto = plan["protocol_pack"]
    if lint_ok and golden:
        verdict = "SOLID"
    elif lint_ok and (proto in ("generic", "stream") or "$isunknown" in sv):
        verdict = "PARTIAL"
    elif lint_ok:
        verdict = "PARTIAL"
    else:
        verdict = "WEAK"
    return {
        "design": name,
        "dut": mod["name"],
        "protocol": proto,
        "engine": engine,
        "verdict": verdict,
        "lint_ok": lint_ok,
        "lint_issues": issues,
        "score": score["auto_score"],
        "has_golden": golden,
        "has_dump": "$dump" in sv,
        "has_finish": "$finish" in sv,
        "has_urandom": "urandom" in sv.lower(),
        "lines": sv.count("\n") + 1,
        **(extra or {}),
    }


async def llm_tb(name: str, rtl: str) -> tuple[str, str, list, str]:
    from generation_rules import (
        rules_for_module,
        default_user_prompt,
        tb_golden_hint_from_ports,
        num_predict_for_module,
    )
    from llm_provider import stream_chat

    mods = extract_modules(rtl)
    mod = mods[0]
    ports = [p["name"] for p in mod["ports"]]
    skeleton = render_randomized_tb(mod, cycles=32, seed=11)
    system = (
        "You are ChipSutra-VLSI. Output ONLY SystemVerilog testbench.\n"
        + rules_for_module("testbench", has_ports=True)
    )
    user = default_user_prompt("testbench", dut_hint=f"module {mod['name']}")
    user += f"\n\n--- FILE: {name}.sv ---\n{rtl}\n"
    user = (
        "MANDATORY reference (copy structure; keep exact ports):\n"
        + skeleton
        + f"\n\nGolden hint: {tb_golden_hint_from_ports(ports)}\n\n"
        + "User request:\n"
        + user
    )
    chunks: list[str] = []
    async for d in stream_chat(
        "ollama",
        os.environ.get("OLLAMA_MODEL", "chipsutra-vlsi:3b"),
        system,
        user,
        session_id=f"sample-review-{name}",
        num_predict=num_predict_for_module("testbench"),
    ):
        chunks.append(d)
    raw = "".join(chunks)
    final, engine, issues = choose_testbench_output(
        raw,
        skeleton=skeleton,
        dut_name=mod["name"],
        required_ports=ports,
        force_uvm=False,
    )
    return final, engine, issues, raw


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--llm-only", default="", help="comma names without sample_ prefix, e.g. counter,mux2,alu")
    args = ap.parse_args()

    os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")
    os.environ.setdefault("OLLAMA_MODEL", "chipsutra-vlsi:3b")
    os.environ.setdefault("OLLAMA_HTTP_TIMEOUT", "300")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(SAMPLES_DIR.glob("sample_*.sv"))
    if not files:
        print(f"No samples in {SAMPLES_DIR}")
        return 1

    want_llm = None
    if args.llm_only.strip():
        want_llm = {f"sample_{x.strip()}" for x in args.llm_only.split(",") if x.strip()}

    results = []
    print("=== Sample designs → Fast-random skeleton ===\n")
    for path in files:
        name = path.stem
        rtl = path.read_text(encoding="utf-8")
        mods = extract_modules(rtl)
        if not mods:
            print(f"[FAIL] parse {name}")
            continue
        sk = render_randomized_tb(mods[0], cycles=32, seed=11)
        (OUT_DIR / f"{name}_skeleton_tb.sv").write_text(sk, encoding="utf-8")
        r = review_sv(name, rtl, sk, "skeleton")
        results.append(r)
        print(
            f"[{r['verdict']}] {name:16} proto={r['protocol']:8} "
            f"score={r['score']} golden={r['has_golden']} lines={r['lines']}"
        )
        if r["lint_issues"]:
            print(f"  lint={r['lint_issues']}")

    if not args.skip_llm:
        print("\n=== Sample designs → LLM (chipsutra-vlsi:3b) + quality gate ===\n")
        for path in files:
            name = path.stem
            if want_llm is not None and name not in want_llm:
                continue
            rtl = path.read_text(encoding="utf-8")
            print(f"… LLM generating for {name} (may take 1–3 min)…")
            try:
                final, engine, gate_issues, raw = await llm_tb(name, rtl)
            except Exception as e:
                results.append(
                    {
                        "design": name,
                        "engine": "llm",
                        "verdict": "ERROR",
                        "note": str(e),
                        "score": 0,
                    }
                )
                print(f"[ERROR] {name}: {e}\n")
                continue
            (OUT_DIR / f"{name}_llm_raw.txt").write_text(raw, encoding="utf-8")
            (OUT_DIR / f"{name}_llm_tb.sv").write_text(final, encoding="utf-8")
            r = review_sv(
                name,
                rtl,
                final,
                engine,
                extra={"gate_issues": gate_issues, "raw_chars": len(raw)},
            )
            results.append({**r, "path": "llm"})
            print(
                f"[{r['verdict']}] {name:16} engine={engine:18} "
                f"score={r['score']} golden={r['has_golden']} lines={r['lines']}"
            )
            if r["lint_issues"]:
                print(f"  lint={r['lint_issues']}")
            print()

    summary = {
        "samples_dir": str(SAMPLES_DIR),
        "out_dir": str(OUT_DIR),
        "solid": sum(1 for r in results if r.get("verdict") == "SOLID"),
        "partial": sum(1 for r in results if r.get("verdict") == "PARTIAL"),
        "weak_or_error": sum(1 for r in results if r.get("verdict") in ("WEAK", "ERROR")),
        "total": len(results),
        "results": results,
    }
    report = OUT_DIR / "review_report.json"
    report.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("=== SUMMARY ===")
    print(json.dumps({k: summary[k] for k in ("solid", "partial", "weak_or_error", "total", "out_dir")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
