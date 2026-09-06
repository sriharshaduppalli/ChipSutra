"""Class-based Pure SV TB lint + mechanical repair (close gap vs Claude/GPT).

Catches: missing clock, wire-driven stimulus, task+return, missing new(),
undeclared ports/errors, NBA in scoreboard, noop constraints, missing errors=0,
missing post-reset settle.
"""
from __future__ import annotations

import re
from typing import List, Optional, Sequence, Tuple

from tb_lint import (
    _GOOD_CLOCK,
    _HAS_DUMP,
    _HAS_FINISH,
    _HAS_POSEDGE,
    _declared_idents,
    extract_sv,
    lint_testbench,
    repair_soft_tb_gaps,
)

_WIDTH_HINT = {
    "count": "[3:0]",
    "cnt": "[3:0]",
    "q": "[3:0]",
    "data": "[7:0]",
    "wr_data": "[7:0]",
    "rd_data": "[7:0]",
    "wdata": "[31:0]",
    "rdata": "[31:0]",
}


def _port_spec_map(port_specs: Optional[Sequence[dict]]) -> dict:
    out: dict = {}
    for p in port_specs or []:
        n = (p.get("name") or "").strip()
        if n:
            out[n.lower()] = p
    return out


def _width_for(name: str, port_specs: Optional[Sequence[dict]] = None) -> str:
    sp = _port_spec_map(port_specs).get(name.lower())
    if sp and (sp.get("width") or "").strip():
        return (sp.get("width") or "").strip()
    return _WIDTH_HINT.get(name.lower(), "")


def _strip_classes(sv: str) -> str:
    return re.sub(r"\bclass\b[\s\S]*?\bendclass\b", "\n", sv, flags=re.I)


_CLASS_BLOCK = re.compile(r"\bclass\b[\s\S]*?\bendclass\b", re.I)
_PARAM_DECL = re.compile(
    r"\b(?:parameter|localparam)\s+(?:int\s+|integer\s+)?(\w+)\s*=\s*([^,;\)\n]+)",
    re.I,
)


def class_scope_param_gaps(sv: str) -> List[Tuple[str, str]]:
    """Module parameters referenced inside file-scope classes.

    Classes declared BEFORE the module ($unit scope) cannot see module
    parameters like WIDTH/DEPTH — a compile error premium models never make.
    Returns [(name, default_value), ...] for params needing a file-scope hoist.
    """
    mod = re.search(r"\bmodule\b", sv, re.I)
    if not mod:
        return []
    pre, module_region = sv[: mod.start()], sv[mod.start() :]
    classes = _CLASS_BLOCK.findall(pre)
    if not classes:
        return []
    gaps: List[Tuple[str, str]] = []
    for m in _PARAM_DECL.finditer(module_region):
        name, val = m.group(1), m.group(2).strip()
        # Already visible at file scope before the classes?
        if re.search(rf"\b(?:parameter|localparam)\b[^;\n]*\b{re.escape(name)}\b", pre, re.I):
            continue
        for cls in classes:
            if re.search(rf"\b{re.escape(name)}\b", cls) and not re.search(
                rf"\blocalparam\b[^;\n]*\b{re.escape(name)}\b", cls, re.I
            ):
                gaps.append((name, val))
                break
    return list(dict.fromkeys(gaps))


def _module_declared(sv: str) -> set:
    """Identifiers declared in the TB module (not inside classes)."""
    region = _strip_classes(sv)
    names = set(_declared_idents(region))
    for m in re.finditer(
        r"\b(?:int|integer)\b\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;",
        region,
        re.I,
    ):
        for part in m.group(1).split(","):
            n = part.strip().split("=")[0].strip()
            if n:
                names.add(n.lower())
    for m in re.finditer(r"\bautomatic\s+\w+\s+(\w+)\s*=", region, re.I):
        names.add(m.group(1).lower())
    return names


def undeclared_tb_ports(sv: str, required_ports: Optional[Sequence[str]]) -> List[str]:
    """DUT ports referenced as TB identifiers but never declared as logic/reg/…"""
    if not required_ports:
        return []
    region = _strip_classes(sv)
    declared = _module_declared(sv)
    missing: List[str] = []
    for p in required_ports:
        if not p:
            continue
        if not re.search(rf"(?<!\.)\b{re.escape(p)}\b", region):
            continue
        if p.lower() not in declared:
            missing.append(p)
    return missing


_SCOREBOARD_CLASS = re.compile(r"\bclass\s+\w*scoreboard\w*\b[\s\S]*?\bendclass\b", re.I)
_RST_PORT_NAMES = frozenset(
    {"rst_n", "rst", "reset_n", "resetn", "aresetn", "presetn", "hresetn", "reset"}
)
# Outputs that are often X after reset (FWFT head, uninitialized mem) — skip post-reset '0 check
_POST_RESET_SKIP_OUTS = frozenset(
    {
        "rd_data",
        "rdata",
        "data_out",
        "dout",
        "q",
        "mem_dout",
        "prdata",
        "hrdata",
        "s_axi_rdata",
        # Active-high status that is 1 after reset (not '0)
        "empty",
        "almost_empty",
    }
)


def _known_port_names(
    port_specs: Optional[Sequence[dict]], required_ports: Optional[Sequence[str]]
) -> set:
    names = {(p.get("name") or "").strip().lower() for p in (port_specs or []) if p.get("name")}
    if required_ports:
        names |= {p.lower() for p in required_ports if p}
    return names


