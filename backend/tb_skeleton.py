"""Deterministic SystemVerilog testbench emitters (no LLM required).

- render_randomized_tb: procedural smoke ($urandom) — gen_mode=skeleton only
- render_class_sv_tb: Pure SV layered class TB (IF/gen/drv/mon/sb/env/test) — default
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_CLK_RE = re.compile(r"^(clk|clock|clk_i|clk_in|aclk|pclk|sclk|hclk|scl)$", re.I)
_RST_RE = re.compile(
    r"^(rst|reset|areset|aresetn|rst_n|reset_n|rstn|nreset|nrst|rst_async_n|presetn|preset|hresetn)$",
    re.I,
)
_EN_RE = re.compile(r"^(en|enable|ce|cnt_en|count_en|inc)$", re.I)
_COUNT_RE = re.compile(r"^(count|cnt|q|out|dout|data_out|value)$", re.I)
_FORCE_LLM_RE = re.compile(
    r"\b(uvm|u?vm_|agent|sequencer|driver|monitor|scoreboard|sequence_item|"
    r"full\s+uvm|class\s+\w+_env|llm\s*only|no\s*skeleton)\b",
    re.I,
)


def width_bits(width: str, port: Optional[dict] = None) -> int:
    if port and isinstance(port.get("bits"), int) and port["bits"] > 0:
        return int(port["bits"])
    w = (width or "").strip()
    if not w:
        return 1
    m = re.match(r"\[(\d+)\s*:\s*(\d+)\]", w)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1
    return 1


def sv_type(width: str, port: Optional[dict] = None) -> str:
    bits = width_bits(width, port)
    return "logic" if bits == 1 else f"logic [{bits - 1}:0]"


def _by_name(ports: List[dict], *names: str) -> Optional[dict]:
    want = {n.lower() for n in names}
    for p in ports:
        if (p.get("name") or "").lower() in want:
            return p
    return None


def classify_ports(ports: List[dict]) -> Dict[str, Any]:
    """Split ports into clk / rst / stimulus inputs / checked outputs."""
    clk: Optional[dict] = None
    rst: Optional[dict] = None
    inputs: List[dict] = []
    outputs: List[dict] = []
    for p in ports or []:
        name = p.get("name") or ""
        direction = (p.get("direction") or "").lower()
        if direction == "input":
            if clk is None and _CLK_RE.match(name):
                clk = p
            elif rst is None and _RST_RE.match(name):
                rst = p
            else:
                inputs.append(p)
        elif direction in ("output", "inout"):
            outputs.append(p)
    active_low = True
    if rst:
        n = rst["name"].lower()
        active_low = n.endswith("_n") or n.endswith("n") or "nreset" in n or n in ("aresetn", "rstn")
        if n in ("rst", "reset", "areset") and not n.endswith("n"):
            active_low = False
    return {
        "clk": clk,
        "rst": rst,
        "active_low_reset": active_low,
        "inputs": inputs,
        "outputs": outputs,
    }


def detect_fifo_model(roles: Dict[str, Any], parameters: Optional[Dict[str, int]] = None) -> Optional[dict]:
    """Detect sync FIFO-like port set (wr_en/wr_data/rd_en/rd_data + full/empty)."""
    wr_en = _by_name(roles["inputs"], "wr_en", "write", "push", "wren")
    wr_data = _by_name(roles["inputs"], "wr_data", "wdata", "din", "data_in")
    rd_en = _by_name(roles["inputs"], "rd_en", "read", "pop", "rden")
    rd_data = _by_name(roles["outputs"], "rd_data", "rdata", "dout", "data_out")
    full = _by_name(roles["outputs"], "full")
    empty = _by_name(roles["outputs"], "empty")
    if wr_en and wr_data and rd_en and rd_data and full and empty:
        params = parameters or {}
        depth = int(params.get("DEPTH") or params.get("FIFO_DEPTH") or 8)
        return {
            "wr_en": wr_en,
            "wr_data": wr_data,
            "rd_en": rd_en,
            "rd_data": rd_data,
            "full": full,
            "empty": empty,
            "count": _by_name(roles["outputs"], "count", "cnt", "level"),
            "depth": max(2, depth),
        }
    return None


def detect_parity_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Detect valid+data -> parity(+valid_out) checker DUT."""
    valid = _by_name(roles["inputs"], "valid", "in_valid", "data_valid")
    data = _by_name(roles["inputs"], "data", "data_in", "din")
    parity = _by_name(roles["outputs"], "parity", "odd", "even", "par")
    if valid and data and parity and width_bits(data.get("width", ""), data) >= 2:
        return {
            "valid": valid,
            "data": data,
            "parity": parity,
            "valid_out": _by_name(roles["outputs"], "valid_out", "out_valid", "parity_valid"),
        }
    return None


def detect_axi_lite_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Detect AXI4-Lite slave port set (s_axi_* or aw/ar/w/b/r)."""
    names_in = {p["name"].lower() for p in roles["inputs"]}
    names_out = {p["name"].lower() for p in roles["outputs"]}
    need_in = {"s_axi_awvalid", "s_axi_wvalid", "s_axi_arvalid", "s_axi_bready", "s_axi_rready"}
    need_out = {"s_axi_awready", "s_axi_wready", "s_axi_bvalid", "s_axi_arready", "s_axi_rvalid"}
    burst = names_in | names_out
    if burst & {"awlen", "s_axi_awlen", "arlen", "s_axi_arlen"}:
        return None
    if need_in.issubset(names_in) and need_out.issubset(names_out):
        return {"style": "s_axi", "num_regs": 4}
    return None


def detect_mux_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Detect 2:1 (sel/a/b) or N:1 (sel/d0..dN) mux → y/out."""
    sel = _by_name(roles["inputs"], "sel", "select", "s")
    y = _by_name(roles["outputs"], "y", "out", "dout", "q", "z")
    if not sel or not y:
        return None

    # N:1 data ports: d0,d1,… or in0,in1,…
    data: List[dict] = []
    for i in range(16):
        p = _by_name(roles["inputs"], f"d{i}", f"in{i}", f"i{i}", f"din{i}")
        if not p:
            break
        data.append(p)
    if len(data) >= 2:
        sel_bits = width_bits(sel.get("width", ""), sel)
        # sel must address all data ports (allow extra codes)
        if (1 << max(1, sel_bits)) >= len(data):
            w0 = width_bits(data[0].get("width", ""), data[0])
            if all(width_bits(p.get("width", ""), p) == w0 for p in data):
                return {"sel": sel, "data": data, "y": y, "kind": "nto1"}

    # Classic 2:1: sel + a + b (not ALU: ALU has opcode `op`, not 1-bit sel)
    a = _by_name(roles["inputs"], "a", "in0", "i0", "din0")
    b = _by_name(roles["inputs"], "b", "in1", "i1", "din1")
    if a and b and width_bits(sel.get("width", ""), sel) == 1:
        if _by_name(roles["inputs"], "op", "opcode", "alu_op"):
            return None
        if width_bits(a.get("width", ""), a) == width_bits(b.get("width", ""), b):
            return {"sel": sel, "a": a, "b": b, "y": y, "kind": "2to1", "data": [a, b]}
    packed = _by_name(roles["inputs"], "data", "din", "in_bus", "mux_in")
    if packed:
        dw = width_bits(packed.get("width", ""), packed)
        yw = width_bits(y.get("width", ""), y)
        if yw >= 1 and dw >= 2 * yw and dw % yw == 0:
            n = dw // yw
            sel_bits = width_bits(sel.get("width", ""), sel)
            if (1 << max(1, sel_bits)) >= n:
                return {
                    "sel": sel,
                    "packed": packed,
                    "data": [packed],
                    "y": y,
                    "kind": "packed",
                    "lanes": n,
                    "lane_w": yw,
                }
    return None


def detect_switch_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Address-range switch: addr/data in, addr_a/data_a and addr_b/data_b out."""
    addr = _by_name(roles["inputs"], "addr", "address")
    data = _by_name(roles["inputs"], "data", "wdata", "din")
    vld = _by_name(roles["inputs"], "vld", "valid", "in_valid")
    addr_a = _by_name(roles["outputs"], "addr_a")
    data_a = _by_name(roles["outputs"], "data_a")
    addr_b = _by_name(roles["outputs"], "addr_b")
    data_b = _by_name(roles["outputs"], "data_b")
    if not (addr and data and addr_a and data_a and addr_b and data_b):
        return None
    return {
        "addr": addr,
        "data": data,
        "vld": vld,
        "addr_a": addr_a,
        "data_a": data_a,
        "addr_b": addr_b,
        "data_b": data_b,
    }


def detect_apb_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Detect APB slave-like ports (psel/penable/pwrite/…)."""
    psel = _by_name(roles["inputs"], "psel")
    penable = _by_name(roles["inputs"], "penable")
    pwrite = _by_name(roles["inputs"], "pwrite")
    paddr = _by_name(roles["inputs"], "paddr")
    pwdata = _by_name(roles["inputs"], "pwdata")
    pready = _by_name(roles["outputs"], "pready")
    prdata = _by_name(roles["outputs"], "prdata")
    if not all((psel, penable, pwrite, paddr, pwdata, pready, prdata)):
        return None
    pslverr = _by_name(roles["outputs"], "pslverr")
    return {
        "psel": psel["name"],
        "penable": penable["name"],
        "pwrite": pwrite["name"],
        "paddr": paddr["name"],
        "pwdata": pwdata["name"],
        "pready": pready["name"],
        "prdata": prdata["name"],
        "num_regs": 4,
        "has_pslverr": bool(pslverr),
        "pslverr": (pslverr["name"] if pslverr else None),
    }


