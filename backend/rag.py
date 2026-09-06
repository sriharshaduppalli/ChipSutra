"""
Lightweight RAG for ChipSutra generation (no vector DB, no extra deps).

Loads markdown-ish chunks from backend/knowledge/ and retrieves by keyword overlap.
Disable with RAG_ENABLED=false.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

try:  # optional: vector/embedding reranking. Keyword retrieval works without it.
    import rag_vector
except Exception:  # pragma: no cover - module absent or broken import
    rag_vector = None  # type: ignore[assignment]

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

# Not RAG corpus (Modelfile authoring / internal)
_SKIP_KNOWLEDGE_FILES = frozenset({"vlsi_system.txt", "readme.txt"})

# Boost retrieval when module or filenames hint at a domain
MODULE_HINTS: dict[str, tuple[str, ...]] = {
    "testbench": (
        "verilator",
        "randomized",
        "urandom",
        "randomize",
        "constraint",
        "rand",
        "golden",
        "expected",
        "scoreboard",
        "fifo",
        "axi-lite",
        "template",
        "methodology",
        "uvm",
        "uvm_agent",
        "config_db",
        "run_test",
        "systemverilog",
        "datatype",
        "logic",
        "array",
        "queue",
        "covergroup",
        "coverpoint",
        "assertion",
        "property",
        "interface",
        "modport",
        "clocking",
        "mailbox",
        "semaphore",
        "fork",
        "class",
        "oop",
        "generator",
        "environment",
        "fundamentals",
        "dut",
        "duv",
        "design under test",
        "abstraction",
        "layered",
        "program",
        "reactive region",
        "scope resolution",
        "extern",
        "local",
        "protected",
        "function",
        "ref",
        "automatic",
        "package",
        "import",
        "callback",
        "`define",
        "`ifdef",
        "always_comb",
        "always_ff",
        "cheat sheet",
        "plusargs",
        "$test$plusargs",
        "$value$plusargs",
        "$fopen",
        "$fdisplay",
        "$fgets",
        "reg_ctrl",
        "switch",
        "adder",
        "carry",
        "ready",
        "semaphore",
        "scoreboard",
        "uvm",
        "ovm",
        "vmm",
        "sequence",
        "driver",
        "monitor",
        "agent",
    ),
    "assertions": (
        "sva",
        "assert",
        "property",
        "sequence",
        "formal",
        "handshake",
        "disable iff",
        "concurrent",
        "immediate",
        "cover property",
        "assume",
        "bind",
        "fast-track",
        "multiclock",
    ),
    "spec2rtl": ("fpga", "latch", "synth", "yosys", "mathlib", "fixed-point", "cordic"),
    "checkers": ("checker", "scoreboard", "protocol", "assertion"),
    "covergroups": (
        "coverage",
        "bin",
        "cross",
        "covergroup",
        "coverpoint",
        "illegal_bins",
        "ignore_bins",
        "sample",
        "functional coverage",
    ),
    "debug": ("uvm_error", "simulation", "debug", "log", "timeout", "x propagation", "verilator"),
    "coverage_holes": (
        "coverage",
        "bin",
        "cross",
        "hole",
        "sequence",
        "covergroup",
        "directed",
        "closure",
        "constraint",
    ),
    "formal_hints": ("sva", "assume", "cover", "formal", "restrict", "bounded", "proof", "fast-track", "multiclock"),
    "testplan": ("verification plan", "simulation", "formal", "emulation", "fpga"),
}

# Preferred knowledge sources when design analysis supplies a protocol pack
PROTOCOL_PACK_SOURCES: dict[str, tuple[str, ...]] = {
    "axi_lite": ("protocol_vip_axi_lite.txt", "protocol_tb_guidance.txt"),
    "axi4_lite": ("protocol_vip_axi_lite.txt", "protocol_tb_guidance.txt"),
    "axi4": ("protocol_vip_axi_full.txt", "protocol_vip_axi_lite.txt"),
    "axi4_burst": ("protocol_vip_axi_full.txt", "vlsi_protocols_compact.txt"),
    "ace": ("protocol_vip_axi_full.txt", "vlsi_protocols_compact.txt"),
    "chi": ("protocol_vip_axi_full.txt", "vlsi_protocols_compact.txt"),
    "apb": ("protocol_vip_apb.txt", "protocol_tb_guidance.txt"),
    "apb3": ("protocol_vip_apb.txt", "protocol_tb_guidance.txt"),
    "apb4": ("protocol_vip_apb.txt", "protocol_tb_guidance.txt"),
    "ahb": ("protocol_vip_ahb.txt", "protocol_tb_guidance.txt"),
    "ahb_lite": ("protocol_vip_ahb.txt", "protocol_tb_guidance.txt"),
    "ahb5": ("protocol_vip_ahb.txt", "protocol_tb_guidance.txt"),
    "axis": ("protocol_vip_axis.txt", "protocol_tb_guidance.txt"),
    "axi4_stream": ("protocol_vip_axis.txt", "protocol_tb_guidance.txt"),
    "spi": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "spi_mode0": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "spi_mode1": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "spi_mode2": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "spi_mode3": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "qspi": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "i2c": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "i2c_7bit": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "i2c_10bit": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "i2c_master": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "uart": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "uart_8n1": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "uart_rx": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "uart_tx": ("protocol_vip_serial.txt", "protocol_tb_guidance.txt"),
    "can": ("protocol_vip_can.txt", "vlsi_protocols_compact.txt"),
    "canfd": ("protocol_vip_can.txt", "vlsi_protocols_compact.txt"),
    "i3c": ("protocol_vip_i3c.txt", "protocol_vip_serial.txt"),
    "processor": ("protocol_vip_riscv.txt", "protocol_vip_scale.txt"),
    "ip": ("protocol_vip_anatomy.txt", "verification_stages.txt"),
    "vip": ("protocol_vip_anatomy.txt", "protocol_vip_commercial.txt"),
    "block": ("protocol_vip_scale.txt", "verification_stages.txt"),
    "subsystem": ("protocol_vip_scale.txt", "verification_stages.txt"),
    "soc": ("protocol_vip_scale.txt", "verification_stages.txt"),
    "chiplet": ("protocol_vip_scale.txt", "protocol_vip_d2d.txt"),
    "pcie": ("protocol_vip_offchip.txt", "vlsi_protocols_compact.txt"),
    "pcie_ep": ("protocol_vip_offchip.txt", "vlsi_protocols_compact.txt"),
    "pcie_rc": ("protocol_vip_offchip.txt", "vlsi_protocols_compact.txt"),
    "cxl": ("protocol_vip_offchip.txt", "vlsi_protocols_compact.txt"),
    "ucie": ("protocol_vip_d2d.txt", "protocol_vip_scale.txt"),
    "bow": ("protocol_vip_d2d.txt", "protocol_vip_scale.txt"),
    "aib": ("protocol_vip_d2d.txt", "protocol_vip_scale.txt"),
    "ddr": ("protocol_vip_memory.txt", "vlsi_protocols_compact.txt"),
    "lpddr": ("protocol_vip_memory.txt", "vlsi_protocols_compact.txt"),
    "hbm": ("protocol_vip_memory.txt", "vlsi_protocols_compact.txt"),
    "dfi": ("protocol_vip_memory.txt", "vlsi_protocols_compact.txt"),
    "sram": ("protocol_vip_memory.txt", "protocol_vip_simple.txt"),
    "ethernet": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "rgmii": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "gmii": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "usb": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "mipi": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "csi": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "dsi": ("protocol_vip_netio.txt", "vlsi_protocols_compact.txt"),
    "tilelink": ("protocol_vip_onchip.txt", "vlsi_protocols_compact.txt"),
    "tl_ul": ("protocol_vip_onchip.txt", "vlsi_protocols_compact.txt"),
    "jtag": ("protocol_vip_debug.txt", "vlsi_soc_dft_power.txt"),
    "swd": ("protocol_vip_debug.txt", "vlsi_soc_dft_power.txt"),
    "dft": ("protocol_vip_debug.txt", "vlsi_soc_dft_power.txt"),
    "formal": ("verification_techniques.txt", "sva_patterns.txt"),
    "simulation": ("verification_techniques.txt", "verification_methodologies_curriculum.txt"),
    "emulation": ("verification_techniques.txt", "protocol_vip_commercial.txt"),
    "fpga_proto": ("verification_techniques.txt", "vlsi_soc_dft_power.txt"),
    "block_level": ("verification_stages.txt", "protocol_vip_scale.txt"),
    "subsystem_level": ("verification_stages.txt", "protocol_vip_scale.txt"),
    "soc_level": ("verification_stages.txt", "protocol_vip_scale.txt"),
    "ral": ("protocol_vip_ral.txt", "uvm_ral.txt"),
    "uvm_ral": ("protocol_vip_ral.txt", "uvm_ral_classes.txt"),
    "fifo": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "sync_fifo_fwft": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "mux": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "combinational_mux": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "mux4_combinational": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "alu": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "combinational_alu": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "counter": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "enable_counter": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "parity": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "xor_parity": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "switch": ("protocol_vip_simple.txt", "uvm_tb_example2.txt"),
    "addr_range_switch": ("protocol_vip_simple.txt", "uvm_tb_example2.txt"),
    "stream": ("protocol_vip_axis.txt", "protocol_tb_guidance.txt"),
    "riscv": ("protocol_vip_riscv.txt", "protocol_tb_guidance.txt"),
    "rv32i": ("protocol_vip_riscv.txt", "protocol_tb_guidance.txt"),
    "rv32i_smoke": ("protocol_vip_riscv.txt", "protocol_tb_guidance.txt"),
    "wishbone": ("protocol_vip_onchip.txt", "vlsi_protocols_compact.txt"),
    "avalon": ("protocol_vip_onchip.txt", "vlsi_protocols_compact.txt"),
    "avalon_mm": ("protocol_vip_onchip.txt", "vlsi_protocols_compact.txt"),
    "fsm": ("protocol_vip_onchip.txt", "protocol_vip_simple.txt"),
    "encoder": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "gray": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "edge": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
    "cdc": ("protocol_vip_simple.txt", "protocol_tb_guidance.txt"),
}

# First-TB Example 1 graph — pin UVM generate to this stack, not later tutorial pages.
UVM_FIRST_TB_SOURCES = (
    "uvm_tb_example1.txt",
    "sv_vs_uvm_tb_map.txt",
    "uvm_agent.txt",
    "uvm_scoreboard.txt",
    "uvm_tb_top.txt",
)
TB_COMPARE_SOURCES = ("sv_vs_uvm_tb_map.txt",)
UVM_GUIDE_SOURCES = ("uvm_users_guide_emit.txt", "uvm_guide_reusable_vip.txt", "uvm_guide_using_vip.txt")
OVM_VMM_INTEROP_SOURCES = ("ovm_vmm_interop_emit.txt",)
UVM_EXAMPLE2_SOURCES = ("uvm_tb_example2.txt",)
UVM_DEMOTE_SOURCES = frozenset(
    {
        "uvm_subscriber.txt",
        "uvm_tlm_blocking_get.txt",
        "uvm_tlm_blocking_put.txt",
        "uvm_tlm_nonblocking_get.txt",
        "uvm_tlm_nonblocking_put.txt",
        "uvm_get_put.txt",
        "uvm_tlm_sockets.txt",
        "uvm_do.txt",
        "uvm_sequence_macros.txt",
        "uvm_ral.txt",
        "uvm_ral_backdoor.txt",
        "uvm_ral_classes.txt",
        "uvm_ral_connect.txt",
        "uvm_ral_env.txt",
        "uvm_ral_example.txt",
        "uvm_user_phases.txt",
        "uvm_virtual_sequence.txt",
        "uvm_virtual_sequencer.txt",
    }
)

PROTOCOL_ALIASES: dict[str, tuple[str, ...]] = {
    "can": ("can", "can-fd", "bus-off", "can_ip", "iso 11898"),
    "lin": ("lin", "lin bus"),
    "flexray": ("flexray", "tdma"),
    # Avoid bare valid/ready — too common in every SV TB curriculum chunk
    "axi": ("axi", "axi4", "axi-lite", "axilite", "awvalid", "wvalid", "arvalid"),
    "axi_lite": ("axi-lite", "axi4-lite", "axilite", "s_axi_awvalid", "wstrb", "bresp", "axi5-lite"),
    "ace": ("ace", "ace-lite", "snoop", "coherency"),
    "chi": ("chi", "amba chi", "flit"),
    "apb": ("apb", "psel", "penable", "pready", "pstrb", "pprot"),
    "ahb": ("ahb", "htrans", "hready", "hburst", "hreadyout", "nonseq", "hwrite", "hwdata"),
    "axis": ("axis", "axi-stream", "axi stream", "tvalid", "tlast"),
    "fifo": ("fifo", "wr_en", "rd_en", "fwft", "almost_full"),
    "mux": ("mux", "select", "combinational mux"),
    "alu": ("alu", "opcode", "adder"),
    "counter": ("counter", "enable counter"),
    "parity": ("parity", "xor reduction"),
    "switch": ("switch", "addr_a", "addr_b", "data_a", "data_b", "addr range"),
    "riscv": ("riscv", "rv32i", "rv32e", "opcode", "funct3", "imem"),
    "wishbone": ("wishbone", "wbm", "wbs", "cyc", "stb"),
    "avalon": ("avalon", "waitrequest", "readdatavalid"),
    "tilelink": ("tilelink", "tl-ul", "tl-uh", "tl-c"),
    "pcie": ("pcie", "tlp", "completion", "ltssm"),
    "cxl": ("cxl", "cxl.io", "cxl.cache"),
    "ethernet": ("ethernet", "rgmii", "gmii", "mii", "mdio", "mac", "pcs"),
    "ddr": ("ddr", "lpddr", "hbm", "memory controller", "dfi"),
    "sram": ("sram", "rf ", "byte enable", "ecc"),
    "i2c": ("i2c", "sda", "scl", "smbus"),
    "i3c": ("i3c", "ccc", "ibi"),
    "spi": ("spi", "cpol", "cpha", "qspi", "flash"),
    "uart": ("uart", "baud", "usart"),
    "i2s": ("i2s", "tdm", "pdm", "audio"),
    "usb": ("usb", "utmi", "ulpi", "ltssm"),
    "mipi": ("mipi", "csi", "dsi", "d-phy"),
    "jtag": ("jtag", "tap", "tdi", "tdo", "tms", "boundary scan"),
    "swd": ("swd", "swclk", "swdio"),
    "dft": ("dft", "scan", "mbist", "lbist", "atpg", "occ"),
    "formal": ("formal verification", "bounded proof", "full proof", "state space explosion"),
    "emulation": ("emulation", "hardware emulator", "software bring-up"),
    "fpga_proto": ("fpga prototyping", "fpga prototype", "near real-time"),
    "block_level": ("block-level", "unit-level verification", "block sign-off"),
    "subsystem_level": ("subsystem-level", "integration verification", "inter-block"),
    "soc_level": ("system-level verification", "soc verification", "full chip"),
    "cdc": ("cdc", "async fifo", "metastability", "2ff", "rdc"),
    "upf": ("upf", "power domain", "isolation", "retention"),
    "ucie": ("ucie", "bow", "chiplet", "die-to-die", "aib"),
    "vip": (
        "verification ip",
        "reusable vip",
        "uvc",
        "protocol vip",
        "synopsys vip",
        "smartdv",
        "test suite",
        "vplan",
        "bus functional model",
        "bfm vs vip",
    ),
    "riscv": ("risc-v", "riscv", "plic", "clint", "pmp"),
    "uvm": (
        "uvm",
        "uvm_env",
        "uvm_agent",
        "uvm_driver",
        "uvm_monitor",
        "uvm_sequencer",
        "uvm_sequence",
        "sequence_item",
        "uvm_test",
        "ral",
        "scoreboard",
        "config_db",
        "factory",
        "uvm_phase",
        "objection",
        "uvm_component",
        "uvm_object",
        "uvm_transaction",
        "analysis_port",
        "tlm",
        "uvm_home",
        "accellera",
        "incdir",
        "uvm install",
        "hello uvm",
        "run_test",
        "print_topology",
        "uvm_test_top",
        "uvm_pkg",
        "class library",
        "uvm_root",
        "reg_block",
        "reg_if",
        "first testbench",
        "uvm_object",
        "uvm_object_utils",
        "type_id::create",
        "sequence_item",
        "uvm_field_int",
        "reg_transaction",
        "uvm_component",
        "uvm_component_utils",
        "build_phase",
        "get_full_name",
        "uvm_driver",
        "get_next_item",
        "item_done",
        "seq_item_port",
        "uvm_monitor",
        "analysis_port",
        "mon_analysis_port",
        "uvm_subscriber",
        "analysis_export",
        "covergroup",
        "uvm_sequencer",
        "seq_item_export",
        "pull model",
        "uvm_sequence",
        "start_item",
        "finish_item",
        "body()",
        "raise_objection",
        "drop_objection",
        "default_sequence",
        "pre_body",
        "post_body",
        "uvm_scoreboard",
        "analysis_imp",
        "reference model",
        "mismatch",
        "uvm_agent",
        "is_active",
        "UVM_ACTIVE",
        "UVM_PASSIVE",
        "get_is_active",
        "uvm_env",
        "reg_env",
        "uvm_test",
        "print_topology",
        "UVM_TESTNAME",
        "tb_top",
        "run_test",
        "dumpvars",
        "uvm_void",
        "uvm_report_object",
        "uvm_transaction",
        "uvm_top",
        "uvm_root",
        "find_all",
        "uvm_test_top",
        "pack_bytes",
        "unpack",
        "do_pack",
        "uvm_packer",
        "do_compare",
        "compare",
        "MISCMP",
        "do_print",
        "sprint",
        "convert2string",
        "uvm_printer",
        "do_copy",
        "clone",
        "uvm_object_utils",
        "uvm_component_utils",
        "uvm_field_int",
        "uvm_field_enum",
        "uvm_field_object",
        "uvm_field_queue_int",
        "uvm_field_string",
        "UVM_DEFAULT",
        "UVM_NOCOPY",
        "UVM_REFERENCE",
        "UVM_HEX",
        "build_phase",
        "connect_phase",
        "run_phase",
        "end_of_elaboration",
        "extract_phase",
        "check_phase",
        "report_phase",
        "final_phase",
        "main_phase",
        "reset_phase",
        "raise_objection",
        "drop_objection",
        "set_drain_time",
        "get_starting_phase",
        "set_automatic_phase_objection",
        "UVM_OBJECTION_TRACE",
        "uvm_task_phase",
        "uvm_domain",
        "get_common_domain",
        "get_uvm_domain",
        "user-defined phase",
        "custom phase",
        "set_type_override",
        "set_inst_override",
        "type_override",
        "instance override",
        "uvm_factory",
        "factory.print",
        "uvm_config_db",
        "uvm_resource_db",
        "uvm_active_passive_enum",
        "UVM_ACTIVE",
        "UVM_PASSIVE",
        "config object",
        "env_cfg",
        "uvm_resource_pool",
        "resource database",
        "get_by_name",
        "get_by_type",
        "UVM_CONFIG_DB_TRACE",
        "NO_REG_TESTS",
        "wait_modified",
        "config_db::set",
        "config_db::get",
        "set_config_int",
        "my_agent_config",
        "CFGDB/SET",
        "CFGDB/GET",
        "config_db_trace",
        "TLM",
        "transaction level",
        "tlm port",
        "tlm export",
        "analysis_port",
        "seq_item_port",
        "uvm_blocking_put_port",
        "uvm_blocking_put_imp",
        "blocking put",
        "uvm_blocking_get_port",
        "uvm_blocking_get_imp",
        "blocking get",
        "uvm_tlm_fifo",
        "put_export",
        "get_export",
        "is_full",
        "tlm hierarchy",
        "port forward",
        "blocking_put_export",
        "uvm_analysis_port",
        "uvm_analysis_imp",
        "analysis_export",
        "ap.write",
        "b_transport",
        "initiator_socket",
        "target_socket",
        "uvm_tlm_b_initiator_socket",
        "uvm_tlm_time",
        "uvm_blocking_put_imp_decl",
        "uvm_analysis_imp_decl",
        "put_1",
        "write_expected",
        "try_put",
        "can_put",
        "uvm_nonblocking_put_port",
        "uvm_nonblocking_put_imp",
        "port to export",
        "export to imp",
        "hierarchical tlm",
        "try_get",
        "can_get",
        "uvm_nonblocking_get_port",
        "uvm_nonblocking_get_imp",
        "pre_body",
        "post_body",
        "pre_start",
        "post_start",
        "pre_do",
        "mid_do",
        "post_do",
        "call_pre_post",
        "parent_sequence",
        "uvm_do",
        "uvm_do_with",
        "uvm_do_on_pri_with",
        "uvm_do_on",
        "uvm_do_pri",
        "m_sequencer",
        "do_not_randomize",
        "RNDFLD",
        "uvm_send",
        "uvm_rand_send",
        "uvm_create",
        "uvm_send_pri",
        "virtual sequence",
        "virtual_seq",
        "uvm_declare_p_sequencer",
        "p_sequencer",
        "virtual sequencer",
        "virtual_sequencer",
        "m_vseqr",
        "uvm_sequence_library",
        "UVM_SEQ_LIB_RAND",
        "UVM_SEQ_LIB_RANDC",
        "init_sequence_library",
        "add_typewide_sequence",
        "set_arbitration",
        "UVM_SEQ_ARB_FIFO",
        "UVM_SEQ_ARB_STRICT_FIFO",
        "UVM_SEQ_ARB_RANDOM",
        "UVM_SEQ_ARB_WEIGHTED",
        "this_priority",
        "uvm_report_handler",
        "uvm_report_server",
        "reporting classes",
        "reporting functions",
        "uvm_report_info",
        "uvm_report_warning",
        "uvm_report_error",
        "uvm_report_fatal",
        "set_report_verbosity",
        "UVM_NONE",
        "UVM_LOW",
        "UVM_MEDIUM",
        "UVM_HIGH",
        "UVM_FULL",
        "UVM_DEBUG",
        "UVM_VERBOSITY",
        "uvm_table_printer",
        "uvm_tree_printer",
        "uvm_line_printer",
        "uvm_default_printer",
        "uvm_printer_knobs",
        "print_object",
        "uvm_comparer",
        "compare_field",
        "compare_field_int",
        "compare_object",
        "compare_string",
        "show_max",
        "MISCMP",
        "uvm_register_cb",
        "uvm_do_callbacks",
        "uvm_callbacks",
        "uvm_event",
        "wait_trigger",
        "wait_ptrigger",
        "wait_on",
        "wait_off",
        "uvm_event_pool",
        "get_global_pool",
        "get_global",
        "register abstraction",
        "RAL",
        "uvm_reg",
        "uvm_reg_block",
        "uvm_reg_field",
        "uvm_reg_map",
        "memory map",
        "desired value",
        "mirrored value",
        "get_mirrored_value",
        "individually_accessible",
        "create_map",
        "add_reg",
        "uvm_reg_adapter",
        "reg2bus",
        "bus2reg",
        "uvm_reg_predictor",
        "uvm_reg_bus_op",
        "lock_model",
        "provides_responses",
        "supports_byte_enable",
        "set_sequencer",
        "default_map",
        "UVM_BACKDOOR",
        "UVM_FRONTDOOR",
        "add_hdl_path",
        "add_hdl_path_slice",
        "backdoor",
        "ral_sys_traffic",
        "reg2apb_adapter",
        "traffic",
        "include_coverage",
        "get_next_item",
        "item_done",
        "start_item",
        "finish_item",
        "transaction object",
        "convert2string",
        "get_response",
        "seq_item_port.get",
        "seq_item_port.put",
        "uvm_hdl_deposit",
        "uvm_hdl_force",
        "uvm_hdl_read",
        "uvm_hdl_check_path",
        "uvm_hdl_release",
        "singleton",
        "static get",
        "reusable",
        "verification IP",
        "VIP",
        "is_active",
        "agent_cfg",
        "UVC",
        "chip_env",
        "env_cfg",
        "pattern detector",
        "det_1011",
        "ref_pattern",
        "reg_item",
        "reg_vif",
        "gen_item_seq",
        "switch_item",
        "switch_vif",
        "addr_a",
        "ovm",
        "1800.2",
        "user's guide",
        "UVC",
        "end of test",
        "register layer",
    ),
    "ovm": (
        "ovm",
        "ovm_env",
        "ovm_agent",
        "run_test",
        "interop",
        "avt_",
        "vmm_channel",
        "vmm_notify",
        "OVM-on-top",
    ),
    "vmm": (
        "vmm",
        "vmm_data",
        "vmm_channel",
        "xactor",
        "interop",
        "avt_",
        "tlm2channel",
        "VMM-on-top",
        "notify",
    ),
    "methodology": ("methodology", "pure sv", "systemverilog testbench", "verification methodology"),
    "constraint": ("constraint", "randomize", "randc", "dist", "soft constraint", "solve before"),
    "interface": ("interface", "modport", "clocking", "virtual interface"),
    "sva": ("sva", "assert property", "cover property", "disable iff", "sequence"),
    "covergroup": ("covergroup", "coverpoint", "bins", "cross", "functional coverage"),
    "oop": ("class", "extends", "virtual", "polymorphism", "handle", "oops", "object"),
    "ipc": ("mailbox", "semaphore", "event", "fork", "join_any", "join_none"),
    "queue": ("queue", "push_back", "pop_front", "associative", "dynamic array"),
    "datatype": ("logic", "bit", "reg", "int", "enum", "typedef", "2-state", "4-state"),
    "program": ("program block", "endprogram", "reactive region", "program automatic"),
    "functions": (
        "function",
        "endfunction",
        "pass by value",
        "pass by reference",
        "ref int",
        "automatic",
        "return",
    ),
    "package": (
        "package",
        "endpackage",
        "import",
        "wildcard import",
        "alu_pkg",
        "my_pkg::",
    ),
    "callback": (
        "callback",
        "register_callback",
        "uvm_callback",
        "uvm_register_cb",
        "uvm_do_callbacks",
        "uvm_callbacks",
        "pre_err_callback",
        "post_drive",
        "hook",
    ),
    "macros": (
        "`define",
        "define macro",
        "`ifdef",
        "uvm_object_utils",
        "text substitution",
        "concatenate",
    ),
    "oss_lab": (
        "skywater",
        "opensta",
        "yosys",
        "icarus",
        "waveform",
        "pdk",
        "chipverify lab",
    ),
    "refresher": (
        "quick refresher",
        "cheat sheet",
        "always_comb",
        "always_ff",
        "unique case",
        "synthesis",
        "pitfalls",
    ),
    "scope": (
        "scope resolution",
        "::",
        "extern",
        "extern function",
        "extern task",
        "out of body",
        "namespace",
        "my_pkg::",
        "static function",
        "local",
        "protected",
        "encapsulation",
        "access qualifier",
    ),
    "plusargs": (
        "plusargs",
        "$test$plusargs",
        "$value$plusargs",
        "+SEED",
        "+N_TXN",
        "command line",
    ),
    "fileops": (
        "$fopen",
        "$fclose",
        "$fdisplay",
        "$fgets",
        "$feof",
        "$fscanf",
        "file descriptor",
        "multichannel",
    ),
    "tb_example": (
        "reg_ctrl",
        "reg_item",
        "testbench example",
        "refq",
        "apply_stim",
        "drv_done",
        "switch_item",
        "ADDR_DIV",
        "sample_port",
        "my_adder",
        "clk_if",
        "buggy design",
    ),
    "control": ("for loop", "foreach", "repeat", "while", "case equality", "===",),
    "fundamentals": (
        "fundamentals",
        "must-know",
        "data types",
        "arrays",
        "classes",
        "randomization",
        "constraints",
        "covergroups",
        "assertions",
    ),
}


def _enabled() -> bool:
    return os.environ.get("RAG_ENABLED", "true").lower() in ("1", "true", "yes")


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_\-/]{3,}", (text or "").lower()))


def load_chunks(knowledge_dir: Optional[Path] = None) -> List[dict]:
    """Parse ## sections from .txt files in knowledge_dir."""
    root = knowledge_dir or KNOWLEDGE_DIR
    if not root.is_dir():
        return []
    chunks: List[dict] = []
    for path in sorted(root.glob("*.txt")):
        if path.name.lower() in _SKIP_KNOWLEDGE_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        parts = re.split(r"(?m)^##\s+", text)
        if len(parts) <= 1:
            chunks.append({"source": path.name, "title": path.stem, "body": text.strip()})
            continue
        for part in parts[1:]:
            lines = part.strip().splitlines()
            title = lines[0].strip() if lines else path.stem
            body = "\n".join(lines[1:]).strip()
            if body:
                chunks.append({"source": path.name, "title": title, "body": body})
    return chunks


