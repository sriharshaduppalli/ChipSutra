from pathlib import Path

from rtl_ports import extract_modules
from tb_architecture import analyze_tb_architecture
from tb_skeleton import render_class_sv_tb
from tb_uvm_skeleton import render_uvm_smoke_tb

DUTS = Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts"


def test_class_sv_counter_complete():
    rtl = (DUTS / "counter_en.sv").read_text(encoding="utf-8")
    sv = render_class_sv_tb(extract_modules(rtl)[0], cycles=8, seed=1)
    arch = analyze_tb_architecture(sv, methodology_hint="sv")
    assert arch["methodology"] == "sv"
    assert arch["dut"] == "counter_en"
    present = {n["id"]: n["present"] for n in arch["nodes"]}
    assert present["driver"] and present["scoreboard"] and present["dut"]
    assert arch["verdict"] in ("ok", "gaps")
    assert "flowchart" in arch["mermaid"]


def test_uvm_has_agent_and_run_test():
    rtl = (DUTS / "counter_en.sv").read_text(encoding="utf-8")
    sv = render_uvm_smoke_tb(extract_modules(rtl)[0], cycles=8)
    arch = analyze_tb_architecture(sv, methodology_hint="uvm")
    assert arch["methodology"] == "uvm"
    by = {n["id"]: n for n in arch["nodes"]}
    assert by["agent"]["present"]
    assert by["test"]["present"]
    assert any(e["label"] == "seq_item" for e in arch["edges"])


def test_vip_stub_flagged():
    rtl = """
    module axi4_slv(
      input aclk, input aresetn,
      input s_axi_awvalid, input [7:0] s_axi_awlen, input s_axi_wvalid, input s_axi_arvalid,
      input s_axi_bready, input s_axi_rready,
      output s_axi_awready, output s_axi_wready, output s_axi_bvalid,
      output s_axi_arready, output s_axi_rvalid
    ); endmodule
    """
    sv = render_class_sv_tb(extract_modules(rtl)[0], cycles=8, seed=1)
    arch = analyze_tb_architecture(sv)
    assert arch["require_user_vip"] is True
    assert any("VIP" in f["title"] or "vip" in f["title"].lower() for f in arch["findings"])


def test_procedural_smoke():
    sv = """
    module foo_tb;
      reg clk; foo dut(.clk(clk));
      initial begin clk=0; forever #5 clk=~clk; end
    endmodule
    """
    arch = analyze_tb_architecture(sv)
    assert arch["methodology"] == "procedural"
    assert arch["dut"] == "foo"
