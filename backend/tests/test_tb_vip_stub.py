from rtl_ports import extract_modules
from tb_skeleton import render_class_sv_tb
from tb_uvm_skeleton import render_uvm_smoke_tb
from tb_vip_stub import VIP_PROTOCOLS, needs_user_vip

AXI4 = """
module axi4_slv(
  input aclk, input aresetn,
  input s_axi_awvalid, input [7:0] s_axi_awlen, input s_axi_wvalid, input s_axi_arvalid,
  input s_axi_bready, input s_axi_rready,
  output s_axi_awready, output s_axi_wready, output s_axi_bvalid,
  output s_axi_arready, output s_axi_rvalid
);
endmodule
"""

PCIE = """
module pcie_ep(input clk, input rst_n, input tlp_valid, output [7:0] ltssm);
endmodule
"""

AXI_LITE = """
module axi_lite_slave(
  input aclk, input aresetn,
  input s_axi_awvalid, input [7:0] s_axi_awaddr, input s_axi_wvalid, input [31:0] s_axi_wdata,
  input [3:0] s_axi_wstrb, input s_axi_arvalid, input [7:0] s_axi_araddr,
  input s_axi_bready, input s_axi_rready, input [2:0] s_axi_awprot, input [2:0] s_axi_arprot,
  output s_axi_awready, output s_axi_wready, output s_axi_bvalid, output [1:0] s_axi_bresp,
  output s_axi_arready, output s_axi_rvalid, output [31:0] s_axi_rdata, output [1:0] s_axi_rresp
);
endmodule
"""


def test_axi4_and_pcie_need_vip():
    axi = extract_modules(AXI4)[0]
    need, cls = needs_user_vip(axi, rtl_text=AXI4)
    assert need and cls.get("protocol") in VIP_PROTOCOLS
    pcie = extract_modules(PCIE)[0]
    need, cls = needs_user_vip(pcie, rtl_text=PCIE)
    assert need and cls.get("protocol") == "pcie"


def test_axi4_class_sv_is_stub_not_lite_golden():
    mod = extract_modules(AXI4)[0]
    sv = render_class_sv_tb(mod, cycles=8, seed=1)
    blob = sv.lower()
    assert "require_user_vip" in blob or "attach user vip" in blob
    assert "model_reg" not in sv
    assert "no invented" in blob or "do not invent" in blob


def test_axi4_uvm_not_seen_plus():
    mod = extract_modules(AXI4)[0]
    sv = render_uvm_smoke_tb(mod, cycles=8)
    assert "seen++" not in sv.replace(" ", "")
    assert "require_user_vip" in sv or "VIP" in sv
    assert "model_reg" not in sv


def test_axi_lite_still_has_real_golden():
    mod = extract_modules(AXI_LITE)[0]
    need, _ = needs_user_vip(mod, rtl_text=AXI_LITE)
    assert need is False
    sv = render_class_sv_tb(mod, cycles=8, seed=1)
    assert "require_user_vip" not in sv.lower()