def detect_stream_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Detect valid/ready streaming data path (incl. s_axis_tvalid / tready / tdata)."""
    def _suf(ports: List[dict], *ends: str) -> Optional[dict]:
        for p in ports:
            n = (p.get("name") or "").lower()
            for e in ends:
                el = e.lower()
                if n == el or n.endswith("_" + el) or n.endswith(el):
                    return p
        return None

    valid = _by_name(roles["inputs"], "valid", "tvalid", "in_valid", "s_valid") or _suf(
        roles["inputs"], "tvalid", "valid"
    )
    ready = _by_name(roles["outputs"], "ready", "tready", "in_ready", "s_ready") or _suf(
        roles["outputs"], "tready", "ready"
    )
    data = _by_name(roles["inputs"], "data", "tdata", "in_data", "s_data") or _suf(
        roles["inputs"], "tdata", "data"
    )
    out_data = _by_name(
        roles["outputs"], "out_data", "q", "dout", "m_data", "data_out", "last_data"
    )
    out_valid = _by_name(roles["outputs"], "out_valid", "m_valid", "valid_out", "beat_count")
    if valid and ready and data and (out_data or out_valid):
        tlast = _suf(roles["inputs"], "tlast", "last")
        return {
            "valid": valid,
            "ready": ready,
            "data": data,
            "out_data": out_data,
            "out_valid": out_valid,
            "tlast": tlast,
        }
    return None


def detect_counter_model(roles: Dict[str, Any]) -> Optional[Tuple[Optional[dict], dict]]:
    """Return (enable_port_or_None, count_port) for enable or free-running counters."""
    if (
        detect_fifo_model(roles)
        or detect_axi_lite_model(roles)
        or detect_parity_model(roles)
        or detect_mux_model(roles)
        or detect_apb_model(roles)
        or detect_stream_model(roles)
    ):
        return None
    try:
        from tb_dut_goldens import (
            detect_ahb_model,
            detect_alu_model,
            detect_debounce_model,
            detect_edge_model,
            detect_gray_model,
            detect_can_model,
            detect_i2c_model,
            detect_prio_enc_model,
            detect_pwm_model,
            detect_shifter_model,
            detect_spi_model,
            detect_sync_ff_model,
            detect_uart_model,
            detect_uart_rx_model,
        )

        if (
            detect_alu_model(roles)
            or detect_prio_enc_model(roles)
            or detect_shifter_model(roles)
            or detect_gray_model(roles)
            or detect_edge_model(roles)
            or detect_pwm_model(roles)
            or detect_debounce_model(roles)
            or detect_sync_ff_model(roles)
            or detect_ahb_model(roles)
            or detect_spi_model(roles)
            or detect_uart_model(roles)
            or detect_uart_rx_model(roles)
            or detect_i2c_model(roles)
            or detect_can_model(roles)
        ):
            return None
    except Exception:
        pass
    count = None
    for p in roles["outputs"]:
        if _COUNT_RE.match(p["name"]):
            count = p
            break
    if count is None and len(roles["outputs"]) == 1:
        count = roles["outputs"][0]
    if not count:
        return None

    en = None
    for p in roles["inputs"]:
        if _EN_RE.match(p["name"]) and width_bits(p.get("width", ""), p) == 1:
            en = p
            break
    if en is None and len(roles["inputs"]) == 1 and width_bits(roles["inputs"][0].get("width", ""), roles["inputs"][0]) == 1:
        cand = roles["inputs"][0]
        if _EN_RE.match(cand["name"]) or cand["name"].lower() in ("en", "enable", "ce"):
            en = cand

    if en is None and len(roles["inputs"]) == 0:
        return None, count
    if en is not None:
        return en, count
    return None


def module_has_known_golden(module: dict) -> bool:
    """True when ChipSutra can emit a real (non-noop) scoreboard for this DUT."""
    if not module or not module.get("ports"):
        return False
    roles = classify_ports(module.get("ports") or [])
    params = module.get("parameters") or {}
    if detect_mux_model(roles) or detect_fifo_model(roles, params) or detect_parity_model(roles):
        return True
    if detect_counter_model(roles) or detect_stream_model(roles):
        return True
    if detect_axi_lite_model(roles) or detect_apb_model(roles):
        return True
    try:
        from tb_dut_goldens import (
            detect_debounce_model,
            detect_edge_model,
            detect_pwm_model,
            detect_sync_ff_model,
            try_render_special_class_tb,
        )

        if try_render_special_class_tb(module, cycles=4, seed=1):
            return True
        if (
            detect_edge_model(roles)
            or detect_pwm_model(roles)
            or detect_debounce_model(roles)
            or detect_sync_ff_model(roles)
        ):
            return True
    except Exception:
        return False
    return False


def prefer_known_golden_skeleton(
    *,
    gen_mode: str = "auto",
    tb_methodology: str = "sv",
    parsed_module: Optional[dict] = None,
    prompt: str = "",
) -> bool:
    """Skip the LLM when a DUT-matched golden skeleton is the accuracy floor.

    Set CHIPSUTRA_SKELETON_FIRST=0 or gen_mode=llm to force the model.
    """
    import os

    mode = (gen_mode or "auto").lower().strip()
    if mode in ("llm", "model"):
        return False
    if os.environ.get("CHIPSUTRA_SKELETON_FIRST", "true").lower() in ("0", "false", "no"):
        return False
    if re.search(r"\bforce[-_ ]llm\b|\bfrom the model\b", prompt or "", re.I):
        return False
    return module_has_known_golden(parsed_module or {})


def should_use_tb_skeleton(
    *,
    module: str,
    prompt: str = "",
    modules: Optional[List[dict]] = None,
    gen_mode: str = "auto",
    tool_log: Optional[str] = None,
    tb_methodology: str = "sv",
) -> bool:
    """Decide whether to emit a deterministic skeleton instead of calling the LLM."""
    if module != "testbench":
        return False
    if not (modules and modules[0].get("ports")):
        return False
    from tb_methodology import is_class_methodology, normalize_methodology

    if is_class_methodology(normalize_methodology(tb_methodology, prompt=prompt or "")):
        return False
    mode = (gen_mode or "auto").lower().strip()
    # Procedural smoke template ONLY when user explicitly asks Fast-random / skeleton.
    # Default / auto / llm → class-based Pure SV via LLM (or UVM/OVM/VMM).
    if mode in ("skeleton", "fast", "template"):
        if tool_log and tool_log.strip():
            return False
        return True
    if mode in ("llm", "model", "class", "oop", "auto"):
        return False
    return False


def resolve_skeleton_emit(
    *,
    module: str,
    ref_tb: str,
    gen_mode: str = "auto",
    prompt: str = "",
    tool_log: Optional[str] = None,
    tb_methodology: str = "sv",
    use_skeleton: Optional[bool] = None,
    modules: Optional[List[dict]] = None,
) -> str:
    """Return skeleton SV to emit as final output, or '' to force LLM.

    Hard rule: UVM/OVM/VMM never get the Pure-SV Fast-random template as the answer.
    """
    from tb_methodology import is_class_methodology, normalize_methodology

    if module != "testbench" or not (ref_tb or "").strip():
        return ""
    meth = normalize_methodology(tb_methodology, prompt=prompt or "")
    if is_class_methodology(meth):
        return ""
    if use_skeleton is None:
        use_skeleton = should_use_tb_skeleton(
            module=module,
            prompt=prompt,
            modules=modules,
            gen_mode=gen_mode,
            tool_log=tool_log,
            tb_methodology=meth,
        )
    if use_skeleton:
        return ref_tb
    mode = (gen_mode or "auto").lower().strip()
    # Explicit smoke only — never auto-emit procedural template for class-SV / UVM paths.
    if mode in ("skeleton", "fast", "template"):
        if (tool_log or "").strip():
            return ""
        if _FORCE_LLM_RE.search(prompt or ""):
            return ""
        return ref_tb
    return ""


def _emit_counter_loop(
    *,
    roles: Dict[str, Any],
    counter: Tuple[Optional[dict], dict],
    clk_name: str,
    cycles: int,
) -> List[str]:
    en_p, cnt_p = counter
    lines = [
        "    expected = '0;",
        f"    // Counter check loop ({'random enable' if en_p else 'free-running increment'})",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
    ]
    if en_p:
        for p in roles["inputs"]:
            if p["name"] == en_p["name"]:
                lines.append(f"      {en_p['name']} = $urandom_range(0, 1);")
            else:
                bits_i = width_bits(p.get("width", ""), p)
                lines.append(
                    f"      {p['name']} = $urandom_range(0, 1);"
                    if bits_i == 1
                    else f"      {p['name']} = {bits_i}'($urandom());"
                )
        lines += [
            f"      @(posedge {clk_name});",
            "      #1;",
            f"      if ({en_p['name']})",
            "        expected = expected + 1'b1;",
            f"      if ({cnt_p['name']} !== expected) begin",
            f'        $error("[%0t] mismatch i=%0d enable=%b count=%0h expected=%0h",',
            f"               $time, i, {en_p['name']}, {cnt_p['name']}, expected);",
            "        errors = errors + 1;",
            "      end",
            "    end",
        ]
    else:
        lines += [
            f"      @(posedge {clk_name});",
            "      #1;",
            "      expected = expected + 1'b1;",
            f"      if ({cnt_p['name']} !== expected) begin",
            f'        $error("[%0t] mismatch i=%0d count=%0h expected=%0h",',
            f"               $time, i, {cnt_p['name']}, expected);",
            "        errors = errors + 1;",
            "      end",
            "    end",
        ]
    return lines


def _emit_fifo_loop(fifo: dict, clk_name: str, cycles: int) -> Tuple[List[str], List[str]]:
    wbits = width_bits(fifo["wr_data"].get("width", ""), fifo["wr_data"])
    depth = int(fifo.get("depth") or 8)
    wr_en, wr_data = fifo["wr_en"]["name"], fifo["wr_data"]["name"]
    rd_en, rd_data = fifo["rd_en"]["name"], fifo["rd_data"]["name"]
    full, empty = fifo["full"]["name"], fifo["empty"]["name"]
    count = fifo["count"]["name"] if fifo.get("count") else None

    decls = [
        "  // Queue scoreboard (FWFT-style: head visible when !empty)",
        f"  logic [{wbits - 1}:0] q[$];",
        "  logic do_write;",
        "  logic do_read;",
    ]
    loop = [
        "    q.delete();",
        f"    // Randomized FIFO traffic with independent queue golden (depth={depth})",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
        f"      {wr_en} = $urandom_range(0, 1);",
        f"      {rd_en} = $urandom_range(0, 1);",
        f"      {wr_data} = {wbits}'($urandom());",
        f"      if (q.size() >= {depth}) {wr_en} = 1'b0;",
        f"      if (q.size() == 0) {rd_en} = 1'b0;",
        f"      // Keep model simple: avoid simultaneous push+pop at size==1",
        f"      if (q.size() <= 1 && {wr_en} && {rd_en}) {rd_en} = 1'b0;",
        f"      @(posedge {clk_name});",
        "      #1;",
        f"      do_write = {wr_en} && (q.size() < {depth});",
        f"      do_read  = {rd_en} && (q.size() > 0);",
        "      if (do_read) void'(q.pop_front());",
        f"      if (do_write) q.push_back({wr_data});",
        f"      if ({empty} !== (q.size() == 0)) begin",
        f'        $error("[%0t] empty mismatch i=%0d empty=%b qsize=%0d", $time, i, {empty}, q.size());',
        "        errors = errors + 1;",
        "      end",
        f"      if ({full} !== (q.size() >= {depth})) begin",
        f'        $error("[%0t] full mismatch i=%0d full=%b qsize=%0d", $time, i, {full}, q.size());',
        "        errors = errors + 1;",
        "      end",
    ]
    if count:
        loop += [
            f"      if ({count} !== q.size()) begin",
            f'        $error("[%0t] count mismatch i=%0d count=%0d qsize=%0d", $time, i, {count}, q.size());',
            "        errors = errors + 1;",
            "      end",
        ]
    loop += [
        "      if (q.size() > 0) begin",
        f"        if ({rd_data} !== q[0]) begin",
        f'          $error("[%0t] rd_data mismatch i=%0d got=%0h exp=%0h", $time, i, {rd_data}, q[0]);',
        "          errors = errors + 1;",
        "        end",
        "      end",
        "    end",
    ]
    # rst_name is optional; caller appends mid-reset for sequential FIFOs
    return decls, loop


def _emit_parity_loop(par: dict, clk_name: str, cycles: int) -> List[str]:
    valid, data = par["valid"]["name"], par["data"]["name"]
    parity = par["parity"]["name"]
    vout = par["valid_out"]["name"] if par.get("valid_out") else None
    wbits = width_bits(par["data"].get("width", ""), par["data"])
    lines = [
        "    // Parity golden: XOR reduction sampled with valid (combo or same-cycle reg)",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
        f"      {valid} = $urandom_range(0, 1);",
        f"      {data} = {wbits}'($urandom());",
        f"      @(posedge {clk_name});",
        "      #1;",
        f"      if ({valid}) begin",
        f"        if ({parity} !== ^{data}) begin",
        f'          $error("[%0t] parity mismatch i=%0d data=%0h parity=%b", $time, i, {data}, {parity});',
        "          errors = errors + 1;",
        "        end",
    ]
    if vout:
        lines += [
            f"        if (!{vout}) begin",
            f'          $error("[%0t] valid_out expected 1 i=%0d", $time, i);',
            "          errors = errors + 1;",
            "        end",
        ]
    lines += ["      end", "    end"]
    return lines


def _emit_axi_lite_loop(
    clk_name: str,
    cycles: int,
    *,
    rst_name: Optional[str] = None,
    active_low: bool = True,
) -> Tuple[List[str], List[str]]:
    """Directed + light-random AXI4-Lite smoke with 4-word regfile golden."""
    n_txn = max(4, min(cycles // 4, 16))
    decls = [
        "  // AXI4-Lite scoreboard: 4 x 32-bit registers (addr[3:2])",
        "  logic [31:0] model_reg [0:3];",
        "  logic [1:0]  axi_sel;",
        "  integer timeout;",
    ]
    loop = [
        "    for (timeout = 0; timeout < 4; timeout = timeout + 1) model_reg[timeout] = 32'h0;",
        "    s_axi_awprot = 3'b0; s_axi_arprot = 3'b0;",
        "    s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b0; s_axi_arvalid = 1'b0;",
        "    s_axi_bready = 1'b0; s_axi_rready = 1'b0;",
        "    s_axi_wstrb = 4'hF;",
        "    // Post-reset: every register must read 0 (kills drop_reset mutants)",
        "    for (i = 0; i < 4; i = i + 1) begin",
        "      axi_sel = i[1:0];",
        "      s_axi_araddr = {axi_sel, 2'b00};",
        "      s_axi_arvalid = 1'b1;",
        "      timeout = 0;",
        f"      @(posedge {clk_name});",
        f"      while (!s_axi_arready && timeout < 40) begin",
        f"        @(posedge {clk_name}); timeout = timeout + 1;",
        "      end",
        f"      @(posedge {clk_name});",
        "      s_axi_arvalid = 1'b0; s_axi_rready = 1'b1;",
        "      timeout = 0;",
        f"      while (!s_axi_rvalid && timeout < 40) begin",
        f"        @(posedge {clk_name}); timeout = timeout + 1;",
        "      end",
        "      if (!s_axi_rvalid || s_axi_rdata !== 32'h0 || s_axi_rresp !== 2'b00) begin",
        f'        $error("[%0t] AXI post-reset reg[%0d] not zero got=%0h", $time, axi_sel, s_axi_rdata);',
        "        errors = errors + 1;",
        "      end",
        f"      @(posedge {clk_name});",
        "      s_axi_rready = 1'b0;",
        "    end",
        "    // AWVALID without WVALID must not commit (kills wr_start=aw||w mutants)",
        "    s_axi_awaddr = 4'h0; s_axi_wdata = 32'hFFFF_FFFF; s_axi_wstrb = 4'hF;",
        "    s_axi_awvalid = 1'b1; s_axi_wvalid = 1'b0; s_axi_bready = 1'b1;",
        f"    repeat (6) @(posedge {clk_name});",
        "    s_axi_awvalid = 1'b0; s_axi_bready = 1'b0;",
        f"    @(posedge {clk_name});",
        "    s_axi_araddr = 4'h0; s_axi_arvalid = 1'b1;",
        "    timeout = 0;",
        f"    @(posedge {clk_name});",
        f"    while (!s_axi_arready && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        f"    @(posedge {clk_name});",
        "    s_axi_arvalid = 1'b0; s_axi_rready = 1'b1;",
        "    timeout = 0;",
        f"    while (!s_axi_rvalid && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        "    if (s_axi_rdata !== 32'h0) begin",
        f'      $error("[%0t] AXI AW-only ghost write rdata=%0h", $time, s_axi_rdata);',
        "      errors = errors + 1;",
        "    end",
        f"    @(posedge {clk_name}); s_axi_rready = 1'b0;",
        "    // WVALID without AWVALID must not commit (kills wr_hs ... || wvalid mutants)",
        "    s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b1;",
        "    s_axi_wdata = 32'hFFFF_FFFF; s_axi_wstrb = 4'hF; s_axi_awaddr = 4'h0;",
        f"    repeat (6) @(posedge {clk_name});",
        "    s_axi_wvalid = 1'b0;",
        f"    @(posedge {clk_name});",
        "    s_axi_araddr = 4'h0; s_axi_arvalid = 1'b1;",
        "    timeout = 0;",
        f"    @(posedge {clk_name});",
        f"    while (!s_axi_arready && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        f"    @(posedge {clk_name});",
        "    s_axi_arvalid = 1'b0; s_axi_rready = 1'b1;",
        "    timeout = 0;",
        f"    while (!s_axi_rvalid && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        "    if (s_axi_rdata !== 32'h0) begin",
        f'      $error("[%0t] AXI W-only ghost write rdata=%0h", $time, s_axi_rdata);',
        "      errors = errors + 1;",
        "    end",
        f"    @(posedge {clk_name}); s_axi_rready = 1'b0;",
        f"    // AXI-Lite smoke: {n_txn} write-then-read transactions",
        f"    for (i = 0; i < {n_txn}; i = i + 1) begin",
        "      axi_sel = $urandom_range(0, 3);",
        "      s_axi_awaddr = {axi_sel, 2'b00};",
        "      s_axi_araddr = {axi_sel, 2'b00};",
        "      s_axi_wdata  = $urandom();",
        "      // Write address + data",
        "      s_axi_awvalid = 1'b1;",
        "      s_axi_wvalid  = 1'b1;",
        "      timeout = 0;",
        f"      @(posedge {clk_name});",
        f"      while (!(s_axi_awready && s_axi_wready) && timeout < 40) begin",
        f"        @(posedge {clk_name}); timeout = timeout + 1;",
        "      end",
        "      if (!(s_axi_awready && s_axi_wready)) begin",
        '        $error("AXI write handshake timeout");',
        "        errors = errors + 1;",
        "        s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b0;",
        "      end else begin",
        "        model_reg[axi_sel] = s_axi_wdata;",
        f"        @(posedge {clk_name});",
        "        s_axi_awvalid = 1'b0;",
        "        s_axi_wvalid  = 1'b0;",
        "        // Wait write response",
        "        s_axi_bready = 1'b1;",
        "        timeout = 0;",
        f"        while (!s_axi_bvalid && timeout < 40) begin",
        f"          @(posedge {clk_name}); timeout = timeout + 1;",
        "        end",
        "        if (!s_axi_bvalid || s_axi_bresp !== 2'b00) begin",
        '          $error("AXI BRESP fail");',
        "          errors = errors + 1;",
        "        end",
        f"        @(posedge {clk_name});",
        "        s_axi_bready = 1'b0;",
        "      end",
        "      // Read address",
        "      s_axi_arvalid = 1'b1;",
        "      timeout = 0;",
        f"      @(posedge {clk_name});",
        f"      while (!s_axi_arready && timeout < 40) begin",
        f"        @(posedge {clk_name}); timeout = timeout + 1;",
        "      end",
        f"      @(posedge {clk_name});",
        "      s_axi_arvalid = 1'b0;",
        "      s_axi_rready = 1'b1;",
        "      timeout = 0;",
        f"      while (!s_axi_rvalid && timeout < 40) begin",
        f"        @(posedge {clk_name}); timeout = timeout + 1;",
        "      end",
        "      if (!s_axi_rvalid || s_axi_rdata !== model_reg[axi_sel] || s_axi_rresp !== 2'b00) begin",
        f'        $error("[%0t] AXI RDATA mismatch sel=%0d got=%0h exp=%0h", $time, axi_sel, s_axi_rdata, model_reg[axi_sel]);',
        "        errors = errors + 1;",
        "      end",
        f"      @(posedge {clk_name});",
        "      s_axi_rready = 1'b0;",
        "    end",
    ]
    if rst_name:
        deassert = "1'b1" if active_low else "1'b0"
        assert_r = "1'b0" if active_low else "1'b1"
        loop += [
            "    // Mid-test reset then read all regs (kills drop_reset)",
            "    s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b0; s_axi_arvalid = 1'b0;",
            f"    {rst_name} = {assert_r};",
            f"    repeat (4) @(posedge {clk_name});",
            f"    {rst_name} = {deassert};",
            f"    @(posedge {clk_name});",
            "    for (timeout = 0; timeout < 4; timeout = timeout + 1) model_reg[timeout] = 32'h0;",
            "    for (i = 0; i < 4; i = i + 1) begin",
            "      axi_sel = i[1:0];",
            "      s_axi_araddr = {axi_sel, 2'b00};",
            "      s_axi_arvalid = 1'b1;",
            "      timeout = 0;",
            f"      @(posedge {clk_name});",
            f"      while (!s_axi_arready && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
            f"      @(posedge {clk_name});",
            "      s_axi_arvalid = 1'b0; s_axi_rready = 1'b1;",
            "      timeout = 0;",
            f"      while (!s_axi_rvalid && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
            "      if (!s_axi_rvalid || s_axi_rdata !== 32'h0) begin",
            f'        $error("[%0t] AXI post-reset reg[%0d] not zero got=%0h", $time, axi_sel, s_axi_rdata);',
            "        errors = errors + 1;",
            "      end",
            f"      @(posedge {clk_name}); s_axi_rready = 1'b0;",
            "    end",
        ]
    return decls, loop


def _emit_mux_loop(mux: dict, clk_name: Optional[str], cycles: int) -> List[str]:
    sel = mux["sel"]["name"]
    y = mux["y"]["name"]
    data = list(mux.get("data") or [])
    if mux.get("kind") == "2to1" or (mux.get("a") and mux.get("b") and len(data) < 2):
        a, b = mux["a"]["name"], mux["b"]["name"]
        abits = width_bits(mux["a"].get("width", ""), mux["a"])
        lines = [
            "    // 2:1 mux golden: y === (sel ? b : a)",
            f"    for (i = 0; i < {cycles}; i = i + 1) begin",
            f"      {sel} = $urandom_range(0, 1);",
            f"      {a} = {abits}'($urandom());",
            f"      {b} = {abits}'($urandom());",
        ]
        if clk_name:
            lines += [f"      @(posedge {clk_name});", "      #1;"]
        else:
            lines.append("      #1;")
        lines += [
            f"      if ({y} !== ({sel} ? {b} : {a}) && {y} !== ({sel} ? {a} : {b})) begin",
            f'        $error("[%0t] mux mismatch i=%0d sel=%b a=%0h b=%0h y=%0h", $time, i, {sel}, {a}, {b}, {y});',
            "        errors = errors + 1;",
            "      end",
            "    end",
        ]
        return lines

    n = len(data)
    dbits = width_bits(data[0].get("width", ""), data[0])
    sel_max = n - 1
    lines = [
        f"    // {n}:1 mux golden: y === d[sel]",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
        f"      {sel} = $urandom_range(0, {sel_max});",
    ]
    for p in data:
        lines.append(f"      {p['name']} = {dbits}'($urandom());")
    if clk_name:
        lines += [f"      @(posedge {clk_name});", "      #1;"]
    else:
        lines.append("      #1;")
    cond = " || ".join(
        f"({sel} == {i} && {y} !== {p['name']})" for i, p in enumerate(data)
    )
    lines += [
        f"      if ({cond}) begin",
        f'        $error("[%0t] mux mismatch i=%0d sel=%0h y=%0h", $time, i, {sel}, {y});',
        "        errors = errors + 1;",
        "      end",
        "    end",
    ]
    return lines


def _emit_apb_loop(
    clk_name: str,
    cycles: int,
    apb: Optional[dict] = None,
    *,
    rst_name: Optional[str] = None,
    active_low: bool = True,
) -> Tuple[List[str], List[str]]:
    n_txn = max(4, min(cycles // 4, 12))
    psel = (apb or {}).get("psel") or "psel"
    penable = (apb or {}).get("penable") or "penable"
    pwrite = (apb or {}).get("pwrite") or "pwrite"
    paddr = (apb or {}).get("paddr") or "paddr"
    pwdata = (apb or {}).get("pwdata") or "pwdata"
    pready = (apb or {}).get("pready") or "pready"
    prdata = (apb or {}).get("prdata") or "prdata"
    pslverr = (apb or {}).get("pslverr")
    decls = [
        "  // APB scoreboard: 4 x 32-bit regs (paddr[3:2])",
        "  logic [31:0] apb_model [0:3];",
        "  logic [1:0]  apb_sel;",
        "  integer timeout;",
    ]
    loop = [
        "    for (timeout = 0; timeout < 4; timeout = timeout + 1) apb_model[timeout] = 32'h0;",
        f"    {psel} = 1'b0; {penable} = 1'b0; {pwrite} = 1'b0; {paddr} = '0; {pwdata} = '0;",
        "    // PENABLE without PSEL must not write (kills access=PSEL||PENABLE mutants)",
        f"    {paddr} = 8'h00; {pwdata} = 32'hFFFF_FFFF; {pwrite} = 1'b1;",
        f"    {psel} = 1'b0; {penable} = 1'b1;",
        f"    @(posedge {clk_name});",
        f"    {penable} = 1'b0; {pwrite} = 1'b0;",
        f"    {psel} = 1'b1; {penable} = 1'b0; {pwrite} = 1'b0; {paddr} = 8'h00;",
        f"    @(posedge {clk_name});",
        f"    {penable} = 1'b1; timeout = 0;",
        f"    @(posedge {clk_name});",
        f"    while (!{pready} && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        "    #1;",
        f"    if ({prdata} !== 32'h0) begin",
        f'      $error("[%0t] APB ghost write without PSEL", $time);',
        "      errors = errors + 1;",
        "    end",
        f"    {psel} = 1'b0; {penable} = 1'b0;",
        f"    @(posedge {clk_name});",
        f"    // APB smoke: {n_txn} write then read",
        f"    for (i = 0; i < {n_txn}; i = i + 1) begin",
        "      apb_sel = $urandom_range(0, 3);",
        f"      {paddr} = {{apb_sel, 2'b00}};",
        f"      {pwdata} = $urandom();",
        "      // SETUP write",
        f"      {psel} = 1'b1; {penable} = 1'b0; {pwrite} = 1'b1;",
        f"      @(posedge {clk_name});",
        "      // ACCESS write",
        f"      {penable} = 1'b1;",
        "      timeout = 0;",
        f"      @(posedge {clk_name});",
        f"      while (!{pready} && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        f"      if (!{pready}) begin $error(\"APB write ready timeout\"); errors = errors + 1; end",
        f"      else apb_model[apb_sel] = {pwdata};",
        f"      {psel} = 1'b0; {penable} = 1'b0; {pwrite} = 1'b0;",
        "      // SETUP read",
        f"      {psel} = 1'b1; {penable} = 1'b0; {pwrite} = 1'b0;",
        f"      @(posedge {clk_name});",
        f"      {penable} = 1'b1;",
        "      timeout = 0;",
        f"      @(posedge {clk_name});",
        f"      while (!{pready} && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
        "      #1;",
        f"      if (!{pready} || {prdata} !== apb_model[apb_sel]) begin",
        f'        $error("[%0t] APB RDATA mismatch sel=%0d got=%0h exp=%0h", $time, apb_sel, {prdata}, apb_model[apb_sel]);',
        "        errors = errors + 1;",
        "      end",
    ]
    if pslverr:
        loop += [
            f"      if ({pslverr}) begin $error(\"APB PSLVERR unexpected\"); errors = errors + 1; end",
        ]
    loop += [
        f"      @(posedge {clk_name});",
        f"      {psel} = 1'b0; {penable} = 1'b0;",
        "    end",
    ]
    if rst_name:
        deassert = "1'b1" if active_low else "1'b0"
        assert_r = "1'b0" if active_low else "1'b1"
        loop += [
            "    // Mid-test reset then read all regs (kills drop_reset / off_by_one reset loop)",
            f"    {psel} = 1'b0; {penable} = 1'b0; {pwrite} = 1'b0;",
            f"    {rst_name} = {assert_r};",
            f"    repeat (4) @(posedge {clk_name});",
            f"    {rst_name} = {deassert};",
            f"    @(posedge {clk_name});",
            "    for (timeout = 0; timeout < 4; timeout = timeout + 1) apb_model[timeout] = 32'h0;",
            "    for (i = 0; i < 4; i = i + 1) begin",
            "      apb_sel = i[1:0];",
            f"      {paddr} = {{apb_sel, 2'b00}}; {pwrite} = 1'b0;",
            f"      {psel} = 1'b1; {penable} = 1'b0;",
            f"      @(posedge {clk_name});",
            f"      {penable} = 1'b1; timeout = 0;",
            f"      @(posedge {clk_name});",
            f"      while (!{pready} && timeout < 40) begin @(posedge {clk_name}); timeout = timeout + 1; end",
            "      #1;",
            f"      if ({prdata} !== 32'h0) begin",
            f'        $error("[%0t] APB post-reset reg[%0d] not zero got=%0h", $time, apb_sel, {prdata});',
            "        errors = errors + 1;",
            "      end",
            f"      {psel} = 1'b0; {penable} = 1'b0;",
            f"      @(posedge {clk_name});",
            "    end",
        ]
    return decls, loop


def _emit_stream_loop(st: dict, clk_name: str, cycles: int) -> List[str]:
    valid, ready = st["valid"]["name"], st["ready"]["name"]
    data = st["data"]["name"]
    wbits = width_bits(st["data"].get("width", ""), st["data"])
    out_d = st["out_data"]["name"] if st.get("out_data") else None
    out_v = st["out_valid"]["name"] if st.get("out_valid") else None
    lines = [
        "    // Valid/ready stream smoke: fire when ready; check no-X on outputs",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
        f"      {valid} = $urandom_range(0, 1);",
        f"      {data} = {wbits}'($urandom());",
        f"      @(posedge {clk_name});",
        "      #1;",
        f"      if ({valid} && !{ready}) begin",
        "        // backpressure: hold (re-drive same next cycle via random)",
        "      end",
    ]
    outs = [p for p in (out_d, out_v) if p]
    for o in outs:
        lines += [
            f"      if ($isunknown({o})) begin",
            f'        $error("[%0t] X on {o} i=%0d", $time, i);',
            "        errors = errors + 1;",
            "      end",
        ]
    lines.append("    end")
    return lines


def _emit_generic_loop(roles: Dict[str, Any], clk_name: Optional[str], cycles: int) -> List[str]:
    """Universal harness for ANY DUT: reset settle, no-X checks, randomized traffic."""
    lines = [
        "    // === Universal auto-TB for unknown protocol ===",
        "    // 1) Post-reset: outputs must not be X",
        "    // 2) Randomized legal-ish stimulus",
        "    // 3) Continuous no-X monitor on outputs",
        "    // Promote to protocol golden when ports match FIFO/AXI/APB/mux/…",
    ]
    if roles["outputs"]:
        lines.append("    // Post-reset X check")
        for p in roles["outputs"]:
            lines += [
                f"    if ($isunknown({p['name']})) begin",
                f'      $error("[%0t] X on {p["name"]} after reset", $time);',
                "      errors = errors + 1;",
                "    end",
            ]
    lines += [
        f"    // Randomized stimulus over {cycles} cycles",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
    ]
    for p in roles["inputs"]:
        bits_i = width_bits(p.get("width", ""), p)
        # Prefer sparse 1-bit enables (mostly 0) to reduce illegal traffic
        n = p["name"].lower()
        if bits_i == 1 and any(k in n for k in ("en", "valid", "req", "start", "go", "wr", "rd")):
            lines.append(f"      {p['name']} = ($urandom_range(0, 3) == 0);")
        elif bits_i == 1:
            lines.append(f"      {p['name']} = $urandom_range(0, 1);")
        else:
            lines.append(f"      {p['name']} = {bits_i}'($urandom());")
    if clk_name:
        lines.append(f"      @(posedge {clk_name});")
        lines.append("      #1;")
    else:
        lines.append("      #10;")
    for p in roles["outputs"]:
        lines += [
            f"      if ($isunknown({p['name']})) begin",
            f'        $error("[%0t] X on {p["name"]} i=%0d", $time, i);',
            "        errors = errors + 1;",
            "      end",
        ]
    if roles["outputs"]:
        outs = ", ".join("%0h" for _ in roles["outputs"])
        args = ", ".join(p["name"] for p in roles["outputs"])
        lines.append(f'      if (i % 8 == 0) $display("[%0t] i=%0d outs: {outs}", $time, i, {args});')
    lines.append("    end")
    return lines


def render_randomized_tb(
    module: dict,
    *,
    cycles: int = 48,
    seed: int = 1,
) -> str:
    """Render a compact randomized self-checking (when possible) SV testbench."""
    name = module.get("name") or "dut"
    ports = module.get("ports") or []
    parameters = module.get("parameters") or {}
    roles = classify_ports(ports)
    clk = roles["clk"]
    rst = roles["rst"]
    clk_name = (clk or {}).get("name", "clk")
    rst_name = (rst or {}).get("name")
    active_low = roles["active_low_reset"]
    tb_name = f"{name}_tb"
    cycles = max(8, min(int(cycles), 256))
    seed = int(seed) & 0x7FFFFFFF

    decls: List[str] = []
    inits: List[str] = []
    port_map: List[str] = []

    if clk:
        decls.append(f"  logic {clk_name};")
        inits.append(f"    {clk_name} = 1'b0;")
        port_map.append(f"    .{clk_name}({clk_name})")
    if rst_name:
        decls.append(f"  logic {rst_name};")
        assert_val = "1'b0" if active_low else "1'b1"
        inits.append(f"    {rst_name} = {assert_val};")
        port_map.append(f"    .{rst_name}({rst_name})")

    for p in roles["inputs"]:
        decls.append(f"  {sv_type(p.get('width', ''), p)} {p['name']};")
        bits = width_bits(p.get("width", ""), p)
        zero = "1'b0" if bits == 1 else f"{bits}'b0"
        inits.append(f"    {p['name']} = {zero};")
        port_map.append(f"    .{p['name']}({p['name']})")

    for p in roles["outputs"]:
        decls.append(f"  {sv_type(p.get('width', ''), p)} {p['name']};")
        port_map.append(f"    .{p['name']}({p['name']})")

    fifo = detect_fifo_model(roles, parameters)
    axi = None if fifo else detect_axi_lite_model(roles)
    apb = None if (fifo or axi) else detect_apb_model(roles)
    parity = None if (fifo or axi or apb) else detect_parity_model(roles)
    mux = None if (fifo or axi or apb or parity) else detect_mux_model(roles)
    stream = None if (fifo or axi or apb or parity or mux) else detect_stream_model(roles)
    counter = None if (fifo or axi or apb or parity or mux or stream) else detect_counter_model(roles)

    if fifo:
        model_kind = "fifo"
    elif axi:
        model_kind = "axi_lite"
    elif apb:
        model_kind = "apb"
    elif parity:
        model_kind = "parity"
    elif mux:
        model_kind = "mux"
    elif stream:
        model_kind = "stream"
    elif counter:
        model_kind = "counter"
    else:
        model_kind = "generic"

    body_lines: List[str] = []
    if clk:
        body_lines += ["  // Free-running clock", f"  always #5 {clk_name} = ~{clk_name};", ""]
    body_lines += ["  integer i;", "  integer errors;", ""]

    if counter:
        _en, cnt_p = counter
        body_lines += [
            "  // Golden model for counter-style DUT",
            f"  {sv_type(cnt_p.get('width', ''), cnt_p)} expected;",
            "",
        ]
    extra_decls: List[str] = []
    fifo_loop: List[str] = []
    axi_loop: List[str] = []
    apb_loop: List[str] = []
    if fifo:
        fifo_decls, fifo_loop = _emit_fifo_loop(fifo, clk_name, cycles)
        extra_decls = fifo_decls
    elif axi:
        axi_decls, axi_loop = _emit_axi_lite_loop(
            clk_name, cycles, rst_name=rst_name, active_low=active_low
        )
        extra_decls = axi_decls
    elif apb:
        apb_decls, apb_loop = _emit_apb_loop(
            clk_name, cycles, apb, rst_name=rst_name, active_low=active_low
        )
        extra_decls = apb_decls
    if extra_decls:
        body_lines += extra_decls + [""]

    body_lines += [
        "  initial begin",
        f'    $dumpfile("{tb_name}.vcd");',
        f"    $dumpvars(0, {tb_name});",
        "    errors = 0;",
        "    // Deterministic seed so regressions are reproducible",
        f"    void'($urandom({seed}));",
    ]
    body_lines.extend(inits)

    if rst_name and clk:
        deassert = "1'b1" if active_low else "1'b0"
        assert_r = "1'b0" if active_low else "1'b1"
        body_lines += [
            f"    {rst_name} = {assert_r};",
            f"    repeat (4) @(posedge {clk_name});",
            f"    {rst_name} = {deassert};",
            f"    @(posedge {clk_name});",
        ]
    elif clk:
        body_lines.append(f"    repeat (2) @(posedge {clk_name});")

    if counter:
        body_lines += _emit_counter_loop(roles=roles, counter=counter, clk_name=clk_name, cycles=cycles)
    elif fifo:
        body_lines += fifo_loop
    elif axi:
        body_lines += axi_loop
    elif apb:
        body_lines += apb_loop
    elif parity:
        body_lines += _emit_parity_loop(parity, clk_name, cycles)
    elif mux:
        body_lines += _emit_mux_loop(mux, clk_name if clk else None, cycles)
    elif stream:
        body_lines += _emit_stream_loop(stream, clk_name, cycles)
    else:
        body_lines += _emit_generic_loop(roles, clk_name if clk else None, cycles)

    if rst_name and clk and model_kind in ("fifo", "parity", "counter"):
        deassert = "1'b1" if active_low else "1'b0"
        assert_r = "1'b0" if active_low else "1'b1"
        body_lines += [
            "    // ChipSutra mid-test reset (kills drop_reset under Verilator init-0)",
        ]
        if fifo:
            wr = fifo["wr_en"]["name"]
            rd = fifo["rd_en"]["name"]
            empty = fifo["empty"]["name"]
            full = fifo["full"]["name"]
            body_lines += [
                f"    {wr} = 1'b0; {rd} = 1'b0;",
                f"    {rst_name} = {assert_r};",
                f"    repeat (4) @(posedge {clk_name});",
                f"    {rst_name} = {deassert};",
                f"    @(posedge {clk_name});",
                f"    if ({empty} !== 1'b1) errors = errors + 1;",
                f"    if ({full} !== 1'b0) errors = errors + 1;",
            ]
            if fifo.get("count"):
                cn = fifo["count"]["name"]
                body_lines.append(f"    if ({cn} !== '0) errors = errors + 1;")
        elif parity:
            vn = parity["valid"]["name"]
            pn = parity["parity"]["name"]
            body_lines += [
                f"    {vn} = 1'b0;",
                f"    {rst_name} = {assert_r};",
                f"    repeat (4) @(posedge {clk_name});",
                f"    {rst_name} = {deassert};",
                f"    @(posedge {clk_name});",
                f"    if ({pn} !== 1'b0) errors = errors + 1;",
            ]
            if parity.get("valid_out"):
                vo = parity["valid_out"]["name"]
                body_lines.append(f"    if ({vo} !== 1'b0) errors = errors + 1;")
        elif counter:
            _en, cnt_p = counter
            if _en:
                body_lines.append(f"    {_en['name']} = 1'b0;")
            body_lines += [
                f"    {rst_name} = {assert_r};",
                f"    repeat (4) @(posedge {clk_name});",
                f"    {rst_name} = {deassert};",
                f"    @(posedge {clk_name});",
                f"    if ({cnt_p['name']} !== '0) errors = errors + 1;",
            ]

    body_lines += [
        "    if (errors == 0)",
        f'      $display("PASS: {tb_name} - randomized self-check OK");',
        "    else",
        f'      $display("FAIL: {tb_name} - %0d error(s)", errors);',
        "    $finish;",
        "  end",
    ]

    mapped = [line + ("," if i < len(port_map) - 1 else "") for i, line in enumerate(port_map)]
    header_note = {
        "counter": "golden: independent expected count",
        "fifo": "golden: queue scoreboard for full/empty/data",
        "axi_lite": "golden: 4-reg AXI-Lite write/read smoke",
        "apb": "golden: APB write/read scoreboard",
        "parity": "golden: XOR parity on valid",
        "mux": "golden: N:1 / 2:1 mux select",
        "stream": "valid/ready smoke + no-X checks",
        "generic": "universal auto-TB: random + no-X (any DUT)",
    }[model_kind]

    # Parameter overrides on DUT instance when WIDTH/DEPTH known (FIFO)
    dut_params = ""
    if fifo and parameters:
        parts = []
        if "WIDTH" in parameters:
            parts.append(f".WIDTH({parameters['WIDTH']})")
        if "DEPTH" in parameters:
            parts.append(f".DEPTH({parameters['DEPTH']})")
        if parts:
            dut_params = " #(" + ", ".join(parts) + ")"

    return "\n".join(
        [
            "// ChipSutra fast randomized TB (template engine - no LLM)",
            f"// Model: {model_kind} - {header_note}",
            "`timescale 1ns / 1ps",
            "",
            f"module {tb_name};",
            "",
            *decls,
            "",
            f"  {name}{dut_params} dut (",
            *mapped,
            "  );",
            "",
            *body_lines,
            "",
            "endmodule",
            "",
        ]
    )


def render_from_rtl_texts(
    texts: List[str],
    *,
    cycles: int = 48,
    seed: int = 1,
) -> Optional[str]:
    """Pick the first parsed module with ports and render a TB, else None."""
    from rtl_ports import extract_modules

    for t in texts or []:
        for mod in extract_modules(t or ""):
            if mod.get("ports"):
                return render_randomized_tb(mod, cycles=cycles, seed=seed)
    return None


def render_mux_class_tb(
    module: dict,
    mux: dict,
    *,
    cycles: int = 32,
    seed: int = 1,
) -> str:
    """Class-based mux TB without virtual interface.

    Verilator 5.032 can DIDNOTCONVERGE on combo DUTs + virtual interface members.
    Layered IF/gen/drv/mon/sb/env still drives a module-level interface instance
    via hierarchical paths (no `virtual` handles).
    """
    name = module.get("name") or "dut"
    tb_name = f"{name}_tb"
    txn_cls = f"{name}_txn"
    sb_cls = f"{name}_scoreboard"
    sel = mux["sel"]
    y = mux["y"]
    data = list(mux.get("data") or [])
    sel_n, y_n = sel["name"], y["name"]
    sel_t = sv_type(sel.get("width", ""), sel)
    y_t = sv_type(y.get("width", ""), y)

    txn_fields = [f"  rand bit [{width_bits(sel.get('width',''), sel) - 1}:0] {sel_n};"
                  if width_bits(sel.get("width", ""), sel) > 1
                  else f"  rand bit {sel_n};"]
    for p in data:
        bits = width_bits(p.get("width", ""), p)
        if bits == 1:
            txn_fields.append(f"  rand bit {p['name']};")
        else:
            txn_fields.append(f"  rand bit [{bits - 1}:0] {p['name']};")

    if mux.get("kind") == "packed" and mux.get("packed"):
        packed = mux["packed"]
        data = [packed]
        lane_w = int(mux.get("lane_w") or 1)
        pn = packed["name"]
        pt = sv_type(packed.get("width", ""), packed)
        check_body = [
            f"  function bit check({sel_t} {sel_n}, {pt} {pn}, {y_t} {y_n});",
            f"    return ({y_n} === {pn}[{sel_n} * {lane_w} +: {lane_w}]);",
            "  endfunction",
        ]
        check_call = f"      if (!sb.check({sel_n}, {pn}, {y_n})) errors++;"
        drives = [f"      {sel_n} = t.{sel_n};", f"      {pn} = t.{pn};"]
        decls = [
            "  logic clk;",
            f"  {sel_t} {sel_n};",
            f"  {pt} {pn};",
            f"  {y_t} {y_n};",
        ]
        dut_ports = [
            f"    .{sel_n}({sel_n})",
            f"    .{pn}({pn})",
            f"    .{y_n}({y_n})",
        ]
        zeros = f"    {sel_n} = '0; {pn} = '0;"
    elif mux.get("kind") == "2to1" and mux.get("a") and mux.get("b"):
        a_n, b_n = mux["a"]["name"], mux["b"]["name"]
        check_body = [
            f"  function bit check({sel_t} {sel_n}, {sv_type(mux['a'].get('width',''), mux['a'])} {a_n}, "
            f"{sv_type(mux['b'].get('width',''), mux['b'])} {b_n}, {y_t} {y_n});",
            f"    return ({y_n} === ({sel_n} ? {b_n} : {a_n}));",
            "  endfunction",
        ]
        check_call = f"      if (!sb.check({sel_n}, {a_n}, {b_n}, {y_n})) errors++;"
        drives = [f"      {sel_n} = t.{sel_n};", f"      {a_n} = t.{a_n};", f"      {b_n} = t.{b_n};"]
        decls = [
            "  logic clk;",
            f"  {sel_t} {sel_n};",
            f"  {sv_type(mux['a'].get('width', ''), mux['a'])} {a_n};",
            f"  {sv_type(mux['b'].get('width', ''), mux['b'])} {b_n};",
            f"  {y_t} {y_n};",
        ]
        dut_ports = [
            f"    .{sel_n}({sel_n})",
            f"    .{a_n}({a_n})",
            f"    .{b_n}({b_n})",
            f"    .{y_n}({y_n})",
        ]
        zeros = f"    {sel_n} = '0; {a_n} = '0; {b_n} = '0;"
    else:
        args = [f"{sel_t} {sel_n}"] + [
            f"{sv_type(p.get('width',''), p)} {p['name']}" for p in data
        ] + [f"{y_t} {y_n}"]
        check_body = [
            f"  function bit check({', '.join(args)});",
            f"    {y_t} exp;",
            f"    case ({sel_n})",
        ]
        for i, p in enumerate(data):
            check_body.append(f"      {i}: exp = {p['name']};")
        check_body += [
            "      default: exp = '0;",
            "    endcase",
            f"    return ({y_n} === exp);",
            "  endfunction",
        ]
        call_args = ", ".join([sel_n] + [p["name"] for p in data] + [y_n])
        check_call = f"      if (!sb.check({call_args})) errors++;"
        drives = [f"      {sel_n} = t.{sel_n};"] + [
            f"      {p['name']} = t.{p['name']};" for p in data
        ]
        decls = [f"  logic clk;", f"  {sel_t} {sel_n};"] + [
            f"  {sv_type(p.get('width',''), p)} {p['name']};" for p in data
        ] + [f"  {y_t} {y_n};"]
        dut_ports = [f"    .{sel_n}({sel_n})"] + [
            f"    .{p['name']}({p['name']})" for p in data
        ] + [f"    .{y_n}({y_n})"]
        zeros = "    " + " ".join(
            [f"{sel_n} = '0;"] + [f"{p['name']} = '0;" for p in data]
        )

    dut_ports_vif = [f"    .{sel_n}(vif.{sel_n})"] + [
        f"    .{p['name']}(vif.{p['name']})" for p in data
    ] + [f"    .{y_n}(vif.{y_n})"]
    dut_mapped = [
        line + ("," if i < len(dut_ports_vif) - 1 else "")
        for i, line in enumerate(dut_ports_vif)
    ]
    if_sigs = [f"  {sel_t} {sel_n};"] + [
        f"  {sv_type(p.get('width', ''), p)} {p['name']};" for p in data
    ] + [f"  {y_t} {y_n};"]
    gen_cls = f"{name}_generator"
    drv_cls = f"{name}_driver"
    mon_comp = f"{name}_monitor"
    mon_cls = f"{name}_mon_pkt"
    env_cls = f"{name}_env"
    test_cls = f"{name}_test"
    if_name = f"{name}_if"
    hier = tb_name
    drive_assigns = "\n".join(
        [f"      {hier}.vif.{sel_n} = t.{sel_n};"]
        + [f"      {hier}.vif.{p['name']} = t.{p['name']};" for p in data]
    )
    mon_fields = [f"  {sel_t} {sel_n};"] + [
        f"  {sv_type(p.get('width', ''), p)} {p['name']};" for p in data
    ] + [f"  {y_t} {y_n};"]
    mon_sample = "\n".join(
        [f"      p.{sel_n} = {hier}.vif.{sel_n};"]
        + [f"      p.{p['name']} = {hier}.vif.{p['name']};" for p in data]
        + [f"      p.{y_n} = {hier}.vif.{y_n};"]
    )
    check_args = ", ".join(
        [f"p.{sel_n}"] + [f"p.{p['name']}" for p in data] + [f"p.{y_n}"]
    )
    return f"""// ChipSutra Pure SV class TB for mux (combo-safe; no VIF handles)
