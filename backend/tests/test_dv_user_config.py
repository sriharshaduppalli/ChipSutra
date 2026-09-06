"""User DV knobs, protocol packs, and new goldens (no live LLM)."""
from dv_planner import classify_dut, plan_generation
from dv_user_config import parse_dv_config, prompt_block, attach_knobs
from design_analyze import analyze_design, detect_protocol_variant
from rag import retrieve
from rtl_ports import extract_modules
from tb_dut_goldens import (
    detect_can_model,
    detect_uart_rx_model,
    try_render_special_class_tb,
)
from tb_skeleton import classify_ports, detect_axi_lite_model, render_class_sv_tb


SPI = """
module spi_slave(input sclk, input cs_n, input mosi, output miso, output [7:0] rx_byte, output rx_valid);
endmodule
"""

UART_RX = """
module uart_rx(input clk, input rst_n, input rx, output [7:0] dout, output rx_valid);
endmodule
"""

CAN = """
module can_ctrl(input clk, input rst_n, input can_rx, output can_tx);
endmodule
"""

I3C = """
module i3c_target(input scl, input sda_in, output sda_out, input ccc, output ibi);
endmodule
"""

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


def test_parse_prompt_serial_knobs():
    cfg = parse_dv_config(None, prompt="SPI mode 2, I2C master 10-bit, UART RX baud_div=16", env=False)
    k = cfg["protocol_knobs"]
    assert k["spi_mode"] == 2
    assert k["i2c_role"] == "master"
    assert k["i2c_addr_bits"] == 10
    assert k["uart_dir"] == "rx"
    assert k["uart_baud_div"] == 16


def test_parse_json_scale_and_maps():
    cfg = parse_dv_config(
        {
            "scale": "subsystem",
            "memory_map": [{"name": "IMEM", "base": "0x0", "size": "0x10000"}],
            "csr_list": [{"name": "mstatus", "addr": "0x300"}],
            "agents": [{"name": "apb0", "protocol": "apb"}, {"name": "uart0", "protocol": "uart"}],
            "address_map": [{"name": "uart", "base": "0x40000000"}],
        },
        env=False,
    )
    assert cfg["scale"] == "subsystem"
    assert cfg["require_user_vip"] is True
    assert cfg["memory_map"][0]["name"] == "IMEM"
    assert cfg["csr_list"][0]["name"] == "mstatus"
    block = prompt_block(cfg)
    assert "SCALE ORCHESTRATION" in block
    assert "mstatus=0x300" in block
    assert "apb0" in block


def test_parse_memory_map_from_prompt():
    cfg = parse_dv_config(
        None,
        prompt="scale=processor memory_map: IMEM=0x0/65536 DMEM=0x80000000/65536 csr: mstatus=0x300 mtvec=0x305",
        env=False,
    )
    assert cfg["scale"] == "processor"
    assert len(cfg["memory_map"]) == 2
    assert {c["name"] for c in cfg["csr_list"]} >= {"mstatus", "mtvec"}


def test_interface_rtl_is_not_ace():
    rtl = """
    interface foo_if(input logic clk);
      logic a;
    endinterface
    module foo(input clk, input rst_n, output [3:0] count);
    endmodule
    """
    d = classify_dut(extract_modules(rtl), rtl_text=rtl)
    assert d["protocol"] != "ace"


def test_classify_can_i3c_axi4():
    assert classify_dut(extract_modules(CAN))["protocol"] == "can"
    assert classify_dut(extract_modules(I3C))["protocol"] == "i3c"
    d = classify_dut(extract_modules(AXI4))
    assert d["protocol"] == "axi4"
    assert "require_user_vip" in d["tags"]


def test_axi_lite_detector_skips_burst():
    roles = classify_ports(extract_modules(AXI4)[0]["ports"])
    assert detect_axi_lite_model(roles) is None


def test_uart_rx_and_can_goldens():
    urx = extract_modules(UART_RX)[0]
    roles = classify_ports(urx["ports"])
    assert detect_uart_rx_model(roles)
    sv = render_class_sv_tb(urx, cycles=8, seed=1)
    assert "uart_rx" in sv and "baud_div" in sv
    assert "function bit check(); return 1;" not in sv

    can = extract_modules(CAN)[0]
    assert detect_can_model(classify_ports(can["ports"]))
    csv = render_class_sv_tb(can, cycles=4, seed=1)
    assert "can_rx" in csv and "$isunknown" in csv
    assert "function bit check(); return 1;" not in csv


