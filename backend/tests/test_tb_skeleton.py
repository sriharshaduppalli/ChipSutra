"""Unit tests for deterministic randomized TB skeleton (no Ollama)."""
from __future__ import annotations

from pathlib import Path

from rtl_ports import extract_modules
from tb_skeleton import (
    classify_ports,
    detect_axi_lite_model,
    detect_counter_model,
    detect_fifo_model,
    detect_parity_model,
    module_has_known_golden,
    prefer_known_golden_skeleton,
    render_class_sv_tb,
    render_randomized_tb,
    render_from_rtl_texts,
    should_use_tb_skeleton,
    width_bits,
)

GOLDEN = Path(__file__).resolve().parents[1] / "knowledge" / "golden"

COUNTER = """
module counter_rtl (
    input wire clk,
    input wire rst_n,
    input wire enable,
    output reg [3:0] count
);
endmodule
"""

GENERIC = """
module mux2 (
    input wire clk,
    input wire rst_n,
    input wire sel,
    input wire [7:0] a,
    input wire [7:0] b,
    output wire [7:0] y
);
endmodule
"""


def test_width_bits():
    assert width_bits("") == 1
    assert width_bits("[3:0]") == 4
    assert width_bits("[15:0]") == 16


def test_counter_detection_and_render():
    mod = extract_modules(COUNTER)[0]
    roles = classify_ports(mod["ports"])
    assert roles["clk"]["name"] == "clk"
    assert roles["rst"]["name"] == "rst_n"
    assert roles["active_low_reset"] is True
    pair = detect_counter_model(roles)
    assert pair is not None
    assert pair[0]["name"] == "enable"
    assert pair[1]["name"] == "count"

    sv = render_randomized_tb(mod, cycles=32, seed=7)
    assert "module counter_rtl_tb" in sv
    assert "counter_rtl dut" in sv
    assert ".enable(enable)" in sv
    assert "$urandom_range" in sv
    assert "expected" in sv
    assert "Test case 1" not in sv
    assert "void'($urandom(7))" in sv
    assert "for (i = 0; i < 32;" in sv
    assert len(sv.splitlines()) < 120


def test_free_running_counter_golden():
    rtl = """
    module counter (
        input  wire       clk,
        input  wire       rst,
        output reg  [7:0] q
    );
    endmodule
    """
    mod = extract_modules(rtl)[0]
    assert len(mod["ports"]) == 3
    pair = detect_counter_model(classify_ports(mod["ports"]))
    assert pair is not None
    assert pair[0] is None  # free-running
    assert pair[1]["name"] == "q"
    sv = render_randomized_tb(mod, cycles=16, seed=1)
    assert "expected = expected + 1'b1" in sv
    assert "always #5 clk" in sv


def test_generic_randomized_no_fake_golden():
    # Truly unknown protocol (ALU-ish) — universal auto-TB, no fake golden
    rtl = """
    module tiny_alu (
        input wire clk,
        input wire rst_n,
        input wire [1:0] op,
        input wire [7:0] a,
        input wire [7:0] b,
        output wire [7:0] result
    );
    endmodule
    """
    sv = render_from_rtl_texts([rtl], cycles=16, seed=1)
    assert sv is not None
    assert "tiny_alu dut" in sv
    assert "Model: generic" in sv
    assert "$isunknown" in sv
    assert "$urandom" in sv
    assert "data_in" not in sv


def test_mux_golden():
    sv = render_from_rtl_texts([GENERIC], cycles=16, seed=1)
    assert sv is not None
    assert "mux2 dut" in sv
    assert "Model: mux" in sv
    assert "mux mismatch" in sv
    assert "sel = $urandom_range" in sv


def test_apb_golden():
    rtl = """
    module apb_regs (
        input wire pclk,
        input wire presetn,
        input wire psel,
        input wire penable,
        input wire pwrite,
        input wire [7:0] paddr,
        input wire [31:0] pwdata,
        output logic pready,
        output logic [31:0] prdata
    );
    endmodule
    """
    from tb_skeleton import detect_apb_model, classify_ports
    mod = extract_modules(rtl)[0]
    roles = classify_ports(mod["ports"])
    assert detect_apb_model(roles) is not None
    sv = render_randomized_tb(mod, cycles=24, seed=4)
    assert "Model: apb" in sv
    assert "apb_model" in sv
    assert "APB RDATA mismatch" in sv
    assert "always #5 pclk" in sv


def test_stream_smoke():
    rtl = """
    module stream_pipe (
        input wire clk,
        input wire rst_n,
        input wire valid,
        input wire [7:0] data,
        output logic ready,
        output logic [7:0] out_data,
        output logic out_valid
    );
    endmodule
    """
    from tb_skeleton import detect_stream_model, classify_ports
    mod = extract_modules(rtl)[0]
    assert detect_stream_model(classify_ports(mod["ports"])) is not None
    sv = render_randomized_tb(mod, cycles=16, seed=2)
    assert "Model: stream" in sv
    assert "$isunknown" in sv
    assert "valid = $urandom_range" in sv


