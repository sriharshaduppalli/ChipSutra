"""Lightweight UVM TB lint + mechanical repair (DUT-correct top / TLM hints)."""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Tuple

_FAKE_PUT = re.compile(r"\.\s*put\s*\(", re.I)
_FAKE_CONFIGURE_VIF = re.compile(r"\.\s*configure\s*\(\s*vif\s*\)", re.I)
_FAKE_CAST_RHS = re.compile(r"\bcast\s*\(\s*rhs\s*\)", re.I)
_FAKE_DRIVER_START = re.compile(r"\bdriver\s*\.\s*start\s*\(\s*this\s*\)", re.I)
_HAS_CONFIG_DB = re.compile(r"\buvm_config_db\b", re.I)
_HAS_RUN_TEST = re.compile(r"\brun_test\s*\(", re.I)
_EXTENDS_UVM = re.compile(
    r"\bclass\s+(\w+)\s+extends\s+(uvm_\w+)",
    re.I,
)
_HAS_COMPONENT_UTILS = re.compile(r"`\s*uvm_component_utils\b", re.I)
_HAS_OBJECT_UTILS = re.compile(r"`\s*uvm_object_utils\b", re.I)
_UVM_COMPONENT_BASES = re.compile(
    r"uvm_(?:component|agent|driver|monitor|sequencer|env|test|scoreboard)\b",
    re.I,
)
_UVM_OBJECT_BASES = re.compile(
    r"uvm_(?:object|sequence_item|sequence)\b",
    re.I,
)
_BUILD_PHASE = re.compile(
    r"function\s+void\s+build_phase\s*\([^)]*\)\s*;([\s\S]*?)\bendfunction\b",
    re.I,
)
_IF_LOGIC_DECL = re.compile(
    r"\b(?:logic|wire|bit|reg)\s+(?:(?:signed|unsigned)\s+)?(?:(\[[^\]]+\])\s+)?([^;]+);",
    re.I,
)


def _packed_width(packed: str) -> int:
    m = re.match(r"\[(\d+)\s*:\s*(\d+)\]", (packed or "").strip())
    if not m:
        return 1
    return abs(int(m.group(1)) - int(m.group(2))) + 1


def _interface_signal_widths(sv: str) -> Dict[str, int]:
    """logic/wire widths declared inside interface…endinterface blocks."""
    widths: Dict[str, int] = {}
    for im in re.finditer(r"\binterface\s+\w+\b[\s\S]*?\bendinterface\b", sv or "", re.I):
        block = im.group(0)
        block = re.sub(r"\bmodport\b[\s\S]*?;", "", block, flags=re.I)
        block = re.sub(r"\bclocking\b[\s\S]*?\bendclocking\b", "", block, flags=re.I)
        for line in block.splitlines():
            if re.search(r"\b(?:interface|endinterface)\b", line, re.I):
                continue
            m = _IF_LOGIC_DECL.search(line)
            if not m:
                continue
            bits = _packed_width(m.group(1) or "")
            for raw in (m.group(2) or "").split(","):
                name = re.split(r"\s*=\s*", raw.strip(), maxsplit=1)[0].strip()
                name = re.sub(r"\[.*?\]", "", name).strip()
                if re.match(r"^[A-Za-z_]\w*$", name):
                    widths[name.lower()] = bits
    return widths


