"""RTL port extractor and lint-feedback helpers (no live LLM)."""
from pathlib import Path

from lint_feedback import format_lint_feedback, summarize_log
from rtl_ports import extract_modules, extract_port_context_from_texts, format_port_context
from rag import rag_status, retrieve

GOLDEN = Path(__file__).resolve().parents[1] / "knowledge" / "golden" / "counter.sv"


def test_extract_ansi_ports_counter():
    text = GOLDEN.read_text(encoding="utf-8")
    mods = extract_modules(text)
    assert len(mods) == 1
    assert mods[0]["name"] == "counter"
    names = [p["name"] for p in mods[0]["ports"]]
    assert names == ["clk", "rst", "q"]
    assert mods[0]["ports"][2]["width"] == "[7:0]"
    assert mods[0]["ports"][2]["direction"] == "output"


def test_extract_legacy_ports():
    rtl = """
module foo(a, b);
  input wire a;
  output reg [3:0] b;
endmodule
"""
    mods = extract_modules(rtl)
    assert mods[0]["name"] == "foo"
    names = [p["name"] for p in mods[0]["ports"]]
    assert "a" in names and "b" in names


def test_port_context_format():
    ctx = extract_port_context_from_texts([GOLDEN.read_text(encoding="utf-8")])
    assert "module counter" in ctx
    assert "clk" in ctx and "do not invent" in ctx.lower()


def test_summarize_verilator_log():
    log = "%Error: foo.sv:12: syntax error, unexpected IDENTIFIER\nUVM_ERROR @ 50: tb.env [SB] mismatch\nok line"
    findings = summarize_log(log)
    assert any("Error" in f or "UVM_ERROR" in f for f in findings)


def test_format_lint_feedback_includes_prior():
    block = format_lint_feedback("%Error: x.sv:1: bad", prior_code="module x; endmodule")
    assert "Tool / simulation feedback" in block
    assert "module x" in block


def test_rag_has_expanded_knowledge():
    st = rag_status()
    assert st["chunk_count"] >= 15
    for src in (
        "uvm_patterns.txt",
        "sva_patterns.txt",
        "sim_debug_playbook.txt",
        "vlsi_protocols_compact.txt",
        "vlsi_soc_dft_power.txt",
        "vlsi_verification_glossary.txt",
    ):
        assert src in st["sources"]


def test_rag_retrieves_sva_for_assertions():
    chunks = retrieve("concurrent assert property handshake", module="assertions")
    blob = " ".join(c["title"] + c["body"] for c in chunks).lower()
    assert "sva" in blob or "assert" in blob or "property" in blob