def lint_class_sv_tb(
    sv: str,
    *,
    dut_name: Optional[str] = None,
    required_ports: Optional[List[str]] = None,
    dut_outputs: Optional[Sequence[str]] = None,
    protocol: str = "generic",
    port_specs: Optional[Sequence[dict]] = None,
) -> Tuple[bool, List[str]]:
    """Lint tuned for class-based Pure SV (randomize OK instead of $urandom)."""
    body = extract_sv(sv) or sv
    _ok, issues = lint_testbench(
        body,
        dut_name=dut_name,
        required_ports=required_ports,
        dut_outputs=dut_outputs,
    )
    if re.search(r"\b(?:std::)?randomize\s*\(|\brand\b", body, re.I):
        issues = [i for i in issues if i != "missing_urandom"]

    extras: List[str] = []
    if re.search(r"\bclass\b", body) and re.search(r"\brandomize\s*\(", body, re.I):
        if not re.search(r"\bnew\s*\(", body):
            extras.append("missing_new_construct")
    if re.search(r"\btask\b[\s\S]{0,200}?\breturn\b", body, re.I):
        extras.append("task_with_return")
    if re.search(r"\bexpected\s*<=", body):
        extras.append("nba_in_scoreboard_model")
    if re.search(r"\berrors\b", body) and not re.search(
        r"\b(?:int|integer|logic|reg)\b[^;\n]*\berrors\b", body, re.I
    ):
        extras.append("undeclared_errors")
    if re.search(r"\berrors\b", body) and not re.search(r"\berrors\s*=\s*0\b", body):
        extras.append("errors_not_initialized")
    # LLM: `sb.errors++` when scoreboard has no errors member (module owns errors)
    if re.search(r"\b\w+\.errors\s*(?:\+\+|=\s*\w+\.errors\s*\+\s*1)", body):
        sb_declares_errors = any(
            re.search(r"\b(?:int|integer|logic|reg)\b[^;\n]*\berrors\b", blk, re.I)
            for blk in _SCOREBOARD_CLASS.findall(body)
        )
        if not sb_declares_errors:
            extras.append("sb_errors_not_member")
    # Scoreboard uses `expected = ...` without declaring the member
    for blk in _SCOREBOARD_CLASS.findall(body):
        uses_assign = bool(re.search(r"(?<![\w.])expected\s*=", blk))
        # Member decl at class scope (not a function formal like check(... expected ...))
        declares = bool(
            re.search(
                r"^\s*(?:logic|bit|reg|int|integer)\b[^;\n]*\bexpected\b",
                blk,
                re.I | re.M,
            )
        )
        if uses_assign and not declares:
            extras.append("undeclared_expected")
            break
    if re.search(r"constraint\s+\w+\s*\{\s*1\s*;\s*\}", body, re.I) or re.search(
        r"constraint\s+\w+\s*\{\s*\}", body, re.I
    ):
        extras.append("noop_constraint")
    if re.search(
        r"rst_n\s*=\s*(?:1'b1|1)\s*;\s*(?:\n\s*)*for\s*\(",
        body,
        re.I,
    ):
        extras.append("missing_post_reset_settle")
    if _active_low_reset_stuck(body):
        extras.append("stuck_active_low_reset")

    # Soft: invented reset stimulus on combo DUT (no reset port)
    known = _known_port_names(port_specs, required_ports)
    if known and not (known & _RST_PORT_NAMES) and re.search(r"\brst_n\s*=", body, re.I):
        extras.append("combo_invented_reset")

    if re.search(
        r"\b(?:import\s+uvm_pkg|`\s*uvm_|uvm_component_utils|uvm_object_utils|ovm_|vmm_)\b",
        body,
        re.I,
    ):
        extras.append("uvm_in_pure_sv")

    # Soft: layered Pure SV component stack (default methodology — keep so
    # compact txn+sb still triggers LLM repair toward IF/gen/drv/mon/env/test)
    if re.search(r"\bclass\b", body) and not re.search(r"\buvm_", body, re.I):
        if not re.search(r"\binterface\b", body, re.I):
            extras.append("missing_sv_interface")
        if not re.search(r"\bclass\s+\w*(generator|gen)\b|_generator\b", body, re.I):
            extras.append("missing_sv_generator")
        if not re.search(r"\bclass\s+\w*driver\b|_driver\b", body, re.I):
            extras.append("missing_sv_driver")
        if not re.search(r"\bclass\s+\w*monitor\b|_monitor\b", body, re.I):
            extras.append("missing_sv_monitor")
        if not re.search(r"\bclass\s+\w*(env|environment)\b|_env\b", body, re.I):
            extras.append("missing_sv_env")
        if not re.search(r"\bclass\s+\w*test\b|_test\b", body, re.I):
            extras.append("missing_sv_test")
        if _layered_syntax_broken(body):
            extras.append("layered_syntax_broken")

    for p in undeclared_tb_ports(body, required_ports):
        extras.append(f"undeclared_signal:{p}")

    for pname, _val in class_scope_param_gaps(body):
        extras.append(f"class_param_scope:{pname}")

    # Invented DUT pins: `.clk(...)` in the port map when the DUT has no clk
    known_pins = {
        (p.get("name") or "").strip() for p in (port_specs or []) if p.get("name")
    }
    if known_pins:
        m_inst = re.search(r"\b\w+\s+dut\s*\(([^;]*?)\)\s*;", body, re.S)
        if m_inst:
            for pin in re.findall(r"\.(\w+)\s*\(", m_inst.group(1)):
                if pin not in known_pins:
                    extras.append(f"unknown_dut_pin:{pin}")

    # Width mismatch: `logic count;` when DUT has [3:0]
    region = _strip_classes(body)
    for name, sp in _port_spec_map(port_specs).items():
        w = (sp.get("width") or "").strip()
        if not w or w == "[0:0]":
            continue
        # bare scalar decl of a wide port
        if re.search(rf"\blogic\s+{re.escape(sp.get('name') or name)}\s*;", region, re.I):
            extras.append(f"wrong_width:{sp.get('name') or name}")

    try:
        from tb_semantic import lint_semantic_golden

        extras.extend(lint_semantic_golden(body, protocol=protocol or "generic"))
    except Exception:
        pass

    # Soft: functional coverage expected for premium DV quality (repair inserts it)
    try:
        from tb_coverage import has_covergroup

        if not has_covergroup(body):
            extras.append("missing_functional_coverage")
    except Exception:
        pass

    for m in re.finditer(r"for\s*\([^)]*\)\s*begin", body, re.I):
        depth = 0
        j = m.end()
        while j < len(body):
            if re.match(r"\bbegin\b", body[j:], re.I):
                depth += 1
                j += 5
                continue
            if re.match(r"\bend\b", body[j:], re.I):
                if depth == 0:
                    chunk = body[m.end() : j]
                    if re.search(r"\$display\s*\(\s*\"PASS:", chunk, re.I):
                        extras.append("pass_inside_loop")
                    break
                depth -= 1
                j += 3
                continue
            j += 1
        break

    issues = list(dict.fromkeys(issues + extras))

    hard = {
        "no_module",
        "bad_or_missing_clock",
        "circular_golden",
        "missing_dut_instance",
        "missing_posedge_sync",
        "missing_new_construct",
        "task_with_return",
        "undeclared_errors",
        "undeclared_expected",
        "sb_errors_not_member",
        "undeclared_queue_q",
        "undeclared_DEPTH",
        "noop_constraint",
        "semantic_circular_out",
        "semantic_fifo_no_queue",
        "semantic_fifo_count_arith",
        "semantic_fifo_reset_rd_data",
        "semantic_axi_no_ready_wait",
        "semantic_axi_no_resp_check",
        "semantic_axi_no_wstrb",
        "semantic_apb_no_access_phase",
        "semantic_apb_no_model_reg",
        "semantic_noop_check",
        "semantic_mux_no_select",
        "layered_syntax_broken",
        "incomplete_module",
        "uvm_in_pure_sv",
    }

    def _hard(i: str) -> bool:
        return (
            i in hard
            or i.startswith("missing_port_map:")
            or i.startswith("drives_dut_output:")
            or i.startswith("wire_driven_procedurally:")
            or i.startswith("undeclared_signal:")
            or i.startswith("wrong_width:")
            or i.startswith("class_param_scope:")
            or i.startswith("unknown_dut_pin:")
        )

    ok = not any(_hard(i) for i in issues)
    if any(i in ("missing_dump", "missing_finish") for i in issues):
        ok = False
    return ok, issues


_DECL_PLAIN = re.compile(
    r"^([ \t]*)(?:automatic\s+)?(?:int|integer)\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*;\s*(.*)$"
)
_DECL_INIT = re.compile(
    r"^([ \t]*)(?:automatic\s+)?(?:int|integer)\s+(\w+)\s*=\s*([^;]+);\s*(.*)$"
)
_DECL_CLASS_NEW = re.compile(
    r"^[ \t]*(?:automatic\s+)?(\w+)\s+(\w+)\s*=\s*(new\s*\(\s*\)|\w+\.clone\s*\(\s*\))\s*;\s*$"
)


