"""Deterministic UVM smoke TB skeleton — DUT-correct top + protocol golden.

Used as: (1) LLM style reference for methodology=uvm, (2) mechanical fallback when
LLM UVM fails hard lint (missing DUT / broken TLM / empty scoreboard).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from tb_skeleton import (
    classify_ports,
    detect_counter_model,
    detect_fifo_model,
    detect_mux_model,
    detect_parity_model,
    detect_switch_model,
    sv_type,
    width_bits,
)


def _safe_id(name: str, fallback: str = "dut") -> str:
    n = "".join(c if c.isalnum() or c == "_" else "_" for c in (name or fallback))
    if not n or n[0].isdigit():
        n = "d_" + n
    return n


def _iface_signals(ports: List[dict], clk_name: Optional[str]) -> List[str]:
    lines = []
    for p in ports:
        n = p.get("name") or ""
        if not n:
            continue
        if clk_name and n == clk_name:
            continue  # clock is interface port
        lines.append(f"  {sv_type(p.get('width') or '', p)} {n};")
    return lines


def _dut_port_map(ports: List[dict], *, vif: str = "vif", clk_name: Optional[str] = None) -> List[str]:
    conns = []
    for p in ports:
        n = p.get("name") or ""
        if not n:
            continue
        if clk_name and n == clk_name:
            conns.append(f"    .{n}({clk_name})")
        else:
            conns.append(f"    .{n}({vif}.{n})")
    return conns


def _rand_field(p: dict) -> str:
    n = p["name"]
    bits = width_bits(p.get("width") or "", p)
    if bits == 1:
        return f"  rand bit {n};"
    return f"  rand logic [{bits - 1}:0] {n};"


def _obs_field(p: dict) -> str:
    n = p["name"]
    bits = width_bits(p.get("width") or "", p)
    if bits == 1:
        return f"  bit {n};"
    return f"  logic [{bits - 1}:0] {n};"


def _detect_kind(
    cls: Dict[str, Any], parameters: Optional[Dict[str, Any]] = None
) -> Tuple[str, dict]:
    """Return (kind, model) for protocol-aware UVM scoreboards."""
    from tb_skeleton import (
        detect_apb_model,
        detect_axi_lite_model,
        detect_stream_model,
    )

    fifo = detect_fifo_model(cls, parameters)
    if fifo:
        return "fifo", fifo
    switch = detect_switch_model(cls)
    if switch:
        return "switch", switch
    mux = detect_mux_model(cls)
    if mux:
        return "mux", mux
    parity = detect_parity_model(cls)
    if parity:
        return "parity", parity
    axi = detect_axi_lite_model(cls)
    if axi:
        return "axi", axi
    apb = detect_apb_model(cls)
    if apb:
        return "apb", apb
    stream = detect_stream_model(cls)
    if stream:
        return "stream", stream
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
    except Exception:
        detect_ahb_model = detect_alu_model = detect_debounce_model = None  # type: ignore
        detect_can_model = detect_edge_model = detect_gray_model = detect_i2c_model = None  # type: ignore
        detect_prio_enc_model = detect_pwm_model = detect_shifter_model = None  # type: ignore
        detect_spi_model = detect_sync_ff_model = detect_uart_model = detect_uart_rx_model = None  # type: ignore

    for kind, fn in (
        ("alu", detect_alu_model),
        ("prio", detect_prio_enc_model),
        ("shifter", detect_shifter_model),
        ("gray", detect_gray_model),
        ("edge", detect_edge_model),
        ("pwm", detect_pwm_model),
        ("debounce", detect_debounce_model),
        ("syncff", detect_sync_ff_model),
        ("ahb", detect_ahb_model),
        ("can", detect_can_model),
        ("spi", detect_spi_model),
        ("uart", detect_uart_model),
        ("uart_rx", detect_uart_rx_model),
        ("i2c", detect_i2c_model),
    ):
        if fn is None:
            continue
        model = fn(cls)
        if model:
            return kind, model
    counter = detect_counter_model(cls)
    if counter:
        en, count = counter
        return "counter", {"enable": en, "count": count}
    return "generic", {}


def _build_txn_fields(
    kind: str,
    model: dict,
    inputs: List[dict],
    outputs: List[dict],
    *,
    rst: Optional[dict] = None,
    tb_clk: str = "clk",
) -> Tuple[List[str], List[str], List[str]]:
    """Return (txn_fields, drive_assigns, mon_sample_assigns)."""
    if kind == "counter":
        en, count = model.get("enable"), model["count"]
        fields = []
        drive = []
        sample = []
        if rst and rst.get("name"):
            fields.append(_obs_field(rst))
            sample.append(f"      t.{rst['name']} = vif.{rst['name']};")
        if en:
            fields.append(_rand_field(en))
            drive.append(f"      vif.{en['name']} = req.{en['name']};")
            sample.append(f"      t.{en['name']} = vif.{en['name']};")
        fields.append(_obs_field(count))
        sample.append(f"      t.{count['name']} = vif.{count['name']};")
        return fields, drive or ["      ;"], sample

    if kind == "mux":
        sel = model["sel"]
        y = model["y"]
        data = list(model.get("data") or [])
        fields = [_rand_field(sel)] + [_rand_field(p) for p in data] + [_obs_field(y)]
        drive = [f"      vif.{sel['name']} = req.{sel['name']};"]
        drive += [f"      vif.{p['name']} = req.{p['name']};" for p in data]
        sample = [f"      t.{sel['name']} = vif.{sel['name']};"]
        sample += [f"      t.{p['name']} = vif.{p['name']};" for p in data]
        sample.append(f"      t.{y['name']} = vif.{y['name']};")
        return fields, drive, sample

    if kind == "switch":
        addr, data = model["addr"], model["data"]
        vld = model.get("vld")
        outs = [model["addr_a"], model["data_a"], model["addr_b"], model["data_b"]]
        fields = [_rand_field(addr), _rand_field(data)]
        drive = [
            f"      vif.{addr['name']} = req.{addr['name']};",
            f"      vif.{data['name']} = req.{data['name']};",
        ]
        sample = [
            f"      t.{addr['name']} = vif.{addr['name']};",
            f"      t.{data['name']} = vif.{data['name']};",
        ]
        if vld:
            fields.append(_rand_field(vld))
            drive.append(f"      vif.{vld['name']} = req.{vld['name']};")
            sample.append(f"      t.{vld['name']} = vif.{vld['name']};")
        fields += [_obs_field(p) for p in outs]
        # ChipVerify Example 2: outputs appear one cycle after the input sample.
        sample.append(f"      @(posedge vif.{tb_clk});")
        sample.append("      #1;")
        sample += [f"      t.{p['name']} = vif.{p['name']};" for p in outs]
        return fields, drive, sample

    if kind == "parity":
        valid, data, parity = model["valid"], model["data"], model["parity"]
        fields = [_rand_field(valid), _rand_field(data), _obs_field(parity)]
        drive = [
            f"      vif.{valid['name']} = req.{valid['name']};",
            f"      vif.{data['name']} = req.{data['name']};",
        ]
        sample = [
            f"      t.{valid['name']} = vif.{valid['name']};",
            f"      t.{data['name']} = vif.{data['name']};",
            f"      t.{parity['name']} = vif.{parity['name']};",
        ]
        return fields, drive, sample

    if kind == "fifo":
        wr_en, wr_data = model["wr_en"], model["wr_data"]
        rd_en, rd_data = model["rd_en"], model["rd_data"]
        full, empty = model["full"], model["empty"]
        fields = [
            _rand_field(wr_en),
            _rand_field(wr_data),
            _rand_field(rd_en),
            _obs_field(rd_data),
            _obs_field(full),
            _obs_field(empty),
        ]
        drive = [
            f"      vif.{wr_en['name']} = req.{wr_en['name']};",
            f"      vif.{wr_data['name']} = req.{wr_data['name']};",
            f"      vif.{rd_en['name']} = req.{rd_en['name']};",
        ]
        sample = [
            f"      t.{wr_en['name']} = vif.{wr_en['name']};",
            f"      t.{wr_data['name']} = vif.{wr_data['name']};",
            f"      t.{rd_en['name']} = vif.{rd_en['name']};",
            f"      t.{rd_data['name']} = vif.{rd_data['name']};",
            f"      t.{full['name']} = vif.{full['name']};",
            f"      t.{empty['name']} = vif.{empty['name']};",
        ]
        return fields, drive, sample

    if kind == "spi":
        mosi, cs, rx = model["mosi"], model["cs"], model["rx"]
        fields = ["  rand logic [7:0] data;"]
        for p in (mosi, cs, rx, model.get("miso"), model.get("rx_valid")):
            if p and p.get("name"):
                fields.append(_obs_field(p))
        drive = [
            f"      vif.{cs['name']} = 1'b1;",
            f"      vif.{mosi['name']} = 1'b0;",
        ]
        sample = [
            f"      t.{mosi['name']} = vif.{mosi['name']};",
            f"      t.{cs['name']} = vif.{cs['name']};",
            f"      t.{rx['name']} = vif.{rx['name']};",
        ]
        if model.get("rx_valid"):
            sample.append(
                f"      t.{model['rx_valid']['name']} = vif.{model['rx_valid']['name']};"
            )
        return fields, drive, sample

    if kind == "uart":
        din, start, tx = model["din"], model["start"], model["tx"]
        fields = [_rand_field(din), _rand_field(start)]
        drive = [
            f"      vif.{din['name']} = req.{din['name']};",
            f"      vif.{start['name']} = req.{start['name']};",
        ]
        sample = [
            f"      t.{din['name']} = vif.{din['name']};",
            f"      t.{start['name']} = vif.{start['name']};",
            f"      t.{tx['name']} = vif.{tx['name']};",
        ]
        for key in ("busy", "done", "last"):
            p = model.get(key)
            if p and p.get("name"):
                fields.append(_obs_field(p))
                sample.append(f"      t.{p['name']} = vif.{p['name']};")
        if rst and rst.get("name"):
            fields.append(_obs_field(rst))
            sample.append(f"      t.{rst['name']} = vif.{rst['name']};")
        return fields, drive, sample

    if kind == "uart_rx":
        rx, dout = model["rx"], model["dout"]
        fields = [_rand_field(rx), _obs_field(dout)]
        drive = [f"      vif.{rx['name']} = req.{rx['name']};"]
        sample = [
            f"      t.{rx['name']} = vif.{rx['name']};",
            f"      t.{dout['name']} = vif.{dout['name']};",
        ]
        if model.get("valid"):
            fields.append(_obs_field(model["valid"]))
            sample.append(
                f"      t.{model['valid']['name']} = vif.{model['valid']['name']};"
            )
        return fields, drive, sample

    if kind == "i2c":
        sda, start, last = model["sda"], model["start"], model["last"]
        fields = ["  rand logic [7:0] data;", _rand_field(start)]
        drive = [f"      vif.{start['name']} = req.{start['name']};"]
        sample = [
            f"      t.{sda['name']} = vif.{sda['name']};",
            f"      t.{start['name']} = vif.{start['name']};",
            f"      t.{last['name']} = vif.{last['name']};",
        ]
        fields += [_obs_field(sda), _obs_field(last)]
        for key in ("got", "sda_out"):
            p = model.get(key)
            if p and p.get("name"):
                fields.append(_obs_field(p))
                sample.append(f"      t.{p['name']} = vif.{p['name']};")
        return fields, drive, sample

    # generic: rand all inputs, observe all outputs (+ rst so sequential goldens can skip reset)
    fields = [_rand_field(p) for p in inputs if p.get("name")]
    if not fields:
        fields = ["  rand bit pad;"]
    if rst and rst.get("name"):
        fields.append(_obs_field(rst))
    fields += [_obs_field(p) for p in outputs if p.get("name")]
    drive = [f"      vif.{p['name']} = req.{p['name']};" for p in inputs if p.get("name")] or [
        "      ;"
    ]
    sample = [f"      t.{p['name']} = vif.{p['name']};" for p in inputs if p.get("name")]
    if rst and rst.get("name"):
        sample.append(f"      t.{rst['name']} = vif.{rst['name']};")
    sample += [f"      t.{p['name']} = vif.{p['name']};" for p in outputs if p.get("name")]
    return fields, drive, sample


def _scoreboard_body(
    kind: str, model: dict, txn: str, *, rst: Optional[dict] = None, active_low: bool = True
) -> str:
    """Scoreboard members + write() with independent golden (no DUT mirroring)."""
    if kind == "counter":
        en = model.get("enable")
        count = model["count"]
        bits = width_bits(count.get("width") or "", count)
        cn, en_n = count["name"], (en or {}).get("name")
        en_pred = f"t.{en_n}" if en_n else "1'b1"
        if rst and rst.get("name"):
            rn = rst["name"]
            in_reset = f"(!t.{rn})" if active_low else f"(t.{rn})"
            reset_arm = f"""
    if ({in_reset}) begin
      expected = '0;
      return;
    end"""
        else:
            reset_arm = ""
        return f"""  int unsigned errors;
  logic [{bits - 1}:0] expected;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    expected = '0;
  endfunction
  function void write({txn} t);{reset_arm}
    // Monitor samples after posedge+#1 — DUT already applied enable; predict then check.
    if ({en_pred})
      expected = expected + 1'b1;
    if (t.{cn} !== expected) begin
      `uvm_error("SCB", $sformatf("{cn} mismatch got=0x%0h exp=0x%0h en=%0b",
                 t.{cn}, expected, {en_pred}))
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: counter golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d counter mismatch(es)", errors))
  endfunction"""

    if kind == "mux":
        sel, y = model["sel"], model["y"]
        data = list(model.get("data") or [])
        bits = width_bits(y.get("width") or "", y)
        if model.get("kind") == "2to1" and len(data) >= 2:
            a, b = data[0]["name"], data[1]["name"]
            exp_assign = f"exp = t.{sel['name']} ? t.{b} : t.{a};"
        else:
            cases = "\n".join(
                f"      {i}: exp = t.{p['name']};" for i, p in enumerate(data)
            )
            exp_assign = f"case (t.{sel['name']})\n{cases}\n      default: exp = '0;\n    endcase"
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    logic [{bits - 1}:0] exp;
    {exp_assign}
    if (t.{y['name']} !== exp) begin
      `uvm_error("SCB", $sformatf("mux y mismatch got=0x%0h exp=0x%0h sel=%0d",
                 t.{y['name']}, exp, t.{sel['name']}))
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: mux golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d mux mismatch(es)", errors))
  endfunction"""

    if kind == "parity":
        valid, data, parity = model["valid"], model["data"], model["parity"]
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    bit exp;
    if (!t.{valid['name']}) return;
    exp = ^t.{data['name']};
    if (t.{parity['name']} !== exp) begin
      `uvm_error("SCB", $sformatf("parity mismatch got=%0b exp=%0b data=0x%0h",
                 t.{parity['name']}, exp, t.{data['name']}))
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: parity golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d parity mismatch(es)", errors))
  endfunction"""

    if kind == "fifo":
        wr_en, wr_data = model["wr_en"], model["wr_data"]
        rd_en, rd_data = model["rd_en"], model["rd_data"]
        full, empty = model["full"], model["empty"]
        depth = int(model.get("depth") or 8)
        wbits = width_bits(wr_data.get("width") or "", wr_data)
        return f"""  int unsigned errors;
  logic [{wbits - 1}:0] q[$];
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    int unsigned sz0;
    bit do_wr, do_rd;
    sz0 = q.size();
    do_wr = t.{wr_en['name']} && (sz0 < {depth});
    do_rd = t.{rd_en['name']} && (sz0 > 0);
    // FWFT-style: present head before pop; flags reflect post-op occupancy
    if (do_rd) begin
      if (t.{rd_data['name']} !== q[0]) begin
        `uvm_error("SCB", $sformatf("rd_data mismatch got=0x%0h exp=0x%0h",
                   t.{rd_data['name']}, q[0]))
        errors++;
      end
    end
    if (do_wr) q.push_back(t.{wr_data['name']});
    if (do_rd) void'(q.pop_front());
    if (t.{full['name']} !== (q.size() >= {depth})) begin
      `uvm_error("SCB", "full flag mismatch")
      errors++;
    end
    if (t.{empty['name']} !== (q.size() == 0)) begin
      `uvm_error("SCB", "empty flag mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: fifo golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d fifo mismatch(es)", errors))
  endfunction"""

    if kind == "switch":
        addr, data = model["addr"], model["data"]
        addr_a, data_a = model["addr_a"], model["data_a"]
        addr_b, data_b = model["addr_b"], model["data_b"]
        vld = model.get("vld")
        bits = max(1, width_bits(addr.get("width") or "", addr))
        thresh = 1 << (bits - 1)
        an, dn = addr["name"], data["name"]
        aa, da, ab, db = addr_a["name"], data_a["name"], addr_b["name"], data_b["name"]
        vld_guard = f"    if (!t.{vld['name']}) return;\n" if vld else ""
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    bit to_a;
{vld_guard}    // MSB split — do not invent a magic ChipVerify threshold unless the user spec says so.
    to_a = (t.{an} < {thresh});
    if (to_a) begin
      if (t.{aa} !== t.{an} || t.{da} !== t.{dn}) begin
        `uvm_error("SCB", $sformatf("port A mismatch addr=0x%0h data=0x%0h got A=(0x%0h,0x%0h)",
                   t.{an}, t.{dn}, t.{aa}, t.{da}))
        errors++;
      end
    end else begin
      if (t.{ab} !== t.{an} || t.{db} !== t.{dn}) begin
        `uvm_error("SCB", $sformatf("port B mismatch addr=0x%0h data=0x%0h got B=(0x%0h,0x%0h)",
                   t.{an}, t.{dn}, t.{ab}, t.{db}))
        errors++;
      end
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: switch golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d switch mismatch(es)", errors))
  endfunction"""

    if kind == "alu":
        a, b, op, y = model["a"], model["b"], model["op"], model["y"]
        bits = width_bits(y.get("width") or "", y)
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    logic [{bits - 1}:0] exp;
    case (t.{op['name']})
      0: exp = t.{a['name']} + t.{b['name']};
      1: exp = t.{a['name']} - t.{b['name']};
      2: exp = t.{a['name']} & t.{b['name']};
      default: exp = t.{a['name']} | t.{b['name']};
    endcase
    if (t.{y['name']} !== exp) begin
      `uvm_error("SCB", $sformatf("alu y mismatch got=0x%0h exp=0x%0h", t.{y['name']}, exp))
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: alu golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d alu mismatch(es)", errors))
  endfunction"""

    if kind == "prio":
        req, grant = model["req"], model["grant"]
        n = int(model.get("width") or width_bits(req.get("width") or "", req))
        vld = model.get("valid")
        assigns = "\n".join(
            [f"    if (t.{req['name']}[{n - 1}]) exp = {n - 1};"]
            + [f"    else if (t.{req['name']}[{i}]) exp = {i};" for i in range(n - 2, -1, -1)]
        )
        vld_chk = ""
        if vld:
            vld_chk = f"""
    if ((|t.{req['name']}) !== t.{vld['name']}) begin
      `uvm_error("SCB", "prio valid mismatch")
      errors++;
    end"""
        gbits = max(1, width_bits(grant.get("width") or "", grant))
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    logic [{gbits - 1}:0] exp;
    exp = '0;
{assigns}{vld_chk}
    if (t.{grant['name']} !== exp) begin
      `uvm_error("SCB", $sformatf("prio grant mismatch got=%0d exp=%0d", t.{grant['name']}, exp))
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: prio golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d prio mismatch(es)", errors))
  endfunction"""

    if kind == "shifter":
        din, shamt, dout = model["din"], model["shamt"], model["dout"]
        dirp = model.get("dir")
        bits = width_bits(dout.get("width") or "", dout)
        exp_line = (
            f"    exp = t.{dirp['name']} ? (t.{din['name']} >> t.{shamt['name']}) : (t.{din['name']} << t.{shamt['name']});"
            if dirp
            else f"    exp = t.{din['name']} << t.{shamt['name']};"
        )
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    logic [{bits - 1}:0] exp;
{exp_line}
    if (t.{dout['name']} !== exp) begin
      `uvm_error("SCB", "shifter mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: shifter golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d shifter mismatch(es)", errors))
  endfunction"""

    if kind == "gray":
        src, dst = model["src"], model["dst"]
        bits = width_bits(src.get("width") or "", src)
        if model.get("kind") == "bin2gray":
            exp_body = f"    exp = t.{src['name']} ^ (t.{src['name']} >> 1);"
        else:
            exp_body = " ^ ".join(
                [f"t.{src['name']}"] + [f"(t.{src['name']} >> {i})" for i in range(1, bits)]
            )
            exp_body = f"    exp = {exp_body};"
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
    logic [{bits - 1}:0] exp;
{exp_body}
    if (t.{dst['name']} !== exp) begin
      `uvm_error("SCB", "gray mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: gray golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d gray mismatch(es)", errors))
  endfunction"""

    if kind == "edge":
        din, rise, fall = model["din"], model["rise"], model["fall"]
        return f"""  int unsigned errors;
  bit din_d;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    din_d = 1'b0;
  endfunction
  function void write({txn} t);
    bit exp_r, exp_f;
    exp_r = t.{din['name']} & ~din_d;
    exp_f = ~t.{din['name']} & din_d;
    din_d = t.{din['name']};
    if (t.{rise['name']} !== exp_r || t.{fall['name']} !== exp_f) begin
      `uvm_error("SCB", "edge mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: edge golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d edge mismatch(es)", errors))
  endfunction"""

    if kind == "pwm":
        duty, pwm = model["duty"], model["pwm"]
        dbits = width_bits(duty.get("width") or "", duty)
        return f"""  int unsigned errors;
  logic [{dbits - 1}:0] cnt;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    cnt = '0;
  endfunction
  function void write({txn} t);
    bit exp;
    exp = (cnt < t.{duty['name']});
    cnt = cnt + 1'b1;
    if (t.{pwm['name']} !== exp) begin
      `uvm_error("SCB", "pwm mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: pwm golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d pwm mismatch(es)", errors))
  endfunction"""

    if kind == "debounce":
        noisy, clean = model["noisy"], model["clean"]
        settle = int(model.get("settle") or 7)
        return f"""  int unsigned errors;
  bit clean_exp;
  int unsigned dcnt;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    clean_exp = 1'b0;
    dcnt = 0;
  endfunction
  function void write({txn} t);
    if (t.{noisy['name']} == clean_exp) dcnt = 0;
    else if (dcnt == {settle}) begin
      clean_exp = t.{noisy['name']};
      dcnt = 0;
    end else dcnt = dcnt + 1;
    if (t.{clean['name']} !== clean_exp) begin
      `uvm_error("SCB", "debounce mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: debounce golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d debounce mismatch(es)", errors))
  endfunction"""

    if kind == "syncff":
        d, q = model["d"], model["q"]
        return f"""  int unsigned errors;
  bit meta;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    meta = 1'b0;
  endfunction
  function void write({txn} t);
    bit exp;
    exp = meta;
    meta = t.{d['name']};
    if (t.{q['name']} !== exp) begin
      `uvm_error("SCB", "sync_ff mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: sync_ff golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d sync_ff mismatch(es)", errors))
  endfunction"""

    if kind == "stream":
        val, rdy, data = model["valid"], model["ready"], model["data"]
        out_d = model.get("out_data")
        bits = width_bits((out_d or data).get("width") or "", out_d or data)
        odn = (out_d or {}).get("name") or "last_data"
        return f"""  int unsigned errors;
  logic [{bits - 1}:0] last_exp;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    last_exp = '0;
  endfunction
  function void write({txn} t);
    if (t.{val['name']} && t.{rdy['name']}) last_exp = t.{data['name']};
    if (t.{odn} !== last_exp) begin
      `uvm_error("SCB", "stream last_data mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: stream golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d stream mismatch(es)", errors))
  endfunction"""

    if kind == "axi":
        return f"""  int unsigned errors;
  logic [31:0] model_reg [0:3];
  bit [1:0] pend_ar;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
    pend_ar = 0;
  endfunction
  function void write({txn} t);
    if (t.s_axi_awvalid && t.s_axi_awready && t.s_axi_wvalid && t.s_axi_wready) begin
      if (t.s_axi_wstrb[0]) model_reg[t.s_axi_awaddr[3:2]][7:0] = t.s_axi_wdata[7:0];
      if (t.s_axi_wstrb[1]) model_reg[t.s_axi_awaddr[3:2]][15:8] = t.s_axi_wdata[15:8];
      if (t.s_axi_wstrb[2]) model_reg[t.s_axi_awaddr[3:2]][23:16] = t.s_axi_wdata[23:16];
      if (t.s_axi_wstrb[3]) model_reg[t.s_axi_awaddr[3:2]][31:24] = t.s_axi_wdata[31:24];
    end
    if (t.s_axi_arvalid && t.s_axi_arready) pend_ar = t.s_axi_araddr[3:2];
    if (t.s_axi_rvalid && t.s_axi_rready) begin
      if (t.s_axi_rdata !== model_reg[pend_ar] || t.s_axi_rresp !== 2'b00) begin
        `uvm_error("SCB", "AXI RDATA mismatch")
        errors++;
      end
    end
    if (t.s_axi_bvalid && t.s_axi_bready && t.s_axi_bresp !== 2'b00) begin
      `uvm_error("SCB", "AXI BRESP mismatch")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: axi_lite golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d axi mismatch(es)", errors))
  endfunction"""

    if kind == "apb":
        psel, pen, pw = model["psel"], model["penable"], model["pwrite"]
        pa, pwd, prd = model["paddr"], model["pwdata"], model["prdata"]
        return f"""  int unsigned errors;
  logic [31:0] model_reg [0:3];
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
  endfunction
  function void write({txn} t);
    if (t.{psel} && t.{pen}) begin
      if (t.{pw}) model_reg[t.{pa}[3:2]] = t.{pwd};
      else if (t.{prd} !== model_reg[t.{pa}[3:2]]) begin
        `uvm_error("SCB", "APB PRDATA mismatch")
        errors++;
      end
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: apb golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d apb mismatch(es)", errors))
  endfunction"""

    if kind == "ahb":
        return f"""  int unsigned errors;
  logic [31:0] model_reg [0:3];
  bit pend_wr;
  bit [1:0] pend_sel;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    pend_wr = 0;
    pend_sel = 0;
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
  endfunction
  function void write({txn} t);
    if (pend_wr) begin
      model_reg[pend_sel] = t.HWDATA;
      pend_wr = 0;
    end
    if (t.HSEL && t.HREADY && (t.HTRANS == 2'b10 || t.HTRANS == 2'b11)) begin
      if (t.HWRITE) begin
        pend_wr = 1;
        pend_sel = t.HADDR[3:2];
      end else if (t.HRDATA !== model_reg[t.HADDR[3:2]]) begin
        `uvm_error("SCB", "AHB HRDATA mismatch")
        errors++;
      end
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: ahb golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d ahb mismatch(es)", errors))
  endfunction"""

    if kind == "spi":
        mosi, cs, rx = model["mosi"], model["cs"], model["rx"]
        return f"""  int unsigned errors;
  logic [7:0] sh;
  int unsigned bit_cnt;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    sh = '0;
    bit_cnt = 0;
  endfunction
  function void write({txn} t);
    if (t.{cs['name']}) begin
      bit_cnt = 0;
      sh = '0;
      return;
    end
    sh = {{sh[6:0], t.{mosi['name']}}};
    bit_cnt = bit_cnt + 1;
    if (bit_cnt == 8) begin
      if (t.{rx['name']} !== sh) begin
        `uvm_error("SCB", $sformatf("spi rx mismatch got=0x%0h exp=0x%0h", t.{rx['name']}, sh))
        errors++;
      end
      bit_cnt = 0;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: spi golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d spi mismatch(es)", errors))
  endfunction"""

    if kind == "uart":
        din, start = model["din"], model["start"]
        last = model.get("last")
        reset_arm = ""
        if rst and rst.get("name"):
            rn = rst["name"]
            in_reset = f"(!t.{rn})" if active_low else f"(t.{rn})"
            reset_arm = f"""
    if ({in_reset}) begin
      latched = '0;
      return;
    end"""
        last_chk = ""
        if last:
            last_chk = f"""
    if (t.{start['name']} && t.{last['name']} !== t.{din['name']}) begin
      `uvm_error("SCB", $sformatf("uart last_byte mismatch got=0x%0h exp=0x%0h", t.{last['name']}, t.{din['name']}))
      errors++;
    end"""
        else:
            last_chk = f"""
    if (t.{start['name']})
      latched = t.{din['name']};"""
        return f"""  int unsigned errors;
  logic [7:0] latched;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    latched = '0;
  endfunction
  function void write({txn} t);{reset_arm}{last_chk}
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: uart golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d uart mismatch(es)", errors))
  endfunction"""

    if kind == "uart_rx":
        dout = model["dout"]
        valid = model.get("valid")
        vld_guard = (
            f"    if (!t.{valid['name']}) return;\n" if valid else ""
        )
        return f"""  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
  endfunction
  function void write({txn} t);
{vld_guard}    if (t.{dout['name']} === 'x) begin
      `uvm_error("SCB", "uart_rx dout is X when valid")
      errors++;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: uart_rx no-X OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d uart_rx mismatch(es)", errors))
  endfunction"""

    if kind == "i2c":
        sda, start, last = model["sda"], model["start"], model["last"]
        got = model.get("got")
        got_chk = ""
        if got:
            got_chk = f"""
      if (t.{got['name']} !== 1'b1) begin
        `uvm_error("SCB", "i2c got_write not set after 8 bits")
        errors++;
      end"""
        return f"""  int unsigned errors;
  logic [7:0] sh;
  int unsigned bit_cnt;
  bit active;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    errors = 0;
    sh = '0;
    bit_cnt = 0;
    active = 0;
  endfunction
  function void write({txn} t);
    if (t.{start['name']}) begin
      active = 1;
      bit_cnt = 0;
      sh = '0;
      return;
    end
    if (!active) return;
    sh = {{sh[6:0], t.{sda['name']}}};
    bit_cnt = bit_cnt + 1;
    if (bit_cnt == 8) begin
      if (t.{last['name']} !== sh) begin
        `uvm_error("SCB", $sformatf("i2c last_data mismatch got=0x%0h exp=0x%0h", t.{last['name']}, sh))
        errors++;
      end{got_chk}
      active = 0;
      bit_cnt = 0;
    end
  endfunction
  function void report_phase(uvm_phase phase);
    if (errors == 0) `uvm_info("SCB", "PASS: i2c golden OK", UVM_LOW)
    else `uvm_error("SCB", $sformatf("FAIL: %0d i2c mismatch(es)", errors))
  endfunction"""

    if kind == "vip_stub":
        proto = model.get("protocol") or "vip"
        return f"""  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
  endfunction
  function void write({txn} t);
    `uvm_info("VIP", "require_user_vip ({proto}) — no invented pin-level golden", UVM_LOW)
  endfunction
  function void report_phase(uvm_phase phase);
    `uvm_warning("VIP", "Attach user VIP monitor/scoreboard. ChipSutra stub only.")
  endfunction"""

    # generic: at least count samples + require non-placeholder (no silent pass)
    return f"""  int unsigned seen;
  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
    seen = 0;
    errors = 0;
  endfunction
  function void write({txn} t);
    seen++;
  endfunction
  function void report_phase(uvm_phase phase);
    // Unrecognized protocol: no invented golden — require traffic only
    if (seen == 0) `uvm_error("SCB", "FAIL: scoreboard saw 0 transactions")
    else `uvm_info("SCB", $sformatf("generic smoke saw %0d txn(s)", seen), UVM_LOW)
  endfunction"""


