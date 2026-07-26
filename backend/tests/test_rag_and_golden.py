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
    assert st["chunk_count"] >= 3
    assert "vlsi_protocols_compact.txt" in st["sources"]


def test_rag_retrieves_can_for_can_ip_prompt():
    chunks = retrieve("CAN IP testbench bus-off error frame", module="testbench", filenames=["can_ip_design.v"])
    blob = " ".join(c["body"] for c in chunks).lower()
    assert "can" in blob and ("bus-off" in blob or "frame" in blob)


def test_rag_retrieves_axi_for_axi_prompt():
    chunks = retrieve("AXI4 valid ready handshake", module="assertions")
    blob = " ".join(c["title"] + c["body"] for c in chunks).lower()
    assert "axi" in blob


def test_rag_augment_disabled(monkeypatch):
    monkeypatch.setenv("RAG_ENABLED", "false")
    assert augment_generation_context(module="testbench", prompt="CAN") == ""


def test_rag_augment_includes_uvm_for_testbench_module():
    ctx = augment_generation_context(module="testbench", prompt="generate env")
    assert "uvm" in ctx.lower() or "sequencer" in ctx.lower()


def test_golden_counter_sv_exists():
    assert GOLDEN_COUNTER.is_file()
    text = GOLDEN_COUNTER.read_text()
    assert "module counter" in text
    assert "posedge clk" in text


@pytest.mark.skipif(not shutil.which("verilator"), reason="verilator not installed")
def test_golden_counter_verilator_lint():
    proc = subprocess.run(
        ["verilator", "--lint-only", "-Wno-fatal", str(GOLDEN_COUNTER)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