def hoist_initial_decls(body: str) -> str:
    """Move declarations that appear after statements inside `initial` blocks
    to module scope (illegal in SV; a very common LLM mistake).

    `int t = 0;` → module-scope `integer t;` + in-place `t = 0;`.
    `Cls v = new();` → module-scope `Cls v;` + in-place `v = new();`.
    `Cls v = x.clone();` with no clone() defined → `v = x;` (alias).
    """
    m_mod = re.search(r"\bmodule\s+\w+\s*(?:#\s*\([^)]*\)\s*)?(?:\([^)]*\)\s*)?;", body)
    if not m_mod:
        return body
    class_names = set(re.findall(r"\bclass\s+(\w+)", body))
    has_clone = bool(re.search(r"\bfunction\b[^;\n]*\bclone\s*\(", body))
    lines = body.splitlines()
    hoisted: list = []
    out: list = []
    in_initial = False
    depth = 0
    stmt_seen = False
    for ln in lines:
        if not in_initial and re.search(r"\binitial\s+begin\b", ln):
            in_initial = True
            depth = 0
            stmt_seen = False
        if in_initial:
            depth += len(re.findall(r"\bbegin\b", ln)) - len(re.findall(r"\bend\b", ln))
            handled = False
            mp = _DECL_PLAIN.match(ln)
            mi = _DECL_INIT.match(ln) if not mp else None
            mc = _DECL_CLASS_NEW.match(ln) if not (mp or mi) else None
            if mp:
                names = [n.strip() for n in mp.group(2).split(",") if n.strip()]
                hoisted.extend(f"  integer {n};" for n in names)
                rest = (mp.group(3) or "").strip()
                if rest:
                    out.append(f"{mp.group(1)}{rest}")
                handled = True
            elif mi:
                hoisted.append(f"  integer {mi.group(2)};")
                rest = (mi.group(4) or "").strip()
                tail = f" {rest}" if rest else ""
                out.append(f"{mi.group(1)}{mi.group(2)} = {mi.group(3).strip()};{tail}")
                handled = True
            elif mc and mc.group(1) in class_names:
                rhs = mc.group(3)
                if ".clone" in rhs and not has_clone:
                    rhs = rhs.split(".")[0]
                hoisted.append(f"  {mc.group(1)} {mc.group(2)};")
                indent = ln[: len(ln) - len(ln.lstrip())]
                out.append(f"{indent}{mc.group(2)} = {rhs.strip()};")
                handled = True
            if not handled:
                out.append(ln)
                if re.search(r"[;)]\s*$|\bbegin\b", ln):
                    stmt_seen = True
            if depth <= 0 and re.search(r"\bend\b", ln):
                in_initial = False
        else:
            out.append(ln)
    _ = stmt_seen
    if not hoisted:
        return body
    text = "\n".join(out)
    # Deduplicate against existing module-scope declarations
    uniq = []
    for h in hoisted:
        name = h.strip().rstrip(";").split()[-1]
        if not re.search(
            rf"^[ \t]*(?:integer|int|logic|reg|bit|\w+)\s+(?:\[[^\]]*\]\s*)?{re.escape(name)}\s*;",
            text,
            re.M,
        ):
            uniq.append(h)
    if not uniq:
        return text
    frag = m_mod.group(0)
    at = text.find(frag) + len(frag)
    return text[:at] + "\n" + "\n".join(dict.fromkeys(uniq)) + text[at:]


def qualify_class_members(body: str) -> str:
    """`model_reg[...]` at module scope → `sb.model_reg[...]` when model_reg is a
    class member and `sb` is that class's instance (common LLM scoping slip)."""
    spans = [(m.start(), m.end(), m.group(0)) for m in _CLASS_BLOCK.finditer(body)]
    if not spans:
        return body
    module_region = _strip_classes(body)
    declared = _module_declared(body)
    for _s, _e, block in spans:
        m_cls = re.search(r"\bclass\s+(\w+)", block)
        if not m_cls:
            continue
        m_inst = re.search(rf"\b{re.escape(m_cls.group(1))}\s+(\w+)\s*;", module_region)
        if not m_inst:
            continue
        inst = m_inst.group(1)
        members = re.findall(
            r"^\s*(?:logic|bit|reg|int|integer)\s*(?:\[[^\]]+\]\s*)?(\w+)",
            block,
            re.M,
        )
        for mem in members:
            if mem in declared or not re.search(rf"(?<![\w.]){re.escape(mem)}\b", module_region):
                continue
            new_region = re.sub(
                rf"(?<![\w.]){re.escape(mem)}\b(?!\s*\()", f"{inst}.{mem}", module_region
            )
            if new_region != module_region:
                # Apply the same rewrite to body outside class blocks
                parts, last = [], 0
                for s2, e2, _b in spans:
                    seg = body[last:s2]
                    parts.append(
                        re.sub(
                            rf"(?<![\w.]){re.escape(mem)}\b(?!\s*\()",
                            f"{inst}.{mem}",
                            seg,
                        )
                    )
                    parts.append(body[s2:e2])
                    last = e2
                parts.append(
                    re.sub(
                        rf"(?<![\w.]){re.escape(mem)}\b(?!\s*\()",
                        f"{inst}.{mem}",
                        body[last:],
                    )
                )
                body = "".join(parts)
                module_region = _strip_classes(body)
    return body


def drop_unknown_dut_pins(
    body: str, port_specs: Optional[Sequence[dict]], dut_name: Optional[str] = None
) -> str:
    """Remove `.pin(sig)` connections the DUT does not have (LLMs invent
    clk/rst pins on combinational DUTs, which is a hard compile error)."""
    known = {(p.get("name") or "").strip() for p in (port_specs or []) if p.get("name")}
    if not known:
        return body
    pat = re.compile(
        rf"\b{re.escape(dut_name)}\s+\w+\s*\(([^;]*?)\)\s*;" if dut_name
        else r"\b\w+\s+dut\s*\(([^;]*?)\)\s*;",
        re.S,
    )
    m = pat.search(body)
    if not m or "." not in m.group(1):
        return body
    conns = re.findall(r"\.\w+\s*\([^()]*\)", m.group(1))
    kept = [c for c in conns if re.match(r"\.(\w+)", c).group(1) in known]
    if len(kept) == len(conns) or not kept:
        return body
    new_list = ",\n    ".join(kept)
    inner_start = m.start(1)
    return body[:inner_start] + "\n    " + new_list + "\n  " + body[m.end(1):]


def add_missing_dut_pins(body: str, port_specs: Optional[Sequence[dict]]) -> str:
    """Append `.pin(pin)` for DUT ports absent from the port map.

    Unconnected inputs read as 0 in 2-state sims, silently breaking protocol
    TBs (e.g. AXI WSTRB=0 masks every write). Signals are declared by the
    later undeclared-port repair; inputs still need TB stimulus to be useful,
    but a visible connection beats a silently tied-off pin.
    """
    known = [
        (p.get("name") or "").strip() for p in (port_specs or []) if p.get("name")
    ]
    if not known:
        return body
    m = re.search(r"\b\w+\s+dut\s*\(([^;]*?)(\)\s*;)", body, re.S)
    if not m or "." not in m.group(1):
        return body
    present = set(re.findall(r"\.(\w+)\s*\(", m.group(1)))
    missing = [p for p in known if p not in present]
    if not missing:
        return body
    inner = m.group(1).rstrip()
    if inner.endswith(","):
        inner = inner[:-1]
    add = ", ".join(f".{p}({p})" for p in missing)
    return body[: m.start(1)] + inner + ",\n    " + add + "\n  " + body[m.start(2):]


