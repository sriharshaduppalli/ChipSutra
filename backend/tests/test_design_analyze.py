"""Design analysis — protocol variant + TB recommendation before generate."""
from design_analyze import analyze_design, detect_protocol_variant, recommend_tb
from rtl_ports import extract_modules

COUNTER = """
module counter_en (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""

MUX = """
module mux2_8 (
  input wire sel, input wire [7:0] a, input wire [7:0] b, output wire [7:0] y
);
endmodule
"""

APB4 = """
module apb4_regs (
  input pclk, input presetn, input psel, input penable, input pwrite,
  input [7:0] paddr, input [31:0] pwdata, input [3:0] pstrb, input [2:0] pprot,
  output pready, output [31:0] prdata, output pslverr
);
endmodule
"""


def test_analyze_counter_recommends_sv_or_uvm_shape():
    mods = extract_modules(COUNTER)
    a = analyze_design(mods, tb_methodology="sv")
    assert a["protocol"] == "counter"
    assert a["timing_style"] == "sequential"
    assert a["recommendation"]["methodology"] == "sv"
    assert "DESIGN ANALYSIS" in a["prompt_block"]


def test_analyze_mux_is_combo():
    mods = extract_modules(MUX)
    a = analyze_design(mods, tb_methodology="uvm")
    assert a["protocol"] == "mux"
    assert a["timing_style"] == "combo"
    assert a["recommendation"]["methodology"] == "uvm"
    assert "COMBO" in a["brief"]


def test_apb4_variant():
    mods = extract_modules(APB4)
    names = {p["name"].lower() for p in mods[0]["ports"]}
    v = detect_protocol_variant("apb", names)
    assert v["protocol_variant"] == "apb4"
    assert "pstrb" in v["features"]


def test_recommend_uvm_bus_shape():
    r = recommend_tb(
        protocol="axi_lite",
        timing_style="bus",
        port_count=30,
        tb_methodology="uvm",
        confidence=0.9,
    )
    assert r["tb_shape"] == "uvm_agent_env"


def test_csr_stance_no_ral_for_apb_without_map():
    from design_analyze import detect_csr_stance

    s = detect_csr_stance({"paddr", "pwdata", "prdata"}, "", "apb")
    assert s["ral_allowed"] is False
    assert "NO RAL" in s["stance"] or "no invented" in s["stance"].lower()


def test_context_pack_budget_and_vip():
    from design_analyze import build_tb_context_pack

    mods = extract_modules(APB4)
    a = analyze_design(mods, tb_methodology="uvm")
    assert a["protocol_variant"] == "apb4"
    pack = build_tb_context_pack(a, max_chars=4200, vip_chars=1800)
    assert "DESIGN ANALYSIS" in pack
    assert "CSR/RAL" in pack
    assert len(pack) <= 4300
    assert "apb" in pack.lower() or "PSEL" in pack or "psel" in pack.lower()


def test_support_tier_supported_for_apb():
    mods = extract_modules(APB4)
    a = analyze_design(mods, tb_methodology="sv")
    assert a["support_tier"] == "supported"
    assert "SUPPORT TIER" in a["prompt_block"] or "Support tier" in a["brief"]


def test_support_tier_best_effort_generic():
    rtl = """
    module weird_block(input a, input b, output y);
      assign y = a ^ b;
    endmodule
    """
    mods = extract_modules(rtl)
    a = analyze_design(mods, tb_methodology="sv")
    assert a["support_tier"] in ("best_effort", "supported", "experimental")
    if a["protocol"] == "generic" or float(a["dut"]["confidence"]) < 0.55:
        assert a["support_tier"] == "best_effort"
        assert a["recommendation"]["tb_shape"] == "procedural_smoke"


def test_analyze_riscv_experimental_and_ir():
    rtl = """
    module mini_rv32 #(parameter int XLEN = 32) (
      input clk, input rst_n,
      output [31:0] pc, input [31:0] instr,
      output [31:0] mem_addr, input [31:0] mem_rdata
    );
      typedef enum logic [1:0] {IDLE, FETCH} state_e;
    endmodule
    """
    mods = extract_modules(rtl)
    a = analyze_design(mods, rtl_text=rtl, tb_methodology="sv")
    assert a["protocol"] == "riscv"
    assert a["support_tier"] == "experimental"
    assert a["recommendation"]["tb_shape"] == "procedural_smoke"
    assert a["rtl_ir"]["looks_riscv"] is True
    assert "RISC-V" in a["brief"]
    assert "protocol_vip_riscv" in (a.get("protocol_guidance") or "").lower() or "NOP" in (
        a.get("protocol_guidance") or ""
    )
