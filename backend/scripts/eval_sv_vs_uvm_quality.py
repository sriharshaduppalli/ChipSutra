"""Cross-check Pure SV vs UVM TB generate on sample DUTs (product lint gate).

Usage (from backend/):
  .venv\\Scripts\\python.exe scripts/eval_sv_vs_uvm_quality.py
  .venv\\Scripts\\python.exe scripts/eval_sv_vs_uvm_quality.py --limit 1
  .venv\\Scripts\\python.exe scripts/eval_sv_vs_uvm_quality.py --skeleton-only --sim
  .venv\\Scripts\\python.exe scripts/eval_sv_vs_uvm_quality.py --skip-existing
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")
os.environ.setdefault("PYTHONUNBUFFERED", "1")
_TOOLS = ROOT / "tools"
if _TOOLS.is_dir():
    os.environ["PATH"] = str(_TOOLS) + os.pathsep + os.environ.get("PATH", "")

from generation_rules import (  # noqa: E402
    default_user_prompt,
    num_predict_for_module,
    rules_for_module,
    style_ref_for_protocol,
    tb_golden_hint_from_ports,
)
from llm_provider import ollama_runtime_options  # noqa: E402
from rtl_ports import extract_modules  # noqa: E402
from tb_class_lint import lint_class_sv_tb, score_class_sv_competitive  # noqa: E402
from tb_lint import choose_testbench_output, extract_sv  # noqa: E402
from tb_semantic import lint_semantic_golden  # noqa: E402
from tb_skeleton import (  # noqa: E402
    classify_ports,
    detect_apb_model,
    detect_axi_lite_model,
    detect_fifo_model,
    detect_mux_model,
    detect_parity_model,
    detect_stream_model,
    detect_switch_model,
    detect_counter_model,
    render_class_sv_tb,
)
from tb_uvm_lint import lint_uvm_tb  # noqa: E402
from tb_uvm_skeleton import render_uvm_smoke_tb  # noqa: E402

DUTS = Path(__file__).resolve().parent / "eval_suite" / "duts"
OUT = Path(__file__).resolve().parent / "eval_suite" / "sv_vs_uvm_out"
SKEL_OUT = OUT / "skeleton"
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL = os.environ.get("OLLAMA_MODEL", "chipsutra-vlsi:7b")

CASES = [
    ("counter_en", "counter_en.sv", "counter"),
    ("mux2_8", "mux2_8.sv", "mux"),
    ("mux_4to1", "mux_4to1.sv", "mux"),
    ("sync_fifo8", "sync_fifo8.sv", "fifo"),
    ("sample_parity", "sample_parity.sv", "parity"),
    ("alu4", "alu4.sv", "alu"),
    ("prio_enc4", "prio_enc4.sv", "encoder"),
    ("shifter8", "shifter8.sv", "shifter"),
    ("gray2bin4", "gray2bin4.sv", "gray"),
    ("bin2gray4", "bin2gray4.sv", "gray"),
    ("edge_detect", "edge_detect.sv", "edge"),
    ("pwm8", "pwm8.sv", "pwm"),
    ("sync_ff", "sync_ff.sv", "cdc"),
    ("debounce", "debounce.sv", "debounce"),
    ("apb_regs", "apb_regs.sv", "apb"),
    ("axi_lite_slave", "axi_lite_slave.sv", "axi_lite"),
    ("axis_sink", "axis_sink.sv", "axis"),
    ("ahb_slave", "ahb_slave.sv", "ahb"),
    ("spi_slave", "spi_slave.sv", "spi"),
    ("i2c_slave", "i2c_slave.sv", "i2c"),
    ("uart_tx", "uart_tx.sv", "uart"),
]


def detect_skel_kind(mod: dict) -> str:
    roles = classify_ports(mod.get("ports") or [])
    params = mod.get("parameters") or {}
    if detect_fifo_model(roles, params):
        return "fifo"
    if detect_switch_model(roles):
        return "switch"
    if detect_mux_model(roles):
        return "mux"
    if detect_parity_model(roles):
        return "parity"
    if detect_axi_lite_model(roles):
        return "axi_lite"
    if detect_apb_model(roles):
        return "apb"
    if detect_stream_model(roles):
        return "stream"
    if detect_counter_model(roles):
        return "counter"
    try:
        from tb_dut_goldens import (
            detect_alu_model,
            detect_edge_model,
            detect_gray_model,
            detect_prio_enc_model,
            detect_shifter_model,
        )

        if detect_alu_model(roles):
            return "alu"
        if detect_prio_enc_model(roles):
            return "encoder"
        if detect_shifter_model(roles):
            return "shifter"
        if detect_gray_model(roles):
            return "gray"
        if detect_edge_model(roles):
            return "edge"
    except Exception:
        pass
    return "generic"


def _golden_flags(sv: str) -> dict:
    return {
        "q_queue": bool(re.search(r"\bq\s*\[\s*\$\s*\]", sv)),
        "xor_parity": bool(re.search(r"\^", sv)) and bool(re.search(r"\bparity\b", sv, re.I)),
        "mux_select": bool(re.search(r"\?\s*\w+\s*:\s*\w+|case\s*\(\s*\w*sel", sv, re.I)),
        "noop_check": bool(
            re.search(r"function\s+bit\s+check\s*\(\s*\)\s*;\s*return\s+1\s*;", sv, re.I)
        ),
        "beats_plus": "beats++" in sv.replace(" ", ""),
        "model_reg": bool(re.search(r"\bmodel_reg\b|\bregs\s*\[", sv, re.I)),
        "seen_plus": bool(re.search(r"\bseen\s*\+\+", sv)),
    }


def _mix_flags(sv: str, meth: str) -> list[str]:
    flags: list[str] = []
    if meth == "sv":
        if re.search(r"\b(uvm_|import\s+uvm_pkg|run_test\s*\()", sv, re.I):
            flags.append("uvm_in_pure_sv")
    else:
        if re.search(r"\bclass\s+\w*generator\b", sv, re.I):
            flags.append("generator_in_uvm")
        if re.search(r"\bmailbox\s*(?:#\s*\([^)]*\))?\s*gen2drv\b", sv, re.I):
            flags.append("mailbox_gen2drv_in_uvm")
    nmod = len(re.findall(r"\bmodule\s+\w+", sv, re.I))
    if nmod != 1:
        flags.append(f"module_count:{nmod}")
    if re.search(r"\bmodule\b", sv, re.I) and not re.search(r"\bendmodule\b", sv, re.I):
        flags.append("truncated_module")
    return flags


def _shape_sv(sv: str) -> dict:
    return {
        "interface": bool(re.search(r"\binterface\b", sv, re.I)),
        "generator": bool(re.search(r"\bclass\s+\w*generator\b", sv, re.I)),
        "mailbox": bool(re.search(r"\bmailbox\b", sv, re.I)),
        "driver": bool(re.search(r"\bclass\s+\w*driver\b", sv, re.I)),
        "monitor": bool(re.search(r"\bclass\s+\w*monitor\b", sv, re.I)),
        "scoreboard": bool(re.search(r"\bclass\s+\w*scoreboard\b", sv, re.I)),
        "env": bool(re.search(r"\bclass\s+\w*env\b", sv, re.I)),
        "no_uvm": not bool(re.search(r"\buvm_", sv, re.I)),
    }


def _shape_uvm(sv: str) -> dict:
    return {
        "sequence_item": bool(re.search(r"\bextends\s+uvm_sequence_item\b", sv, re.I)),
        "sequencer": bool(re.search(r"\buvm_sequencer\b", sv, re.I)),
        "get_next_item": "get_next_item" in sv,
        "item_done": "item_done" in sv,
        "analysis_port": bool(re.search(r"\buvm_analysis_port\b", sv, re.I)),
        "analysis_imp": bool(re.search(r"\buvm_analysis_imp\b", sv, re.I)),
        "connect_phase": bool(re.search(r"\bconnect_phase\b", sv, re.I)),
        "run_test": bool(re.search(r"\brun_test\s*\(", sv)),
        "objection": "raise_objection" in sv,
        "no_generator": not bool(re.search(r"\bclass\s+\w*generator\b", sv, re.I)),
        "monitor_not_subscriber": not bool(
            re.search(r"\bclass\s+\w*monitor\w*\s+extends\s+uvm_subscriber\b", sv, re.I)
        ),
    }


def generate(rtl: str, dut: str, protocol: str, meth: str, ports: list, hint_tb: str) -> tuple[str, float]:
    system = rules_for_module("testbench", has_ports=True, tb_methodology=meth)
    user = default_user_prompt("testbench", dut_hint=f"module {dut}", tb_methodology=meth)
    hint = tb_golden_hint_from_ports(ports)
    style = style_ref_for_protocol(protocol, hint_tb, methodology=meth)
    user = (
        f"{user}\n{hint}\n\n"
        f"STYLE REFERENCE (adapt names to THIS DUT; honor methodology={meth}):\n{style}\n\n"
        f"DUT RTL:\n{rtl.strip()}\n"
    )
    npred = num_predict_for_module("testbench", tb_methodology=meth, protocol=protocol)
    t0 = time.time()
    r = requests.post(
        f"{OLLAMA}/api/chat",
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": "45m",
            "options": {
                **ollama_runtime_options(num_predict=npred),
                "temperature": 0.10,
                "repeat_penalty": 1.06,
            },
        },
        timeout=int(os.environ.get("CHIPSUTRA_EVAL_LLM_TIMEOUT", "180")),
    )
    r.raise_for_status()
    text = (r.json().get("message") or {}).get("content") or ""
    return text, time.time() - t0


def run_one(
    name: str,
    dut_file: str,
    protocol: str,
    meth: str,
    *,
    skeleton_only: bool = False,
    do_sim: bool = False,
) -> dict:
    rtl = (DUTS / dut_file).read_text(encoding="utf-8")
    mods = extract_modules(rtl)
    if not mods:
        return {"design": name, "methodology": meth, "error": "parse_fail"}
    ports = [p["name"] for p in mods[0].get("ports") or [] if p.get("name")]
    specs = list(mods[0].get("ports") or [])
    outs = [
        p["name"]
        for p in specs
        if (p.get("direction") or "").lower() in ("output", "out", "inout")
    ]
    skel_kind = detect_skel_kind(mods[0])
    if meth == "uvm":
        skel = render_uvm_smoke_tb(mods[0], cycles=12)
    else:
        skel = render_class_sv_tb(mods[0], cycles=16, seed=1)

    print(f"\n=== {name} methodology={meth} protocol={protocol} kind={skel_kind} ===", flush=True)
    issues: list = []
    if skeleton_only:
        sv = skel
        engine = "skeleton"
        raw = ""
        latency = 0.0
    else:
        try:
            raw, latency = generate(rtl, mods[0]["name"], protocol, meth, ports, skel)
        except Exception as e:
            print(f"  LLM failed ({e}); using skeleton", flush=True)
            raw, latency = "", 0.0
            sv = skel
            engine = "timeout_skeleton"
            issues = [f"llm_error:{type(e).__name__}"]
            # Fall through to lint the skeleton
            final = skel
        else:
            final, engine, issues = choose_testbench_output(
                raw,
                skeleton=skel,
                dut_name=mods[0]["name"],
                required_ports=ports,
                dut_outputs=outs,
                force_uvm=(meth == "uvm"),
                protocol=protocol,
                port_specs=specs,
            )
        sv = extract_sv(final) or final
    mix = _mix_flags(sv, meth)
    golden = _golden_flags(sv)
    sem = lint_semantic_golden(sv, protocol=protocol)
    if meth == "uvm":
        ok, lint_issues = lint_uvm_tb(sv, port_specs=specs)
        shape = _shape_uvm(sv)
        shape_ok = all(shape.values())
    else:
        ok, lint_issues = lint_class_sv_tb(
            sv,
            dut_name=mods[0]["name"],
            required_ports=ports,
            dut_outputs=outs,
            protocol=protocol,
            port_specs=specs,
        )
        shape = _shape_sv(sv)
        shape_ok = all(shape.values())
        _ = score_class_sv_competitive(
            sv, required_ports=ports, dut_outputs=outs, protocol=protocol, port_specs=specs
        )

    sim_pass = None
    sim_reason = None
    if do_sim and meth == "sv":
        try:
            from dv_verify import verify_testbench

            r = verify_testbench(
                [(dut_file, rtl)], sv, tb_name=f"{mods[0]['name']}_tb.sv", mode="run"
            )
            sim_pass = r.get("sim_pass")
            sim_reason = r.get("reason")
            if r.get("skipped"):
                sim_reason = "skipped"
        except Exception as e:
            sim_pass = False
            sim_reason = str(e)[:160]

    if ok and shape_ok and not mix and (sim_pass is not False):
        verdict = "solid"
    elif ok and not mix:
        verdict = "usable"
    else:
        verdict = "needs_work"
    if golden.get("noop_check") or golden.get("beats_plus"):
        if skel_kind == "generic":
            verdict = "generic_golden" if ok else verdict
        else:
            verdict = "needs_work"

    dest = SKEL_OUT if skeleton_only else OUT
    dest.mkdir(parents=True, exist_ok=True)
    if raw:
        (dest / f"{name}_{meth}_raw.txt").write_text(raw, encoding="utf-8")
    (dest / f"{name}_{meth}_tb.sv").write_text(sv, encoding="utf-8")

    report = {
        "design": name,
        "methodology": meth,
        "protocol": protocol,
        "skel_kind": skel_kind,
        "model": MODEL if not skeleton_only else "skeleton",
        "latency_s": round(latency, 1),
        "engine": engine,
        "lint_ok": ok,
        "lint_issues": lint_issues[:8],
        "semantic": sem[:8],
        "gate_issues": (issues or [])[:8],
        "golden": golden,
        "mix": mix,
        "shape": shape,
        "shape_ok": shape_ok,
        "sim_pass": sim_pass,
        "sim_reason": sim_reason,
        "verdict": verdict,
        "lines": sv.count("\n") + 1,
    }
    print(
        f"  engine={engine} lint_ok={ok} shape_ok={shape_ok} kind={skel_kind} "
        f"sim={sim_pass} mix={mix or '-'} verdict={verdict} {latency:.0f}s",
        flush=True,
    )
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", action="append", default=[], help="Design name (repeatable)")
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--skeleton-only", action="store_true")
    ap.add_argument("--sim", action="store_true", help="Verilator run for Pure SV")
    args = ap.parse_args()
    cases = CASES[: args.limit] if args.limit else list(CASES)
    if args.only:
        want = {n.lower() for n in args.only}
        cases = [c for c in cases if c[0].lower() in want]
    rows = []
    dest = SKEL_OUT if args.skeleton_only else OUT
    dest.mkdir(parents=True, exist_ok=True)
    report_path = dest / "report.json"
    if args.skip_existing and report_path.is_file() and not args.skeleton_only:
        try:
            rows = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            rows = []
    done = {(r.get("design"), r.get("methodology")) for r in rows if r.get("design")}
    for name, fn, proto in cases:
        for meth in ("sv", "uvm"):
            out_tb = dest / f"{name}_{meth}_tb.sv"
            if args.skip_existing and ((name, meth) in done or out_tb.is_file()):
                print(f"skip {name} {meth}", flush=True)
                continue
            try:
                rows.append(
                    run_one(
                        name,
                        fn,
                        proto,
                        meth,
                        skeleton_only=args.skeleton_only,
                        do_sim=args.sim,
                    )
                )
            except Exception as e:
                rows.append(
                    {
                        "design": name,
                        "methodology": meth,
                        "error": str(e)[:240],
                        "verdict": "error",
                    }
                )
                print(f"  ERROR {e}", flush=True)
            dest.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("\n=== summary ===")
    print(
        f"{'design':<16} {'meth':<5} {'kind':<10} {'verdict':<14} "
        f"{'engine':<18} lint shape sim"
    )
    for r in rows:
        print(
            f"{r.get('design','?'):<16} {r.get('methodology','?'):<5} "
            f"{r.get('skel_kind','?'):<10} {r.get('verdict','?'):<14} "
            f"{str(r.get('engine', r.get('error','?'))):<18} "
            f"{r.get('lint_ok')} {r.get('shape_ok')} {r.get('sim_pass')}"
        )
    print(f"\nWrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
