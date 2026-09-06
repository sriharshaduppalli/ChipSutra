"""RAL / register-model emit from a *user-supplied* CSR map.

Never invent registers, offsets, reset values, or fields.
Pure SV model is Verilator-friendly. UVM RAL is for commercial simulators.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _ident(name: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_]", "_", (name or "").strip())
    if not s or s[0].isdigit():
        s = f"{fallback}_{s}" if s else fallback
    if not _ID_RE.match(s):
        s = fallback
    return s


def _int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, int):
        return val
    try:
        return int(str(val).strip(), 0)
    except ValueError:
        return default


def _hex(val: int, bits: int = 32) -> str:
    return f"{bits}'h{val:x}"


def normalize_csr_list(raw: Optional[List[dict]], *, limit: int = 32) -> List[Dict[str, Any]]:
    """Keep only user-named CSRs with parseable addresses."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, item in enumerate(raw or []):
        if not isinstance(item, dict):
            continue
        raw_name = str(item.get("name") or "").strip()
        if not raw_name:
            continue
        name = _ident(raw_name, f"REG{i}")
        if name in seen:
            continue
        addr = _int(item.get("addr") or item.get("address") or item.get("offset"), -1)
        if addr < 0:
            continue
        seen.add(name)
        width = max(1, min(64, _int(item.get("width") or item.get("n_bits"), 32)))
        access = str(item.get("access") or "rw").strip().upper()
        if access not in ("RW", "RO", "WO", "W1C", "RC"):
            access = "RW"
        fields = []
        for j, f in enumerate(item.get("fields") or []):
            if not isinstance(f, dict):
                continue
            fname = _ident(str(f.get("name") or ""), f"f{j}")
            fields.append(
                {
                    "name": fname,
                    "lsb": max(0, _int(f.get("lsb") or f.get("lsb_pos"), 0)),
                    "width": max(1, min(width, _int(f.get("width") or f.get("size"), 1))),
                    "access": str(f.get("access") or access).strip().upper(),
                    "reset": _int(f.get("reset"), 0),
                }
            )
        out.append(
            {
                "name": name,
                "addr": addr,
                "reset": _int(item.get("reset") or item.get("reset_val"), 0),
                "access": access,
                "width": width,
                "fields": fields,
            }
        )
        if len(out) >= limit:
            break
    return out


def csr_list_of(module: Optional[dict]) -> List[Dict[str, Any]]:
    if not module:
        return []
    cfg = module.get("_dv_knobs") or {}
    return normalize_csr_list(cfg.get("csr_list") if isinstance(cfg, dict) else None)


def wants_ral(module: Optional[dict]) -> bool:
    if not module:
        return False
    cfg = module.get("_dv_knobs") or {}
    if not isinstance(cfg, dict):
        return False
    if cfg.get("enable_ral") is False:
        return False
    return bool(csr_list_of(module)) and bool(cfg.get("enable_ral"))


def addr_inside_constraint(csrs: List[Dict[str, Any]], field: str = "addr") -> str:
    if not csrs:
        return f"soft {field} == 0;"
    lits = ", ".join(_hex(c["addr"]) for c in csrs)
    return f"{field} inside {{{lits}}};"


