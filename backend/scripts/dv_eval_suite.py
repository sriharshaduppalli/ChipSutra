"""DV evaluation suite — accuracy + latency harness for ChipSutra generators.

Phase-1 of docs/ADVANCED_DV_ARCHITECTURE.md.
Run:  python scripts/dv_eval_suite.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dv_planner import plan_generation
from rtl_ports import extract_modules
from tb_lint import lint_testbench
from tb_skeleton import render_randomized_tb
from kg_rating import auto_score_testbench

GOLDEN = ROOT / "knowledge" / "golden"

SAMPLES = {
    "counter_enable": """
module counter_rtl (
    input wire clk, input wire rst_n, input wire enable,
    output reg [3:0] count
);
endmodule
""",
    "counter_free": (GOLDEN / "counter.sv").read_text(encoding="utf-8") if (GOLDEN / "counter.sv").is_file() else "",
    "fifo": (GOLDEN / "fifo.sv").read_text(encoding="utf-8") if (GOLDEN / "fifo.sv").is_file() else "",
    "axi_lite_slave": (GOLDEN / "axi_lite_slave.sv").read_text(encoding="utf-8") if (GOLDEN / "axi_lite_slave.sv").is_file() else "",
    "parity_byte": """
module parity_byte (
    input wire clk, input wire rst_n, input wire valid,
    input wire [7:0] data, output reg parity, output reg valid_out
);
endmodule
""",
    "mux2": """
module mux2 (
    input wire clk, input wire rst_n, input wire sel,
    input wire [7:0] a, input wire [7:0] b, output wire [7:0] y
);
endmodule
""",
    "apb_regs": """
module apb_regs (
    input wire pclk, input wire presetn,
    input wire psel, input wire penable, input wire pwrite,
    input wire [7:0] paddr, input wire [31:0] pwdata,
    output logic pready, output logic [31:0] prdata
);
endmodule
""",
    "stream_pipe": """
module stream_pipe (
    input wire clk, input wire rst_n,
    input wire valid, input wire [7:0] data,
    output logic ready, output logic [7:0] out_data, output logic out_valid
);
endmodule
""",
    "tiny_alu_generic": """
module tiny_alu (
    input wire clk, input wire rst_n,
    input wire [1:0] op, input wire [7:0] a, input wire [7:0] b,
    output wire [7:0] result
);
endmodule
""",
}


def eval_one(name: str, rtl: str) -> dict:
    t0 = time.perf_counter()
    mods = extract_modules(rtl)
    if not mods or not mods[0].get("ports"):
        return {"design": name, "ok": False, "error": "parse_failed"}
    plan = plan_generation(
        module="testbench",
        prompt="",
        gen_mode="skeleton",
        modules=mods,
        rtl_text=rtl,
    )
    sv = render_randomized_tb(mods[0], cycles=24, seed=7)
    ports = [p["name"] for p in mods[0]["ports"]]
    lint_ok, issues = lint_testbench(sv, dut_name=mods[0]["name"], required_ports=ports)
    score = auto_score_testbench(sv, "skeleton", lint_ok, issues)
    ms = (time.perf_counter() - t0) * 1000.0
    has_golden = any(
        x in sv
        for x in (
            "expected = expected +",
            "q[$]",
            "model_reg",
            "apb_model",
            "!== ^",
            "=== ^",
            "mux mismatch",
        )
    )
    if lint_ok and (has_golden or plan["protocol_pack"] in ("generic", "stream")):
        # generic/stream: universal auto-TB / smoke is acceptable PARTIAL unless golden present
        if has_golden:
            verdict = "SOLID"
        elif plan["protocol_pack"] == "stream" and "$isunknown" in sv:
            verdict = "PARTIAL"
        elif plan["protocol_pack"] == "generic" and "$isunknown" in sv:
            verdict = "PARTIAL"
        else:
            verdict = "PARTIAL"
    elif lint_ok:
        verdict = "PARTIAL"
    else:
        verdict = "WEAK"
    return {
        "design": name,
        "dut": mods[0]["name"],
        "protocol": plan["protocol_pack"],
        "engine_preference": plan["engine_preference"],
        "verdict": verdict,
        "lint_ok": lint_ok,
        "lint_issues": issues,
        "score": score["auto_score"],
        "latency_ms": round(ms, 1),
        "has_golden": has_golden,
        "lines": sv.count("\n") + 1,
    }


def main() -> int:
    results = []
    print("=== ChipSutra DV eval suite (skeleton / planner) ===\n")
    for name, rtl in SAMPLES.items():
        if not (rtl or "").strip():
            continue
        r = eval_one(name, rtl)
        results.append(r)
        print(
            f"[{r.get('verdict')}] {name:16} proto={r.get('protocol'):10} "
            f"score={r.get('score')} {r.get('latency_ms')}ms"
        )
        if r.get("lint_issues"):
            print(f"  lint={r['lint_issues']}")

    solid = sum(1 for r in results if r.get("verdict") == "SOLID")
    partial = sum(1 for r in results if r.get("verdict") == "PARTIAL")
    weak = sum(1 for r in results if r.get("verdict") == "WEAK")
    lat = [r["latency_ms"] for r in results if "latency_ms" in r]
    summary = {
        "solid": solid,
        "partial": partial,
        "weak": weak,
        "total": len(results),
        "latency_ms_p50": sorted(lat)[len(lat) // 2] if lat else None,
        "latency_ms_max": max(lat) if lat else None,
        "results": results,
    }
    out = Path(os.environ.get("TEMP", ".")) / "chipsutra_dv_eval.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps({k: summary[k] for k in ("solid", "partial", "weak", "total", "latency_ms_p50", "latency_ms_max")}, indent=2))
    print(f"wrote {out}")
    # Fail CI only on WEAK (PARTIAL generics are expected)
    return 1 if weak else 0


if __name__ == "__main__":
    raise SystemExit(main())