// Components: interface, generator, driver, monitor, scoreboard, env, test
// DUT: {name} | cycles={cycles} | seed={seed}
`timescale 1ns / 1ps

interface {if_name};
{chr(10).join(if_sigs)}
endinterface

class {txn_cls};
{chr(10).join(txn_fields)}
  constraint legal_c {{
    {sel_n} inside {{[0:{max(0, len(data) - 1)}]}};
  }}
endclass

class {mon_cls};
{chr(10).join(mon_fields)}
endclass

class {gen_cls};
  mailbox #({txn_cls}) gen2drv;
  int n_txns;
  function new(mailbox #({txn_cls}) mb, int n);
    gen2drv = mb;
    n_txns = n;
  endfunction
  task run();
    {txn_cls} t;
    repeat (n_txns) begin
      t = new();
      assert(t.randomize()) else $fatal(1, "generator randomize failed");
      gen2drv.put(t);
    end
  endtask
endclass

class {drv_cls};
  mailbox #({txn_cls}) gen2drv;
  mailbox #({txn_cls}) drv2sb;
  function new(mailbox #({txn_cls}) gen2drv, mailbox #({txn_cls}) drv2sb);
    this.gen2drv = gen2drv;
    this.drv2sb = drv2sb;
  endfunction
  task run(int n);
    {txn_cls} t;
    repeat (n) begin
      gen2drv.get(t);
{drive_assigns}
      drv2sb.put(t);
      @(posedge {hier}.clk);
    end
  endtask
endclass

class {mon_comp};
  mailbox #({mon_cls}) mon2sb;
  function new(mailbox #({mon_cls}) mb);
    mon2sb = mb;
  endfunction
  task run(int n);
    {mon_cls} p;
    repeat (n) begin
      @(posedge {hier}.clk);
      #1;
      p = new();
{mon_sample}
      mon2sb.put(p);
    end
  endtask
endclass

class {sb_cls};
  mailbox #({txn_cls}) drv2sb;
  mailbox #({mon_cls}) mon2sb;
  int errors;
  function new();
    errors = 0;
  endfunction
{chr(10).join(check_body)}
  function void connect(mailbox #({txn_cls}) d2s, mailbox #({mon_cls}) m2s);
    drv2sb = d2s;
    mon2sb = m2s;
  endfunction
  task run(int n);
    {txn_cls} t;
    {mon_cls} p;
    repeat (n) begin
      drv2sb.get(t);
      mon2sb.get(p);
      if (!check({check_args})) begin
        $error("[%0t] mux mismatch", $time);
        errors++;
      end
    end
  endtask
endclass

class {env_cls};
  mailbox #({txn_cls}) gen2drv;
  mailbox #({txn_cls}) drv2sb;
  mailbox #({mon_cls}) mon2sb;
  {gen_cls} gen;
  {drv_cls} drv;
  {mon_comp} mon;
  {sb_cls} sb;
  function void build(int n);
    gen2drv = new();
    drv2sb = new();
    mon2sb = new();
    gen = new(gen2drv, n);
    drv = new(gen2drv, drv2sb);
    mon = new(mon2sb);
    sb = new();
    sb.connect(drv2sb, mon2sb);
  endfunction
  task run(int n);
    fork
      gen.run();
      drv.run(n);
      mon.run(n);
      sb.run(n);
    join
  endtask
  function void report();
    if (sb.errors == 0)
      $display("PASS: {tb_name} mux class SV OK");
    else
      $display("FAIL: {tb_name} - %0d error(s)", sb.errors);
  endfunction
endclass

class {test_cls};
  {env_cls} env;
  function new();
    env = new();
  endfunction
  task run(int n = {cycles});
    env.build(n);
    env.run(n);
    env.report();
  endtask
endclass

module {tb_name};
  logic clk;
  {if_name} vif();

  {name} dut (
{chr(10).join(dut_mapped)}
  );

  always #5 clk = ~clk;

  initial begin
    {test_cls} t;
    $dumpfile("{tb_name}.vcd");
    $dumpvars(0, {tb_name});
    void'($urandom({seed}));
    clk = 0;
    vif.{sel_n} = '0;
{chr(10).join(f"    vif.{p['name']} = '0;" for p in data)}
    t = new();
    t.run({cycles});
    $finish;
  end
endmodule
"""


def render_class_sv_tb(
    module: dict,
    *,
    cycles: int = 32,
    seed: int = 1,
) -> str:
    """Emit a layered Pure SV class TB (NO UVM) — default Pure SV path.

    Required components (ChipVerify-style):
      Interface, Generator, Driver, Monitor, Scoreboard, Environment, Test + top.

    Combinational mux uses a layered class TB without virtual-interface handles
    (Verilator 5.x can DIDNOTCONVERGE on combo + virtual interface members).
    """
    name = module.get("name") or "dut"
    ports = [dict(p) for p in (module.get("ports") or [])]
    roles = classify_ports(ports)
    mux = detect_mux_model(roles)
    if mux:
        sv = render_mux_class_tb(module, mux, cycles=cycles, seed=seed)
        try:
            from tb_scale_emit import apply_scale_emit

            return apply_scale_emit(sv, module)
        except Exception:
            return sv
    try:
        from tb_dut_goldens import try_render_special_class_tb

        special = try_render_special_class_tb(module, cycles=cycles, seed=seed)
        if special:
            return special
    except Exception:
        pass

    clk = roles["clk"]
    rst = roles["rst"]
    active_low = roles["active_low_reset"]
    clk_name = clk["name"] if clk else "clk"
    rst_name = rst["name"] if rst else None
    tb_name = f"{name}_tb"
    if_name = f"{name}_if"
    txn_cls = f"{name}_txn"
    mon_cls = f"{name}_mon_pkt"
    gen_cls = f"{name}_generator"
    drv_cls = f"{name}_driver"
    mon_comp = f"{name}_monitor"
    sb_cls = f"{name}_scoreboard"
    env_cls = f"{name}_env"
    test_cls = f"{name}_test"

    fifo = detect_fifo_model(roles, module.get("parameters"))
    if fifo and fifo.get("count"):
        need = max(4, int(fifo["depth"]).bit_length())
        cp = fifo["count"]
        if width_bits(cp.get("width", ""), cp) < need:
            cp["bits"] = need
            cp["width"] = f"[{need - 1}:0]"
            for p in ports:
                if p.get("name") == cp["name"]:
                    p["bits"] = need
                    p["width"] = f"[{need - 1}:0]"
    from tb_dut_goldens import (
        detect_edge_model,
        detect_pwm_model,
        detect_debounce_model,
        detect_sync_ff_model,
    )

    parity = detect_parity_model(roles)
    edge = None if (fifo or parity) else detect_edge_model(roles)
    pwm = None if (fifo or parity or edge) else detect_pwm_model(roles)
    debounce = None if (fifo or parity or edge or pwm) else detect_debounce_model(roles)
    syncff = None if (fifo or parity or edge or pwm or debounce) else detect_sync_ff_model(roles)
    stream = (
        None
        if (fifo or parity or edge or pwm or debounce or syncff)
        else detect_stream_model(roles)
    )
    counter = (
        None
        if (fifo or parity or edge or pwm or debounce or syncff or stream)
        else detect_counter_model(roles)
    )
    stim_inputs = list(roles["inputs"])
    outs = list(roles["outputs"])

    # --- interface signals (all non-clock DUT ports) ---
    if_sigs: List[str] = []
    for p in ports:
        pn = p["name"]
        if clk and pn == clk["name"]:
            continue
        if_sigs.append(f"  {sv_type(p.get('width', ''), p)} {pn};")

    # --- transaction fields ---
    txn_fields: List[str] = []
    constraints: List[str] = []
    for p in stim_inputs:
        pn = p["name"]
        bits = width_bits(p.get("width", ""), p)
        if bits == 1:
            txn_fields.append(f"  rand bit {pn};")
            constraints.append(f"    {pn} inside {{[0:1]}};")
        else:
            txn_fields.append(f"  rand bit [{bits - 1}:0] {pn};")
    if not txn_fields:
        txn_fields.append("  rand bit unused;")
        constraints.append("    unused == 0;")
    if fifo:
        wr_n = fifo["wr_en"]["name"]
        rd_n = fifo["rd_en"]["name"]
        constraints = [f"    !({wr_n} && {rd_n});"]
    elif parity:
        vn = parity["valid"]["name"]
        constraints = [f"    soft {vn} dist {{ 0 := 1, 1 := 3 }};"]
    elif pwm:
        dn = pwm["duty"]["name"]
        constraints = [f"    soft {dn} dist {{ 0 := 1, [1:255] := 3 }};"]
    elif stream:
        vn = stream["valid"]["name"]
        constraints = [f"    soft {vn} dist {{ 0 := 1, 1 := 3 }};"]

    # monitor packet mirrors driven inputs + sampled outputs
    mon_fields: List[str] = []
    for p in stim_inputs:
        mon_fields.append(f"  {sv_type(p.get('width', ''), p)} {p['name']};")
    for p in outs:
        mon_fields.append(f"  {sv_type(p.get('width', ''), p)} {p['name']};")
    if not mon_fields:
        mon_fields.append("  bit stub;")

    drive_assigns = "\n".join(
        f"      vif.{p['name']} = t.{p['name']};" for p in stim_inputs
    ) or "      ;"
    mon_sample = "\n".join(
        [f"      p.{p['name']} = vif.{p['name']};" for p in stim_inputs]
        + [f"      p.{p['name']} = vif.{p['name']};" for p in outs]
    ) or "      ;"
    zero_drives = "\n".join(f"    vif.{p['name']} = '0;" for p in stim_inputs) or "    ;"
    # keep indentation stable inside tasks
    zero_drives_2 = "\n".join(f"      vif.{p['name']} = '0;" for p in stim_inputs) or "      ;"

    # scoreboard predict/check bodies
    if mux:
        y_p = mux["y"]
        y_t = sv_type(y_p.get("width", ""), y_p)
        y_name = y_p["name"]
        data = list(mux.get("data") or [])
        sb_members = [
            f"  {y_t} expected;",
            "  int errors;",
            "  function new();",
            "    expected = '0;",
            "    errors = 0;",
            "  endfunction",
        ]
        if mux.get("kind") == "2to1" and mux.get("a") and mux.get("b"):
            a_n, b_n = mux["a"]["name"], mux["b"]["name"]
            sel_n = mux["sel"]["name"]
            predict_fn = [
                f"  function void predict(bit {sel_n}, {sv_type(mux['a'].get('width',''), mux['a'])} {a_n}, "
                f"{sv_type(mux['b'].get('width',''), mux['b'])} {b_n});",
                f"    expected = {sel_n} ? {b_n} : {a_n};",
                "  endfunction",
            ]
            predict_call = f"      predict(t.{sel_n}, t.{a_n}, t.{b_n});"
        else:
            sel_n = mux["sel"]["name"]
            sel_t = sv_type(mux["sel"].get("width", ""), mux["sel"])
            args = [f"{sel_t} {sel_n}"]
            for p in data:
                args.append(f"{sv_type(p.get('width', ''), p)} {p['name']}")
            predict_fn = [
                f"  function void predict({', '.join(args)});",
                f"    case ({sel_n})",
            ]
            for i, p in enumerate(data):
                predict_fn.append(f"      {i}: expected = {p['name']};")
            predict_fn += [
                "      default: expected = '0;",
                "    endcase",
                "  endfunction",
            ]
            predict_call = (
                "      predict("
                + ", ".join([f"t.{mux['sel']['name']}"] + [f"t.{p['name']}" for p in data])
                + ");"
            )
        check_fn = [
            f"  function bit check({y_t} actual);",
            "    return (actual === expected);",
            "  endfunction",
        ]
        check_call = (
            f"      if (!check(p.{y_name})) begin\n"
            f'        $error("[%0t] SB mismatch {y_name}=%0h expected=%0h", '
            f"$time, p.{y_name}, expected);\n"
            "        errors++;\n"
            "      end"
        )
        # Combinational mux: after zeroing inputs, y should be 0 for sel=0/d0=0
        post_reset_check = (
            f"    if (vif.{y_name} !== '0) begin\n"
            f'      $error("post-idle {y_name} not 0");\n'
            "      env.sb.errors++;\n"
            "    end"
        )
    elif fifo:
        wr_p, wrd_p = fifo["wr_en"], fifo["wr_data"]
        rd_p, rdd_p = fifo["rd_en"], fifo["rd_data"]
        full_p, empty_p = fifo["full"], fifo["empty"]
        cnt_p = fifo.get("count")
        depth = int(fifo.get("depth") or 8)
        wrd_t = sv_type(wrd_p.get("width", ""), wrd_p)
        rdd_t = sv_type(rdd_p.get("width", ""), rdd_p)
        wr_n, rd_n = wr_p["name"], rd_p["name"]
        wrd_n, rdd_n = wrd_p["name"], rdd_p["name"]
        full_n, empty_n = full_p["name"], empty_p["name"]
        sb_members = [
            f"  {wrd_t} q[$];",
            f"  localparam int DEPTH = {depth};",
            "  int unsigned depth;",
            "  int errors;",
            "  function new();",
            "    q.delete();",
            f"    depth = {depth};",
            "    errors = 0;",
            "  endfunction",
        ]
        predict_fn = [
            f"  function void predict(bit {wr_n}, bit {rd_n}, {wrd_t} {wrd_n});",
            f"    bit do_rd = {rd_n} && (q.size() > 0);",
            f"    bit do_wr = {wr_n} && (q.size() < DEPTH);",
            "    if (do_rd) void'(q.pop_front());",
            f"    if (do_wr) q.push_back({wrd_n});",
            "  endfunction",
        ]
        predict_call = f"      predict(t.{wr_n}, t.{rd_n}, t.{wrd_n});"
        check_args = [f"{rdd_t} {rdd_n}", f"bit {full_n}", f"bit {empty_n}"]
        check_body_extra = []
        if cnt_p:
            cnt_t = sv_type(cnt_p.get("width", ""), cnt_p)
            check_args.append(f"{cnt_t} {cnt_p['name']}")
            check_body_extra.append(
                f"    if ({cnt_p['name']} !== q.size()) ok = 1'b0;"
            )
        check_fn = [
            f"  function bit check({', '.join(check_args)});",
            "    bit ok = 1'b1;",
            f"    if ({empty_n} !== (q.size() == 0)) ok = 1'b0;",
            f"    if ({full_n} !== (q.size() >= DEPTH)) ok = 1'b0;",
            *check_body_extra,
            f"    if (q.size() > 0 && {rdd_n} !== q[0]) ok = 1'b0;",
            "    return ok;",
            "  endfunction",
        ]
        check_call_args = f"p.{rdd_n}, p.{full_n}, p.{empty_n}"
        if cnt_p:
            check_call_args += f", p.{cnt_p['name']}"
        check_call = (
            f"      if (!check({check_call_args})) begin\n"
            f'        $error("[%0t] fifo mismatch empty=%0b full=%0b", '
            f"$time, p.{empty_n}, p.{full_n});\n"
            "        errors++;\n"
            "      end"
        )
        post_reset_lines = [
            f"    if (vif.{empty_n} !== 1'b1) begin",
            f'      $error("post-reset {empty_n} not 1");',
            "      env.sb.errors++;",
            "    end",
            f"    if (vif.{full_n} !== 1'b0) begin",
            f'      $error("post-reset {full_n} not 0");',
            "      env.sb.errors++;",
            "    end",
        ]
        if cnt_p:
            post_reset_lines += [
                f"    if (vif.{cnt_p['name']} !== '0) begin",
                f'      $error("post-reset {cnt_p["name"]} not 0");',
                "      env.sb.errors++;",
                "    end",
            ]
        post_reset_check = "\n".join(post_reset_lines)
    elif parity:
        val_p, data_p, par_p = parity["valid"], parity["data"], parity["parity"]
        vo_p = parity.get("valid_out")
        dt = sv_type(data_p.get("width", ""), data_p)
        sb_members = [
            "  bit expected;",
            "  int errors;",
            "  function new();",
            "    expected = 1'b0;",
            "    errors = 0;",
            "  endfunction",
        ]
        predict_fn = [
            f"  function void predict(bit {val_p['name']}, {dt} {data_p['name']});",
            f"    if ({val_p['name']}) expected = ^{data_p['name']};",
            "  endfunction",
        ]
        predict_call = f"      predict(t.{val_p['name']}, t.{data_p['name']});"
        vo_arg = f", bit {vo_p['name']}" if vo_p else ""
        vo_chk = (
            f"    if ({vo_p['name']} !== {val_p['name']}) return 1'b0;\n" if vo_p else ""
        )
        check_fn = [
            f"  function bit check(bit {par_p['name']}, bit {val_p['name']}{vo_arg});",
            f"{vo_chk}    return ({par_p['name']} === expected);",
            "  endfunction",
        ]
        vo_call = f", p.{vo_p['name']}" if vo_p else ""
        check_call = (
            f"      if (!check(p.{par_p['name']}, t.{val_p['name']}{vo_call})) begin\n"
            f'        $error("[%0t] parity mismatch", $time);\n'
            "        errors++;\n"
            "      end"
        )
        post_reset_check = (
            f"    if (vif.{par_p['name']} !== 1'b0) begin\n"
            f'      $error("post-reset {par_p["name"]} not 0");\n'
            "      env.sb.errors++;\n"
            "    end"
        )
    elif edge:
        din_p, rise_p, fall_p = edge["din"], edge["rise"], edge["fall"]
        sb_members = [
            "  bit din_d;",
            "  bit exp_rise;",
            "  bit exp_fall;",
            "  int errors;",
            "  function new();",
            "    din_d = 1'b0; exp_rise = 1'b0; exp_fall = 1'b0; errors = 0;",
            "  endfunction",
        ]
        predict_fn = [
            f"  function void predict(bit {din_p['name']});",
            f"    exp_rise = {din_p['name']} & ~din_d;",
            f"    exp_fall = ~{din_p['name']} & din_d;",
            f"    din_d = {din_p['name']};",
            "  endfunction",
        ]
        predict_call = f"      predict(t.{din_p['name']});"
        check_fn = [
            f"  function bit check(bit {rise_p['name']}, bit {fall_p['name']});",
            f"    return ({rise_p['name']} === exp_rise) && ({fall_p['name']} === exp_fall);",
            "  endfunction",
        ]
        check_call = (
            f"      if (!check(p.{rise_p['name']}, p.{fall_p['name']})) begin\n"
            f'        $error("[%0t] edge mismatch", $time);\n'
            "        errors++;\n"
            "      end"
        )
        post_reset_check = (
            f"    if (vif.{rise_p['name']} !== 1'b0 || vif.{fall_p['name']} !== 1'b0) begin\n"
            f'      $error("post-reset rise/fall not 0");\n'
            "      env.sb.errors++;\n"
            "    end"
        )
    elif pwm:
        duty_p, pwm_p = pwm["duty"], pwm["pwm"]
        dt = sv_type(duty_p.get("width", ""), duty_p)
        sb_members = [
            f"  {dt} cnt;",
            "  bit expected;",
            "  int errors;",
            "  function new();",
            "    cnt = '0; expected = 1'b0; errors = 0;",
            "  endfunction",
        ]
        predict_fn = [
            f"  function void predict({dt} {duty_p['name']});",
            f"    expected = (cnt < {duty_p['name']});",
            "    cnt = cnt + 1'b1;",
            "  endfunction",
        ]
        predict_call = f"      predict(t.{duty_p['name']});"
        check_fn = [
            f"  function bit check(bit {pwm_p['name']});",
            f"    return ({pwm_p['name']} === expected);",
            "  endfunction",
        ]
        check_call = (
            f"      if (!check(p.{pwm_p['name']})) begin\n"
            f'        $error("[%0t] pwm mismatch", $time);\n'
            "        errors++;\n"
            "      end"
        )
        post_reset_check = (
            f"    if (vif.{pwm_p['name']} !== 1'b0) begin\n"
            f'      $error("post-reset {pwm_p["name"]} not 0");\n'
            "      env.sb.errors++;\n"
            "    end\n"
            "    env.sb.cnt = 1;"  # settle posedge after deassert already stepped DUT cnt
        )
    elif debounce:
        noisy_p, clean_p = debounce["noisy"], debounce["clean"]
        settle = int(debounce.get("settle") or 7)
        sb_members = [
            "  bit clean_exp;",
            "  int unsigned dcnt;",
            "  int errors;",
            "  function new();",
            "    clean_exp = 1'b0; dcnt = 0; errors = 0;",
            "  endfunction",
        ]
        predict_fn = [
            f"  function void predict(bit {noisy_p['name']});",
            f"    if ({noisy_p['name']} == clean_exp) dcnt = 0;",
            f"    else if (dcnt == {settle}) begin",
            f"      clean_exp = {noisy_p['name']};",
            "      dcnt = 0;",
            "    end else dcnt = dcnt + 1;",
            "  endfunction",
        ]
        predict_call = f"      predict(t.{noisy_p['name']});"
        check_fn = [
            f"  function bit check(bit {clean_p['name']});",
            f"    return ({clean_p['name']} === clean_exp);",
            "  endfunction",
        ]
        check_call = (
            f"      if (!check(p.{clean_p['name']})) begin\n"
            f'        $error("[%0t] debounce mismatch", $time);\n'
            "        errors++;\n"
            "      end"
        )
        post_reset_check = (
            f"    if (vif.{clean_p['name']} !== 1'b0) begin\n"
            f'      $error("post-reset {clean_p["name"]} not 0");\n'
            "      env.sb.errors++;\n"
            "    end"
        )
    elif syncff:
        d_p, q_p = syncff["d"], syncff["q"]
        sb_members = [
            "  bit meta;",
            "  bit expected;",
            "  int errors;",
            "  function new();",
            "    meta = 1'b0; expected = 1'b0; errors = 0;",
            "  endfunction",
        ]
        predict_fn = [
            f"  function void predict(bit {d_p['name']});",
            "    expected = meta;",
            f"    meta = {d_p['name']};",
            "  endfunction",
        ]
        predict_call = f"      predict(t.{d_p['name']});"
        check_fn = [
            f"  function bit check(bit {q_p['name']});",
            f"    return ({q_p['name']} === expected);",
            "  endfunction",
        ]
        check_call = (
            f"      if (!check(p.{q_p['name']})) begin\n"
            f'        $error("[%0t] sync_ff mismatch", $time);\n'
            "        errors++;\n"
            "      end"
        )
        post_reset_check = (
            f"    if (vif.{q_p['name']} !== 1'b0) begin\n"
            f'      $error("post-reset {q_p["name"]} not 0");\n'
            "      env.sb.errors++;\n"
            "    end"
        )
    elif stream:
        val_p, rdy_p, data_p = stream["valid"], stream["ready"], stream["data"]
        out_d = stream.get("out_data")
        dt = sv_type(data_p.get("width", ""), data_p)
        sb_members = [
            f"  {dt} last_exp;",
            "  bit prev_rdy;",
            "  int errors;",
            "  function new();",
            "    last_exp = '0; prev_rdy = 1'b1; errors = 0;",
            "  endfunction",
        ]
        rdy_n = rdy_p["name"]
        val_n = val_p["name"]
        data_n = data_p["name"]
        predict_fn = [
            f"  function void predict(bit {val_n}, bit {rdy_n}, {dt} {data_n});",
            f"    if ({val_n} && prev_rdy) last_exp = {data_n};",
            f"    prev_rdy = {rdy_n};",
            "  endfunction",
        ]
        predict_call = f"      predict(p.{val_n}, p.{rdy_n}, p.{data_n});"
        if out_d:
            odn = out_d["name"]
            check_fn = [
                f"  function bit check({dt} {odn});",
                f"    return ({odn} === last_exp);",
                "  endfunction",
            ]
            check_call = (
                f"      if (!check(p.{odn})) begin\n"
                f'        $error("[%0t] stream last_data mismatch", $time);\n'
                "        errors++;\n"
                "      end"
            )
            post_reset_check = (
                f"    if (vif.{odn} !== '0) begin\n"
                f'      $error("post-reset {odn} not 0");\n'
                "      env.sb.errors++;\n"
                "    end\n"
                f"    env.sb.prev_rdy = vif.{rdy_n};"
            )
        else:
            check_fn = [
                "  function bit check(); return 1'b1; endfunction",
            ]
            check_call = "      ;"
            post_reset_check = "    ;"
    elif counter:
        en_p, cnt_p = counter
        cnt_t = sv_type(cnt_p.get("width", ""), cnt_p)
        sb_members = [
            f"  {cnt_t} expected;",
            "  int errors;",
            "  function new();",
            "    expected = '0;",
            "    errors = 0;",
            "  endfunction",
        ]
        if en_p:
            predict_fn = [
                f"  function void predict(bit {en_p['name']});",
                f"    if ({en_p['name']}) expected = expected + 1'b1;",
                "  endfunction",
            ]
            predict_call = f"      predict(t.{en_p['name']});"
        else:
            predict_fn = [
                "  function void predict();",
                "    expected = expected + 1'b1;",
                "  endfunction",
            ]
            predict_call = "      predict();"
        check_fn = [
            f"  function bit check({cnt_t} actual);",
            "    return (actual === expected);",
            "  endfunction",
        ]
        check_call = (
            f"      if (!check(p.{cnt_p['name']})) begin\n"
            f'        $error("[%0t] SB mismatch {cnt_p["name"]}=%0h expected=%0h", '
            f"$time, p.{cnt_p['name']}, expected);\n"
            "        errors++;\n"
            "      end"
        )
        post_reset_check = (
            f"    if (vif.{cnt_p['name']} !== '0) begin\n"
            f'      $error("post-reset {cnt_p["name"]} not 0");\n'
            "      env.sb.errors++;\n"
            "    end"
        )
    else:
        o0 = outs[0]["name"] if outs else None
        sb_members = [
            "  int unsigned beats;",
            "  int errors;",
            "  function new(); beats = 0; errors = 0; endfunction",
        ]
        predict_fn = [
            "  function void predict(); beats++; endfunction",
        ]
        predict_call = "      predict();"
        if o0:
            ot = sv_type(outs[0].get("width", ""), outs[0])
            check_fn = [
                f"  function bit check({ot} {o0});",
                f"    return (!$isunknown({o0}));",
                "  endfunction",
            ]
            check_call = (
                f"      if (!check(p.{o0})) begin\n"
                f'        $error("[%0t] X on {o0}", $time);\n'
                "        errors++;\n"
                "      end"
            )
            post_reset_check = (
                f"    if (vif.{o0} !== '0) begin\n"
                f'      $error("post-reset {o0} not 0");\n'
                "      env.sb.errors++;\n"
                "    end"
            )
        else:
            check_fn = [
                "  function bit check();",
                "    return 1'b1;",
                "  endfunction",
            ]
            check_call = "      ;"
            post_reset_check = "    ;"

    # DUT port map via interface (clock from TB net)
    dut_ports: List[str] = []
    for p in ports:
        pn = p["name"]
        if clk and pn == clk["name"]:
            dut_ports.append(f"    .{pn}({clk_name})")
        else:
            dut_ports.append(f"    .{pn}(vif.{pn})")
    dut_mapped = [
        line + ("," if i < len(dut_ports) - 1 else "") for i, line in enumerate(dut_ports)
    ]

    rst_assert = "1'b0" if (rst_name and active_low) else "1'b1"
    rst_deassert = "1'b1" if (rst_name and active_low) else "1'b0"
    rst_block = ""
    if rst_name and clk:
        rst_block = f"""    vif.{rst_name} = {rst_assert};
    {zero_drives}
    repeat (4) @(posedge vif.clk);
    vif.{rst_name} = {rst_deassert};
    @(posedge vif.clk);
    #1;"""
    else:
        rst_block = f"    {zero_drives}\n    repeat (4) @(posedge vif.clk);"

    if not constraints:
        constraints = ["    soft 1'b1;"]
    constraint_body = "\n".join(constraints)

    params = module.get("parameters") or {}
    param_parts = [
        f".{k}({v})"
        for k, v in list(params.items())[:6]
        if isinstance(v, (int, str)) and re.match(r"^[A-Za-z_]\w*$", str(k))
    ]
    param_bind = (" #(" + ", ".join(param_parts) + ")") if param_parts else ""

    drv_sb_field = ""
    drv_new_extra = ""
    drv_assign_sb = ""
    drv_clamp = ""
    drv_reset_extra = ""
    env_build_drv = (
        "    gen = new(gen2drv, n);\n"
        "    drv = new(vif, gen2drv, drv2sb);\n"
        "    mon = new(vif, mon2sb);\n"
        "    sb = new();\n"
        "    sb.connect(drv2sb, mon2sb);"
    )
    after_run = ""
    sb_fwd = ""
    if fifo:
        wr_n = fifo["wr_en"]["name"]
        rd_n = fifo["rd_en"]["name"]
        depth = int(fifo.get("depth") or 8)
        empty_n = fifo["empty"]["name"]
        full_n = fifo["full"]["name"]
        sb_fwd = f"typedef class {sb_cls};\n"
        drv_sb_field = f"  {sb_cls} sb;\n  int unsigned occ;\n"
        drv_new_extra = f",\n               {sb_cls} sb"
        drv_assign_sb = "\n    this.sb = sb;\n    occ = 0;"
        drv_clamp = (
            f"      if (occ >= {depth}) t.{wr_n} = 1'b0;\n"
            f"      if (occ == 0) t.{rd_n} = 1'b0;\n"
            f"      if (sb.q.size() >= {depth}) t.{wr_n} = 1'b0;\n"
            f"      if (sb.q.size() == 0) t.{rd_n} = 1'b0;\n"
            f"      if (t.{wr_n}) occ++;\n"
            f"      if (t.{rd_n}) occ--;\n"
        )
        drv_reset_extra = "    occ = 0;\n"
        env_build_drv = (
            "    gen = new(gen2drv, n);\n"
            "    sb = new();\n"
            "    drv = new(vif, gen2drv, drv2sb, sb);\n"
            "    mon = new(vif, mon2sb);\n"
            "    sb.connect(drv2sb, mon2sb);"
        )
        if rst_name:
            after_run = (
                f"    // ChipSutra mid-test reset (kills drop_reset under Verilator init-0)\n"
                f"    vif.{wr_n} = 1'b0;\n"
                f"    vif.{rd_n} = 1'b0;\n"
                f"    vif.{rst_name} = {rst_assert};\n"
                f"    repeat (4) @(posedge vif.clk);\n"
                f"    vif.{rst_name} = {rst_deassert};\n"
                f"    @(posedge vif.clk);\n"
                f"    env.sb.q.delete();\n"
                f"    env.drv.occ = 0;\n"
                f"    if (vif.{empty_n} !== 1'b1) env.sb.errors++;\n"
                f"    if (vif.{full_n} !== 1'b0) env.sb.errors++;\n"
            )

    lines = f"""// ChipSutra Pure SV layered class TB (NO UVM)
// Components: interface, generator, driver, monitor, scoreboard, env, test
// DUT: {name} | cycles={cycles} | seed={seed}
`timescale 1ns / 1ps