def _dut_port_widths(port_specs: Optional[Sequence[dict]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for p in port_specs or []:
        n = (p.get("name") or "").strip()
        if not n:
            continue
        bits = p.get("bits")
        if isinstance(bits, int) and bits > 0:
            out[n.lower()] = bits
            continue
        w = (p.get("width") or "").strip()
        mw = re.match(r"\[(\d+)\s*:\s*(\d+)\]", w)
        if mw:
            out[n.lower()] = abs(int(mw.group(1)) - int(mw.group(2))) + 1
        else:
            out[n.lower()] = 1
    return out


def lint_uvm_tb(
    sv: str,
    port_specs: Optional[Sequence[dict]] = None,
) -> Tuple[bool, List[str]]:
    """Return (ok, issues). Fake APIs / missing run_test/config_db are hard."""
    if not sv:
        return False, ["no_module"]
    issues: List[str] = []

    if _FAKE_PUT.search(sv):
        issues.append("uvm_fake_api:put")
    if _FAKE_CONFIGURE_VIF.search(sv):
        issues.append("uvm_fake_api:configure")
    if _FAKE_CAST_RHS.search(sv):
        issues.append("uvm_fake_api:cast")
    if _FAKE_DRIVER_START.search(sv):
        issues.append("uvm_fake_api:driver_start")
    if re.search(r"\bextends\s+uvm_test_top\b", sv, re.I):
        issues.append("uvm_fake_base:test_top")
    # Correct API is phase.raise_objection(this) inside task run_phase(uvm_phase phase).
    # Fake: treating the phase task name as a handle — run_phase.raise_objection(...)
    if re.search(
        r"\brun_phase\s*\.\s*(?:raise|drop)_objection\b|"
        r"\buvm_test_top\s*\.\s*test\b|"
        r"\bstart_phase\s*\.\s*raise_objection\b",
        sv,
        re.I,
    ):
        issues.append("uvm_fake_api:phase_objection")

    looks_uvm = bool(
        re.search(r"\b(?:uvm_|`uvm_|import\s+uvm_pkg)", sv, re.I)
        or issues
    )
    if looks_uvm:
        if not _HAS_CONFIG_DB.search(sv):
            issues.append("uvm_missing_config_db")
        if not _HAS_RUN_TEST.search(sv):
            issues.append("uvm_missing_run_test")

        # Soft: utils macros when class extends uvm_*
        for m in _EXTENDS_UVM.finditer(sv):
            cls, base = m.group(1), m.group(2)
            # Find class body roughly
            start = m.start()
            end_m = re.search(r"\bendclass\b", sv[start:], re.I)
            body = sv[start : start + end_m.end()] if end_m else sv[start : start + 800]
            if _UVM_COMPONENT_BASES.search(base) and not _HAS_COMPONENT_UTILS.search(body):
                issues.append("uvm_missing_component_utils")
            elif _UVM_OBJECT_BASES.search(base) and not _HAS_OBJECT_UTILS.search(body):
                issues.append("uvm_missing_object_utils")

        # TLM .connect only belongs in connect_phase (not build_phase)
        for m in _BUILD_PHASE.finditer(sv):
            if re.search(r"\.\s*connect\s*\(", m.group(1)):
                issues.append("uvm_connect_in_build")
                break

        # Illegal SV that UVM LLMs invent (not IEEE 1800)
        if re.search(r"\bendprotected\b", sv, re.I):
            issues.append("uvm_illegal_sv:endprotected")
        if re.search(r"\b(?:protected\s+)?virtual\s+void\s+\w+\s*\(", sv, re.I):
            issues.append("uvm_illegal_sv:virtual_void")

        # Virtual interface type used but never declared
        vif_types = {
            m.group(1).lower()
            for m in re.finditer(r"\bvirtual\s+(\w+_if)\b", sv, re.I)
        }
        if_decls = {
            m.group(1).lower()
            for m in re.finditer(r"\binterface\s+(\w+)\b", sv, re.I)
        }
        if vif_types and not (vif_types & if_decls):
            issues.append("uvm_missing_interface")

        # Driver seq_item_port must connect to sequencer, not monitor/SB
        if re.search(
            r"seq_item_port\s*\.\s*connect\s*\([^)]*"
            r"(?:monitor|analysis_export|scoreboard)",
            sv,
            re.I,
        ):
            issues.append("uvm_wrong_tlm")

        # Monitor is a producer (uvm_monitor + analysis_port), not uvm_subscriber
        if re.search(
            r"\bclass\s+\w*monitor\w*\s+extends\s+uvm_subscriber\b", sv, re.I
        ):
            issues.append("uvm_monitor_is_subscriber")

        for mm in re.finditer(
            r"\bclass\s+\w*monitor\w*\s+extends\s+uvm_monitor\b([\s\S]*?)\bendclass\b",
            sv,
            re.I,
        ):
            mbody = re.sub(r"//[^\n]*", "", mm.group(1))
            if re.search(r"\bvif\s*\.\s*\w+\s*=", mbody):
                issues.append("uvm_monitor_drives")
                break

        # Phantom includes — ChipSutra UVM smoke is one file
        for inc in re.finditer(r'`include\s+"([^"]+)"', sv):
            name = (inc.group(1) or "").replace("\\", "/").split("/")[-1].lower()
            if name not in ("uvm_macros.svh",):
                issues.append("uvm_phantom_include")
                break

        # Bare uvm_sequence#(T) seq = new() has no body — not a real sequence
        if re.search(
            r"\buvm_sequence\s*#\s*\([^)]+\)\s+\w+\s*;", sv, re.I
        ) and not re.search(
            r"\bclass\s+\w+\s+extends\s+uvm_sequence\b", sv, re.I
        ):
            issues.append("uvm_generic_seq_new")

        # Scoreboard write() is a function — time controls are a Pure SV run() leak
        for wm in re.finditer(
            r"function\s+(?:void\s+)?write\s*\([^)]*\)\s*;([\s\S]*?)endfunction",
            sv,
            re.I,
        ):
            wbody = re.sub(r"//[^\n]*", "", wm.group(1))
            wbody = re.sub(r"/\*[\s\S]*?\*/", "", wbody)
            if re.search(
                r"@\s*\(?\s*(?:posedge|negedge)|(?<![\w`])#\s*\d+",
                wbody,
                re.I,
            ):
                issues.append("uvm_write_has_time")
                break

        # Env fork of generator threads is Pure SV concurrency leaking into UVM
        for em in re.finditer(
            r"\bclass\s+\w+\s+extends\s+uvm_env\b([\s\S]*?)\bendclass\b",
            sv,
            re.I,
        ):
            if re.search(r"task\s+run_phase[\s\S]*?\bfork\b", em.group(1), re.I):
                issues.append("uvm_env_fork_generator")
                break

        # Pure SV layered stack mixed into UVM (generator + mailboxes)
        if re.search(r"\bclass\s+\w*generator\b", sv, re.I) or re.search(
            r"\bmailbox\s*(?:#\s*\([^)]*\))?\s*gen2drv\b", sv, re.I
        ):
            issues.append("uvm_mixed_pure_sv")

        # Scoreboard sink: analysis_port.get / seq_item_port.get is wrong
        sb = re.search(
            r"\bclass\s+\w*scoreboard\w*\b[\s\S]*?\bendclass\b", sv, re.I
        )
        if sb:
            sb_body = sb.group(0)
            if re.search(r"\bseq_item_port\s*\.\s*get\s*\(", sb_body, re.I):
                issues.append("uvm_sb_seq_item_get")
            if re.search(r"\bvirtual\s+\w+_if\b", sb_body, re.I):
                issues.append("uvm_sb_has_vif")
            if re.search(r"\buvm_analysis_port\b", sb_body, re.I):
                if re.search(r"\.\s*get\s*\(", sb_body):
                    issues.append("uvm_sb_analysis_port_get")
                elif not re.search(
                    r"\buvm_analysis_imp\b|\buvm_subscriber\b|\bfunction\s+void\s+write\s*\(",
                    sb_body,
                    re.I,
                ):
                    issues.append("uvm_missing_analysis_imp")
            # Empty / placeholder golden — not a real checker
            write_m = re.search(
                r"function\s+void\s+write\s*\([^)]*\)\s*;([\s\S]*?)\bendfunction\b",
                sb_body,
                re.I,
            )
            if write_m:
                wbody = write_m.group(1)
                placeholder = bool(
                    re.search(
                        r"predict/check goes here|Independent predict",
                        wbody,
                        re.I,
                    )
                )
                has_check = bool(
                    re.search(
                        r"!==|!=|`uvm_error|errors\s*\+\+|mismatch|expected\s*=",
                        wbody,
                        re.I,
                    )
                )
                # seen++ alone is empty unless report_phase guards seen==0 (generic smoke)
                only_seen = (
                    bool(re.search(r"\bseen\s*\+\+", wbody))
                    and not has_check
                    and not re.search(r"seen\s*==\s*0", sb_body)
                )
                if placeholder or only_seen:
                    issues.append("uvm_empty_scoreboard")

        if re.search(r"\buvm_agent\b|\buvm_env\b|\buvm_test\b", sv, re.I):
            if not re.search(r"\bfunction\s+void\s+connect_phase\b", sv, re.I):
                if re.search(r"\.\s*connect\s*\(", sv):
                    issues.append("uvm_missing_connect_phase")

        # Top must instantiate DUT (named port map; allow parameters)
        has_dut = bool(
            re.search(r"\b\w+\s*(?:#\s*\([^;]*\))?\s+\w+\s*\(\s*\.", sv, re.S)
            or re.search(r"\bdut\s*(?:#\s*\([^;]*\))?\s*\(", sv, re.I | re.S)
        )
        if re.search(r"\bmodule\b", sv, re.I) and not has_dut:
            issues.append("uvm_missing_dut_instance")

    # Agent / env structure: if it claims to be UVM, require hierarchy + sequencer.
    if looks_uvm and re.search(r"\buvm_agent\b|\buvm_env\b|\buvm_test\b", sv, re.I):
        if not re.search(r"\bextends\s+uvm_(?:agent|env|test)\b", sv, re.I):
            issues.append("uvm_missing_env_hierarchy")
        if not re.search(r"\buvm_sequence_item\b", sv, re.I):
            issues.append("uvm_missing_sequencer_item")
        if not re.search(r"\buvm_sequencer\b", sv, re.I):
            issues.append("uvm_missing_sequencer")

    dut_w = _dut_port_widths(port_specs)
    if_w = _interface_signal_widths(sv)
    if dut_w and if_w:
        clk_names = {"clk", "clock", "clk_i", "aclk", "pclk", "sclk"}
        for pname, bits in dut_w.items():
            if pname in clk_names:
                continue
            if pname in if_w and if_w[pname] != bits:
                issues.append("uvm_if_width_mismatch")
                break

    issues = list(dict.fromkeys(issues))
    # Soft structural nits when hierarchy is incomplete; hard when fake/missing core
    soft = {
        "uvm_missing_component_utils",
        "uvm_missing_object_utils",
        "uvm_missing_connect_phase",
        "uvm_missing_analysis_imp",
        "uvm_missing_env_hierarchy",
        "uvm_missing_sequencer_item",
    }
    # Missing DUT in top is hard — TB will not exercise RTL without it.
    if not re.search(r"\bextends\s+uvm_(?:agent|env|test)\b", sv or "", re.I):
        soft |= {"uvm_missing_component_utils", "uvm_missing_object_utils"}
    hard = [i for i in issues if i not in soft]
    ok = not hard
    return ok, issues


def repair_uvm_hints(sv: str) -> str:
    """Append a comment block of required UVM fixes; do not invent full UVM."""
    _ok, issues = lint_uvm_tb(sv)
    if not issues:
        return sv
    hints = [
        "// CHIP_SUTRA_UVM_HINTS — mechanical notes only (not a full UVM env):",
    ]
    for i in issues:
        if i == "uvm_fake_api:put":
            hints.append("//   - Replace fake .put(...) with seq_item_port.put / analysis_port.write")
        elif i == "uvm_fake_api:configure":
            hints.append("//   - Replace .configure(vif) with uvm_config_db#(virtual if)::set/get")
        elif i == "uvm_fake_api:cast":
            hints.append("//   - Replace cast(rhs) with $cast(lhs, rhs)")
        elif i == "uvm_fake_api:driver_start":
            hints.append("//   - Do not call driver.start(this); use phase.run_phase / sequencer start")
        elif i == "uvm_fake_base:test_top":
            hints.append("//   - Do not extend uvm_test_top; use uvm_test + module top that calls run_test()")
        elif i == "uvm_fake_api:phase_objection":
            hints.append("//   - Objections: phase.raise_objection(this) in test run_phase — never run_phase.raise_objection")
        elif i == "uvm_connect_in_build":
            hints.append("//   - Move TLM .connect(...) from build_phase into connect_phase")
        elif i == "uvm_sb_analysis_port_get":
            hints.append("//   - Scoreboard: use uvm_analysis_imp#(T,this) + write(), not analysis_port.get()")
        elif i == "uvm_sb_seq_item_get":
            hints.append("//   - Scoreboard: analysis_imp.write(), never seq_item_port.get (that is the driver)")
        elif i == "uvm_illegal_sv:endprotected":
            hints.append("//   - Illegal SV: there is no endprotected — use function/task + endfunction/endtask")
        elif i == "uvm_illegal_sv:virtual_void":
            hints.append("//   - Illegal SV: use `virtual function void foo()` or `virtual task foo()`, never `virtual void`")
        elif i == "uvm_missing_interface":
            hints.append("//   - Declare `interface <dut>_if` — virtual <dut>_if is not a type without it")
        elif i == "uvm_missing_sequencer":
            hints.append("//   - Agent needs uvm_sequencer#(txn); test starts the sequence on env.agent.sequencer")
        elif i == "uvm_wrong_tlm":
            hints.append("//   - connect_phase: driver.seq_item_port.connect(sequencer.seq_item_export); mon.ap → sb.imp")
        elif i == "uvm_monitor_is_subscriber":
            hints.append("//   - Monitor extends uvm_monitor and analysis_port.write; subscriber is for SB/coverage")
        elif i == "uvm_generic_seq_new":
            hints.append("//   - Define class <dut>_seq extends uvm_sequence#(txn) with task body(); never seq = new()")
        elif i == "uvm_mixed_pure_sv":
            hints.append("//   - UVM must not use Pure SV generator/mailboxes; use sequencer+sequence and analysis TLM")
        elif i == "uvm_write_has_time":
            hints.append("//   - write() is a function: no @(posedge)/# delays — sample in the monitor run_phase")
        elif i == "uvm_env_fork_generator":
            hints.append("//   - Do not fork a generator in uvm_env; start a sequence from the test on the sequencer")
        elif i == "uvm_sb_has_vif":
            hints.append("//   - Scoreboard compares txns — no virtual interface; the monitor samples pins")
        elif i == "uvm_monitor_drives":
            hints.append("//   - Monitor is passive: sample vif, never assign vif.*")
        elif i == "uvm_phantom_include":
            hints.append("//   - Smoke is one .sv; only `include \"uvm_macros.svh\" (no extra TB files)")
        elif i == "uvm_if_width_mismatch":
            hints.append(
                "//   - Interface signal widths must match DUT ports "
                "(do not collapse vectors to 1-bit comma lists)"
            )
        elif i == "uvm_missing_analysis_imp":
            hints.append("//   - Scoreboard needs uvm_analysis_imp / uvm_subscriber and write()")
        elif i == "uvm_empty_scoreboard":
            hints.append(
                "//   - Scoreboard write() must predict/check DUT outputs "
                "(not seen++ / placeholder comments)"
            )
        elif i == "uvm_missing_connect_phase":
            hints.append("//   - Add connect_phase and wire sqr↔drv + mon.ap→sb there")
        elif i == "uvm_missing_dut_instance":
            hints.append("//   - Instantiate the real DUT in the top module with a named port map")
        elif i == "uvm_missing_config_db":
            hints.append("//   - Add uvm_config_db#(virtual <if>)::set/get for the vif")
        elif i == "uvm_missing_run_test":
            hints.append("//   - Call run_test(\"...\") from the TB initial block")
        elif i == "uvm_missing_component_utils":
            hints.append("//   - Add `uvm_component_utils(<class>) in uvm_component subclasses")
        elif i == "uvm_missing_object_utils":
            hints.append("//   - Add `uvm_object_utils(<class>) in uvm_object/sequence_item subclasses")
        else:
            hints.append(f"//   - Fix: {i}")
    block = "\n".join(hints) + "\n"
    if "CHIP_SUTRA_UVM_HINTS" in sv:
        return sv
    return sv.rstrip() + "\n\n" + block


_HARD_FALLBACK = frozenset(
    {
        "uvm_missing_dut_instance",
        "uvm_missing_run_test",
        "uvm_missing_config_db",
        "uvm_fake_base:test_top",
        "uvm_sb_analysis_port_get",
        "uvm_sb_seq_item_get",
        "uvm_fake_api:put",
        "uvm_fake_api:phase_objection",
        "uvm_empty_scoreboard",
        "uvm_illegal_sv:endprotected",
        "uvm_illegal_sv:virtual_void",
        "uvm_missing_interface",
        "uvm_missing_sequencer",
        "uvm_wrong_tlm",
        "uvm_monitor_is_subscriber",
        "uvm_generic_seq_new",
        "uvm_mixed_pure_sv",
        "uvm_write_has_time",
        "uvm_env_fork_generator",
        "uvm_sb_has_vif",
        "uvm_monitor_drives",
        "uvm_phantom_include",
        "uvm_if_width_mismatch",
        "no_module",
    }
)


def repair_uvm_tb(
    sv: str,
    *,
    dut_name: Optional[str] = None,
    port_specs: Optional[Sequence[dict]] = None,
    parameters: Optional[dict] = None,
) -> str:
    """Mechanical UVM fixes; replace broken/missing top with DUT-correct skeleton top.

    When the LLM hierarchy is badly broken (no DUT, fake test_top, SB analysis_port.get),
    fall back to a full deterministic UVM smoke TB for the parsed DUT.
    """
    body = (sv or "").strip()
    ok, issues = lint_uvm_tb(body, port_specs=port_specs)
    if ok and not any(i in _HARD_FALLBACK for i in issues):
        return body

    # Need port list to emit a real top / full skeleton
    if not dut_name or not port_specs:
        return repair_uvm_hints(body)

    try:
        from tb_uvm_skeleton import render_uvm_smoke_tb, render_uvm_top_only
    except Exception:
        return repair_uvm_hints(body)

    mod = {
        "name": dut_name,
        "ports": list(port_specs),
        "parameters": parameters or {},
    }

    # Catastrophic / empty checker / illegal UVM graph → full protocol-aware skeleton
    _full_always = (
        "no_module",
        "uvm_fake_base:test_top",
        "uvm_fake_api:put",
        "uvm_fake_api:phase_objection",
        "uvm_empty_scoreboard",
        "uvm_illegal_sv:endprotected",
        "uvm_illegal_sv:virtual_void",
        "uvm_missing_interface",
        "uvm_missing_sequencer",
        "uvm_wrong_tlm",
        "uvm_sb_seq_item_get",
        "uvm_monitor_is_subscriber",
        "uvm_generic_seq_new",
        "uvm_mixed_pure_sv",
        "uvm_write_has_time",
        "uvm_env_fork_generator",
        "uvm_sb_has_vif",
        "uvm_monitor_drives",
        "uvm_phantom_include",
        "uvm_if_width_mismatch",
    )
    needs_full = (
        not body
        or any(i in issues for i in _full_always)
        or (
            "uvm_missing_dut_instance" in issues
            and not re.search(r"\bextends\s+uvm_(?:agent|env|test)\b", body, re.I)
        )
        or (
            "uvm_sb_analysis_port_get" in issues
            and "uvm_missing_dut_instance" in issues
        )
    )
    if needs_full:
        return render_uvm_smoke_tb(mod)

    # Surgical: keep classes, replace module top(s) with DUT-correct top
    if "uvm_missing_dut_instance" in issues or "uvm_missing_run_test" in issues:
        top = render_uvm_top_only(mod)
        # Drop existing module…endmodule blocks
        stripped = re.sub(
            r"\bmodule\b[\s\S]*?\bendmodule\b",
            "",
            body,
            flags=re.I,
        ).rstrip()
        # LLM often truncates mid-top (`module foo` with no endmodule) — drop that stub
        stripped = re.sub(
            r"\bmodule\b[\s\S]*$",
            "",
            stripped,
            flags=re.I,
        ).rstrip()
        # Drop stale hint blocks
        stripped = re.sub(
            r"\n*// CHIP_SUTRA_UVM_HINTS[\s\S]*$",
            "",
            stripped,
        ).rstrip()
        body = stripped + "\n\n" + top

    # Light TLM comment if SB still wrong but hierarchy kept
    ok2, issues2 = lint_uvm_tb(body, port_specs=port_specs)
    if not ok2 and any(
        i in ("uvm_sb_analysis_port_get", "uvm_missing_analysis_imp") for i in issues2
    ):
        body = repair_uvm_hints(body)
    return body
