"""Tests for DV planner routing."""
from dv_planner import classify_dut, plan_generation, plan_to_learning
from rtl_ports import extract_modules

FIFO = """
module fifo #(parameter int WIDTH = 8, parameter int DEPTH = 8) (
  input wire clk, input wire rst_n,
  input wire wr_en, input wire [WIDTH-1:0] wr_data,
  input wire rd_en, output logic [WIDTH-1:0] rd_data,
  output logic full, empty, output logic [3:0] count
);
endmodule
"""

COUNTER = """
module counter_rtl (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""


def test_classify_fifo():
    mods = extract_modules(FIFO)
    d = classify_dut(mods)
    assert d["protocol"] == "fifo"
    assert d["confidence"] >= 0.8


def test_plan_fast_random_uses_skeleton():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="skeleton", modules=mods)
    assert p["engine_preference"] == "skeleton"
    assert p["protocol_pack"] == "counter"


def test_plan_llm_mode_is_hybrid_for_tb():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="llm", modules=mods)
    assert p["engine_preference"] == "hybrid"


def test_plan_uvm_prompt_auto_hybrid():
    mods = extract_modules(COUNTER)
    p = plan_generation(
        module="testbench",
        gen_mode="auto",
        prompt="full UVM agent please",
        modules=mods,
    )
    assert p["engine_preference"] == "hybrid"
    assert p["intent"]["wants_uvm"] is True


def test_plan_spec2rtl_prefers_llm():
    p = plan_generation(module="spec2rtl", prompt="build a UART from this spec")
    assert p["engine_preference"] == "llm"
    assert p["model_tier"] == "7b_preferred"


def test_classify_mux_apb_stream():
    mux = extract_modules(
        """
        module mux2 (input wire sel, input wire [7:0] a, input wire [7:0] b, output wire [7:0] y);
        endmodule
        """
    )
    assert classify_dut(mux)["protocol"] == "mux"
    apb = extract_modules(
        """
        module apb_regs (
          input pclk, input presetn, input psel, input penable, input pwrite,
          input [7:0] paddr, input [31:0] pwdata, output pready, output [31:0] prdata
        );
        endmodule
        """
    )
    assert classify_dut(apb)["protocol"] == "apb"
    stream = extract_modules(
        """
        module s (input clk, input valid, input [7:0] data, output ready, output [7:0] out_data);
        endmodule
        """
    )
    assert classify_dut(stream)["protocol"] == "stream"


def test_plan_to_learning_compact():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="skeleton", modules=mods)
    learn = plan_to_learning(p)
    assert learn["protocol_pack"] == "counter"
    assert "engine_preference" in learn