def _constraint_block(kind: str, model: dict) -> str:
    if kind == "fifo":
        # Prefer legal traffic: not both full-push and empty-pop nonsense every cycle
        wr, rd = model["wr_en"]["name"], model["rd_en"]["name"]
        return f"""
  constraint legal_c {{
    // keep some idle / single-sided cycles
    soft ({wr} != {rd});
  }}
"""
    if kind == "counter" and model.get("enable"):
        en = model["enable"]["name"]
        return f"""
  constraint legal_c {{
    soft {en} dist {{ 0 := 1, 1 := 3 }};
  }}
"""
    if kind == "switch":
        addr = model["addr"]
        bits = max(1, width_bits(addr.get("width") or "", addr))
        an = addr["name"]
        lines = ["    // Cover both routing halves (MSB split, not an invented threshold)"]
        if bits > 1:
            lines.append(f"    soft {an}[{bits - 1}] dist {{ 0 := 1, 1 := 1 }};")
        vld = model.get("vld")
        if vld:
            lines.append(f"    soft {vld['name']} dist {{ 0 := 1, 1 := 3 }};")
        if len(lines) == 1:
            return ""
        body = "\n".join(lines)
        return f"""
  constraint legal_c {{
{body}
  }}
"""
    if kind in ("spi", "i2c"):
        return """
  constraint legal_c {
    soft data != 8'h00;
  }
"""
    if kind == "uart" and model.get("din"):
        dn = model["din"]["name"]
        return f"""
  constraint legal_c {{
    soft {dn} != 8'h00;
  }}
"""
    return ""