def _term_in_text(term: str, text: str) -> bool:
    """Match protocol terms; short tokens use word boundaries (avoid can in ChipVerify, stb in testbench)."""
    t = (term or "").lower().strip()
    if not t:
        return False
    # Short aliases are noisy as substrings (can/stb/cyc/ace/chi/cdc).
    if len(t) <= 4 and " " not in t:
        return re.search(rf"(?<![a-z0-9_]){re.escape(t)}(?![a-z0-9_])", text) is not None
    return t in text


def _score_chunk(
    query_tokens: set[str],
    chunk: dict,
    extra_terms: Sequence[str],
    protocol_terms: Sequence[str],
    query_text: str = "",
) -> float:
    blob = f"{chunk['title']} {chunk['body']}".lower()
    ctoks = _tokenize(blob)
    if not ctoks:
        return 0.0
    overlap = len(query_tokens & ctoks)
    qlow = (query_text or "").lower()
    for term in protocol_terms:
        # Only boost aliases that the user actually mentioned (stops curriculum floods)
        if _term_in_text(term, blob) and (not qlow or _term_in_text(term, qlow)):
            t = term.lower().strip()
            overlap += 14 if len(t) >= 5 else 8
    for term in extra_terms:
        if _term_in_text(term, blob):
            # Module hints only lightly boost unless also in the user query
            overlap += 2 if term.lower() in query_tokens else 1
    return overlap - (len(chunk["body"]) / 8000.0)


