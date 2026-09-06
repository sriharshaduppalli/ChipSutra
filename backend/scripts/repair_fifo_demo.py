"""End-to-end G1 demo: sim-failing FIFO TB -> LLM repair with evidence -> sim PASS?"""
from pathlib import Path
import asyncio
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dv_verify import verify_testbench  # noqa: E402
from tb_class_lint import lint_class_sv_tb, repair_class_sv_tb  # noqa: E402
from tb_llm_repair import llm_repair_class_sv  # noqa: E402
from tb_lint import extract_sv  # noqa: E402

import os

os.environ.setdefault("OLLAMA_URL", "http://127.0.0.1:11434")

SUITE = Path(__file__).resolve().parent / "eval_suite"
rtl = (SUITE / "duts" / "sync_fifo8.sv").read_text(encoding="utf-8")
tb = repair_class_sv_tb((SUITE / "chipsutra_out" / "sync_fifo8_tb.sv").read_text(encoding="utf-8"))

ok, issues = lint_class_sv_tb(tb, protocol="fifo")
print("lint ok:", ok, "issues:", issues)

base = verify_testbench([("sync_fifo8.sv", rtl)], tb, tb_name="sync_fifo8_tb.sv", mode="run")
print("baseline sim:", base.get("reason"), "sim_pass:", base.get("sim_pass"))
evidence = list(base.get("errors") or [])
tail = (base.get("sim_log") or "").splitlines()
evidence += [ln for ln in tail if "FAIL" in ln][:3]
print("evidence:", evidence)


async def main() -> int:
    cand_raw, oks = await llm_repair_class_sv(
        provider="ollama",
        model="chipsutra-vlsi:7b",
        broken_sv=tb,
        issues=issues,
        dut_hint="sync_fifo8 ports=clk,rst_n,wr_en,wr_data,rd_en,rd_data,full,empty,count (WIDTH=8 DEPTH=8)",
        compiler_errors=evidence + ["SIMULATION FAILED: scoreboard count model wrong; use q.size()"],
    )
    if not oks or not cand_raw:
        print("LLM repair stream failed")
        return 1
    cand = repair_class_sv_tb(extract_sv(cand_raw) or cand_raw)
    (SUITE / "chipsutra_out" / "sync_fifo8_tb_repaired.sv").write_text(cand, encoding="utf-8")
    ok2, issues2 = lint_class_sv_tb(cand, protocol="fifo")
    print("repaired lint ok:", ok2, "issues:", issues2)
    r = verify_testbench([("sync_fifo8.sv", rtl)], cand, tb_name="sync_fifo8_tb.sv", mode="run")
    print("repaired sim:", r.get("reason"), "sim_pass:", r.get("sim_pass"))
    if not r.get("ok"):
        for ln in (r.get("sim_log") or r.get("log") or "")[-600:].splitlines()[-10:]:
            print("   ", ln)
    return 0


raise SystemExit(asyncio.run(main()))