def render_sv_csr_sequences(dut_name: str, csrs: List[Dict[str, Any]], *, indent: str = "") -> str:
    """Named frontdoor walk from the user map only (no invented offsets)."""
    del dut_name  # walk lives on the named reg_model class
    lines = [
        f"{indent}// Frontdoor walk — caller drives the bus; model predicts from user CSR list.",
        f"{indent}task automatic frontdoor_walk();",
        f"{indent}  logic [31:0] exp;",
    ]
    for c in csrs:
        addr = _hex(c["addr"])
        w = c["width"]
        if c["access"] in ("RW", "WO"):
            poke = _hex((c["reset"] ^ 0x1) & ((1 << min(32, w)) - 1), 32)
            lines.append(f"{indent}  // {c['name']} @ {addr} {c['access']}")
            lines.append(f"{indent}  predict_write({addr}, {poke});")
            lines.append(f"{indent}  exp = expected_read({addr});")
            lines.append(f"{indent}  if (!check_read({addr}, exp)) errors++;")
        elif c["access"] == "W1C":
            lines.append(f"{indent}  // {c['name']} @ {addr} W1C — write-1-to-clear")
            lines.append(f"{indent}  predict_write({addr}, 32'h1);")
        else:
            lines.append(f"{indent}  // {c['name']} @ {addr} {c['access']} — read-only, no write")
            lines.append(f"{indent}  exp = expected_read({addr});")
            lines.append(f"{indent}  if (!check_read({addr}, exp)) errors++;")
    if not csrs:
        lines.append(f"{indent}  ; // no user CSRs")
    lines.append(f"{indent}endtask")
    return "\n".join(lines)


def render_uvm_frontdoor_seq(dut_name: str, csrs: List[Dict[str, Any]]) -> str:
    """uvm_sequence: frontdoor write/read each user CSR. Commercial UVM sim."""
    name = _ident(dut_name, "dut")
    seq = f"{name}_csr_seq"
    body: List[str] = []
    for c in csrs:
        w = min(32, c["width"])
        mask = (1 << w) - 1
        poke = (c["reset"] ^ 0x1) & mask
        poke_h = _hex(poke, 32)
        rst_h = _hex(c["reset"], 32)
        if c["access"] in ("RW",):
            body.append(
                f"    mdl.{c['name']}.write(st, {poke_h}, UVM_FRONTDOOR);\n"
                f"    if (st != UVM_IS_OK) `uvm_error(\"RAL\", \"{c['name']} write status\");\n"
                f"    mdl.{c['name']}.read(st, rdata, UVM_FRONTDOOR);\n"
                f"    if (rdata !== {poke_h})\n"
                f"      `uvm_error(\"RAL\", $sformatf(\"{c['name']} frontdoor got=0x%0h exp=0x%0h\", rdata, {poke_h}));"
            )
        elif c["access"] == "WO":
            body.append(
                f"    mdl.{c['name']}.write(st, {poke_h}, UVM_FRONTDOOR);\n"
                f"    if (st != UVM_IS_OK) `uvm_error(\"RAL\", \"{c['name']} write status\");"
            )
        elif c["access"] == "W1C":
            body.append(
                f"    mdl.{c['name']}.write(st, 32'h1, UVM_FRONTDOOR);\n"
                f"    mdl.{c['name']}.read(st, rdata, UVM_FRONTDOOR);"
            )
        else:
            body.append(
                f"    mdl.{c['name']}.read(st, rdata, UVM_FRONTDOOR);\n"
                f"    if (rdata !== {rst_h})\n"
                f"      `uvm_error(\"RAL\", $sformatf(\"{c['name']} RO frontdoor got=0x%0h exp=0x%0h\", rdata, {rst_h}));"
            )
    body_txt = "\n".join(body) or "    ;"
    return f"""class {seq} extends uvm_sequence;
  {name}_reg_block mdl;
  `uvm_object_utils({seq})
  function new(string name = "{seq}");
    super.new(name);
  endfunction
  virtual task body();
    uvm_status_e st;
    uvm_reg_data_t rdata;
    if (mdl == null) begin
      `uvm_error("RAL", "csr seq has no reg block — do not invent a map")
      return;
    end
{body_txt}
  endtask
endclass"""


