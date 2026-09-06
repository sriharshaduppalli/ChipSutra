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


SWITCH = """
module switch (
  input wire clk, input wire rstn, input wire vld,
  input wire [7:0] addr, input wire [15:0] data,
  output reg [7:0] addr_a, output reg [15:0] data_a,
  output reg [7:0] addr_b, output reg [15:0] data_b
);
endmodule
"""


def test_classify_addr_switch():
    mods = extract_modules(SWITCH)
    d = classify_dut(mods)
    assert d["protocol"] == "switch"
    assert d["confidence"] >= 0.8


def test_plan_fast_random_still_llm():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="skeleton", modules=mods)
    assert p["engine_preference"] == "llm"
    assert p["protocol_pack"] == "counter"


def test_plan_llm_mode_is_llm_for_tb():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="llm", modules=mods)
    assert p["engine_preference"] == "llm"


def test_plan_auto_pure_sv_is_llm():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="auto", modules=mods, tb_methodology="sv")
    assert p["engine_preference"] == "llm"


def test_plan_uvm_prompt_forces_llm():
    mods = extract_modules(COUNTER)
    p = plan_generation(
        module="testbench",
        gen_mode="auto",
        prompt="full UVM agent please",
        modules=mods,
    )
    assert p["engine_preference"] == "llm"
    assert p["intent"]["wants_uvm"] is True or p["tb_methodology"] == "uvm"


def test_plan_spec2rtl_prefers_llm():
    p = plan_generation(module="spec2rtl", prompt="build a UART from this spec")
    assert p["engine_preference"] == "llm"
    assert p["model_tier"] == "7b_preferred"


def test_multi_module_prefers_14b():
    rtl = """
    module a (input clk, input rst_n, output [3:0] q); endmodule
    module b (input clk, input rst_n, input [3:0] d, output [3:0] q); endmodule
    """
    mods = extract_modules(rtl)
    d = classify_dut(mods)
    assert d["multi_module"] is True
    assert d["module_count"] == 2
    p = plan_generation(module="testbench", modules=mods)
    assert p["model_tier"] == "14b_preferred"
    assert any("Multi-module" in n for n in p["notes"])


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
    ahb = extract_modules(
        """
        module ahb_slave(
          input HCLK, input HRESETn, input [7:0] HADDR, input [1:0] HTRANS,
          input HWRITE, input [31:0] HWDATA, input HSEL, input HREADY,
          output [31:0] HRDATA, output HREADYOUT, output [1:0] HRESP
        ); endmodule
        """
    )
    assert classify_dut(ahb)["protocol"] == "ahb"
    axis = extract_modules(
        """
        module axis_sink(
          input aclk, input aresetn, input [7:0] s_axis_tdata,
          input s_axis_tvalid, input s_axis_tlast, output s_axis_tready,
          output [7:0] last_data
        ); endmodule
        """
    )
    assert classify_dut(axis)["protocol"] == "axis"
    spi = extract_modules(
        "module spi_slave(input sclk, input cs_n, input mosi, output miso, output [7:0] rx_byte); endmodule"
    )
    assert classify_dut(spi)["protocol"] == "spi"


def test_classify_riscv_rv32i():
    rv = extract_modules(
        """
        module mini_rv32(
          input clk, input rst_n,
          output [31:0] pc, input [31:0] instr,
          output [31:0] mem_addr, input [31:0] mem_rdata, output mem_we
        ); endmodule
        """
    )
    d = classify_dut(rv)
    assert d["protocol"] == "riscv"
    assert d["confidence"] >= 0.7
    p = plan_generation(module="testbench", modules=rv)
    assert p["protocol_pack"] == "riscv"


def test_classify_wishbone_avalon_fsm_and_3b_tier():
    wb = extract_modules(
        """
        module wb_slave(
          input clk, input rst_n, input cyc, input stb, input we,
          input [7:0] adr, input [31:0] dat_i, output ack, output [31:0] dat_o
        ); endmodule
        """
    )
    assert classify_dut(wb)["protocol"] == "wishbone"
    av = extract_modules(
        """
        module avs(
          input clk, input rst_n, input [7:0] address, input write, input read,
          input [31:0] writedata, output [31:0] readdata, output waitrequest
        ); endmodule
        """
    )
    assert classify_dut(av)["protocol"] == "avalon"
    fsm = extract_modules(
        """
        module fsm4(input clk, input rst_n, input ev, output [3:0] state);
        endmodule
        """
    )
    assert classify_dut(fsm)["protocol"] == "fsm"
    p_mux = plan_generation(module="testbench", modules=extract_modules(
        "module mux2(input sel, input [7:0] a, input [7:0] b, output [7:0] y); endmodule"
    ), tb_methodology="sv")
    assert p_mux["model_tier"] == "3b"
    p_wb = plan_generation(module="testbench", modules=wb, tb_methodology="sv")
    assert p_wb["model_tier"] == "7b_preferred"
    p_uvm = plan_generation(module="testbench", modules=extract_modules(COUNTER), tb_methodology="uvm")
    assert p_uvm["model_tier"] == "7b_preferred"


def test_plan_to_learning_compact():
    mods = extract_modules(COUNTER)
    p = plan_generation(module="testbench", gen_mode="skeleton", modules=mods)
    learn = plan_to_learning(p)
    assert learn["protocol_pack"] == "counter"
    assert "engine_preference" in learn