def _protocol_driver_run(kind: str, model: dict, tb_clk: str, drive_block: str) -> str:
    """Directed handshake driver for buses; pin-wiggle otherwise."""
    default = f"""  task run_phase(uvm_phase phase);
    forever begin
      seq_item_port.get_next_item(req);
      // Drive before the edge so DUT + monitor see the same transaction
{drive_block}
      @(posedge vif.{tb_clk});
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "axi":
        return f"""  task run_phase(uvm_phase phase);
    int timeout;
    bit [1:0] sel;
    logic [31:0] data;
    forever begin
      seq_item_port.get_next_item(req);
      sel = req.s_axi_awaddr[3:2];
      data = req.s_axi_wdata;
      vif.s_axi_awvalid = 0; vif.s_axi_wvalid = 0; vif.s_axi_arvalid = 0;
      vif.s_axi_bready = 0; vif.s_axi_rready = 0; vif.s_axi_wstrb = 4'hF;
      vif.s_axi_awaddr = {{sel, 2'b00}}; vif.s_axi_wdata = data;
      vif.s_axi_awprot = '0; vif.s_axi_awvalid = 1; vif.s_axi_wvalid = 1;
      timeout = 0;
      @(posedge vif.{tb_clk});
      while (!(vif.s_axi_awready && vif.s_axi_wready) && timeout < 40) begin
        @(posedge vif.{tb_clk}); timeout++;
      end
      @(posedge vif.{tb_clk});
      vif.s_axi_awvalid = 0; vif.s_axi_wvalid = 0; vif.s_axi_bready = 1;
      timeout = 0;
      while (!vif.s_axi_bvalid && timeout < 40) begin @(posedge vif.{tb_clk}); timeout++; end
      @(posedge vif.{tb_clk});
      vif.s_axi_bready = 0;
      vif.s_axi_araddr = {{sel, 2'b00}}; vif.s_axi_arprot = '0; vif.s_axi_arvalid = 1;
      timeout = 0;
      @(posedge vif.{tb_clk});
      while (!vif.s_axi_arready && timeout < 40) begin @(posedge vif.{tb_clk}); timeout++; end
      @(posedge vif.{tb_clk});
      vif.s_axi_arvalid = 0; vif.s_axi_rready = 1;
      timeout = 0;
      while (!vif.s_axi_rvalid && timeout < 40) begin @(posedge vif.{tb_clk}); timeout++; end
      @(posedge vif.{tb_clk});
      vif.s_axi_rready = 0;
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "apb":
        psel, pen, pw = model["psel"], model["penable"], model["pwrite"]
        pa, pwd, pry = model["paddr"], model["pwdata"], model["pready"]
        return f"""  task run_phase(uvm_phase phase);
    int timeout;
    forever begin
      seq_item_port.get_next_item(req);
      vif.{psel} = 0; vif.{pen} = 0; vif.{pw} = 0;
      vif.{pa} = req.{pa}; vif.{pwd} = req.{pwd};
      vif.{psel} = 1; vif.{pen} = 0; vif.{pw} = 1;
      @(posedge vif.{tb_clk});
      vif.{pen} = 1; timeout = 0;
      @(posedge vif.{tb_clk});
      while (!vif.{pry} && timeout < 40) begin @(posedge vif.{tb_clk}); timeout++; end
      vif.{psel} = 0; vif.{pen} = 0; vif.{pw} = 0;
      @(posedge vif.{tb_clk});
      vif.{pa} = req.{pa};
      vif.{psel} = 1; vif.{pen} = 0; vif.{pw} = 0;
      @(posedge vif.{tb_clk});
      vif.{pen} = 1; timeout = 0;
      @(posedge vif.{tb_clk});
      while (!vif.{pry} && timeout < 40) begin @(posedge vif.{tb_clk}); timeout++; end
      vif.{psel} = 0; vif.{pen} = 0;
      @(posedge vif.{tb_clk});
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "ahb":
        return f"""  task run_phase(uvm_phase phase);
    forever begin
      seq_item_port.get_next_item(req);
      vif.HSEL = 1; vif.HREADY = 1;
      vif.HADDR = req.HADDR; vif.HTRANS = 2'b10; vif.HWRITE = 1; vif.HWDATA = req.HWDATA;
      @(posedge vif.{tb_clk});
      vif.HTRANS = 2'b00; vif.HWRITE = 0;
      @(posedge vif.{tb_clk});
      vif.HADDR = req.HADDR; vif.HTRANS = 2'b10; vif.HWRITE = 0;
      @(posedge vif.{tb_clk});
      vif.HTRANS = 2'b00;
      @(posedge vif.{tb_clk});
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "spi":
        mosi, cs = model["mosi"], model["cs"]
        return f"""  task run_phase(uvm_phase phase);
    int i;
    forever begin
      seq_item_port.get_next_item(req);
      vif.{cs['name']} = 1'b1;
      vif.{mosi['name']} = 1'b0;
      @(posedge vif.{tb_clk});
      vif.{cs['name']} = 1'b0;
      for (i = 7; i >= 0; i--) begin
        vif.{mosi['name']} = req.data[i];
        @(posedge vif.{tb_clk});
      end
      vif.{cs['name']} = 1'b1;
      @(posedge vif.{tb_clk});
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "uart":
        din, start = model["din"], model["start"]
        busy = model.get("busy")
        wait_busy = ""
        if busy:
            wait_busy = f"""
      timeout = 0;
      while (vif.{busy['name']} === 1'b1 && timeout < 200) begin
        @(posedge vif.{tb_clk}); timeout++;
      end"""
        return f"""  task run_phase(uvm_phase phase);
    int timeout;
    forever begin
      seq_item_port.get_next_item(req);
      vif.{start['name']} = 1'b0;
      vif.{din['name']} = req.{din['name']};
      @(posedge vif.{tb_clk});
      vif.{start['name']} = 1'b1;
      @(posedge vif.{tb_clk});
      vif.{start['name']} = 1'b0;{wait_busy}
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "i2c":
        sda, start = model["sda"], model["start"]
        return f"""  task run_phase(uvm_phase phase);
    int i;
    forever begin
      seq_item_port.get_next_item(req);
      vif.{start['name']} = 1'b1;
      vif.{sda['name']} = 1'b0;
      @(posedge vif.{tb_clk});
      vif.{start['name']} = 1'b0;
      for (i = 7; i >= 0; i--) begin
        vif.{sda['name']} = req.data[i];
        @(posedge vif.{tb_clk});
      end
      seq_item_port.item_done();
    end
  endtask"""
    if kind == "vip_stub":
        return f"""  task run_phase(uvm_phase phase);
    forever begin
      seq_item_port.get_next_item(req);
      // Idle — do not invent VIP handshake timing
      @(posedge vif.{tb_clk});
      seq_item_port.item_done();
    end
  endtask"""
    return default


def render_uvm_smoke_tb(
    mod: dict,
    *,
    cycles: int = 16,
    test_name: Optional[str] = None,
) -> str:
    """Complete UVM TB with real DUT instance + protocol-aware scoreboard golden."""
    dut = _safe_id(mod.get("name") or "dut")
    ports = list(mod.get("ports") or [])
    cls = classify_ports(ports)
    clk_p = cls.get("clk")
    rst_p = cls.get("rst")
    clk = (clk_p or {}).get("name") if clk_p else None
    rst = (rst_p or {}).get("name") if rst_p else None
    inputs = list(cls.get("inputs") or [])
    outputs = list(cls.get("outputs") or [])
    tb_clk = clk or "tb_clk"
    has_dut_clk = clk is not None
    if_name = f"{dut}_if"
    txn = f"{dut}_txn"
    drv = f"{dut}_driver"
    mon = f"{dut}_monitor"
    ag = f"{dut}_agent"
    sb = f"{dut}_scoreboard"
    env = f"{dut}_env"
    test = test_name or f"{dut}_test"
    seq = f"{dut}_seq"
    tb_mod = f"{dut}_tb"

    kind, model = _detect_kind(cls, mod.get("parameters") or {})
    try:
        from tb_vip_stub import needs_user_vip

        need_vip, cls_dut = needs_user_vip(mod)
        if need_vip:
            kind = "vip_stub"
            model = {"protocol": cls_dut.get("protocol") or "vip"}
    except Exception:
        pass
    active_low = bool(cls.get("active_low_reset", True))
    txn_fields, drive_assigns, mon_sample = _build_txn_fields(
        kind, model, inputs, outputs, rst=rst_p, tb_clk=tb_clk
    )
    sb_body = _scoreboard_body(
        kind,
        model,
        txn,
        rst=rst_p if kind in ("counter", "edge", "pwm", "debounce", "syncff", "stream", "parity", "uart") else None,
        active_low=active_low,
    )
    constraint = _constraint_block(kind, model)
    drv_run = _protocol_driver_run(kind, model, tb_clk, "\n".join(drive_assigns))

    iface_body = "\n".join(_iface_signals(ports, clk if has_dut_clk else None))
    if_clk_port = f"(input logic {tb_clk})"
    rand_fields = "\n".join(txn_fields)
    mon_block = "\n".join(mon_sample)
    dut_conns = ",\n".join(
        _dut_port_map(ports, vif="vif", clk_name=clk if has_dut_clk else None)
    )

    rst_init = ""
    post_rst_check = ""
    if rst:
        active_low = cls.get("active_low_reset", True)
        assert_v = "0" if active_low else "1"
        deassert_v = "1" if active_low else "0"
        en_init = ""
        if kind == "counter" and model.get("enable"):
            en_init = f"      vif.{model['enable']['name']} = 1'b0;\n"
        rst_init = f"""
    if (vif != null) begin
{en_init}      vif.{rst} = 1'b{assert_v};
      repeat (2) @(posedge vif.{tb_clk});
      vif.{rst} = 1'b{deassert_v};
      @(posedge vif.{tb_clk});
    end
"""
        if kind == "counter" and model.get("count"):
            cn = model["count"]["name"]
            post_rst_check = f"""
    if (vif != null && vif.{cn} !== '0)
      `uvm_error("TEST", $sformatf("post-reset {cn} not zero: %0h", vif.{cn}))
"""

    # Combo mux/parity: settle after drive before sample — monitor #1 already helps
    params = mod.get("parameters") or {}
    param_bind = ""
    if params:
        parts = [f".{k}({v})" for k, v in list(params.items())[:6]]
        if parts:
            param_bind = " #(" + ", ".join(parts) + ")"

    kind_tag = (
        f"vip_stub {model.get('protocol') or 'vip'} (require_user_vip)"
        if kind == "vip_stub"
        else kind if kind != "generic"
        else "generic (no invented golden)"
    )
    ral_sv = ""
    ral_adapter_sv = ""
    ral_env_decls = ""
    ral_env_build = ""
    ral_env_connect = ""
    ral_seq_start = ""
    try:
        from tb_ral import csr_list_of, render_uvm_ral_block, render_uvm_reg_adapter, wants_ral

        if wants_ral(mod):
            ral_sv = "\n" + render_uvm_ral_block(dut, csr_list_of(mod)) + "\n"
            ral_adapter_sv = render_uvm_reg_adapter(dut, txn)
            ral_env_decls = (
                f"  {dut}_reg_block ral;\n"
                f"  {dut}_reg_adapter adapter;\n"
                f"  uvm_reg_predictor #({txn}) predictor;\n"
            )
            ral_env_build = (
                f"    ral = {dut}_reg_block::type_id::create(\"ral\");\n"
                f"    ral.build();\n"
                f"    adapter = {dut}_reg_adapter::type_id::create(\"adapter\");\n"
                f"    predictor = uvm_reg_predictor#({txn})::type_id::create(\"predictor\", this);\n"
            )
            ral_env_connect = (
                f"    predictor.map = ral.default_map;\n"
                f"    predictor.adapter = adapter;\n"
                f"    agent.mon.ap.connect(predictor.bus_in);\n"
                f"    ral.default_map.set_sequencer(agent.sqr, adapter);\n"
            )
            ral_seq_start = (
                f"    begin\n"
                f"      {dut}_csr_seq csr_s;\n"
                f"      csr_s = {dut}_csr_seq::type_id::create(\"csr_s\");\n"
                f"      csr_s.mdl = env.ral;\n"
                f"      csr_s.start(env.agent.sqr);\n"
                f"    end\n"
            )
    except Exception:
        ral_sv = ""
        ral_adapter_sv = ""
        ral_env_decls = ""
        ral_env_build = ""
        ral_env_connect = ""
        ral_seq_start = ""

    sv = f"""`timescale 1ns / 1ps
// ChipSutra UVM smoke — DUT-correct top + {kind_tag} scoreboard golden
import uvm_pkg::*;
`include "uvm_macros.svh"
{ral_sv}
interface {if_name}{if_clk_port};
{iface_body}
endinterface

class {txn} extends uvm_sequence_item;
  `uvm_object_utils({txn})
{rand_fields}{constraint}
  function new(string name = "{txn}");
    super.new(name);
  endfunction
endclass
{ral_adapter_sv}
class {drv} extends uvm_driver #({txn});
  `uvm_component_utils({drv})
  virtual {if_name} vif;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual {if_name})::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "driver vif")
  endfunction
{drv_run}
endclass

class {mon} extends uvm_monitor;
  `uvm_component_utils({mon})
  virtual {if_name} vif;
  uvm_analysis_port #({txn}) ap;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap = new("ap", this);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual {if_name})::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "monitor vif")
  endfunction
  task run_phase(uvm_phase phase);
    forever begin
      {txn} t;
      @(posedge vif.{tb_clk});
      #1;
      t = {txn}::type_id::create("t");
{mon_block}
      ap.write(t);
    end
  endtask
endclass

class {sb} extends uvm_scoreboard;
  `uvm_component_utils({sb})
  uvm_analysis_imp #({txn}, {sb}) imp;
{sb_body}
endclass

class {ag} extends uvm_agent;
  `uvm_component_utils({ag})
  {drv} drv;
  {mon} mon;
  uvm_sequencer #({txn}) sqr;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    drv = {drv}::type_id::create("drv", this);
    mon = {mon}::type_id::create("mon", this);
    sqr = uvm_sequencer#({txn})::type_id::create("sqr", this);
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    drv.seq_item_port.connect(sqr.seq_item_export);
  endfunction
endclass

class {env} extends uvm_env;
  `uvm_component_utils({env})
  {ag} agent;
  {sb} sb;
{ral_env_decls}  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    agent = {ag}::type_id::create("agent", this);
    sb = {sb}::type_id::create("sb", this);
{ral_env_build}  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent.mon.ap.connect(sb.imp);
{ral_env_connect}  endfunction
endclass

class {seq} extends uvm_sequence #({txn});
  `uvm_object_utils({seq})
  function new(string name = "{seq}");
    super.new(name);
  endfunction
  task body();
    repeat ({max(cycles, 8)}) begin
      {txn} tr = {txn}::type_id::create("tr");
      start_item(tr);
      void'(tr.randomize());
      finish_item(tr);
    end
  endtask
endclass

class {test} extends uvm_test;
  `uvm_component_utils({test})
  {env} env;
  virtual {if_name} vif;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env = {env}::type_id::create("env", this);
    void'(uvm_config_db#(virtual {if_name})::get(this, "", "vif", vif));
  endfunction
  task run_phase(uvm_phase phase);
    {seq} s;
    phase.raise_objection(this);
{rst_init}{post_rst_check}    s = {seq}::type_id::create("s");
    s.start(env.agent.sqr);
{ral_seq_start}    #50;
    phase.drop_objection(this);
  endtask
endclass

module {tb_mod};
  logic {tb_clk};
  {if_name} vif({tb_clk});

  {dut}{param_bind} dut (
{dut_conns}
  );

  initial begin
    {tb_clk} = 0;
    forever #5 {tb_clk} = ~{tb_clk};
  end

  initial begin
    uvm_config_db#(virtual {if_name})::set(null, "*", "vif", vif);
    run_test("{test}");
  end
endmodule
"""
    try:
        from tb_scale_emit import apply_uvm_scale_emit

        sv = apply_uvm_scale_emit(
            sv, mod, txn=txn, env=env, ag=ag, if_name=if_name, sb=sb
        )
    except Exception:
        pass
    return sv


def render_uvm_top_only(mod: dict, *, test_name: Optional[str] = None) -> str:
    """Just the module top (DUT+IF+config_db+run_test) for surgical repair."""
    full = render_uvm_smoke_tb(mod, test_name=test_name)
    idx = full.rfind("module ")
    if idx < 0:
        return full
    return full[idx:]