def test_should_use_skeleton_policy():
    mods = extract_modules(COUNTER)
    # Auto / llm = class-based Pure SV via LLM (no procedural smoke)
    assert not should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="auto")
    assert not should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="llm")
    # Explicit smoke / Fast-random only
    assert should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="skeleton")
    assert should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="fast")
    assert not should_use_tb_skeleton(
        module="testbench", modules=mods, gen_mode="llm", prompt="full UVM agent please"
    )
    assert not should_use_tb_skeleton(
        module="testbench", modules=mods, gen_mode="auto", prompt="full UVM agent please"
    )
    assert not should_use_tb_skeleton(module="assertions", modules=mods, gen_mode="auto")
    assert not should_use_tb_skeleton(module="testbench", modules=[], gen_mode="auto")


def test_fifo_queue_golden_from_golden_rtl():
    rtl = (GOLDEN / "fifo.sv").read_text(encoding="utf-8")
    mod = extract_modules(rtl)[0]
    assert mod["parameters"].get("DEPTH") == 8
    assert mod["parameters"].get("WIDTH") == 8
    wr = next(p for p in mod["ports"] if p["name"] == "wr_data")
    assert wr["bits"] == 8
    roles = classify_ports(mod["ports"])
    fifo = detect_fifo_model(roles, mod["parameters"])
    assert fifo is not None
    assert fifo["depth"] == 8
    sv = render_randomized_tb(mod, cycles=24, seed=3)
    assert "Model: fifo" in sv
    assert "q[$]" in sv
    assert "fifo #(.WIDTH(8), .DEPTH(8)) dut" in sv
    assert "empty mismatch" in sv
    assert "rd_data mismatch" in sv
    assert "logic [7:0] wr_data" in sv


def test_class_sv_fifo_uses_queue_golden_not_noop():
    rtl = """
    module sync_fifo8 #(
      parameter WIDTH = 8, parameter DEPTH = 8
    ) (
      input wire clk, input wire rst_n,
      input wire wr_en, input wire [7:0] wr_data, input wire rd_en,
      output wire [7:0] rd_data, output wire full, output wire empty,
      output reg [3:0] count
    );
    endmodule
    """
    from tb_semantic import lint_semantic_golden

    mod = extract_modules(rtl)[0]
    sv = render_class_sv_tb(mod, cycles=16, seed=1)
    assert "q[$]" in sv
    assert "function bit check(); return 1;" not in sv
    assert "beats++" not in sv
    assert "sb.q.size() >= 8) t.wr_en = 1'b0" in sv or "q.size() >= 8" in sv
    assert "q.size() == 0" in sv and "rd_en = 1'b0" in sv
    assert "post-reset empty not 1" in sv or "empty !== 1'b1" in sv
    assert "rd_data !== '0" not in sv
    issues = lint_semantic_golden(sv, protocol="fifo")
    assert "semantic_fifo_no_queue" not in issues
    assert "semantic_noop_check" not in issues
    assert "semantic_fifo_reset_rd_data" not in issues
    for needle in (
        "interface sync_fifo8_if",
        "class sync_fifo8_generator",
        "class sync_fifo8_driver",
        "class sync_fifo8_monitor",
        "class sync_fifo8_scoreboard",
        "class sync_fifo8_env",
    ):
        assert needle in sv, needle


def test_parity_xor_golden():
    rtl = """
    module parity_byte (
        input  wire       clk,
        input  wire       rst_n,
        input  wire       valid,
        input  wire [7:0] data,
        output reg        parity,
        output reg        valid_out
    );
    endmodule
    """
    mod = extract_modules(rtl)[0]
    roles = classify_ports(mod["ports"])
    assert detect_parity_model(roles) is not None
    sv = render_randomized_tb(mod, cycles=16, seed=2)
    assert "Model: parity" in sv
    assert "parity !== ^data" in sv
    assert "valid_out" in sv


def test_axi_lite_smoke_golden():
    rtl = (GOLDEN / "axi_lite_slave.sv").read_text(encoding="utf-8")
    mod = extract_modules(rtl)[0]
    roles = classify_ports(mod["ports"])
    assert roles["clk"]["name"] == "aclk"
    assert detect_axi_lite_model(roles) is not None
    sv = render_randomized_tb(mod, cycles=32, seed=5)
    assert "Model: axi_lite" in sv
    assert "model_reg" in sv
    assert "always #5 aclk" in sv
    assert "s_axi_awvalid" in sv
    assert "AXI RDATA mismatch" in sv
    assert "ghost write" in sv
    assert "W-only ghost" in sv
    assert "Mid-test reset" in sv


