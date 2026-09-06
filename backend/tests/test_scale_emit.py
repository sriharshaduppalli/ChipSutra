"""IP / subsystem scale emitters. Block goldens stay unchanged."""
from dv_user_config import attach_knobs, parse_dv_config
from rtl_ports import extract_modules
from tb_class_lint import lint_class_sv_tb
from tb_dut_goldens import try_render_special_class_tb
from tb_scale_emit import match_topology_agents, protocol_from_port_names, scale_of
from tb_skeleton import render_class_sv_tb

APB = """
module apb_regs(
  input pclk, input presetn, input psel, input penable, input pwrite,
  input [7:0] paddr, input [31:0] pwdata, output pready, output [31:0] prdata
);
endmodule
"""


def _mod():
    return extract_modules(APB)[0]


def _lint(sv, mod):
    ports = [p["name"] for p in mod["ports"]]
    outs = [
        p["name"]
        for p in mod["ports"]
        if (p.get("direction") or "").lower() in ("output", "out", "inout")
    ]
    ok, issues = lint_class_sv_tb(
        sv,
        dut_name=mod["name"],
        required_ports=ports,
        dut_outputs=outs,
        port_specs=mod["ports"],
    )
    assert ok, issues


def test_block_scale_has_no_ip_extras():
    mod = _mod()
    sv = render_class_sv_tb(mod, cycles=8, seed=1)
    assert "model_reg [0:3]" in sv
    assert "apb_regs_agent_cfg" not in sv
    assert "apb_regs_vseq" not in sv
    _lint(sv, mod)


def test_ip_scale_emits_vip_four_parts():
    mod = _mod()
    cfg = parse_dv_config({"scale": "ip"}, env=False)
    attach_knobs(mod, cfg)
    assert scale_of(mod) == "ip"
    sv = try_render_special_class_tb(mod, cycles=8, seed=1)
    assert sv
    assert "apb_regs_agent_cfg" in sv
    assert "is_active" in sv
    assert "apb_regs_checker" in sv
    assert "covergroup" in sv
    assert "model_reg [0:3]" in sv  # no user map → eval-compatible model
    assert "apb_regs_vseq" not in sv
    _lint(sv, mod)


def test_subsystem_matches_apb_skips_uart():
    mod = _mod()
    cfg = parse_dv_config(
        {
            "scale": "subsystem",
            "topology": {
                "agents": [
                    {"name": "apb0", "protocol": "apb"},
                    {"name": "uart0", "protocol": "uart"},
                ],
                "clocks": ["pclk", "uclk"],
            },
        },
        env=False,
    )
    attach_knobs(mod, cfg)
    sv = try_render_special_class_tb(mod, cycles=8, seed=1)
    assert sv
    assert "apb_regs_vseq" in sv
    assert "matched DUT ports" in sv
    assert "SKIP agent uart0" in sv
    assert "uart0_ss_agent" in sv
    assert "do not invent RTL" in sv.lower() or "do not invent" in sv.lower()
    assert "CDC:" in sv
    # Did not invent a UART DUT or extra APB slave
    assert sv.lower().count("module apb_regs") == 0 or "apb_regs dut" in sv
    assert "uart_tx" not in sv
    _lint(sv, mod)


def test_match_agents_from_ports():
    names = ["pclk", "psel", "penable", "pwrite", "paddr"]
    assert protocol_from_port_names(names) == "apb"
    agents = match_topology_agents(
        [{"name": "apb0", "protocol": "apb"}, {"name": "spi0", "protocol": "spi"}],
        names,
    )
    by = {a["name"]: a["matched"] for a in agents}
    assert by["apb0"] is True
    assert by["spi0"] is False


def test_uvm_ip_has_active_cfg_and_vip_sketch():
    from tb_uvm_lint import lint_uvm_tb
    from tb_uvm_skeleton import render_uvm_smoke_tb

    mod = _mod()
    cfg = parse_dv_config({"scale": "ip", "require_user_vip": True}, env=False)
    attach_knobs(mod, cfg)
    sv = render_uvm_smoke_tb(mod, cycles=8)
    assert "Commercial VIP integration" in sv
    assert "uvm_active_passive_enum is_active" in sv
    assert "do not copy vendor source" in sv
    ok, issues = lint_uvm_tb(sv, port_specs=mod["ports"])
    assert ok, issues


def test_ip_apb_verilator_if_present():
    from pathlib import Path

    from dv_verify import verify_testbench

    rtl_path = Path(__file__).resolve().parents[1] / "scripts" / "eval_suite" / "duts" / "apb_regs.sv"
    rtl = rtl_path.read_text(encoding="utf-8")
    mod = extract_modules(rtl)[0]
    cfg = parse_dv_config({"scale": "ip"}, env=False)
    attach_knobs(mod, cfg)
    sv = try_render_special_class_tb(mod, cycles=8, seed=1)
    result = verify_testbench([("apb_regs.sv", rtl)], sv, tb_name="apb_regs_tb.sv", mode="run")
    if result.get("skipped") or result.get("reason") == "verilator_not_on_path":
        return
    assert result.get("ok") is True, result.get("sim_log") or result
    assert result.get("sim_pass") is True, result.get("sim_log")