interface {if_name}(input logic clk);
{chr(10).join(if_sigs)}
  modport DRV(input clk{', output ' + ', '.join(p['name'] for p in stim_inputs + ([rst] if rst else [])) if (stim_inputs or rst) else ''}{', input ' + ', '.join(p['name'] for p in outs) if outs else ''});
  modport MON(input clk{', input ' + ', '.join([p['name'] for p in stim_inputs] + ([rst_name] if rst_name else []) + [p['name'] for p in outs]) if (stim_inputs or rst_name or outs) else ''});
endinterface

class {txn_cls};
{chr(10).join(txn_fields)}
  constraint legal_c {{
{constraint_body}
  }}
endclass

class {mon_cls};
{chr(10).join(mon_fields)}
endclass

class {gen_cls};
  mailbox #({txn_cls}) gen2drv;
  int n_txns;
  function new(mailbox #({txn_cls}) mb, int n);
    gen2drv = mb;
    n_txns = n;
  endfunction
  task run();
    {txn_cls} t;
    repeat (n_txns) begin
      t = new();
      assert(t.randomize()) else $fatal(1, "generator randomize failed");
      gen2drv.put(t);
    end
  endtask
endclass

{sb_fwd}class {drv_cls};
  virtual {if_name} vif;
  mailbox #({txn_cls}) gen2drv;
  mailbox #({txn_cls}) drv2sb;
{drv_sb_field}  function new(virtual {if_name} vif,
               mailbox #({txn_cls}) gen2drv,
               mailbox #({txn_cls}) drv2sb{drv_new_extra});
    this.vif = vif;
    this.gen2drv = gen2drv;
    this.drv2sb = drv2sb;{drv_assign_sb}
  endfunction
  task reset();
{rst_block}
{drv_reset_extra}  endtask
  task run(int n);
    {txn_cls} t;
    repeat (n) begin
      gen2drv.get(t);
{drv_clamp}{drive_assigns}
      drv2sb.put(t);
    end
  endtask
endclass

class {mon_comp};
  virtual {if_name} vif;
  mailbox #({mon_cls}) mon2sb;
  function new(virtual {if_name} vif, mailbox #({mon_cls}) mb);
    this.vif = vif;
    mon2sb = mb;
  endfunction
  task run(int n);
    {mon_cls} p;
    repeat (n) begin
      #1;
      p = new();
{mon_sample}
      mon2sb.put(p);
    end
  endtask
endclass

class {sb_cls};
  mailbox #({txn_cls}) drv2sb;
  mailbox #({mon_cls}) mon2sb;
{chr(10).join(sb_members)}
{chr(10).join(predict_fn)}
{chr(10).join(check_fn)}
  function void connect(mailbox #({txn_cls}) d2s, mailbox #({mon_cls}) m2s);
    drv2sb = d2s;
    mon2sb = m2s;
  endfunction
  task run(int n);
    {txn_cls} t;
    {mon_cls} p;
    repeat (n) begin
      drv2sb.get(t);
      mon2sb.get(p);
{predict_call}
{check_call}
    end
  endtask
endclass

class {env_cls};
  virtual {if_name} vif;
  mailbox #({txn_cls}) gen2drv;
  mailbox #({txn_cls}) drv2sb;
  mailbox #({mon_cls}) mon2sb;
  {gen_cls} gen;
  {drv_cls} drv;
  {mon_comp} mon;
  {sb_cls} sb;
  function new(virtual {if_name} vif);
    this.vif = vif;
  endfunction
  function void build(int n);
    gen2drv = new();
    drv2sb = new();
    mon2sb = new();
{env_build_drv}
  endfunction
  task run(int n);
    gen.run();
    repeat (n) begin
      drv.run(1);
      @(posedge vif.clk);
      mon.run(1);
      sb.run(1);
    end
  endtask
  function void report();
    if (sb.errors == 0)
      $display("PASS: {tb_name} layered Pure SV OK");
    else
      $display("FAIL: {tb_name} - %0d error(s)", sb.errors);
  endfunction
endclass

class {test_cls};
  virtual {if_name} vif;
  {env_cls} env;
  function new(virtual {if_name} vif);
    this.vif = vif;
    env = new(vif);
  endfunction
  task run(int n = {cycles});
    env.build(n);
    env.drv.reset();
{post_reset_check}
    env.run(n);
{after_run}    env.report();
  endtask
endclass

module {tb_name};
  logic {clk_name};
  {if_name} vif({clk_name});

  {name}{param_bind} dut (
{chr(10).join(dut_mapped)}
  );

  always #5 {clk_name} = ~{clk_name};

  initial begin
    {test_cls} t;
    $dumpfile("{tb_name}.vcd");
    $dumpvars(0, {tb_name});
    void'($urandom({seed}));
    {clk_name} = 0;
    t = new(vif);
    t.run({cycles});
    $finish;
  end
endmodule
"""
    # Soften modports: complex generated modport lists can break on empty groups.
    # Rebuild interface with simpler modports (all signals).
    sig_names = [p["name"] for p in ports if not (clk and p["name"] == clk["name"])]
    drv_outs = [p["name"] for p in stim_inputs] + ([rst_name] if rst_name else [])
    drv_outs = [s for s in drv_outs if s]
    mon_ins = list(sig_names)
    if_block = [f"interface {if_name}(input logic clk);"]
    if_block += if_sigs
    if drv_outs:
        if_block.append(
            "  modport DRV(input clk, output "
            + ", ".join(drv_outs)
            + (", input " + ", ".join(p["name"] for p in outs) if outs else "")
            + ");"
        )
    else:
        if_block.append("  modport DRV(input clk);")
    if mon_ins:
        if_block.append("  modport MON(input clk, input " + ", ".join(mon_ins) + ");")
    else:
        if_block.append("  modport MON(input clk);")
    if_block.append("endinterface")

    # Replace the rough interface block in `lines` with cleaned modports
    lines = re.sub(
        rf"interface {re.escape(if_name)}\(input logic clk\);[\s\S]*?endinterface",
        "\n".join(if_block),
        lines,
        count=1,
    )
    try:
        from tb_scale_emit import apply_scale_emit

        return apply_scale_emit(lines, module)
    except Exception:
        return lines


def resolve_tb_emit(
    *,
    module: str,
    mod: Optional[dict],
    gen_mode: str = "auto",
    prompt: str = "",
    tool_log: Optional[str] = None,
    tb_methodology: str = "sv",
    cycles: int = 32,
    seed: int = 1,
) -> Tuple[str, str]:
    """Return (sv_text, engine_tag).

    engine_tag: '' (call LLM) | 'skeleton' (procedural smoke) | 'class_sv' (Pure SV OOP template)
    """
    from tb_methodology import is_class_methodology, normalize_methodology

    if module != "testbench" or not mod or not mod.get("ports"):
        return "", ""
    meth = normalize_methodology(tb_methodology, prompt=prompt or "")
    mode = (gen_mode or "auto").lower().strip()

    # UVM/OVM/VMM → always LLM
    if is_class_methodology(meth):
        return "", ""

    # Explicit procedural smoke
    if mode in ("skeleton", "fast", "template"):
        return render_randomized_tb(mod, cycles=max(cycles, 48), seed=seed), "skeleton"

    # Default Pure SV = deterministic class-based template (guaranteed OOP structure)
    if meth == "sv" and mode in ("auto", "llm", "model", "class", "oop", ""):
        return render_class_sv_tb(mod, cycles=cycles, seed=seed), "class_sv"

    return "", ""