def _hybrid_rerank(
    chunks: Sequence[dict],
    query: str,
    scores: Sequence[float],
    top_k: int,
) -> Optional[List[dict]]:
    """Blend keyword scores with embedding similarity; None when vector RAG is unavailable."""
    if rag_vector is None:
        return None
    try:
        if rag_vector.vector_backend() == "disabled":
            return None
        keyword_scores = {i: s for i, s in enumerate(scores) if s > 0}
        hits = rag_vector.hybrid_search(list(chunks), query, keyword_scores=keyword_scores, top_k=top_k)
    except Exception:
        return None
    return hits or None


def _pack_sources(protocol: str = "", protocol_variant: str = "") -> tuple[str, ...]:
    for key in (protocol_variant, protocol):
        k = (key or "").lower().strip()
        if k and k in PROTOCOL_PACK_SOURCES:
            return PROTOCOL_PACK_SOURCES[k]
    return ()


def retrieve(
    query: str,
    *,
    module: str = "",
    filenames: Optional[Iterable[str]] = None,
    top_k: int = 4,
    knowledge_dir: Optional[Path] = None,
    protocol: str = "",
    protocol_variant: str = "",
    methodology: str = "",
) -> List[dict]:
    chunks = load_chunks(knowledge_dir)
    if not chunks:
        return []
    # Alias detection: user text + filenames + explicit protocol (not module name —
    # module="assertions" must not activate the fundamentals curriculum pack).
    alias_text = " ".join(
        filter(None, [query, " ".join(filenames or []), protocol, protocol_variant])
    )
    q = " ".join(filter(None, [alias_text, module]))
    qtok = _tokenize(q)
    extra: List[str] = list(MODULE_HINTS.get(module, ()))
    protocol_terms: List[str] = []
    combined = alias_text.lower()
    for key, aliases in PROTOCOL_ALIASES.items():
        if key in ((protocol or "").lower(), (protocol_variant or "").lower()) or any(
            _term_in_text(a, combined) for a in aliases
        ):
            protocol_terms.extend(aliases)
    # Explicit pack from design analysis
    for key in (protocol_variant, protocol):
        k = (key or "").lower()
        if k and k in PROTOCOL_ALIASES:
            protocol_terms.extend(PROTOCOL_ALIASES[k])
    preferred = set(_pack_sources(protocol, protocol_variant))
    meth = (methodology or "").lower().strip()
    uvm_tb = meth == "uvm" and (module or "") == "testbench"
    if (module or "") == "testbench" and meth in ("sv", "uvm"):
        preferred |= set(TB_COMPARE_SOURCES)
    if uvm_tb:
        preferred |= set(UVM_FIRST_TB_SOURCES)
        preferred |= set(UVM_GUIDE_SOURCES)
        proto_l = (protocol or "").lower()
        var_l = (protocol_variant or "").lower()
        if proto_l in ("switch", "addr_switch", "addr_range_switch") or var_l == "addr_range_switch":
            preferred |= set(UVM_EXAMPLE2_SOURCES)
    if (module or "") == "testbench" and meth in ("ovm", "vmm"):
        preferred |= set(OVM_VMM_INTEROP_SOURCES)
    scores = []
    for c in chunks:
        s = _score_chunk(qtok, c, extra, protocol_terms, query_text=alias_text)
        if preferred and c.get("source") in preferred:
            s += 28.0
        if uvm_tb and c.get("source") in UVM_DEMOTE_SOURCES:
            s -= 40.0
        scores.append(s)
    out = _hybrid_rerank(chunks, q, scores, top_k)
    if out is None:
        scored = list(zip(scores, chunks))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = [c for s, c in scored if s > 0][:top_k]
    if not out and chunks:
        # Prefer pack sources, else first sections
        if preferred:
            pref = [c for c in chunks if c.get("source") in preferred][:top_k]
            out = pref or chunks[: min(2, len(chunks))]
        else:
            out = chunks[: min(2, len(chunks))]
    if uvm_tb and out:
        filtered = [c for c in out if c.get("source") not in UVM_DEMOTE_SOURCES]
        if filtered:
            out = filtered
        need = max(0, top_k - len(out))
        if need:
            extra_pref = [
                c
                for c in chunks
                if c.get("source") in preferred and c not in out
            ]
            out = (list(out) + extra_pref)[:top_k]
    if (module or "") == "testbench" and meth in ("sv", "uvm") and out:
        have = {c.get("source") for c in out}
        if "sv_vs_uvm_tb_map.txt" not in have:
            cmp_chunks = [c for c in chunks if c.get("source") == "sv_vs_uvm_tb_map.txt"]
            if cmp_chunks:
                out = (cmp_chunks[:1] + [c for c in out if c.get("source") != "sv_vs_uvm_tb_map.txt"])[:top_k]
    if uvm_tb and out:
        have = {c.get("source") for c in out}
        if "uvm_tb_example1.txt" not in have:
            ex1 = [c for c in chunks if c.get("source") == "uvm_tb_example1.txt"]
            if ex1:
                out = (ex1[:1] + [c for c in out if c.get("source") != "uvm_tb_example1.txt"])[:top_k]
    return out