def test_spi_mode3_knob_changes_edges():
    mod = extract_modules(SPI)[0]
    attach_knobs(mod, parse_dv_config({"protocol_knobs": {"spi_mode": 3}}, env=False))
    sv = try_render_special_class_tb(mod, cycles=8, seed=1)
    assert sv and "SPI mode 3" in sv
    assert "spi_mode3" in sv


def test_can_sof_only_with_bit_clocks():
    mod = extract_modules(CAN)[0]
    attach_knobs(mod, parse_dv_config({"protocol_knobs": {"can_bit_clocks": 8}}, env=False))
    sv = try_render_special_class_tb(mod, cycles=4, seed=1)
    assert sv and "repeat (8)" in sv


def test_analyze_honors_uart_rx_knob_and_csr_map():
    mods = extract_modules(UART_RX)
    cfg = parse_dv_config(
        {"csr_list": [{"name": "ctrl", "addr": "0x10"}], "protocol_knobs": {"uart_dir": "rx"}},
        env=False,
    )
    a = analyze_design(mods, user_config=cfg)
    assert a["protocol"] == "uart"
    assert a["protocol_variant"] == "uart_rx"
    assert a["csr"].get("user_map") is True


def test_ip_is_not_aliased_to_block():
    cfg = parse_dv_config({"scale": "ip"}, env=False)
    assert cfg["scale"] == "ip"
    block = prompt_block(cfg)
    assert "SCALE IP" in block
    assert "virtual-seq" in block.lower() or "one DUT" in block


def test_classify_offchip_and_tilelink():
    pcie = """
    module pcie_ep(input clk, input rst_n, input tlp_valid, output [7:0] ltssm);
    endmodule
    """
    assert classify_dut(extract_modules(pcie), rtl_text=pcie)["protocol"] == "pcie"
    tl = """
    module tl_ul_sink(input clk, input a_opcode, output d_opcode);
    endmodule
    """
    assert classify_dut(extract_modules(tl), rtl_text=tl)["protocol"] == "tilelink"
    jtag = """
    module tap(input tck, input tms, input tdi, output tdo);
    endmodule
    """
    assert classify_dut(extract_modules(jtag))["protocol"] == "jtag"


def test_rag_new_protocol_packs():
    pcie = retrieve("PCIe TLP LTSSM endpoint", module="testbench", protocol="pcie", top_k=3)
    sources = " ".join(c["source"] for c in pcie)
    assert "protocol_vip_offchip" in sources
    eth = retrieve("RGMII MDIO ethernet MAC", module="testbench", protocol="ethernet", top_k=3)
    assert "protocol_vip_netio" in " ".join(c["source"] for c in eth)
    mem = retrieve("DDR DFI memory controller", module="testbench", protocol="ddr", top_k=3)
    assert "protocol_vip_memory" in " ".join(c["source"] for c in mem)
    d2d = retrieve("UCIe chiplet mainband", module="testbench", protocol="ucie", top_k=3)
    assert "protocol_vip_d2d" in " ".join(c["source"] for c in d2d)
    ip = retrieve("IP level reusable agent RAL", module="testbench", protocol="ip", top_k=3)
    blob = " ".join(c["body"] for c in ip).lower()
    assert "reusable" in blob or "one dut" in blob


def test_plan_scale_notes():
    mods = extract_modules(CAN)
    cfg = parse_dv_config({"scale": "soc", "agents": [{"name": "can0", "protocol": "can"}]}, env=False)
    p = plan_generation(module="testbench", modules=mods, user_config=cfg)
    assert p["scale"] == "soc"
    assert any("Scale=soc" in n for n in p["notes"])


def test_scale_ip_is_not_block():
    cfg = parse_dv_config({"scale": "ip", "csr_list": [{"name": "CTRL", "addr": "0x0"}]}, env=False)
    assert cfg["scale"] == "ip"
    block = prompt_block(cfg)
    assert "SCALE IP" in block or "Verification IP" in block
    low = block.lower()
    assert "driver" in low and "monitor" in low and "checker" in low and "coverage" in low
    p = plan_generation(module="testbench", modules=extract_modules(CAN), user_config=cfg)
    assert any("Scale=ip" in n for n in p["notes"])


