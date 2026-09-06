"""Soft RTL IR — params, FSM, RISC-V tags (no EDA binary required)."""
from rtl_ir import extract_rtl_ir, ir_brief_lines, looks_riscv
from rtl_ports import extract_modules

RV = """
module mini_rv32 #(parameter int XLEN = 32) (
  input wire clk,
  input wire rst_n,
  output logic [31:0] pc,
  input wire [31:0] instr,
  output logic [31:0] mem_addr,
  input wire [31:0] mem_rdata,
  output logic mem_we
);
  typedef enum logic [1:0] {IDLE, FETCH, DECODE, EXECUTE} state_e;
  always_ff @(posedge clk) begin
    if (!rst_n) pc <= 0;
    else pc <= pc + 4;
  end
endmodule
"""

COUNTER = """
module counter_en (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
  always_ff @(posedge clk) if (!rst_n) count <= 0; else if (enable) count <= count + 1;
endmodule
"""


def test_looks_riscv_from_ports():
    names = {"clk", "rst_n", "pc", "instr", "mem_addr", "mem_rdata"}
    assert looks_riscv(names, "") is True
    assert looks_riscv({"clk", "enable", "count"}, "") is False


def test_extract_ir_riscv():
    mods = extract_modules(RV)
    ir = extract_rtl_ir(RV, mods)
    assert ir["looks_riscv"] is True
    assert ir["parameters"].get("XLEN") == 32
    assert ir["always_ff"] >= 1
    assert "FETCH" in ir["fsm_states"] or "IDLE" in ir["fsm_states"]
    blob = "\n".join(ir_brief_lines(ir))
    assert "RISC-V" in blob
    assert "XLEN" in blob


def test_extract_ir_counter_not_riscv():
    mods = extract_modules(COUNTER)
    ir = extract_rtl_ir(COUNTER, mods)
    assert ir["looks_riscv"] is False
    assert ir["parser"].startswith("regex")
    assert ir["module_count"] == 1
    assert ir["cdc_hint"] is False


SOC = """
module apb_regs(input pclk, input psel, input penable, input pwrite, input [7:0] paddr);
endmodule
module uart_tx(input uclk, input rst_n, output txd);
endmodule
"""


def test_extract_ir_hierarchy_and_cdc():
    mods = extract_modules(SOC)
    ir = extract_rtl_ir(SOC, mods)
    assert ir["module_count"] == 2
    assert ir["cdc_hint"] is True
    names = {m["module"] for m in ir["interface_map"]}
    assert "apb_regs" in names and "uart_tx" in names
    by = {m["module"]: m["protocol"] for m in ir["interface_map"]}
    assert by["apb_regs"] == "apb"
    blob = "\n".join(ir_brief_lines(ir))
    assert "Hierarchy" in blob
    assert "CDC hint" in blob
    assert "Interface map" in blob