def format_context(chunks: Sequence[dict], *, max_chars: int = 0) -> str:
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        parts.append(f"### {c['title']} ({c['source']})\n{c['body']}")
    text = "\n\n".join(parts)
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n"
    return text


def augment_generation_context(
    *,
    module: str,
    prompt: str,
    filenames: Optional[Iterable[str]] = None,
    top_k: int = 4,
    protocol: str = "",
    protocol_variant: str = "",
    methodology: str = "",
    max_chars: int = 3200,
) -> str:
    if not _enabled():
        return ""
    chunks = retrieve(
        prompt,
        module=module,
        filenames=filenames,
        top_k=top_k,
        protocol=protocol,
        protocol_variant=protocol_variant,
        methodology=methodology,
    )
    return format_context(chunks, max_chars=max_chars)


def rag_status() -> dict:
    root = KNOWLEDGE_DIR
    chunks = load_chunks(root)
    vector: dict = {"enabled": False, "backend": "disabled", "note": "rag_vector unavailable"}
    if rag_vector is not None:
        try:
            vector = rag_vector.rag_vector_status()
        except Exception as e:
            vector = {"enabled": False, "backend": "disabled", "note": f"rag_vector error: {e}"}
    return {
        "enabled": _enabled(),
        "knowledge_dir": str(root),
        "chunk_count": len(chunks),
        "sources": sorted({c["source"] for c in chunks}),
        "vector": vector,
    }