def test_classify_pcie_ethernet_jtag_tilelink():
    pcie = """
    module pcie_ep(input clk, input rst_n, input tlp_valid, output [7:0] ltssm);
    endmodule
    """
    assert classify_dut(extract_modules(pcie), rtl_text=pcie)["protocol"] == "pcie"
    eth = """
    module mac(input clk, input rst_n, output [3:0] rgmii_txd, inout mdio, output mdc);
    endmodule
    """
    assert classify_dut(extract_modules(eth), rtl_text=eth)["protocol"] == "ethernet"
    jtag = """
    module tap(input tck, input tms, input tdi, output tdo);
    endmodule
    """
    assert classify_dut(extract_modules(jtag))["protocol"] == "jtag"
    tl = """
    module tlul(input clk, input a_opcode, output d_opcode);
    endmodule
    """
    assert classify_dut(extract_modules(tl), rtl_text=tl)["protocol"] == "tilelink"


def test_rag_offchip_memory_netio_scale_packs():
    pcie = retrieve("PCIe TLP LTSSM endpoint", module="testbench", protocol="pcie", top_k=3)
    sources = " ".join(c["source"] for c in pcie)
    assert "protocol_vip_offchip" in sources
    blob = " ".join(c["body"] for c in pcie).lower()
    assert "user vip" in blob or "do not invent" in blob

    mem = retrieve("DDR DFI memory controller", module="testbench", protocol="ddr", top_k=3)
    assert "protocol_vip_memory" in " ".join(c["source"] for c in mem)

    eth = retrieve("RGMII MDIO ethernet MAC", module="testbench", protocol="ethernet", top_k=3)
    assert "protocol_vip_netio" in " ".join(c["source"] for c in eth)

    ip = retrieve("IP level reusable agent RAL", module="testbench", protocol="ip", top_k=3)
    sources = " ".join(c["source"] for c in ip)
    assert "protocol_vip_anatomy" in sources or "verification_stages" in sources or "protocol_vip_scale" in sources
    blob = " ".join(c["body"] for c in ip).lower()
    assert "driver" in blob and "monitor" in blob
    assert "checker" in blob or "coverage" in blob

    vip = retrieve("What is Verification IP driver monitor checker coverage", module="testbench", protocol="vip", top_k=3)
    vblob = " ".join(c["body"] for c in vip).lower()
    vsources = " ".join(c["source"] for c in vip)
    assert "driver" in vblob and "monitor" in vblob and "coverage" in vblob
    assert "protocol_vip_commercial" in vsources or "pcie" in vblob or "dram" in vblob
    bfm = retrieve("VIP vs BFM bus functional model", module="testbench", protocol="vip", top_k=3)
    bblob = " ".join(c["body"] for c in bfm).lower()
    assert "bfm" in bblob and ("checker" in bblob or "coverage" in bblob)


def test_rag_can_and_i3c_and_axi4_packs():
    can = retrieve("CAN IP testbench bus-off", module="testbench", protocol="can", top_k=3)
    blob = " ".join(c["body"] for c in can).lower()
    assert "can" in blob and ("bit-time" in blob or "sof" in blob or "recessive" in blob)

    i3c = retrieve("I3C CCC IBI", module="testbench", protocol="i3c", protocol_variant="i3c", top_k=3)
    sources = " ".join(c["source"] for c in i3c)
    assert "protocol_vip_i3c" in sources

    axi = retrieve("AXI4 burst AWLEN", module="testbench", protocol="axi4", protocol_variant="axi4_burst", top_k=3)
    sources = " ".join(c["source"] for c in axi)
    assert "protocol_vip_axi_full" in sources
    blob = " ".join(c["body"] for c in axi).lower()
    assert "user vip" in blob or "require user" in blob


def test_spi_variant_from_knob():
    v = detect_protocol_variant("spi", {"sclk", "mosi", "cs_n"})
    assert v["protocol_variant"] == "spi_mode0"
    mods = extract_modules(SPI)
    cfg = parse_dv_config({"protocol_knobs": {"spi_mode": 1}}, env=False)
    a = analyze_design(mods, user_config=cfg)
    assert a["protocol_variant"] == "spi_mode1"