def connect_open_dut_ports(body: str, port_specs: Optional[Sequence[dict]]) -> str:
    """`.port()` in the DUT instantiation → `.port(port)`, and `dut.port` → `port`.

    LLMs sometimes leave DUT outputs unconnected and peek them hierarchically,
    which many simulators reject from a TB. Wire them to same-named signals.
    """
    known = {(p.get("name") or "").strip() for p in (port_specs or []) if p.get("name")}
    if not known:
        return body
    fixed = []

    def _conn(m: re.Match) -> str:
        name = m.group(1)
        if name in known:
            fixed.append(name)
            return f".{name}({name})"
        return m.group(0)

    body = re.sub(r"\.(\w+)\s*\(\s*\)", _conn, body)
    # Only rewrite hierarchical peeks through the DUT instance itself
    inst_names = set(re.findall(r"^\s*\w+\s+(\w+)\s*\(\s*$|^\s*\w+\s+(\w+)\s*\(\s*\.", body, re.M))
    insts = {n for tup in inst_names for n in tup if n} | {"dut"}
    for name in known:
        for inst in insts:
            body = re.sub(
                rf"\b{re.escape(inst)}\s*\.\s*({re.escape(name)})\b", r"\1", body
            )
    return body


def _decl_line_for_port(
    name: str,
    dut_outputs: Optional[Sequence[str]],
    port_specs: Optional[Sequence[dict]] = None,
) -> str:
    w = _width_for(name, port_specs)
    if w:
        return f"  logic {w} {name};"
    return f"  logic {name};"


def _task_or_function_ender_mismatch(body: str) -> bool:
    """True if a task is closed with endfunction (or function with endtask)."""
    for kind, wrong in (("task", "endfunction"), ("function", "endtask")):
        for m in re.finditer(rf"\b{kind}\b", body, re.I):
            window = body[m.start() : m.start() + 1500]
            end = re.search(r"\b(endtask|endfunction)\b", window, re.I)
            if end and end.group(1).lower() == wrong:
                return True
    return False


def _layered_syntax_broken(body: str) -> bool:
    """True when layered TB has compile-breaking structure the LLM often emits."""
    if _task_or_function_ender_mismatch(body):
        return True
    if re.search(r"^\s*\w+_test\s+\w+\s*\(\s*\w+\s*\)\s*;", body, re.M):
        return True
    if re.search(r"\w+\s*=\s*\w+\s*=\s*\w+\s*=\s*new\s*\(\s*\)\s*;", body):
        return True
    # C-style function body: function … (args) { … }
    if re.search(r"function\s+(?:void\s+)?\w+\s*\([^;]*\)\s*\{", body, re.I):
        return True
    if re.search(r"\bsb\.connect\s*\(", body, re.I) and not re.search(
        r"function\s+void\s+connect\s*\(", body, re.I
    ):
        return True
    return False


def repair_layered_sv_syntax(body: str) -> str:
    """Fix common LLM mangling of layered Pure SV (IF/gen/drv/mon/sb/env/test)."""
    if not body or not re.search(r"\binterface\b", body, re.I):
        return body

    # task … endfunction → endtask (and function … endtask → endfunction)
    def _fix_task_endfunction(m: re.Match) -> str:
        return m.group(1) + "endtask"

    body = re.sub(
        r"(task\b[\s\S]*?)\bendfunction\b", _fix_task_endfunction, body, flags=re.I
    )
    body = re.sub(
        r"(function\b(?!\s+void\s+connect)[\s\S]*?)\bendtask\b",
        lambda m: m.group(1) + "endfunction",
        body,
        flags=re.I,
    )

    # C-style braces on function/task → SV begin/end style
    body = re.sub(
        r"function\s+(new)\s*\(([^)]*)\)\s*\{([\s\S]*?)\}",
        r"function \1(\2);\n\3\nendfunction",
        body,
        flags=re.I,
    )
    body = re.sub(
        r"function\s+void\s+(\w+)\s*\(([^)]*)\)\s*\{([\s\S]*?)\}",
        r"function void \1(\2);\n\3\nendfunction",
        body,
        flags=re.I,
    )

    # Shared mailbox new(): a=b=c=new() → three independent mailboxes
    body = re.sub(
        r"(\w+)\s*=\s*(\w+)\s*=\s*(\w+)\s*=\s*new\s*\(\s*\)\s*;",
        r"\1 = new(); \2 = new(); \3 = new();",
        body,
    )

    # mailbox #(txn) gen2drv, drv2sb, mon2sb → typed separate decls
    def _split_mboxes(m: re.Match) -> str:
        txn = m.group(1)
        a, b, c = m.group(2), m.group(3), m.group(4)
        mon_t = re.sub(r"_txn$", "_mon_pkt", txn)
        if c.lower() == "mon2sb" or "mon" in c.lower():
            return (
                f"mailbox #({txn}) {a};\n"
                f"  mailbox #({txn}) {b};\n"
                f"  mailbox #({mon_t}) {c};"
            )
        return (
            f"mailbox #({txn}) {a};\n"
            f"  mailbox #({txn}) {b};\n"
            f"  mailbox #({txn}) {c};"
        )

    body = re.sub(
        r"mailbox\s*#\s*\(\s*(\w+)\s*\)\s*(\w+)\s*,\s*(\w+)\s*,\s*(\w+)\s*;",
        _split_mboxes,
        body,
        flags=re.I,
    )

    # Inject missing scoreboard.connect
    if re.search(r"\bsb\.connect\s*\(", body, re.I) and not re.search(
        r"function\s+void\s+connect\s*\(", body, re.I
    ):
        m_sb = re.search(
            r"(class\s+\w*scoreboard\w*\s*;[\s\S]*?)(\bendclass\b)", body, re.I
        )
        if m_sb:
            inject = (
                "\n  function void connect(mailbox #(counter_rtl_txn) d2s, "
                "mailbox #(counter_rtl_mon_pkt) m2s);\n"
                "    drv2sb = d2s; mon2sb = m2s;\n"
                "  endfunction\n"
            )
            # Prefer DUT-agnostic types from existing mailbox decls in the class
            mboxes = re.findall(
                r"mailbox\s*#\s*\(\s*(\w+)\s*\)\s*(\w+)\s*;", m_sb.group(1), re.I
            )
            if len(mboxes) >= 2:
                t0, n0 = mboxes[0]
                t1, n1 = mboxes[1]
                inject = (
                    f"\n  function void connect(mailbox #({t0}) d2s, "
                    f"mailbox #({t1}) m2s);\n"
                    f"    {n0} = d2s; {n1} = m2s;\n"
                    "  endfunction\n"
                )
            body = body[: m_sb.start(2)] + inject + body[m_sb.start(2) :]

    # Class instantiated like a module: counter_rtl_test t(vif);
    body = re.sub(
        r"^(\s*)(\w+_test)\s+(\w+)\s*\(\s*(\w+)\s*\)\s*;",
        r"\1\2 \3;",
        body,
        flags=re.M,
    )

    # Covergroup / module refs to bare enable/count when vif exists
    if re.search(r"\b\w+_if\s+vif\b", body):
        body = re.sub(
            r"(coverpoint\s+)(enable|count|rst_n)\b",
            r"\1vif.\2",
            body,
        )
        # Drop illegal module-scope checks using undeclared count/errors
        body = re.sub(
            r"^\s*if\s*\(\s*count\s*!==\s*'0\s*\)\s*errors\+\+\s*;\s*$",
            "",
            body,
            flags=re.M,
        )

    # Prefer always #5 clk=~clk over initial forever #5
    if not re.search(r"always\s+#\s*\d+\s+\w+\s*=\s*~\s*\w+", body, re.I):
        body = re.sub(
            r"initial\s+forever\s+#\s*(\d+)\s+(\w+)\s*=\s*~\s*\2\s*;",
            r"always #\1 \2 = ~\2;",
            body,
            flags=re.I,
        )

    return body