def render_sv_reg_model(dut_name: str, csrs: List[Dict[str, Any]]) -> str:
    """Verilator-friendly named register model (not uvm_reg)."""
    name = _ident(dut_name, "dut")
    cls = f"{name}_reg_model"
    decls = []
    resets = []
    wr_arms = []
    rd_arms = []
    for c in csrs:
        w = c["width"]
        decls.append(f"  logic [{w - 1}:0] {c['name']}; // {_hex(c['addr'])} {c['access']}")
        resets.append(f"    {c['name']} = {_hex(c['reset'], w)};")
        if c["access"] in ("RW", "WO"):
            wr_arms.append(f"      {_hex(c['addr'])}: {c['name']} = data[{w - 1}:0];")
        elif c["access"] == "W1C":
            wr_arms.append(
                f"      {_hex(c['addr'])}: {c['name']} = {c['name']} & ~data[{w - 1}:0];"
            )
        else:
            wr_arms.append(f"      {_hex(c['addr'])}: ; // {c['access']} — ignore write")
        rd_arms.append(f"      {_hex(c['addr'])}: return {c['name']};")
    wr_body = "\n".join(wr_arms) or "      default: ;"
    rd_body = "\n".join(rd_arms) or "      default: return '0;"
    rst_body = "\n".join(resets) or "    ;"
    decl_body = "\n".join(decls) or "  // no user CSRs"
    return f"""// ChipSutra SV register model — user CSR map only (not UVM RAL)
class {cls};
{decl_body}
  int errors;
  function new();
{rst_body}
    errors = 0;
  endfunction
  function void predict_write(logic [31:0] addr, logic [31:0] data);
    case (addr)
{wr_body}
      default: ; // unmapped — do not invent a register
    endcase
  endfunction
  function logic [31:0] expected_read(logic [31:0] addr);
    case (addr)
{rd_body}
      default: return '0;
    endcase
  endfunction
  function bit check_read(logic [31:0] addr, logic [31:0] rdata);
    return (rdata === expected_read(addr));
  endfunction
  function logic [31:0] reset_of(logic [31:0] addr);
    case (addr)
{chr(10).join(f"      {_hex(c['addr'])}: return {_hex(c['reset'], c['width'])};" for c in csrs)}
      default: return '0;
    endcase
  endfunction
  function void hw_reset();
{rst_body}
  endfunction
{render_sv_csr_sequences(name, csrs, indent="  ")}
endclass
"""


def render_uvm_ral_block(dut_name: str, csrs: List[Dict[str, Any]], *, base: int = 0) -> str:
    """uvm_reg / uvm_reg_block from the user map. Commercial simulator."""
    name = _ident(dut_name, "dut")
    parts: List[str] = [
        "// ChipSutra UVM RAL — user CSR map only. Do not invent extra regs.",
        "// Full RAL often needs a UVM-capable simulator (not Verilator smoke).",
    ]
    for c in csrs:
        w = c["width"]
        rcls = f"{name}_{c['name']}_reg"
        field_decls = []
        field_build = []
        if c["fields"]:
            for f in c["fields"]:
                field_decls.append(f"  rand uvm_reg_field {f['name']};")
                acc = f["access"] if f["access"] in ("RW", "RO", "WO", "W1C", "RC") else "RW"
                field_build.append(
                    f"    {f['name']} = uvm_reg_field::type_id::create(\"{f['name']}\");\n"
                    f"    {f['name']}.configure(this, {f['width']}, {f['lsb']}, \"{acc}\", "
                    f"0, {_hex(f['reset'], f['width'])}, 1, 1, 1);"
                )
        else:
            field_decls.append("  rand uvm_reg_field value;")
            acc = c["access"] if c["access"] in ("RW", "RO", "WO", "W1C", "RC") else "RW"
            field_build.append(
                f"    value = uvm_reg_field::type_id::create(\"value\");\n"
                f"    value.configure(this, {w}, 0, \"{acc}\", 0, {_hex(c['reset'], w)}, 1, 1, 1);"
            )
        parts.append(
            f"""class {rcls} extends uvm_reg;
{chr(10).join(field_decls)}
  `uvm_object_utils({rcls})
  function new(string name = "{c['name']}");
    super.new(name, {w}, UVM_NO_COVERAGE);
  endfunction
  virtual function void build();
{chr(10).join(field_build)}
  endfunction
endclass"""
        )
    add_regs = []
    reg_decls = []
    builds = []
    for c in csrs:
        rcls = f"{name}_{c['name']}_reg"
        acc = c["access"] if c["access"] in ("RW", "RO", "WO", "W1C", "RC") else "RW"
        reg_decls.append(f"  rand {rcls} {c['name']};")
        builds.append(
            f"    {c['name']} = {rcls}::type_id::create(\"{c['name']}\");\n"
            f"    {c['name']}.configure(this, null, \"\");\n"
            f"    {c['name']}.build();\n"
            f"    default_map.add_reg({c['name']}, {_hex(c['addr'])}, \"{acc}\");"
        )
        add_regs.append(c["name"])
    parts.append(
        f"""class {name}_reg_block extends uvm_reg_block;
{chr(10).join(reg_decls)}
  `uvm_object_utils({name}_reg_block)
  function new(string name = "{name}_reg_block");
    super.new(name, UVM_NO_COVERAGE);
  endfunction
  virtual function void build();
    default_map = create_map("default_map", {_hex(base)}, 4, UVM_LITTLE_ENDIAN, 0);
{chr(10).join(builds)}
    lock_model();
  endfunction
endclass"""
    )
    parts.append(render_uvm_frontdoor_seq(name, csrs))
    return "\n\n".join(parts) + "\n"


