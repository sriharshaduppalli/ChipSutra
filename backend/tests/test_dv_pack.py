from dv_pack import build_dv_pack, dv_pack_zip
from dv_planner import classify_dut
from rtl_ports import extract_modules

COUNTER = """
module counter_rtl (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""

PWM = """
module pwm8 (input wire clk, input wire rst_n, input wire [7:0] duty, output reg pwm);
endmodule
"""

DEBOUNCE = """
module debounce (input wire clk, input wire rst_n, input wire noisy, output reg clean);
endmodule
"""

SHIFTER = """
module shifter8 (input wire [7:0] din, input wire [2:0] shamt, input wire dir, output wire [7:0] dout);
endmodule
"""

SYNC = """
module sync_ff (input wire clk, input wire rst_n, input wire d, output reg q);
endmodule
"""


def test_sv_pack_has_four_artifacts():
    pack = build_dv_pack(COUNTER, methodology="sv")
    assert pack["dut"] == "counter_rtl"
    assert pack["protocol"] == "counter"
    names = set(pack["files"])
    assert any(n.endswith("_tb.sv") for n in names)
    assert any(n.endswith("_sva.sv") for n in names)
    assert any(n.endswith("_cg.sv") for n in names)
    assert "TESTPLAN.md" in names
    assert "mailbox" in pack["files"][f"{pack['dut']}_tb.sv"].lower() or "scoreboard" in pack["files"][f"{pack['dut']}_tb.sv"].lower()
    z = dv_pack_zip(pack)
    assert z[:2] == b"PK"


def test_uvm_pack_is_source_not_verilator():
    pack = build_dv_pack(COUNTER, methodology="uvm")
    assert pack["methodology"] == "uvm"
    tb = next(v for k, v in pack["files"].items() if k.endswith("_tb.sv") or k.endswith("_uvm_tb.sv"))
    assert "run_test" in tb
    assert "uvm_pkg" in tb


def test_classify_pwm_debounce_shifter_sync():
    assert classify_dut(extract_modules(PWM), rtl_text=PWM)["protocol"] == "pwm"
    assert classify_dut(extract_modules(DEBOUNCE), rtl_text=DEBOUNCE)["protocol"] == "debounce"
    assert classify_dut(extract_modules(SHIFTER), rtl_text=SHIFTER)["protocol"] == "shifter"
    assert classify_dut(extract_modules(SYNC), rtl_text=SYNC)["protocol"] == "cdc"