def _skeleton_layered_fallback(
    *,
    dut_name: Optional[str],
    port_specs: Optional[Sequence[dict]],
    clk_name: str = "clk",
) -> str:
    """Deterministic layered TB when LLM output is structurally unrecoverable."""
    if not dut_name or not port_specs:
        return ""
    try:
        from tb_skeleton import render_class_sv_tb

        mod = {"name": dut_name, "ports": list(port_specs)}
        return render_class_sv_tb(mod, cycles=32, seed=1)
    except Exception:
        return ""


def repair_class_sv_tb(
    sv: str,
    *,
    clk_name: str = "clk",
    required_ports: Optional[Sequence[str]] = None,
    dut_outputs: Optional[Sequence[str]] = None,
    port_specs: Optional[Sequence[dict]] = None,
    dut_name: Optional[str] = None,
    protocol: str = "generic",
) -> str:
    """Apply mechanical fixes for common class-SV mistakes. Keeps LLM structure."""
    body = extract_sv(sv) or sv
    if not body:
        return sv

    body = repair_layered_sv_syntax(body)
    if _layered_syntax_broken(body):
        skel = _skeleton_layered_fallback(
            dut_name=dut_name, port_specs=port_specs, clk_name=clk_name
        )
        if skel:
            return skel

    # Noop mux scoreboard (`check(); return 1`) → layered skeleton with real select golden
    if port_specs and re.search(
        r"function\s+bit\s+check\s*\(\s*\)\s*;\s*return\s+1\s*;", body, re.I
    ):
        try:
            from tb_skeleton import classify_ports, detect_mux_model

            if detect_mux_model(classify_ports(list(port_specs))):
                skel = _skeleton_layered_fallback(
                    dut_name=dut_name, port_specs=port_specs, clk_name=clk_name
                )
                if skel:
                    return skel
        except Exception:
            pass

    body = re.sub(r"\btask\s+(check)\s*\(", r"function bit \1(", body, flags=re.I)
    m = re.search(r"function\s+bit\s+check\b[\s\S]*?\bendtask\b", body, re.I)
    if m:
        chunk = re.sub(r"\bendtask\b", "endfunction", m.group(0), count=1, flags=re.I)
        body = body[: m.start()] + chunk + body[m.end() :]

    # Hoist module params referenced by file-scope classes to $unit localparams
    gaps = class_scope_param_gaps(body)
    if gaps:
        decls = "\n".join(f"localparam int {n} = {v};" for n, v in gaps)
        body = re.sub(
            r"(?m)^([ \t]*class\s+\w+)", decls + "\n\n" + r"\1", body, count=1
        )

    body = re.sub(r"\b(expected)\s*<=\s*", r"\1 = ", body)
    body = re.sub(r"\bwire\s+(enable)\s*;", r"logic \1;", body, flags=re.I)
    body = re.sub(r"\breg\s+count\s*;", "logic [3:0] count;", body)

    # Detect the TB's real clock (aclk/pclk/...) so later fixes use it
    m_clk = re.search(r"always\s*#\s*\d+\s+(\w+)\s*=\s*[~!]\s*\1", body)
    if m_clk:
        clk_name = m_clk.group(1)

    # Fix a renamed DUT module in the instantiation (LLMs invent names like
    # `enable_counter` for `counter_en`); we know the real module name.
    if dut_name:
        m_inst = re.search(r"^([ \t]*)(\w+)(\s+\w+\s*\(\s*\.)", body, re.M)
        if m_inst and m_inst.group(2) != dut_name and not re.search(
            rf"\b(?:module|class)\s+{re.escape(m_inst.group(2))}\b", body
        ):
            body = body[: m_inst.start(2)] + dut_name + body[m_inst.end(2):]

    body = hoist_initial_decls(body)
    body = drop_unknown_dut_pins(body, port_specs, dut_name)
    body = add_missing_dut_pins(body, port_specs)
    body = connect_open_dut_ports(body, port_specs)
    body = qualify_class_members(body)

    # Fix bare `logic <wide_port>;` using parsed DUT widths
    for name, sp in _port_spec_map(port_specs).items():
        w = (sp.get("width") or "").strip()
        pname = sp.get("name") or name
        if not w:
            continue
        body = re.sub(
            rf"\blogic\s+{re.escape(pname)}\s*;",
            f"logic {w} {pname};",
            body,
            count=1,
            flags=re.I,
        )

    if re.search(r"constraint\s+\w+\s*\{\s*1\s*;\s*\}", body, re.I) or re.search(
        r"constraint\s+\w+\s*\{\s*\}", body, re.I
    ):
        rands = re.findall(
            r"\brand\s+(?:bit|logic|reg)?\s*(?:\[[^\]]+\]\s*)?(\w+)\s*;",
            body,
            re.I,
        )
        field = rands[0] if rands else "enable"
        body = re.sub(
            r"constraint\s+(\w+)\s*\{\s*(?:1\s*;)?\s*\}",
            rf"constraint \1 {{ {field} inside {{[0:1]}}; }}",
            body,
            count=1,
            flags=re.I,
        )

    missing = undeclared_tb_ports(body, required_ports)
    if missing:
        lines = "\n".join(
            _decl_line_for_port(p, dut_outputs, port_specs) for p in missing
        )
        inserted = False
        region = _strip_classes(body)
        decl_matches = list(
            re.finditer(
                r"^[ \t]*(?:logic|reg|wire|bit)\b[^;]*;",
                region,
                re.I | re.M,
            )
        )
        if decl_matches:
            frag = decl_matches[-1].group(0)
            pos = body.find(frag)
            if pos >= 0:
                at = pos + len(frag)
                body = body[:at] + "\n" + lines + body[at:]
                inserted = True
        if not inserted:
            body = re.sub(
                r"(\bmodule\s+\w+\s*;)",
                rf"\1\n{lines}",
                body,
                count=1,
                flags=re.I,
            )

    if not _GOOD_CLOCK.search(body) and re.search(rf"\b{re.escape(clk_name)}\b", body):
        insert_at = None
        for m in re.finditer(r"\bdut\s*\([\s\S]*?\)\s*;", body, re.I):
            insert_at = m.end()
        if insert_at is None:
            m_mod = re.search(r"\bmodule\s+\w+\s*;", body, re.I)
            insert_at = m_mod.end() if m_mod else 0
        body = body[:insert_at] + f"\n\n  always #5 {clk_name} = ~{clk_name};\n" + body[insert_at:]

    if re.search(r"\brandomize\s*\(", body) and not re.search(r"\bnew\s*\(", body):
        body = re.sub(
            r"(\b(?:void'\(|assert\()?txn\.randomize)",
            r"txn = new(); if (sb == null) sb = new();\n      \1",
            body,
            count=1,
        )

    # `sb.errors++` → module-level `errors++` (scoreboard has no errors member)
    if re.search(r"\b\w+\.errors\s*(?:\+\+|=\s*\w+\.errors\s*\+\s*1)", body):
        sb_declares_errors = any(
            re.search(r"\b(?:int|integer|logic|reg)\b[^;\n]*\berrors\b", blk, re.I)
            for blk in _SCOREBOARD_CLASS.findall(body)
        )
        if not sb_declares_errors:
            body = re.sub(r"\b\w+\.errors\s*\+\+", "errors++", body)
            body = re.sub(
                r"\b\w+\.errors\s*=\s*\w+\.errors\s*\+\s*1",
                "errors = errors + 1",
                body,
            )

    if re.search(r"\berrors\b", body) and not re.search(
        r"\b(?:int|integer|logic|reg)\b[^;\n]*\berrors\b", body, re.I
    ):
        body = re.sub(
            r"(\bmodule\s+\w+\s*;)",
            r"\1\n  integer errors;",
            body,
            count=1,
            flags=re.I,
        )

    if re.search(r"\berrors\b", body) and not re.search(r"\berrors\s*=\s*0\b", body):
        body = re.sub(
            r"(initial\s+begin)",
            r"\1\n    errors = 0;",
            body,
            count=1,
            flags=re.I,
        )

    body = inject_scoreboard_expected(body, port_specs)
    body = strip_combo_invented_reset(body, port_specs, required_ports)
    body = strip_fifo_x_post_reset_rd_data(body)
    body = inject_fifo_size_clamps(body)

    body = re.sub(
        r"(rst_n\s*=\s*(?:1'b1|1)\s*;\s*\n)(\s*for\s*\()",
        rf"\1    @(posedge {clk_name});\n\2",
        body,
        count=1,
        flags=re.I,
    )

    # Ensure AXI WSTRB is driven all-ones when writes are present
    if re.search(r"\bwvalid\s*<?=\s*1", body, re.I) and re.search(r"\bwstrb\b", body, re.I):
        if not re.search(r"\bwstrb\s*<?=\s*(?:4'h[fF]|4'b1111|'1)", body, re.I):
            body = re.sub(
                r"(wvalid\s*=\s*1'b1\s*;)",
                r"s_axi_wstrb = 4'hF; \1" if "s_axi_wstrb" in body else r"wstrb = 4'hF; \1",
                body,
                count=1,
                flags=re.I,
            )

    # Fix inverted / stuck active-low reset before post-reset checks
    body = fix_active_low_reset(body, clk_name=clk_name)

    # Post-reset output-value check (kills drop_reset mutants)
    body = insert_post_reset_checks(body, dut_outputs, clk_name=clk_name)

    # Insert functional coverage (ifndef VERILATOR guarded) when ports are known
    if port_specs:
        try:
            from tb_coverage import insert_covergroup

            body = insert_covergroup(
                body, dut_name or "dut", port_specs, clk=clk_name
            )
        except Exception:
            pass

    body = repair_soft_tb_gaps(body)
    body = sanitize_class_sv_tb(
        body,
        dut_outputs=dut_outputs,
        protocol=protocol,
        port_specs=port_specs,
        required_ports=required_ports,
    )
    return body


