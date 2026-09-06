"""Validate the class-based AXI golden: sim-PASS + clean under our lints."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dv_verify import verify_testbench
from rtl_ports import extract_modules
from tb_class_lint import lint_class_sv_tb, score_class_sv_competitive
from tb_semantic import lint_semantic_golden

ROOT = Path(__file__).resolve().parents[1]
rtl = (ROOT / "scripts" / "eval_suite" / "duts" / "axi_lite_slave.sv").read_text(encoding="utf-8")
gold = (ROOT / "knowledge" / "golden" / "axi_lite_class_sv_tb.sv").read_text(encoding="utf-8")

mods = extract_modules(rtl)
specs = mods[0]["ports"]
ports = [p["name"] for p in specs]

ok, issues = lint_class_sv_tb(
    gold, dut_name="axi_lite_slave", required_ports=ports,
    protocol="axi_lite", port_specs=specs,
)
print("class lint ok:", ok, "issues:", issues)
print("axi semantics:", lint_semantic_golden(gold, protocol="axi_lite"))
sc = score_class_sv_competitive(
    gold, required_ports=ports, protocol="axi_lite", port_specs=specs
)
print("score:", sc["score"], "premium_bar:", sc["premium_bar"])

r = verify_testbench(
    [("axi_lite_slave.sv", rtl)], gold, tb_name="axi_lite_class_sv_tb.sv", mode="run"
)
print("sim: ok=", r.get("ok"), "sim_pass=", r.get("sim_pass"), "reason=", r.get("reason"))
for e in (r.get("errors") or [])[:6]:
    print("   ", e)
tail = (r.get("sim_log") or "").splitlines()
print("   ", " | ".join(tail[-3:]) if tail else "(no sim log)")