def test_apb_uppercase_port_names():
    rtl = """
    module apb_regs (
        input wire PCLK,
        input wire PRESETn,
        input wire PSEL,
        input wire PENABLE,
        input wire PWRITE,
        input wire [7:0] PADDR,
        input wire [31:0] PWDATA,
        output wire PREADY,
        output reg [31:0] PRDATA
    );
    endmodule
    """
    mod = extract_modules(rtl)[0]
    sv = render_randomized_tb(mod, cycles=24, seed=4)
    assert "PSEL = 1'b1" in sv
    assert "psel = 1'b1" not in sv
    assert "ghost write without PSEL" in sv
    assert "Mid-test reset" in sv


def test_class_sv_parity_not_noop():
    rtl = (Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts" / "sample_parity.sv").read_text(
        encoding="utf-8"
    )
    mod = extract_modules(rtl)[0]
    sv = render_class_sv_tb(mod, cycles=16, seed=1)
    assert "beats++" not in sv.replace(" ", "")
    assert "function bit check(); return 1;" not in sv
    assert "^" in sv and "parity" in sv


def test_class_sv_alu_combo_no_virtual():
    rtl = (Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts" / "alu4.sv").read_text(
        encoding="utf-8"
    )
    mod = extract_modules(rtl)[0]
    sv = render_class_sv_tb(mod, cycles=16, seed=1)
    assert "virtual " not in sv
    assert "function bit check(); return 1;" not in sv
    assert "a + b" in sv


def test_class_sv_fifo_count_width_not_1bit():
    rtl = (Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts" / "sync_fifo8.sv").read_text(
        encoding="utf-8"
    )
    mod = extract_modules(rtl)[0]
    sv = render_class_sv_tb(mod, cycles=16, seed=1)
    assert "q[$]" in sv
    assert "logic count;" not in sv
    assert "logic [3:0] count" in sv or "bit [3:0] count" in sv


def test_class_sv_apb_and_axi_have_model_reg():
    root = Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts"
    for fname in ("apb_regs.sv", "axi_lite_slave.sv"):
        mod = extract_modules((root / fname).read_text(encoding="utf-8"))[0]
        sv = render_class_sv_tb(mod, cycles=16, seed=1)
        assert "model_reg" in sv, fname
        assert "beats++" not in sv.replace(" ", ""), fname
        assert "function bit check(); return 1;" not in sv, fname


def test_unknown_dut_generic_check_is_not_noop():
    rtl = """
module weird_block (
  input wire clk,
  input wire rst_n,
  input wire [3:0] foo,
  output wire [3:0] bar
);
endmodule
"""
    mod = extract_modules(rtl)[0]
    sv = render_class_sv_tb(mod, cycles=8, seed=1)
    assert "function bit check(); return 1;" not in sv
    assert "$isunknown" in sv
    assert not module_has_known_golden(mod)
    assert not prefer_known_golden_skeleton(
        gen_mode="auto", parsed_module=mod
    )


def test_packed_mux_wishbone_avalon_fsm_goldens():
    packed = extract_modules(
        """
        module mux_pack(input [1:0] sel, input [31:0] data, output [7:0] y);
        endmodule
        """
    )[0]
    from tb_skeleton import detect_mux_model, classify_ports

    mx = detect_mux_model(classify_ports(packed["ports"]))
    assert mx and mx.get("kind") == "packed"
    sv = render_class_sv_tb(packed, cycles=8, seed=1)
    assert "+:" in sv and "function bit check(); return 1;" not in sv

    wb = extract_modules(
        """
        module wb_slave(
          input clk, input rst_n, input cyc, input stb, input we,
          input [7:0] adr, input [31:0] dat_i, output ack, output [31:0] dat_o
        ); endmodule
        """
    )[0]
    wbsv = render_class_sv_tb(wb, cycles=8, seed=1)
    assert "model_reg" in wbsv and "wb_write" in wbsv
    assert prefer_known_golden_skeleton(parsed_module=wb)

    av = extract_modules(
        """
        module avs(
          input clk, input rst_n, input [7:0] address, input write, input read,
          input [31:0] writedata, output [31:0] readdata, output waitrequest
        ); endmodule
        """
    )[0]
    avsv = render_class_sv_tb(av, cycles=8, seed=1)
    assert "waitrequest" in avsv and "model_reg" in avsv

    fsm = extract_modules(
        "module fsm4(input clk, input rst_n, input ev, output [3:0] state); endmodule"
    )[0]
    fsv = render_class_sv_tb(fsm, cycles=8, seed=1)
    assert "$onehot0" in fsv and "function bit check(); return 1;" not in fsv


def test_prefer_known_golden_for_counter_unless_forced_llm():
    mod = extract_modules(COUNTER)[0]
    assert module_has_known_golden(mod)
    assert prefer_known_golden_skeleton(gen_mode="auto", parsed_module=mod)
    assert not prefer_known_golden_skeleton(gen_mode="llm", parsed_module=mod)