def _active_low_reset_stuck(body: str, rst: str = "rst_n") -> bool:
    """True if last rst assignment before the stimulus for-loop holds reset."""
    m = re.search(r"initial\s+begin([\s\S]*?)(\n\s*for\s*\()", body, re.I)
    if not m:
        return False
    prefix = m.group(1)
    assigns = list(re.finditer(rf"\b{re.escape(rst)}\s*=\s*(1'b[01]|[01])\s*;", prefix, re.I))
    if not assigns:
        return False
    val = assigns[-1].group(1).lower()
    return val in ("0", "1'b0")


def fix_active_low_reset(body: str, *, clk_name: str = "clk", rst: str = "rst_n") -> str:
    """Rewrite inverted active-low reset (assert after idle; never release).

    Common LLM bug seen on counter TBs:
      rst_n=1; repeat..; rst_n=0;  // stuck in reset through stimulus
    Canonical:
      rst_n=0; repeat..; rst_n=1; @(posedge clk);
    """
    if not re.search(rf"\b{re.escape(rst)}\b", body, re.I):
        return body

    # Specific inverted pattern (init high → pulse low, no release).
    # Allow same-line companions like `clk=0; rst_n=1; enable=0;`.
    inverted = re.compile(
        rf"({re.escape(rst)}\s*=\s*(?:1'b1|1)\s*;)"
        rf"([\s\S]{{0,160}}?)"
        rf"(repeat\s*\(\s*\d+\s*\)\s*@\s*\(\s*posedge\s+\w+\s*\)\s*;\s*)"
        rf"{re.escape(rst)}\s*=\s*(?:1'b0|0)\s*;"
        rf"(\s*@\s*\(\s*posedge\s+\w+\s*\)\s*;)?",
        re.I,
    )

    def _flip(m: re.Match) -> str:
        settle = m.group(4) or f"\n    @(posedge {clk_name});"
        mid = m.group(2) or ""
        return f"{rst} = 0;{mid}{m.group(3)}{rst} = 1;{settle}"

    new_body, n = inverted.subn(_flip, body, count=1)
    if n:
        body = new_body

    # Generic: last rst assign before for-loop still holds reset → release
    if _active_low_reset_stuck(body, rst=rst):
        m = re.search(r"(initial\s+begin[\s\S]*?)(\n\s*for\s*\()", body, re.I)
        if m:
            insert = f"\n    {rst} = 1;\n    @(posedge {clk_name});"
            body = body[: m.start(2)] + insert + body[m.start(2) :]
    return body


def inject_scoreboard_expected(
    body: str, port_specs: Optional[Sequence[dict]] = None
) -> str:
    """Declare `expected` inside scoreboard when predict/check assigns it undeclared."""

    def _fix(m: re.Match) -> str:
        blk = m.group(0)
        if not re.search(r"(?<![\w.])expected\s*=", blk):
            return blk
        if re.search(r"\b(?:logic|bit|reg|int|integer)\b[^;\n]*\bexpected\b", blk, re.I):
            return blk
        w = (
            _width_for("y", port_specs)
            or _width_for("rd_data", port_specs)
            or _width_for("count", port_specs)
            or "[7:0]"
        )
        decl = f"  logic {w} expected;\n" if w else "  logic expected;\n"
        # After class header / utils; prefer before first function
        fm = re.search(r"\n(\s*)(?:function|task)\b", blk)
        if fm:
            return blk[: fm.start()] + "\n" + decl + blk[fm.start() + 1 :]
        return re.sub(r"(class\s+\w+\s*;\s*\n)", r"\1" + decl, blk, count=1, flags=re.I)

    return _SCOREBOARD_CLASS.sub(_fix, body)


