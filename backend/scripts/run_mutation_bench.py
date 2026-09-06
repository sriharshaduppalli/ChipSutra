"""Mutation-testing benchmark: do ChipSutra TBs actually catch injected bugs?

Usage: python scripts/run_mutation_bench.py
Writes eval_suite/mutation_results.json.
"""
from pathlib import Path
import json
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dv_mutation import mutation_test  # noqa: E402
from tb_class_lint import repair_class_sv_tb  # noqa: E402

SUITE = Path(__file__).resolve().parent / "eval_suite"
CASES = [
    "counter_en",
    "sync_fifo8",
    "sample_parity",
    "mux2_8",
    "apb_regs",
    "axi_lite_slave",
]


def main() -> int:
    rows = []
    for name in CASES:
        tb_path = SUITE / "chipsutra_out" / f"{name}_tb.sv"
        if not tb_path.exists():
            print(f"{name}: no generated TB yet — skipped")
            continue
        rtl = (SUITE / "duts" / f"{name}.sv").read_text(encoding="utf-8")
        tb = tb_path.read_text(encoding="utf-8")
        tb = repair_class_sv_tb(tb)
        t0 = time.time()
        r = mutation_test(rtl, tb, rtl_name=f"{name}.sv", tb_name=f"{name}_tb.sv")
        dt = round(time.time() - t0, 1)
        row = {"design": name, "elapsed_s": dt, **r}
        rows.append(row)
        if r.get("skipped"):
            print(f"{name}: SKIPPED ({r.get('reason')})")
        elif not r.get("baseline_pass"):
            print(f"{name}: baseline FAILED ({r.get('baseline', {}).get('reason')}) t={dt}s")
        else:
            print(
                f"{name}: kill_rate={r['kill_rate']} "
                f"({r['killed']}/{r['total']} killed, {r['survived']} survived) t={dt}s"
            )
            for m in r.get("mutants") or []:
                print(f"    {m['mutant']}: {m['status']}")
    out = SUITE / "mutation_results.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
