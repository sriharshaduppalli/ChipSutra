"""RAG retrieval and golden fixture tests (no live LLM required)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from rag import augment_generation_context, load_chunks, retrieve, rag_status

REPO = Path(__file__).resolve().parents[2]
GOLDEN_COUNTER = REPO / "backend" / "knowledge" / "golden" / "counter.sv"


def test_rag_status_has_protocol_chunks():
    st = rag_status()
    assert st["enabled"] is True
    assert st["chunk_count"] >= 15
    assert "vlsi_protocols_compact.txt" in st["sources"]
    assert "vlsi_soc_dft_power.txt" in st["sources"]
    assert "vlsi_verification_glossary.txt" in st["sources"]
    assert "covergroup_patterns.txt" in st["sources"]
    assert "uvm_users_guide_emit.txt" in st["sources"]
    assert "ovm_vmm_interop_emit.txt" in st["sources"]


def test_rag_uvm_guide_preferred_for_uvm_tb():
    chunks = retrieve(
        "UVM testbench agent sequencer driver",
        module="testbench",
        methodology="uvm",
        top_k=8,
    )
    sources = [c["source"] for c in chunks]
    assert "uvm_users_guide_emit.txt" in sources or any("uvm_guide" in s for s in sources), sources


def test_rag_ovm_vmm_interop_preferred():
    chunks = retrieve(
        "OVM VMM interop vmm_channel TLM adapter",
        module="testbench",
        methodology="ovm",
        top_k=6,
    )
    sources = [c["source"] for c in chunks]
    assert "ovm_vmm_interop_emit.txt" in sources, sources
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "interconnected" in blob or "avt_" in blob or "channel" in blob


def test_rag_retrieves_can_for_can_ip_prompt():
    chunks = retrieve("CAN IP testbench bus-off error frame", module="testbench", filenames=["can_ip_design.v"])
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "can" in blob and ("bus-off" in blob or "frame" in blob)


def test_rag_retrieves_axi_for_axi_prompt():
    chunks = retrieve("AXI4 valid ready handshake", module="assertions")
    blob = " ".join(c["title"] + c["body"] for c in chunks).lower()
    assert "axi" in blob


def test_rag_protocol_pack_prefers_vip_source():
    chunks = retrieve(
        "generate testbench",
        module="testbench",
        top_k=3,
        protocol="axi_lite",
        protocol_variant="axi4_lite",
    )
    sources = [c["source"] for c in chunks]
    assert any("protocol_vip_axi_lite" in s for s in sources), sources
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "wstrb" in blob or "bresp" in blob or "handshake" in blob


def test_rag_apb4_pack_routes():
    chunks = retrieve(
        "APB registers",
        module="testbench",
        top_k=2,
        protocol="apb",
        protocol_variant="apb4",
    )
    sources = " ".join(c["source"] for c in chunks)
    assert "protocol_vip_apb" in sources or "protocol_tb_guidance" in sources


def test_rag_axi_lite_valid_must_not_wait_ready():
    chunks = retrieve(
        "AXI4-Lite valid ready handshake",
        module="testbench",
        top_k=4,
        protocol="axi_lite",
        protocol_variant="axi4_lite",
    )
    blob = " ".join(c["title"] + " " + c["body"] for c in chunks).lower()
    assert "must not wait" in blob or "not wait for ready" in blob
    assert "wstrb" in blob or "bresp" in blob


def test_rag_ahb_pack_routes_pipeline():
    chunks = retrieve(
        "AHB-Lite slave HTRANS NONSEQ HREADY",
        module="testbench",
        top_k=4,
        protocol="ahb",
        protocol_variant="ahb_lite",
    )
    sources = [c["source"] for c in chunks]
    assert any("protocol_vip_ahb" in s for s in sources), sources
    blob = " ".join(c["title"] + " " + c["body"] for c in chunks).lower()
    assert "address phase" in blob or "data phase" in blob
    assert "htrans" in blob or "nonseq" in blob
    assert "hwdata" in blob or "hwrite" in blob


def test_rag_wishbone_pack_routes():
    chunks = retrieve(
        "Wishbone slave CYC STB ACK",
        module="testbench",
        top_k=3,
        protocol="wishbone",
    )
    sources = " ".join(c["source"] for c in chunks)
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "protocol_vip_onchip" in sources or "cyc" in blob
    assert "ack" in blob


def test_rag_wishbone_pack_routes():
    chunks = retrieve(
        "Wishbone slave CYC STB ACK",
        module="testbench",
        top_k=3,
        protocol="wishbone",
    )
    sources = " ".join(c["source"] for c in chunks)
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "protocol_vip_onchip" in sources or "cyc" in blob
    assert "ack" in blob or "stb" in blob


def test_rag_apb_hold_during_pready_wait():
    chunks = retrieve(
        "APB SETUP ACCESS PREADY wait PSEL PENABLE",
        module="testbench",
        top_k=4,
        protocol="apb",
        protocol_variant="apb3",
    )
    blob = " ".join(c["title"] + " " + c["body"] for c in chunks).lower()
    assert "hold" in blob and "pready" in blob
    assert "psel" in blob and "penable" in blob


def test_rag_retrieves_jtag_dft():
    chunks = retrieve("JTAG TAP boundary scan DFT", module="testbench")
    blob = " ".join(c["title"] + c["body"] for c in chunks).lower()
    assert "jtag" in blob or "tap" in blob or "scan" in blob


def test_rag_retrieves_cdc():
    chunks = retrieve("async FIFO CDC metastability 2FF", module="debug")
    blob = " ".join(c["title"] + c["body"] for c in chunks).lower()
    assert "cdc" in blob or "fifo" in blob or "metastability" in blob


def test_rag_retrieves_tilelink():
    chunks = retrieve("TileLink TL-UL Get Put RISC-V", module="testbench")
    blob = " ".join(c["title"] + c["body"] for c in chunks).lower()
    assert "tilelink" in blob or "tl-" in blob


def test_rag_augment_disabled(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    assert augment_generation_context(module="testbench", prompt="CAN") == ""


def test_rag_augment_includes_uvm_for_testbench_module():
    ctx = augment_generation_context(module="testbench", prompt="generate env")
    assert "uvm" in ctx.lower() or "sequencer" in ctx.lower()


def test_rag_deep_pillars_present_in_corpus():
    st = rag_status()
    sources = set(st["sources"])
    for name in (
        "sv_constraints_patterns.txt",
        "sv_interfaces_patterns.txt",
        "sv_oop_classes_patterns.txt",
        "sv_arrays_collections_patterns.txt",
        "sv_threads_ipc_patterns.txt",
        "sv_randomization_patterns.txt",
        "sv_datatypes_control_patterns.txt",
        "sv_advanced_features_patterns.txt",
        "covergroup_patterns.txt",
        "sva_patterns.txt",
        "verification_methodologies_curriculum.txt",
        "uvm_patterns.txt",
    ):
        assert name in sources


def test_rag_retrieves_oop_for_class_prompt():
    chunks = retrieve(
        "SystemVerilog class extends virtual method polymorphism shallow deep copy",
        module="testbench",
        filenames=[],
    )
    sources = {c["source"] for c in chunks}
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "sv_oop_classes_patterns.txt" in sources or ("class" in blob and "virtual" in blob)


def test_rag_retrieves_ipc_for_mailbox_prompt():
    chunks = retrieve(
        "mailbox semaphore fork join_any event timeout watchdog",
        module="testbench",
        filenames=[],
    )
    sources = {c["source"] for c in chunks}
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "sv_threads_ipc_patterns.txt" in sources or "mailbox" in blob or "semaphore" in blob


def test_rag_retrieves_queue_for_scoreboard_prompt():
    chunks = retrieve(
        "queue push_back pop_front associative array scoreboard FIFO golden",
        module="testbench",
        filenames=[],
    )
    sources = {c["source"] for c in chunks}
    blob = " ".join(c["body"] for c in chunks).lower()
    assert (
        "sv_arrays_collections_patterns.txt" in sources
        or "queue" in blob
        or "push_back" in blob
    )


def test_rag_retrieves_constraints_for_crv_prompt():
    chunks = retrieve(
        "constrained randomize dist soft constraint foreach solve before",
        module="testbench",
        filenames=[],
    )
    blob = " ".join(c["source"] + " " + c["title"] + " " + c["body"] for c in chunks).lower()
    assert "constraint" in blob or "randomize" in blob
    assert any("constraint" in c["source"] or "random" in c["body"].lower() for c in chunks)


def test_rag_retrieves_interfaces_for_modport_prompt():
    chunks = retrieve(
        "virtual interface modport clocking block config_db",
        module="testbench",
        filenames=[],
    )
    sources = {c["source"] for c in chunks}
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "sv_interfaces_patterns.txt" in sources or "modport" in blob or "clocking" in blob


def test_rag_retrieves_covergroup_for_bins_prompt():
    chunks = retrieve(
        "functional coverage covergroup coverpoint bins cross illegal_bins sample",
        module="covergroups",
        filenames=[],
    )
    sources = {c["source"] for c in chunks}
    assert "covergroup_patterns.txt" in sources or any("cover" in c["body"].lower() for c in chunks)


def test_rag_retrieves_sva_for_property_prompt():
    chunks = retrieve(
        "concurrent assert property disable iff sequence cover property bind",
        module="assertions",
        filenames=[],
    )
    sources = {c["source"] for c in chunks}
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "sva_patterns.txt" in sources or "assert property" in blob or "disable iff" in blob


def test_uvm_tb_rag_pins_example1_not_subscriber():
    chunks = retrieve(
        "generate UVM testbench for counter",
        module="testbench",
        top_k=4,
        protocol="counter",
        methodology="uvm",
    )
    sources = [c["source"] for c in chunks]
    assert "uvm_tb_example1.txt" in sources, sources
    assert "uvm_subscriber.txt" not in sources
    assert "uvm_get_put.txt" not in sources


def test_uvm_switch_rag_pins_example2():
    chunks = retrieve(
        "generate UVM testbench for switch",
        module="testbench",
        top_k=4,
        protocol="switch",
        protocol_variant="addr_range_switch",
        methodology="uvm",
    )
    sources = [c["source"] for c in chunks]
    assert "uvm_tb_example2.txt" in sources or "uvm_tb_example1.txt" in sources, sources
    assert "uvm_subscriber.txt" not in sources


def test_tb_rag_includes_sv_vs_uvm_map():
    chunks = retrieve(
        "generate layered testbench",
        module="testbench",
        top_k=4,
        protocol="counter",
        methodology="sv",
    )
    sources = [c["source"] for c in chunks]
    assert "sv_vs_uvm_tb_map.txt" in sources, sources
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "generator" in blob and ("uvm_sequence" in blob or "sequencer" in blob)
    assert "connect_phase" in blob or "build_phase" in blob
    assert "objection" in blob
    assert "mailbox" in blob and "analysis" in blob
    assert "uvm_object" in blob or "uvm_component" in blob
    assert "is_active" in blob or "uvm_active" in blob
    assert "write()" in blob or "function" in blob
    assert "seq_item_export" in blob or "item_done" in blob
    assert "driver" in blob and "monitor" in blob
    assert "virtual if" in blob or "pin" in blob


def test_rag_verification_techniques_formal_and_sim():
    formal = retrieve(
        "formal verification bounded proof arbiter mutex",
        module="formal_hints",
        protocol="formal",
        top_k=3,
    )
    sources = " ".join(c["source"] for c in formal)
    blob = " ".join(c["body"] for c in formal).lower()
    assert "verification_techniques" in sources
    assert "bounded" in blob or "property" in blob
    assert "not" in blob or "≠" in blob or "fully correct" in blob or "you asked" in blob

    emu = retrieve(
        "boot Linux before tapeout emulation",
        module="testplan",
        protocol="emulation",
        top_k=3,
    )
    eblob = " ".join(c["body"] for c in emu).lower()
    assert "emulat" in eblob
    assert "verilator" in eblob or "simulation" in eblob or "boot" in eblob

    stages = retrieve(
        "subsystem integration inter-block CDC shared bus reset order",
        module="testplan",
        protocol="subsystem",
        top_k=3,
    )
    ss = " ".join(c["source"] for c in stages)
    sb = " ".join(c["body"] for c in stages).lower()
    assert "verification_stages" in ss or "protocol_vip_scale" in ss
    assert "inter-block" in sb or "interface" in sb or "cdc" in sb or "connected" in sb


def test_golden_counter_sv_exists():
    assert GOLDEN_COUNTER.is_file()
    text = GOLDEN_COUNTER.read_text()
    assert "module counter" in text
    assert "posedge clk" in text


@pytest.mark.serial
@pytest.mark.verilator
@pytest.mark.skipif(not shutil.which("verilator"), reason="verilator not installed")
def test_golden_counter_verilator_lint():
    # Route through dv_verify: relative paths from a temp cwd also work when
    # verilator is the WSL .bat shim.
    from dv_verify import verify_sv_sources

    src = GOLDEN_COUNTER.read_text(encoding="utf-8")
    r = verify_sv_sources([(GOLDEN_COUNTER.name, src)], mode="lint", timeout_s=60.0)
    assert r.get("ok"), r.get("errors") or r.get("log")