def strip_combo_invented_reset(
    body: str,
    port_specs: Optional[Sequence[dict]],
    required_ports: Optional[Sequence[str]],
) -> str:
    """Remove rst_n assert/deassert when DUT has no reset port (combo mux etc.)."""
    known = _known_port_names(port_specs, required_ports)
    # Unknown port list → do not strip (avoid breaking counters when specs omitted)
    if not known or (known & _RST_PORT_NAMES):
        return body
    if not re.search(r"\brst_n\s*=", body, re.I):
        return body
    # Drop reset-only statements; keep clocked stimulus (premium mux still clocks)
    body = re.sub(
        r"[ \t]*rst_n\s*=\s*(?:1'b[01]|[01])\s*;\s*\n?",
        "",
        body,
        flags=re.I,
    )
    body = re.sub(
        r"[ \t]*repeat\s*\(\s*\d+\s*\)\s*@\s*\(\s*posedge\s+\w+\s*\)\s*;\s*\n?"
        r"[ \t]*(?:rst_n\s*=\s*(?:1'b1|1)\s*;\s*)?@\s*\(\s*posedge\s+\w+\s*\)\s*;\s*\n?",
        "",
        body,
        count=1,
        flags=re.I,
    )
    # Drop invented post-reset '0 checks (combo DUT has no reset)
    body = re.sub(
        r"[ \t]*if\s*\(\s*\w+\s*!==\s*'0\s*\)\s*(?:begin\s*)?errors\s*\+\+\s*;?(?:\s*end)?\s*\n?",
        "",
        body,
        count=1,
        flags=re.I,
    )
    return body


def strip_fifo_x_post_reset_rd_data(body: str) -> str:
    """Fix FIFO post-reset: rd_data may be X; empty is 1 (not '0)."""
    if not re.search(r"\bq\s*\[\s*\$\s*\]", body) and not re.search(
        r"\bwr_en\b.*\brd_en\b", body, re.I | re.S
    ):
        return body
    # `if (rd_data !== '0 || full !== 0 || ...)` → drop the rd_data term
    body = re.sub(
        r"\brd_data\s*!==\s*(?:'0|1'b0|\d+'h0+|0)\s*\|\|\s*",
        "",
        body,
        count=2,
        flags=re.I,
    )
    body = re.sub(
        r"\|\|\s*rd_data\s*!==\s*(?:'0|1'b0|\d+'h0+|0)",
        "",
        body,
        count=2,
        flags=re.I,
    )
    # Standalone `if (rd_data !== '0) errors++;` after reset
    body = re.sub(
        r"[ \t]*if\s*\(\s*rd_data\s*!==\s*(?:'0|1'b0|\d+'h0+|0)\s*\)\s*"
        r"(?:begin\s*)?errors\s*(?:\+\+|= errors \+ 1)\s*;?(?:\s*end)?\s*\n?",
        "",
        body,
        count=2,
        flags=re.I,
    )
    # Mechanical insert sometimes adds `if (empty !== '0)` — empty should be 1
    body = re.sub(
        r"[ \t]*if\s*\(\s*empty\s*!==\s*'0\s*\)\s*errors\s*\+\+\s*;\s*\n?",
        "    if (empty !== 1) errors++;\n",
        body,
        count=1,
        flags=re.I,
    )
    return body


_MID_RESET_MARK = "ChipSutra mid-test reset"


def inject_mid_test_reset(
    body: str,
    dut_outputs: Optional[Sequence[str]] = None,
    *,
    protocol: str = "generic",
) -> str:
    """Pulse reset after stimulus so drop_reset mutants fail under Verilator init-0."""
    if not body or _MID_RESET_MARK in body:
        return body
    proto = (protocol or "generic").lower()
    if proto in ("mux", "combo"):
        return body
    if not re.search(
        r"\.(?:rst_n|rst|aresetn|PRESETn|HRESETn|presetn)\s*\(", body, re.I
    ):
        return body
    rst = None
    deassert, assert_r = "1'b1", "1'b0"
    for cand, de, ast in (
        ("rst_n", "1'b1", "1'b0"),
        ("aresetn", "1'b1", "1'b0"),
        ("PRESETn", "1'b1", "1'b0"),
        ("presetn", "1'b1", "1'b0"),
        ("HRESETn", "1'b1", "1'b0"),
    ):
        if re.search(rf"\b{cand}\b", body):
            rst, deassert, assert_r = cand, de, ast
            break
    if not rst:
        return body
    m_clk = re.search(r"always\s*#\s*\d+\s+(\w+)\s*=\s*[~!]\s*\1", body)
    clk = m_clk.group(1) if m_clk else "clk"

    quiet = []
    for sig in (
        "enable",
        "valid",
        "wr_en",
        "rd_en",
        "PSEL",
        "psel",
        "PENABLE",
        "penable",
        "s_axi_awvalid",
        "s_axi_wvalid",
        "s_axi_arvalid",
    ):
        if re.search(rf"\b{sig}\b", body):
            quiet.append(f"    {sig} = 1'b0;")
    quiet_txt = ("\n".join(quiet) + "\n") if quiet else ""

    checks: List[str] = []
    skip = {s.lower() for s in _POST_RESET_SKIP_OUTS}
    proto_l = proto
    if proto_l == "fifo" or re.search(r"\bempty\b", body):
        if re.search(r"\bempty\b", body):
            checks.append("    if (empty !== 1) errors++;")
        if re.search(r"\bfull\b", body):
            checks.append("    if (full !== 0 && full !== 1'b0) errors++;")
        if re.search(r"\bcount\b", body) and proto_l in ("fifo", "generic", "counter"):
            if proto_l == "fifo" or re.search(r"\bwr_en\b", body):
                checks.append("    if (count !== 0 && count !== '0) errors++;")
    if proto_l in ("parity", "counter", "generic", "fifo"):
        for o in dut_outputs or []:
            if not o or o.lower() in skip:
                continue
            if o.lower() in ("empty", "full", "count") and proto_l == "fifo":
                continue
            checks.append(f"    if ({o} !== '0) errors++;")
    if proto_l == "counter" and not checks:
        checks.append("    if (count !== '0) errors++;")
    if proto_l == "parity" and not checks:
        checks.append("    if (parity !== '0) errors++;")
        if re.search(r"\bvalid_out\b", body):
            checks.append("    if (valid_out !== '0) errors++;")
    if not checks:
        return body
    check_txt = "\n".join(checks)
    block = (
        f"\n    // {_MID_RESET_MARK} (kills drop_reset under Verilator init-0)\n"
        f"{quiet_txt}"
        f"    {rst} = {assert_r};\n"
        f"    repeat (4) @(posedge {clk});\n"
        f"    {rst} = {deassert};\n"
        f"    @(posedge {clk});\n"
        f"{check_txt}\n"
    )
    m = re.search(r"[ \t]*if\s*\(\s*errors\s*==\s*0\s*\)", body)
    if not m:
        m = re.search(r"[ \t]*\$display\s*\(\s*\"PASS", body)
    if not m:
        return body
    return body[: m.start()] + block + body[m.start() :]