def render_uvm_reg_adapter(dut_name: str, txn_class: str) -> str:
    """Compileable uvm_reg_adapter. Predictor is wired in the env connect_phase."""
    name = _ident(dut_name, "dut")
    txn = txn_class or f"{name}_txn"
    return f"""class {name}_reg_adapter extends uvm_reg_adapter;
  `uvm_object_utils({name}_reg_adapter)
  function new(string name = "{name}_reg_adapter");
    super.new(name);
    supports_byte_enable = 0;
    provides_responses = 1;
  endfunction
  virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
    {txn} t;
    t = {txn}::type_id::create("t");
    // Map rw.addr / rw.data / rw.kind onto DUT txn fields (sel/addr/data).
    return t;
  endfunction
  virtual function void bus2reg(uvm_sequence_item bus_item, ref uvm_reg_bus_op rw);
    {txn} t;
    if (!$cast(t, bus_item)) begin
      rw.status = UVM_NOT_OK;
      return;
    end
    rw.status = UVM_IS_OK;
  endfunction
endclass
"""


def ral_prompt_block(
    csrs: List[Dict[str, Any]],
    *,
    methodology: str = "sv",
    enable_ral: bool = False,
) -> str:
    if not enable_ral:
        if csrs:
            return (
                "CSR MAP PRESENT but RAL disabled — opaque model_reg keyed by user "
                "addresses only. Do not emit uvm_reg_*."
            )
        return ""
    if not csrs:
        return (
            "RAL requested but no user csr_list — skip RAL. Do not invent a register map."
        )
    lines = [
        "USER RAL / CSR MAP (emit only these registers — do not invent more):",
    ]
    for c in csrs:
        fld = ""
        if c["fields"]:
            fld = " fields=" + ",".join(
                f"{f['name']}[{f['lsb']}+{f['width']}]" for f in c["fields"]
            )
        lines.append(
            f"  {c['name']} @ {_hex(c['addr'])} {c['access']} reset={_hex(c['reset'], c['width'])}{fld}"
        )
    meth = (methodology or "sv").lower()
    if meth == "uvm":
        lines.append(
            "Emit uvm_reg + uvm_reg_block + adapter + predictor wired in env connect_phase. "
            "Emit a frontdoor write-then-read sequence for each user CSR (no invented offsets). "
            "Commercial UVM sim."
        )
    else:
        lines.append(
            "Pure SV: named reg_model class with predict_write/expected_read "
            "and frontdoor_walk() for the user CSR list. "
            "Not uvm_reg (Verilator path)."
        )
    return "\n".join(lines)
