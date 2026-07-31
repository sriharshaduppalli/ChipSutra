"""Deterministic Verilator-friendly randomized SystemVerilog testbench emitter.

Builds a compact TB from parsed RTL ports (no LLM). Prefer this path for speed;
fall back to the LLM when the user asks for UVM / complex agents or when ports
cannot be parsed.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple


_CLK_RE = re.compile(r"^(clk|clock|clk_i|clk_in|aclk|pclk|sclk)$", re.I)
_RST_RE = re.compile(r"^(rst|reset|areset|aresetn|rst_n|reset_n|rstn|nreset|nrst|rst_async_n)$", re.I)
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
    if need_in.issubset(names_in) and need_out.issubset(names_out):
        return {"style": "s_axi", "num_regs": 4}
    return None


def detect_counter_model(roles: Dict[str, Any]) -> Optional[Tuple[Optional[dict], dict]]:
    """Return (enable_port_or_None, count_port) for enable or free-running counters."""
    if detect_fifo_model(roles) or detect_axi_lite_model(roles) or detect_parity_model(roles):
        return None
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


def should_use_tb_skeleton(
    *,
    module: str,
    prompt: str = "",
    modules: Optional[List[dict]] = None,
    gen_mode: str = "auto",
    tool_log: Optional[str] = None,
) -> bool:
    """Decide whether to emit a deterministic skeleton instead of calling the LLM."""
    if module != "testbench":
        return False
    if not (modules and modules[0].get("ports")):
        return False
    mode = (gen_mode or "auto").lower().strip()
    if mode in ("skeleton", "fast", "template", "auto"):
        if tool_log and tool_log.strip() and mode == "auto":
            return False
        if _FORCE_LLM_RE.search(prompt or "") and mode == "auto":
            return False
        return True
    if mode in ("llm", "model"):
        # Explicit LLM / UVM mode: always call the model (skeleton still used as lint fallback).
        return False
    return True


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


def _emit_axi_lite_loop(clk_name: str, cycles: int) -> Tuple[List[str], List[str]]:
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
    return decls, loop


def _emit_generic_loop(roles: Dict[str, Any], clk_name: Optional[str], cycles: int) -> List[str]:
    lines = [
        f"    // Randomized stimulus over {cycles} cycles (generic DUT - add protocol golden when known)",
        f"    for (i = 0; i < {cycles}; i = i + 1) begin",
    ]
    for p in roles["inputs"]:
        bits_i = width_bits(p.get("width", ""), p)
        lines.append(
            f"      {p['name']} = $urandom_range(0, 1);"
            if bits_i == 1
            else f"      {p['name']} = {bits_i}'($urandom());"
        )
    if clk_name:
        lines.append(f"      @(posedge {clk_name});")
    else:
        lines.append("      #10;")
    if roles["outputs"]:
        outs = ", ".join("%0h" for _ in roles["outputs"])
        args = ", ".join(p["name"] for p in roles["outputs"])
        lines.append(f'      $display("[%0t] i=%0d outs: {outs}", $time, i, {args});')
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
    parity = None if (fifo or axi) else detect_parity_model(roles)
    counter = None if (fifo or axi or parity) else detect_counter_model(roles)

    if fifo:
        model_kind = "fifo"
    elif axi:
        model_kind = "axi_lite"
    elif parity:
        model_kind = "parity"
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
    if fifo:
        fifo_decls, fifo_loop = _emit_fifo_loop(fifo, clk_name, cycles)
        extra_decls = fifo_decls
    elif axi:
        axi_decls, axi_loop = _emit_axi_lite_loop(clk_name, cycles)
        extra_decls = axi_decls
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
    elif parity:
        body_lines += _emit_parity_loop(parity, clk_name, cycles)
    else:
        body_lines += _emit_generic_loop(roles, clk_name if clk else None, cycles)

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
        "parity": "golden: XOR parity on valid",
        "generic": "stimulus-only (add protocol golden when known)",
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