def sanitize_class_sv_tb(
    sv: str,
    *,
    dut_outputs: Optional[Sequence[str]] = None,
    protocol: str = "generic",
    port_specs: Optional[Sequence[dict]] = None,
    required_ports: Optional[Sequence[str]] = None,
) -> str:
    """Always-on mechanical sanitizers even when lint already reports ok."""
    body = extract_sv(sv) or sv
    if not body:
        return sv
    body = strip_combo_invented_reset(body, port_specs, required_ports)
    body = strip_fifo_x_post_reset_rd_data(body)
    body = inject_fifo_size_clamps(body)
    proto = (protocol or "generic").lower()
    if proto in ("counter", "parity", "fifo", "generic"):
        body = inject_mid_test_reset(body, dut_outputs, protocol=proto)
    return body


def inject_fifo_size_clamps(body: str) -> str:
    """After randomize, clamp wr/rd against scoreboard queue occupancy."""
    if not re.search(r"\bq\s*\[\s*\$\s*\]", body) or not re.search(r"\bwr_en\b", body):
        return body
    has_wr_clamp = bool(
        re.search(
            r"q\.size\s*\(\s*\)\s*>=\s*[^;]{0,40}?wr_en\s*=\s*(?:1'b0|0)",
            body,
            re.I | re.S,
        )
    )
    has_rd_clamp = bool(
        re.search(
            r"q\.size\s*\(\s*\)\s*==\s*0[\s\S]{0,60}?rd_en\s*=\s*(?:1'b0|0)",
            body,
            re.I,
        )
    )
    if has_wr_clamp and has_rd_clamp:
        return body
    if not re.search(r"txn\.randomize\s*\(", body, re.I):
        return body
    clamp = (
        "\n      if (sb.q.size() >= 8) txn.wr_en = 0;"
        "\n      if (sb.q.size() == 0) txn.rd_en = 0;"
    )
    return re.sub(
        r"(assert\s*\(\s*txn\.randomize\s*\(\s*\)\s*\)[^;]*;)",
        r"\1" + clamp,
        body,
        count=1,
        flags=re.I,
    )


def insert_post_reset_checks(
    body: str,
    dut_outputs: Optional[Sequence[str]],
    *,
    clk_name: str = "clk",
) -> str:
    """After reset deassert + settle, check key outputs are at reset value."""
    # Combo / no-reset DUT: never invent post-reset checks
    if not re.search(r"\.(?:rst_n|rst|aresetn|PRESETn|HRESETn)\s*\(", body, re.I):
        return body
    outs = [
        o
        for o in (dut_outputs or [])
        if o
        and o.lower()
        not in {
            "clk",
            "clock",
            "aclk",
            "pclk",
            "sclk",
            "hclk",
            "ready",
            "pready",
            "hready",
            "hreadyout",
            "tready",
            "awready",
            "wready",
            "arready",
            "s_axi_awready",
            "s_axi_wready",
            "s_axi_arready",
            "s_axi_bready",
            "s_axi_rready",
            "miso",
            "sda_out",
            "tx",
        }
        and o.lower() not in _POST_RESET_SKIP_OUTS
    ]
    if not outs or not re.search(r"\berrors\b", body):
        return body
    # Only skip when check follows a real deassert (after assert), not init-high alone
    if re.search(
        r"(?:rst_n|aresetn|PRESETn|HRESETn)\s*=\s*(?:1'b0|0)\s*;"
        r"[\s\S]{0,300}?"
        r"(?:rst_n|aresetn|PRESETn|HRESETn)\s*=\s*(?:1'b1|1)\s*;"
        r"[\s\S]{0,300}?!==\s*'0",
        body,
        re.I,
    ):
        return body
    checks = "\n".join(f"    if ({o} !== '0) errors++;" for o in outs[:4])
    # Prefer insert after reset deassert + optional settle
    # Match the last deassert before stimulus (not the erroneous init-high).
    pat = re.compile(
        r"((?:rst_n|aresetn|PRESETn|HRESETn)\s*=\s*(?:1'b1|1)\s*;"
        r"(?:\s*@\s*\(\s*posedge\s+\w+\s*\)\s*;)?)",
        re.I,
    )
    matches = list(pat.finditer(body))
    if not matches:
        return body
    m = matches[-1]
    return body[: m.end()] + "\n" + checks + body[m.end() :]


def score_class_sv_competitive(
    sv: str,
    *,
    required_ports: Optional[Sequence[str]] = None,
    dut_outputs: Optional[Sequence[str]] = None,
    protocol: str = "generic",
    port_specs: Optional[Sequence[dict]] = None,
) -> dict:
    """Rubric score 0–100 approximating premium-model first-pass quality."""
    ok, issues = lint_class_sv_tb(
        sv,
        required_ports=list(required_ports) if required_ports else None,
        dut_outputs=dut_outputs,
        protocol=protocol,
        port_specs=port_specs,
    )
    undecl = [i for i in issues if i.startswith("undeclared_signal:")]
    checks = {
        "has_class_txn": bool(re.search(r"\bclass\b[\s\S]*\brand\b", sv, re.I)),
        "has_interface": bool(re.search(r"\binterface\b", sv, re.I)),
        "has_generator": bool(
            re.search(r"\bclass\s+\w*(generator|gen)\b|_generator\b", sv, re.I)
        ),
        "has_driver": bool(re.search(r"\bclass\s+\w*driver\b|_driver\b", sv, re.I)),
        "has_monitor": bool(re.search(r"\bclass\s+\w*monitor\b|_monitor\b", sv, re.I)),
        "has_scoreboard": bool(re.search(r"scoreboard|expected", sv, re.I)),
        "has_env": bool(re.search(r"\bclass\s+\w*(env|environment)\b|_env\b", sv, re.I)),
        "has_test": bool(re.search(r"\bclass\s+\w*test\b|_test\b", sv, re.I)),
        "has_clock": bool(_GOOD_CLOCK.search(sv)),
        "has_posedge": bool(_HAS_POSEDGE.search(sv)),
        "has_dump": bool(_HAS_DUMP.search(sv)),
        "has_finish": bool(_HAS_FINISH.search(sv)),
        "has_new": bool(re.search(r"\bnew\s*\(", sv)),
        "no_task_return": "task_with_return" not in issues,
        "no_wire_drive": not any(i.startswith("wire_driven") for i in issues),
        "no_missing_clock": "bad_or_missing_clock" not in issues,
        "ports_declared": not undecl,
        "real_constraint": "noop_constraint" not in issues,
        "errors_initialized": "errors_not_initialized" not in issues
        and "undeclared_errors" not in issues
        and "sb_errors_not_member" not in issues
        and "undeclared_expected" not in issues,
        "complete_module": "incomplete_module" not in issues
        and bool(re.search(r"\bendmodule\b", sv, re.I)),
        "no_semantic_hard": not any(
            i in (
                "semantic_circular_out",
                "semantic_fifo_no_queue",
                "semantic_fifo_count_arith",
                "semantic_noop_check",
                "semantic_mux_no_select",
                "semantic_fifo_reset_rd_data",
                "incomplete_module",
            )
            for i in issues
        ),
        "widths_ok": not any(i.startswith("wrong_width:") for i in issues),
    }
    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    score = int(100 * passed / total) if total else 0
    return {
        "ok": ok,
        "score": score,
        "checks": checks,
        "issues": issues,
        "premium_bar": score >= 90 and ok,
    }
