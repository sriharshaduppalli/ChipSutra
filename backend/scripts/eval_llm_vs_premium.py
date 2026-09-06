"""Cross-check ChipSutra-VLSI TB generation vs premium-quality reference TBs.

Generates class-based Pure SV TBs via Ollama (chipsutra-vlsi:7b), applies the
same lint/repair gate as the product, scores both ChipSutra and premium refs.

Usage:
  python scripts/eval_llm_vs_premium.py
  python scripts/eval_llm_vs_premium.py --limit 2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Prefer backend/tools Verilator shim (WSL) when not already on PATH
_TOOLS = ROOT / "tools"
if _TOOLS.is_dir():
    os.environ["PATH"] = str(_TOOLS) + os.pathsep + os.environ.get("PATH", "")

from rtl_ports import extract_modules  # noqa: E402
from tb_lint import choose_testbench_output, extract_sv  # noqa: E402
from tb_class_lint import score_class_sv_competitive, lint_class_sv_tb  # noqa: E402
from dv_planner import classify_dut  # noqa: E402
from llm_provider import ollama_runtime_options  # noqa: E402

SUITE = Path(__file__).resolve().parent / "eval_suite"
DUTS = SUITE / "duts"
PREMIUM = SUITE / "premium_refs"
OUT = SUITE / "chipsutra_out"

OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# llm_provider (used by the LLM repair pass) reads OLLAMA_URL at import time
os.environ.setdefault("OLLAMA_URL", OLLAMA)
MODEL = os.environ.get("OLLAMA_MODEL", "chipsutra-vlsi:7b")

SYSTEM = """You are ChipSutra-VLSI. Output ONLY SystemVerilog for a class-based Pure SV
testbench (NO uvm_*). Declare EVERY DUT port as logic with correct widths.
txn class + scoreboard (function void predict, function bit check); always #5 clk=~clk;
txn=new(); sb=new(); errors=0; real constraints (never {1;}); @(posedge clk) after reset,
then CHECK outputs are at reset values before the stimulus loop.
Goldens must be INDEPENDENT of DUT outputs; for FIFOs use a q[$] queue and check
count===q.size() (never a separate +/- counter).
CLASS SCOPING: class methods may reference ONLY their own arguments and members —
pass txn fields as arguments (sb.predict(txn.addr, txn.data)), never bare.
Declare all variables before any statement in a block, never mid-block.
$dumpfile/$dumpvars/$finish; ONE PASS/FAIL at end. Exact DUT port map from the RTL.
Connect ONLY pins the DUT declares — no invented clk/rst pins on combinational DUTs.
Scoreboard: declare `expected` (or pass args into check); module-level `errors++` only.
FIFO: after randomize clamp wr/rd vs sb.q.size(); do not check rd_data==='0 after reset;
after the loop pulse reset and check empty===1.
ALWAYS close with endmodule — never stop mid-assignment.
After stimulus, mid-test reset then check key outputs === '0 (kills drop_reset)."""


CASES = [
    ("counter_en", "counter_en.sv", "counter_en_tb.sv", "counter"),
    ("sync_fifo8", "sync_fifo8.sv", "sync_fifo8_tb.sv", "fifo"),
    ("sample_parity", "sample_parity.sv", "sample_parity_tb.sv", "parity"),
    ("mux2_8", "mux2_8.sv", "mux2_8_tb.sv", "mux"),
    ("apb_regs", "apb_regs.sv", "apb_regs_tb.sv", "apb"),
    ("axi_lite_slave", "axi_lite_slave.sv", "axi_lite_slave_tb.sv", "axi_lite"),
    ("axis_sink", "axis_sink.sv", "axis_sink_tb.sv", "axis"),
    ("ahb_slave", "ahb_slave.sv", "ahb_slave_tb.sv", "ahb"),
    ("spi_slave", "spi_slave.sv", "spi_slave_tb.sv", "spi"),
    ("i2c_slave", "i2c_slave.sv", "i2c_slave_tb.sv", "i2c"),
    ("uart_tx", "uart_tx.sv", "uart_tx_tb.sv", "uart"),
    ("alu4", "alu4.sv", "alu4_tb.sv", "alu"),
    ("shifter8", "shifter8.sv", "shifter8_tb.sv", "shifter"),
    ("edge_detect", "edge_detect.sv", "edge_detect_tb.sv", "edge"),
    ("sync_ff", "sync_ff.sv", "sync_ff_tb.sv", "cdc"),
    ("prio_enc4", "prio_enc4.sv", "prio_enc4_tb.sv", "encoder"),
    ("gray2bin4", "gray2bin4.sv", "gray2bin4_tb.sv", "gray"),
    ("bin2gray4", "bin2gray4.sv", "bin2gray4_tb.sv", "gray"),
    ("debounce", "debounce.sv", "debounce_tb.sv", "debounce"),
    ("pwm8", "pwm8.sv", "pwm8_tb.sv", "pwm"),
]

