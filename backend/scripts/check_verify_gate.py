"""Smoke-check the Verilator gate on eval-suite generated TBs.

Usage: python scripts/check_verify_gate.py [lint|run]
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dv_verify import verify_testbench, verilator_bin  # noqa: E402
from tb_class_lint import repair_class_sv_tb  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "lint"
print("verilator_bin:", verilator_bin(), "mode:", mode)
suite = Path(__file__).resolve().parent / "eval_suite"
for name in ("counter_en", "sync_fifo8", "sample_parity", "mux2_8"):
    rtl = (suite / "duts" / f"{name}.sv").read_text(encoding="utf-8")
    tb = (suite / "chipsutra_out" / f"{name}_tb.sv").read_text(encoding="utf-8")
    # Same mechanical repair the live pipeline applies before serving output.
    tb = repair_class_sv_tb(tb)
    r = verify_testbench([(f"{name}.sv", rtl)], tb, tb_name=f"{name}_tb.sv", mode=mode)
    line = f"{name}: ok={r['ok']} reason={r['reason']}"
    if mode == "run":
        line += f" sim_pass={r.get('sim_pass')}"
    print(line)
    for e in (r.get("errors") or [])[:6]:
        print("   ", e)
    if mode == "run" and not r["ok"]:
        tail = (r.get("sim_log") or r.get("log") or "")[-500:]
        print("    --- log tail ---")
        for ln in tail.splitlines()[-8:]:
            print("   ", ln)
sys.exit(0)
