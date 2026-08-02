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
    assert should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="auto")
    assert should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="skeleton")
    # Explicit LLM mode always calls the model (skeleton remains lint fallback)
    assert not should_use_tb_skeleton(module="testbench", modules=mods, gen_mode="llm")
    assert not should_use_tb_skeleton(
        module="testbench", modules=mods, gen_mode="llm", prompt="full UVM agent please"
    )
    assert not should_use_tb_skeleton(
        module="testbench", modules=mods, gen_mode="auto", prompt="full UVM agent please"
    )
    assert not should_use_tb_skeleton(
        module="testbench", modules=mods, gen_mode="auto", tool_log="Error: ..."
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