# Protocols where the reference (and often the best TB) is procedural, not class-based
_PROCEDURAL_PROTOCOLS = {
    "apb",
    "axi_lite",
    "axis",
    "ahb",
    "spi",
    "i2c",
    "uart",
    "alu",
    "shifter",
    "edge",
    "cdc",
    "encoder",
    "gray",
    "debounce",
    "pwm",
}


def score_procedural(sv: str, mods: list, ports: list, protocol: str = "generic") -> dict:
    """Lint-based score for procedural TBs (class rubric does not apply).

    Directed protocol smokes (AXI/APB) legitimately have no $urandom.
    """
    from tb_lint import lint_testbench
    from tb_semantic import lint_semantic_golden

    _ok, iss = lint_testbench(
        sv, dut_name=(mods[0]["name"] if mods else None), required_ports=ports
    )
    iss = [i for i in iss if i != "missing_urandom"]
    sem = lint_semantic_golden(sv, protocol=protocol)
    iss = list(dict.fromkeys(list(iss) + sem))
    ok = not iss
    return {
        "ok": ok,
        "score": 90 if ok else 60,
        "premium_bar": ok,
        "issues": iss,
        "checks": {"procedural": True},
    }


def ollama_generate(
    rtl: str, dut_name: str, protocol: str = "generic", port_names: list | None = None
) -> tuple[str, float]:
    style = (
        "a procedural Pure SV smoke testbench with handshake tasks"
        if protocol in _PROCEDURAL_PROTOCOLS
        else "a class-based Pure SV testbench"
    )
    # Same DUT-class hint + golden reference the production server injects
    from generation_rules import golden_ref_for_protocol, tb_golden_hint_from_ports

    hint = tb_golden_hint_from_ports(port_names or [])
    gold = golden_ref_for_protocol(protocol)
    gold_block = (
        f"\nGOLD reference TB for this protocol class (adapt module/port names to "
        f"THIS DUT exactly):\n{gold}\n"
        if gold
        else ""
    )
    user = f"Generate {style} (NO UVM) for this DUT.\n{hint}\n{gold_block}\n{rtl.strip()}\n"
    # Bus-protocol TBs (AXI/APB) are long — give them more headroom
    num_predict = 2400 if protocol in _PROCEDURAL_PROTOCOLS else 1100
    t0 = time.time()
    r = requests.post(
        f"{OLLAMA}/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": "30m",
            "options": {
                **ollama_runtime_options(num_predict=num_predict),
                "temperature": 0.08,
                "repeat_penalty": 1.12,
            },
        },
        timeout=900,
    )
    r.raise_for_status()
    text = (r.json().get("message") or {}).get("content") or ""
    return text, time.time() - t0


def score_tb(sv: str, mods: list, protocol: str) -> dict:
    if not mods:
        return {"ok": False, "score": 0, "premium_bar": False, "issues": ["no_parse"]}
    ports = [p["name"] for p in mods[0].get("ports") or [] if p.get("name")]
    outs = [
        p["name"]
        for p in mods[0].get("ports") or []
        if (p.get("direction") or "").lower() in ("output", "out", "inout")
    ]
    specs = list(mods[0].get("ports") or [])
    return score_class_sv_competitive(
        sv,
        required_ports=ports,
        dut_outputs=outs,
        protocol=protocol,
        port_specs=specs,
    )


