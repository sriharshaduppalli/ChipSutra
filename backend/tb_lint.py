"""Lint / sanitize LLM-generated SystemVerilog testbenches.

Small local models often emit correct DUT ports but broken clocks, circular
goldens, and chat prose. Prefer the deterministic skeleton when lint fails.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple, Dict, Any


_CODE_FENCE = re.compile(r"```(?:systemverilog|verilog|sv)?\s*([\s\S]*?)```", re.I)
_BROKEN_CLOCK = re.compile(
    r"clk\s*=\s*~\s*clk\s*;\s*(?:#\d+\s*)?forever\s*@\s*\(\s*posedge\s+clk\s*\)",
    re.I,
)
_GOOD_CLOCK = re.compile(
    r"(always\s+#\d+\s+\w+\s*=\s*~\s*\w+)|(forever\s+#\d+\s+\w+\s*=\s*~\s*\w+)",
    re.I,
)
# Circular golden: expected derived from a DUT output (e.g. `expected = count + 1`).
# The RHS lookahead excludes self-increment models (`expected_count = expected_count + 1`),
# which are correct independent goldens, not circular reads of DUT outputs.
_CIRCULAR_GOLDEN = re.compile(
    r"\b(?:exp|expected|exp_count|golden)\w*\s*<?=\s*"
    r"(?!(?:exp|expected|golden))\w*(?:count|q|data_out|rd_data)\w*\s*\+\s*",
    re.I,
)
_HAS_DUMP = re.compile(r"\$dump(file|vars)", re.I)
_HAS_FINISH = re.compile(r"\$finish", re.I)
_HAS_URANDOM = re.compile(r"\$urandom(_range)?", re.I)
_HAS_POSEDGE = re.compile(r"@\s*\(\s*posedge\s+[\w.]+\s*\)", re.I)
_CHATTY = re.compile(
    r"(?i)(this testbench|certainly!|here(?:'s| is) (?:a|the)|the testbench (?:initializes|above))"
)
_CLK_PORT_NAMES = frozenset({"clk", "clock", "clk_i", "clk_in", "aclk", "pclk", "sclk"})
_SOFT_ISSUES = frozenset({"missing_dump", "missing_finish", "chat_prose"})
# Semantic nits that must not force skeleton fallback when dump/finish soft-repair can still win
_SOFT_SEMANTIC = frozenset(
    {
        "semantic_missing_post_reset_check",
        "semantic_fifo_no_clamp",
    }
)
_QUEUE_USE = re.compile(
    r"\bq\s*(?:\[|\$|\.size|\.push_|\.pop_|\[\$\])",
    re.I,
)
_QUEUE_DECL = re.compile(
    r"\b(?:logic|reg|bit|wire)\b[^;\n]*\bq\s*(?:\[[^\]]*\]\s*)?\[\s*\$\s*\]",
    re.I,
)
_DEPTH_USE = re.compile(r"\bDEPTH\b")
_DEPTH_DECL = re.compile(
    r"\b(?:parameter|localparam)\s+(?:int\s+|integer\s+)?DEPTH\b|\.\s*DEPTH\s*\(",
    re.I,
)
_WIRE_DECL = re.compile(
    r"\bwire\b(?:\s+\[[^\]]+\])?\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;",
    re.I,
)


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
    # Keep from first timescale/import/class/interface/module through last endmodule
    # (UVM TBs often start with import uvm_pkg; class TBs may omit timescale)
    m0 = re.search(
        r"(`timescale|\bimport\s+uvm_pkg|\bclass\s+\w+|\bmodule\s+\w+|\binterface\s+\w+)",
        body,
        re.I,
    )
    if m0:
        body = body[m0.start() :]
    ends = list(re.finditer(r"\bendmodule\b", body, re.I))
    if ends:
        body = body[: ends[-1].end()]
    return body.strip() + ("\n" if body.strip() else "")


def _declared_idents(sv: str) -> set:
    names: set = set()
    for m in re.finditer(
        r"\b(?:logic|reg|bit|wire|integer|int|byte)\b(?:\s+\[[^\]]+\])?\s+"
        r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;",
        sv,
        re.I,
    ):
        for part in m.group(1).split(","):
            n = part.strip().split("[")[0].strip()
            if n:
                names.add(n.lower())
    # queues: logic [7:0] q[$];
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\[\s*\$\s*\]", sv):
        names.add(m.group(1).lower())
    return names


def _wire_names(sv: str) -> set:
    names: set = set()
    for m in _WIRE_DECL.finditer(sv):
        for part in m.group(1).split(","):
            n = part.strip().split("[")[0].strip()
            if n:
                names.add(n.lower())
    return names


def _procedural_assigns(sv: str) -> set:
    """Signal names assigned with '=' / '<=' in procedural code (not compares / format strings)."""
    names: set = set()
    # Drop strings and port maps so $error("count=%0h") and .count(count) do not count.
    body = re.sub(r'"([^"\\]|\\.)*"', '""', sv)
    body = re.sub(r"\.\w+\s*\([^)]*\)", " ", body)
    # True assigns: = or <= but not == / === / != / !==
    for m in re.finditer(r"(?<![.<!=])\b([A-Za-z_]\w*)\s*(?:<=|=)(?!=)", body):
        names.add(m.group(1).lower())
    return names


def lint_testbench(
    sv: str,
    *,
    dut_name: Optional[str] = None,
    required_ports: Optional[List[str]] = None,
    dut_outputs: Optional[Sequence[str]] = None,
) -> Tuple[bool, List[str]]:
    """Return (ok, issues). ok=False means replace with skeleton."""
    issues: List[str] = []
    if not sv or "module" not in sv.lower():
        return False, ["no_module"]

    if module_incomplete(sv):
        issues.append("incomplete_module")

    if _CHATTY.search(sv) and "endmodule" not in sv.lower():
        issues.append("chat_prose")

    has_clk_port = bool(
        not required_ports or any(p.lower() in _CLK_PORT_NAMES for p in required_ports)
    )
    if _BROKEN_CLOCK.search(sv) or not _GOOD_CLOCK.search(sv):
        if has_clk_port:
            issues.append("bad_or_missing_clock")

    if _CIRCULAR_GOLDEN.search(sv):
        issues.append("circular_golden")

    if not _HAS_DUMP.search(sv):
        issues.append("missing_dump")
    if not _HAS_FINISH.search(sv):
        issues.append("missing_finish")
    if not _HAS_URANDOM.search(sv):
        issues.append("missing_urandom")

    # Sequential stimulus without posedge sync (common LLM bug)
    if has_clk_port and _HAS_URANDOM.search(sv) and re.search(r"\bfor\s*\(", sv, re.I):
        if not _HAS_POSEDGE.search(sv):
            issues.append("missing_posedge_sync")

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

    # DUT outputs must not be driven by the TB
    outs = {o.lower() for o in (dut_outputs or []) if o}
    if outs:
        assigns = _procedural_assigns(sv)
        driven = sorted(outs & assigns)
        # Clock/reset toggles are OK even if mis-tagged; skip clk-like
        driven = [d for d in driven if d not in _CLK_PORT_NAMES and not d.startswith("rst")]
        if driven:
            issues.append("drives_dut_output:" + ",".join(driven[:6]))

    if _QUEUE_USE.search(sv) and not _QUEUE_DECL.search(sv):
        issues.append("undeclared_queue_q")
    if _DEPTH_USE.search(sv) and not _DEPTH_DECL.search(sv):
        issues.append("undeclared_DEPTH")

    # wire driven procedurally (should be logic/reg)
    wires = _wire_names(sv)
    if wires:
        assigns = _procedural_assigns(sv)
        bad = sorted(w for w in (wires & assigns) if w not in _CLK_PORT_NAMES)
        if bad:
            issues.append("wire_driven_procedurally:" + ",".join(bad[:6]))

    # Hard failures → reject
    def _is_hard(i: str) -> bool:
        return (
            i
            in {
                "no_module",
                "bad_or_missing_clock",
                "circular_golden",
                "missing_dut_instance",
                "missing_urandom",
                "missing_posedge_sync",
                "undeclared_queue_q",
                "undeclared_DEPTH",
                "incomplete_module",
            }
            or i.startswith("missing_port_map:")
            or i.startswith("drives_dut_output:")
            or i.startswith("wire_driven_procedurally:")
        )

    ok = not any(_is_hard(i) for i in issues)
    # Soft dump/finish still fail until repaired
    if any(i in ("missing_dump", "missing_finish") for i in issues):
        ok = False
    return ok, issues


def module_incomplete(sv: str) -> bool:
    """True when a module was started but truncated (no endmodule / dangling '=')."""
    if not sv or not re.search(r"\bmodule\b", sv, re.I):
        return False
    n_mod = len(re.findall(r"(?<!\w)module(?!\w)", sv, re.I))
    n_end = len(re.findall(r"(?<!\w)endmodule(?!\w)", sv, re.I))
    if n_mod > n_end:
        return True
    tail = sv.rstrip()
    if tail.endswith("=") or re.search(r"=\s*$", tail):
        return True
    return False


def repair_soft_tb_gaps(sv: str) -> str:
    """Append $dump* / $finish stubs when the TB body is otherwise OK but truncated."""
    if not sv or "module" not in sv.lower():
        return sv
    # Never glue $finish onto a truncated module — that scores as "ok" and ships junk.
    if module_incomplete(sv):
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


def stamp_tb_header(
    sv: str,
    *,
    engine: str = "skeleton",
    model: str = "tb_skeleton",
    protocol: str = "generic",
) -> str:
    """Prepend a one-line standard ChipSutra provenance header (idempotent)."""
    body = (sv or "").lstrip()
    line = f"// ChipSutra engine={engine} model={model} protocol={protocol}\n"
    if body.startswith("// ChipSutra engine="):
        rest = body.split("\n", 1)
        body = rest[1] if len(rest) > 1 else ""
        # Keep existing fallback notes that follow
        while body.startswith("// ChipSutra:") or body.startswith("// ChipSutra "):
            parts = body.split("\n", 1)
            body = parts[1] if len(parts) > 1 else ""
    return line + body.lstrip()


def truncate_tb_reference(sv: str, *, max_lines: int = 48) -> str:
    """Compact mandatory reference for LLM prompts (keeps structure, cuts bulk)."""
    if not sv:
        return ""
    lines = sv.splitlines()
    if len(lines) <= max_lines:
        return sv
    # Prefer keeping header + clock + DUT + first initial loop start + golden hints
    keep_head = 28
    keep_tail = 12
    mid = "  // ... ChipSutra: reference truncated for latency; copy clock/reset/loop/golden ...\n"
    return "\n".join(lines[:keep_head] + [mid.rstrip()] + lines[-keep_tail:]) + "\n"


def choose_testbench_output(
    llm_text: str,
    *,
    skeleton: str,
    dut_name: Optional[str] = None,
    required_ports: Optional[List[str]] = None,
    dut_outputs: Optional[Sequence[str]] = None,
    force_uvm: bool = False,
    protocol: str = "generic",
    port_specs: Optional[Sequence[dict]] = None,
) -> Tuple[str, str, List[str]]:
    """
    Pick final TB text.

    Returns (output, engine_tag, issues) where engine_tag is
    'llm' | 'llm_repaired' | 'skeleton' | 'skeleton_fallback'.
    """
    if force_uvm:
        cleaned = extract_sv(llm_text) or (llm_text or "")
        looks_uvm = bool(
            re.search(r"\b(uvm_|ovm_|vmm_|import\s+uvm_pkg)", cleaned, re.I)
            or re.search(r"\b(uvm_|ovm_|vmm_|import\s+uvm_pkg)", llm_text or "", re.I)
        )
        try:
            from tb_uvm_lint import lint_uvm_tb, repair_uvm_hints, repair_uvm_tb
        except Exception:
            return cleaned, "llm", ["class_methodology_passthrough"]
        if not looks_uvm:
            if skeleton and re.search(r"\buvm_|import\s+uvm_pkg", skeleton, re.I):
                header = (
                    "// ChipSutra: LLM did not emit UVM; "
                    "using DUT-correct UVM smoke skeleton.\n"
                )
                return header + skeleton.lstrip(), "skeleton_fallback", ["uvm_missing_from_llm"]
            return cleaned, "llm", ["uvm_missing_from_llm"]
        # Ensure package import survives extract_sv edge cases
        if "import uvm_pkg" in (llm_text or "") and "import uvm_pkg" not in cleaned:
            cleaned = 'import uvm_pkg::*;\n`include "uvm_macros.svh"\n' + cleaned
        ok_u, issues_u = lint_uvm_tb(cleaned, port_specs=port_specs)
        # Empty scoreboard / hard issues → repair (may emit full protocol skeleton)
        needs_repair = (not ok_u) or ("uvm_empty_scoreboard" in (issues_u or []))
        if not needs_repair:
            return cleaned, "llm", issues_u or ["class_methodology_passthrough"]
        repaired_u = repair_uvm_tb(
            cleaned,
            dut_name=dut_name,
            port_specs=port_specs,
        )
        ok2, issues2 = lint_uvm_tb(repaired_u, port_specs=port_specs)
        if ok2 and "uvm_empty_scoreboard" not in (issues2 or []):
            eng = (
                "skeleton_fallback"
                if "ChipSutra UVM smoke" in repaired_u
                and "scoreboard golden" in repaired_u
                else "llm_repaired"
            )
            return repaired_u, eng, issues2 or issues_u
        if skeleton and re.search(r"\buvm_|import\s+uvm_pkg", skeleton, re.I):
            header = (
                "// ChipSutra: LLM UVM failed lint "
                f"({', '.join(issues_u) or 'empty'}); using DUT-correct UVM smoke skeleton.\n"
            )
            return header + skeleton.lstrip(), "skeleton_fallback", issues_u
        hinted = repair_uvm_hints(repaired_u)
        return hinted, "llm_repaired", issues2 or issues_u

    cleaned = extract_sv(llm_text)

    # Pure SV generate must not ship a UVM/OVM/VMM TB (class lint used to skip these).
    if cleaned and re.search(r"\b(uvm_|ovm_|vmm_|import\s+uvm_pkg)", cleaned, re.I):
        sv_skel = skeleton or ""
        if sv_skel and re.search(r"\b(uvm_|ovm_|vmm_|import\s+uvm_pkg)", sv_skel, re.I):
            sv_skel = ""
        if not sv_skel and dut_name and port_specs:
            try:
                from tb_skeleton import render_class_sv_tb

                sv_skel = render_class_sv_tb(
                    {"name": dut_name, "ports": list(port_specs)}
                )
            except Exception:
                sv_skel = ""
        if sv_skel and not re.search(r"\b(uvm_|ovm_|vmm_|import\s+uvm_pkg)", sv_skel, re.I):
            header = (
                "// ChipSutra: LLM emitted UVM/OVM/VMM for Pure SV methodology; "
                "using DUT-correct layered Pure SV skeleton.\n"
            )
            return header + sv_skel.lstrip(), "skeleton_fallback", ["uvm_in_pure_sv"]
        return cleaned, "llm", ["uvm_in_pure_sv"]


    # Truncated LLM output (no endmodule / dangling '=') must never ship.
    if module_incomplete(cleaned or llm_text or ""):
        if skeleton:
            header = (
                "// ChipSutra: LLM output truncated (incomplete module); "
                "using DUT-correct skeleton.\n"
            )
            return header + skeleton.lstrip(), "skeleton_fallback", ["incomplete_module"]
        return cleaned or llm_text, "llm", ["incomplete_module"]

    # Pure SV class-based: lint + mechanical repair (never swap to procedural smoke).
    if cleaned and re.search(r"\bclass\b", cleaned) and not re.search(
        r"\b(uvm_|ovm_|vmm_)", cleaned, re.I
    ):
        try:
            from tb_class_lint import (
                lint_class_sv_tb,
                repair_class_sv_tb,
                sanitize_class_sv_tb,
            )
        except Exception:
            lint_class_sv_tb = None  # type: ignore
            repair_class_sv_tb = None  # type: ignore
            sanitize_class_sv_tb = None  # type: ignore
        if lint_class_sv_tb and repair_class_sv_tb:
            ok_c, issues_c = lint_class_sv_tb(
                cleaned,
                dut_name=dut_name,
                required_ports=required_ports,
                dut_outputs=dut_outputs,
                protocol=protocol,
                port_specs=port_specs,
            )
            soft_fixable = {
                "errors_not_initialized",
                "missing_post_reset_settle",
                "noop_constraint",
                "semantic_fifo_reset_rd_data",
            }
            needs_repair = (not ok_c) or any(
                i in soft_fixable
                or i.startswith("undeclared_signal:")
                or i.startswith("wrong_width:")
                for i in (issues_c or [])
            )
            if not needs_repair:
                # Bus protocols: still fall back when semantic VIP checks fail hard
                bus = (protocol or "").lower() in (
                    "axi_lite",
                    "axi4_lite",
                    "axi",
                    "apb",
                    "apb3",
                    "apb4",
                    "ahb",
                    "ahb_lite",
                    "ahb5",
                )
                if bus and skeleton:
                    try:
                        from tb_semantic import lint_semantic_golden

                        sem = lint_semantic_golden(cleaned, protocol=protocol or "generic")
                        hard_sem = [
                            i
                            for i in sem
                            if i.startswith("semantic_axi_")
                            or i.startswith("semantic_apb_")
                            or i.startswith("semantic_ahb_")
                        ]
                        if hard_sem:
                            header = (
                                "// ChipSutra: LLM class TB failed bus semantic gate "
                                f"({', '.join(hard_sem)}); using DUT-correct skeleton.\n"
                            )
                            return (
                                header + skeleton.lstrip(),
                                "skeleton_fallback",
                                hard_sem,
                            )
                    except Exception:
                        pass
                if sanitize_class_sv_tb:
                    sanitized = sanitize_class_sv_tb(
                        cleaned,
                        dut_outputs=dut_outputs,
                        protocol=protocol,
                        port_specs=port_specs,
                        required_ports=required_ports,
                    )
                    if sanitized != cleaned:
                        return sanitized, "llm_repaired", issues_c
                return cleaned, "llm", issues_c
            repaired_c = repair_class_sv_tb(
                cleaned,
                required_ports=required_ports,
                dut_outputs=dut_outputs,
                port_specs=port_specs,
                dut_name=dut_name,
                protocol=protocol,
            )
            ok2, issues2 = lint_class_sv_tb(
                repaired_c,
                dut_name=dut_name,
                required_ports=required_ports,
                dut_outputs=dut_outputs,
                protocol=protocol,
                port_specs=port_specs,
            )
            bus = (protocol or "").lower() in (
                "axi_lite",
                "axi4_lite",
                "axi",
                "apb",
                "apb3",
                "apb4",
            )
            if (not ok2) and bus and skeleton:
                header = (
                    "// ChipSutra: LLM class TB failed lint after repair "
                    f"({', '.join(issues2 or issues_c) or 'empty'}); "
                    "using DUT-correct bus skeleton.\n"
                )
                return header + skeleton.lstrip(), "skeleton_fallback", issues2 or issues_c
            return repaired_c, "llm_repaired", issues2 or issues_c

    ok, issues = lint_testbench(
        cleaned,
        dut_name=dut_name,
        required_ports=required_ports,
        dut_outputs=dut_outputs,
    )
    # Protocol semantic findings for procedural TBs too (recorded, drives repair)
    try:
        from tb_semantic import lint_semantic_golden

        sem = lint_semantic_golden(cleaned or "", protocol=protocol or "generic")
        issues = list(dict.fromkeys(list(issues) + sem))
        if any(i.startswith("semantic_axi_") for i in sem):
            ok = False
    except Exception:
        pass
    if ok and cleaned:
        return cleaned, "llm", issues

    # Soft-only gaps (dump/finish/chat): try repair before skeleton fallback
    hardish = [i for i in issues if i not in _SOFT_ISSUES and i not in _SOFT_SEMANTIC]
    if cleaned and not hardish and any(i in _SOFT_ISSUES for i in issues):
        repaired = repair_soft_tb_gaps(cleaned)
        ok2, issues2 = lint_testbench(
            repaired,
            dut_name=dut_name,
            required_ports=required_ports,
            dut_outputs=dut_outputs,
        )
        if ok2 and repaired:
            return repaired, "llm_repaired", issues2 or issues

    if skeleton:
        header = (
            "// ChipSutra: LLM output failed TB lint "
            f"({', '.join(issues) or 'empty'}); using verified randomized template.\n"
        )
        return header + skeleton.lstrip(), "skeleton_fallback", issues

    return cleaned or llm_text, "llm", issues or ["no_skeleton"]
