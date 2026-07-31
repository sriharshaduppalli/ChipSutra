"""Lint / sanitize LLM-generated SystemVerilog testbenches.

Small local models often emit correct DUT ports but broken clocks, circular
goldens, and chat prose. Prefer the deterministic skeleton when lint fails.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple


_CODE_FENCE = re.compile(r"```(?:systemverilog|verilog|sv)?\s*([\s\S]*?)```", re.I)
_BROKEN_CLOCK = re.compile(
    r"clk\s*=\s*~\s*clk\s*;\s*(?:#\d+\s*)?forever\s*@\s*\(\s*posedge\s+clk\s*\)",
    re.I,
)
_GOOD_CLOCK = re.compile(
    r"(always\s+#\d+\s+\w+\s*=\s*~\s*\w+)|(forever\s+#\d+\s+\w+\s*=\s*~\s*\w+)",
    re.I,
)
_CIRCULAR_GOLDEN = re.compile(
    r"\b(exp|expected|exp_count|golden)\s*<?=?\s*\w*(count|q|data_out)\w*\s*\+\s*",
    re.I,
)
_HAS_DUMP = re.compile(r"\$dump(file|vars)", re.I)
_HAS_FINISH = re.compile(r"\$finish", re.I)
_HAS_URANDOM = re.compile(r"\$urandom(_range)?", re.I)
_CHATTY = re.compile(
    r"(?i)(this testbench|certainly!|here(?:'s| is) (?:a|the)|the testbench (?:initializes|above))"
)
_CLK_PORT_NAMES = frozenset({"clk", "clock", "clk_i", "clk_in", "aclk", "pclk", "sclk"})
_SOFT_ISSUES = frozenset({"missing_dump", "missing_finish", "chat_prose"})


def extract_sv(text: str) -> str:
    """Prefer fenced SV; else strip leading/trailing prose around module…endmodule."""
    if not text:
        return ""
    fences = _CODE_FENCE.findall(text)
    if fences:
        # Pick the largest fence (usually the TB)
        body = max((f.strip() for f in fences), key=len)
    else:
        body = text.strip()
    # Keep from first module/timescale through last endmodule
    m0 = re.search(r"(`timescale|module\s+\w+)", body, re.I)
    if m0:
        body = body[m0.start() :]
    ends = list(re.finditer(r"\bendmodule\b", body, re.I))
    if ends:
        body = body[: ends[-1].end()]
    return body.strip() + ("\n" if body.strip() else "")


def lint_testbench(
    sv: str,
    *,
    dut_name: Optional[str] = None,
    required_ports: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """Return (ok, issues). ok=False means replace with skeleton."""
    issues: List[str] = []
    if not sv or "module" not in sv.lower():
        return False, ["no_module"]

    if _CHATTY.search(sv) and "endmodule" not in sv.lower():
        issues.append("chat_prose")

    if _BROKEN_CLOCK.search(sv) or not _GOOD_CLOCK.search(sv):
        # Flag when DUT has a clock-like port (incl. aclk)
        if not required_ports or any(p.lower() in _CLK_PORT_NAMES for p in required_ports):
            issues.append("bad_or_missing_clock")

    if _CIRCULAR_GOLDEN.search(sv):
        issues.append("circular_golden")

    if not _HAS_DUMP.search(sv):
        issues.append("missing_dump")
    if not _HAS_FINISH.search(sv):
        issues.append("missing_finish")
    if not _HAS_URANDOM.search(sv):
        issues.append("missing_urandom")

    # Allow parameterized instances: fifo #(.WIDTH(8), .DEPTH(8)) dut (...)
    if dut_name and not re.search(
        rf"\b{re.escape(dut_name)}\s*(?:#\s*\([^;]*?\))?\s+\w+\s*\(",
        sv,
        re.DOTALL,
    ):
        issues.append("missing_dut_instance")

    if required_ports:
        for p in required_ports:
            if not re.search(rf"\.{re.escape(p)}\s*\(", sv):
                issues.append(f"missing_port_map:{p}")

    # Hard failures → reject
    hard = {
        "no_module",
        "bad_or_missing_clock",
        "circular_golden",
        "missing_dut_instance",
        "missing_urandom",
    }
    hard |= {i for i in issues if i.startswith("missing_port_map:")}
    ok = not any(i in hard or i.startswith("missing_port_map:") for i in issues)
    # Soft dump/finish still fail until repaired
    if any(i in ("missing_dump", "missing_finish") for i in issues):
        ok = False
    return ok, issues


def repair_soft_tb_gaps(sv: str) -> str:
    """Append $dump* / $finish stubs when the TB body is otherwise OK but truncated."""
    if not sv or "module" not in sv.lower():
        return sv
    needs_dump = not _HAS_DUMP.search(sv)
    needs_finish = not _HAS_FINISH.search(sv)
    if not needs_dump and not needs_finish:
        return sv
    m = re.search(r"\bmodule\s+(\w+)", sv, re.I)
    top = m.group(1) if m else "tb"
    lines = ["  // ChipSutra soft-repair: ensure dump/finish present", "  initial begin"]
    if needs_dump:
        lines.append(f'    $dumpfile("{top}.vcd");')
        lines.append(f"    $dumpvars(0, {top});")
    if needs_finish:
        lines.append("    $finish;")
    lines.append("  end")
    block = "\n".join(lines) + "\n"
    idx = re.search(r"\bendmodule\b", sv, re.I)
    if not idx:
        return sv + "\n" + block
    return sv[: idx.start()] + block + sv[idx.start() :]


def choose_testbench_output(
    llm_text: str,
    *,
    skeleton: str,
    dut_name: Optional[str] = None,
    required_ports: Optional[List[str]] = None,
    force_uvm: bool = False,
) -> Tuple[str, str, List[str]]:
    """
    Pick final TB text.

    Returns (output, engine_tag, issues) where engine_tag is
    'llm' | 'llm_repaired' | 'skeleton' | 'skeleton_fallback'.
    """
    if force_uvm and llm_text and re.search(r"\buvm_", llm_text, re.I):
        cleaned = extract_sv(llm_text) or llm_text
        return cleaned, "llm", ["uvm_passthrough"]

    cleaned = extract_sv(llm_text)
    ok, issues = lint_testbench(cleaned, dut_name=dut_name, required_ports=required_ports)
    if ok and cleaned:
        return cleaned, "llm", issues

    # Soft-only gaps (dump/finish/chat): try repair before skeleton fallback
    hardish = [i for i in issues if i not in _SOFT_ISSUES]
    if cleaned and not hardish and any(i in _SOFT_ISSUES for i in issues):
        repaired = repair_soft_tb_gaps(cleaned)
        ok2, issues2 = lint_testbench(repaired, dut_name=dut_name, required_ports=required_ports)
        if ok2 and repaired:
            return repaired, "llm_repaired", issues2 or issues

    if skeleton:
        header = (
            "// ChipSutra: LLM output failed TB lint "
            f"({', '.join(issues) or 'empty'}); using verified randomized template.\n"
        )
        return header + skeleton.lstrip(), "skeleton_fallback", issues

    return cleaned or llm_text, "llm", issues or ["no_skeleton"]