def run_case(name: str, dut_file: str, prem_file: str, protocol: str) -> dict:
    rtl = (DUTS / dut_file).read_text(encoding="utf-8")
    prem = (PREMIUM / prem_file).read_text(encoding="utf-8")
    mods = extract_modules(rtl)
    ports = [p["name"] for p in (mods[0].get("ports") if mods else []) or [] if p.get("name")]
    outs = [
        p["name"]
        for p in (mods[0].get("ports") if mods else []) or []
        if (p.get("direction") or "").lower() in ("output", "out", "inout")
    ]
    specs = list((mods[0].get("ports") if mods else []) or [])
    plan = classify_dut(mods, rtl_text=rtl)
    proto_eff = protocol or plan.get("protocol") or "generic"
    skeleton = ""
    try:
        from tb_skeleton import render_randomized_tb, render_class_sv_tb

        if proto_eff in _PROCEDURAL_PROTOCOLS:
            skeleton = render_randomized_tb(mods[0], cycles=48) if mods else ""
        else:
            skeleton = render_class_sv_tb(mods[0], cycles=32) if mods else ""
    except Exception:
        skeleton = ""

    raw, latency = ollama_generate(rtl, mods[0]["name"] if mods else name, protocol, ports)
    final, engine, issues = choose_testbench_output(
        raw,
        skeleton=skeleton,
        dut_name=(mods[0]["name"] if mods else None),
        required_ports=ports or None,
        dut_outputs=outs or None,
        force_uvm=False,
        protocol=protocol or plan.get("protocol") or "generic",
        port_specs=specs or None,
    )
    final = extract_sv(final) or final
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}_tb.sv").write_text(final, encoding="utf-8")
    (OUT / f"{name}_raw.txt").write_text(raw, encoding="utf-8")

    import re as _re

    if protocol in _PROCEDURAL_PROTOCOLS and not _re.search(r"\bclass\b", final or ""):
        cs = score_procedural(final, mods, ports, protocol)
    else:
        cs = score_tb(final, mods, protocol)
    if protocol in _PROCEDURAL_PROTOCOLS:
        ps = score_procedural(prem, mods, ports, protocol)
    else:
        ps = score_tb(prem, mods, protocol)

    # Sim-run proof (Verilator --binary): does the TB actually PASS?
    # Mirrors production: on failure, one LLM repair pass fed real evidence.
    sim_pass = None
    try:
        from dv_verify import verify_testbench, verilator_bin

        if verilator_bin():
            vr = verify_testbench(
                [(dut_file, rtl)], final, tb_name=f"{name}_tb.sv", mode="run"
            )
            sim_pass = vr.get("sim_pass")
            repair_passes = int(os.environ.get("CHIPSUTRA_COMPILER_REPAIR_PASSES", "2"))
            for _pass in range(repair_passes):
                if vr.get("ok"):
                    break
                import asyncio

                from tb_llm_repair import llm_repair_class_sv

                evidence = list(vr.get("errors") or [])[:8]
                evidence += [
                    ln for ln in (vr.get("sim_log") or "").splitlines() if "FAIL" in ln
                ][:3]
                cand_raw, oks = asyncio.run(
                    llm_repair_class_sv(
                        provider="ollama",
                        model=MODEL,
                        broken_sv=final,
                        issues=list(cs.get("issues") or []),
                        dut_hint=f"{mods[0]['name'] if mods else name} ports={','.join(ports[:20])}",
                        compiler_errors=evidence,
                    )
                )
                if not (oks and cand_raw):
                    break
                from tb_class_lint import repair_class_sv_tb

                cand = extract_sv(cand_raw) or cand_raw
                cand = repair_class_sv_tb(
                    cand, required_ports=ports or None, dut_outputs=outs or None,
                    port_specs=specs or None,
                    dut_name=(mods[0]["name"] if mods else None),
                )
                vr2 = verify_testbench(
                    [(dut_file, rtl)], cand, tb_name=f"{name}_tb.sv", mode="run"
                )
                # Adopt when the gate passes, or on real partial progress:
                # complete module, parse didn't halt, strictly fewer errors.
                errs2 = vr2.get("errors") or []
                partial_ok = (
                    "endmodule" in cand
                    and not any("Cannot continue" in e for e in errs2)
                    and len(errs2) < len(vr.get("errors") or [])
                )
                if vr2.get("ok") or partial_ok:
                    final, engine, vr = cand, "llm_repaired", vr2
                    sim_pass = vr2.get("sim_pass")
                    (OUT / f"{name}_tb.sv").write_text(final, encoding="utf-8")
                    if protocol in _PROCEDURAL_PROTOCOLS and not _re.search(
                        r"\bclass\b", final or ""
                    ):
                        cs = score_procedural(final, mods, ports, protocol)
                    else:
                        cs = score_tb(final, mods, protocol)
                else:
                    break
    except Exception:
        pass
    delta = int(cs.get("score") or 0) - int(ps.get("score") or 0)
    if sim_pass is True and cs.get("ok"):
        verdict = (
            "match_or_beat"
            if (cs.get("score") or 0) >= (ps.get("score") or 0) - 5
            else "close"
        )
    elif sim_pass is False or sim_pass is None:
        verdict = "behind"
    else:
        verdict = (
            "match_or_beat"
            if (cs.get("score") or 0) >= (ps.get("score") or 0) - 5 and cs.get("ok")
            else "behind"
            if (cs.get("score") or 0) < (ps.get("score") or 0) - 10
            else "close"
        )
    return {
        "design": name,
        "protocol": protocol,
        "model": MODEL,
        "latency_s": round(latency, 2),
        "engine": engine,
        "sim_pass": sim_pass,
        "chipsutra": {
            "score": cs.get("score"),
            "ok": cs.get("ok"),
            "premium_bar": cs.get("premium_bar"),
            "issues": (cs.get("issues") or [])[:8],
        },
        "premium_ref": {
            "score": ps.get("score"),
            "ok": ps.get("ok"),
            "premium_bar": ps.get("premium_bar"),
            "issues": (ps.get("issues") or [])[:8],
        },
        "score_delta": delta,
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="", help="comma-separated design names")
    args = ap.parse_args()
    cases = CASES[: args.limit] if args.limit else CASES
    if args.only:
        wanted = {n.strip() for n in args.only.split(",") if n.strip()}
        cases = [c for c in CASES if c[0] in wanted]
    results = []
    print(f"Model={MODEL} Ollama={OLLAMA} cases={len(cases)}\n")
    for name, dut, prem, proto in cases:
        print(f"=== {name} ({proto}) ===")
        try:
            row = run_case(name, dut, prem, proto)
            results.append(row)
            print(
                f"  ChipSutra score={row['chipsutra']['score']} ok={row['chipsutra']['ok']} "
                f"bar={row['chipsutra']['premium_bar']} engine={row['engine']} "
                f"sim_pass={row.get('sim_pass')} t={row['latency_s']}s"
            )
            print(
                f"  Premium   score={row['premium_ref']['score']} ok={row['premium_ref']['ok']} "
                f"delta={row['score_delta']} verdict={row['verdict']}"
            )
            if row["chipsutra"]["issues"]:
                print(f"  issues: {row['chipsutra']['issues']}")
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"design": name, "error": str(e)[:240], "verdict": "error"})

    out_json = SUITE / "comparison_results.json"
    summary = {
        "model": MODEL,
        "cases": results,
        "n_match": sum(1 for r in results if r.get("verdict") == "match_or_beat"),
        "n_close": sum(1 for r in results if r.get("verdict") == "close"),
        "n_behind": sum(1 for r in results if r.get("verdict") == "behind"),
        "n_error": sum(1 for r in results if r.get("verdict") == "error"),
        "avg_chipsutra": round(
            sum(r.get("chipsutra", {}).get("score") or 0 for r in results if "chipsutra" in r)
            / max(1, sum(1 for r in results if "chipsutra" in r)),
            1,
        ),
        "avg_premium": round(
            sum(r.get("premium_ref", {}).get("score") or 0 for r in results if "premium_ref" in r)
            / max(1, sum(1 for r in results if "premium_ref" in r)),
            1,
        ),
        "avg_latency_s": round(
            sum(r.get("latency_s") or 0 for r in results if "latency_s" in r)
            / max(1, sum(1 for r in results if "latency_s" in r)),
            2,
        ),
    }
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote {out_json}")
    print(
        f"Summary: match={summary['n_match']} close={summary['n_close']} "
        f"behind={summary['n_behind']} err={summary['n_error']} "
        f"avg CS={summary['avg_chipsutra']} prem={summary['avg_premium']} "
        f"latency={summary['avg_latency_s']}s"
    )
    return 0 if summary["n_error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
