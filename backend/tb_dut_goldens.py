"""Protocol-specific Pure SV class TBs (combo no-VIF + directed bus + extra detectors).

Used by render_class_sv_tb / UVM kind detect. Goldens are independent of DUT outputs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from tb_skeleton import (
    _by_name,
    classify_ports,
    sv_type,
    width_bits,
)


def _suf(ports: List[dict], *ends: str) -> Optional[dict]:
    for p in ports:
        n = (p.get("name") or "").lower()
        for e in ends:
            el = e.lower()
            if n == el or n.endswith("_" + el):
                return p
    return None


def detect_alu_model(roles: Dict[str, Any]) -> Optional[dict]:
    a = _by_name(roles["inputs"], "a", "op_a", "in_a", "operand_a")
    b = _by_name(roles["inputs"], "b", "op_b", "in_b", "operand_b")
    op = _by_name(roles["inputs"], "op", "opcode", "alu_op", "sel")
    y = _by_name(roles["outputs"], "y", "result", "out", "alu_out")
    if not (a and b and op and y):
        return None
    if width_bits(op.get("width", ""), op) < 2:
        return None
    if width_bits(a.get("width", ""), a) != width_bits(b.get("width", ""), b):
        return None
    return {"a": a, "b": b, "op": op, "y": y}


def detect_prio_enc_model(roles: Dict[str, Any]) -> Optional[dict]:
    req = _by_name(roles["inputs"], "req", "request", "in")
    grant = _by_name(roles["outputs"], "grant", "idx", "enc", "y")
    if not req or not grant:
        return None
    n = width_bits(req.get("width", ""), req)
    if n < 2:
        return None
    return {
        "req": req,
        "grant": grant,
        "valid": _by_name(roles["outputs"], "valid", "vld"),
        "width": n,
    }


def detect_shifter_model(roles: Dict[str, Any]) -> Optional[dict]:
    din = _by_name(roles["inputs"], "din", "data", "in")
    shamt = _by_name(roles["inputs"], "shamt", "shift", "amt")
    dout = _by_name(roles["outputs"], "dout", "out", "q")
    if not (din and shamt and dout):
        return None
    return {
        "din": din,
        "shamt": shamt,
        "dir": _by_name(roles["inputs"], "dir", "right", "shift_right"),
        "dout": dout,
    }


def detect_gray_model(roles: Dict[str, Any]) -> Optional[dict]:
    gray_i = _by_name(roles["inputs"], "gray")
    bin_o = _by_name(roles["outputs"], "bin")
    if gray_i and bin_o:
        return {"kind": "gray2bin", "src": gray_i, "dst": bin_o}
    bin_i = _by_name(roles["inputs"], "bin")
    gray_o = _by_name(roles["outputs"], "gray")
    if bin_i and gray_o:
        return {"kind": "bin2gray", "src": bin_i, "dst": gray_o}
    return None


def detect_edge_model(roles: Dict[str, Any]) -> Optional[dict]:
    din = _by_name(roles["inputs"], "din", "d", "in")
    rise = _by_name(roles["outputs"], "rise", "rising", "posedge")
    fall = _by_name(roles["outputs"], "fall", "falling", "negedge")
    if din and rise and fall:
        return {"din": din, "rise": rise, "fall": fall}
    return None


def detect_pwm_model(roles: Dict[str, Any]) -> Optional[dict]:
    duty = _by_name(roles["inputs"], "duty", "compare", "threshold")
    pwm = _by_name(roles["outputs"], "pwm")
    if duty and pwm and width_bits(duty.get("width", ""), duty) >= 2:
        return {"duty": duty, "pwm": pwm}
    return None


def detect_debounce_model(roles: Dict[str, Any]) -> Optional[dict]:
    noisy = _by_name(roles["inputs"], "noisy", "raw", "bounce")
    clean = _by_name(roles["outputs"], "clean", "debounced")
    if noisy and clean and width_bits(noisy.get("width", ""), noisy) == 1:
        return {"noisy": noisy, "clean": clean, "settle": 7}
    return None


def detect_sync_ff_model(roles: Dict[str, Any]) -> Optional[dict]:
    d = _by_name(roles["inputs"], "d", "din", "async_in", "d_async")
    q = _by_name(roles["outputs"], "q", "dout", "sync_out", "q_sync")
    if d and q and len(roles["inputs"]) <= 2 and len(roles["outputs"]) == 1:
        if detect_debounce_model(roles) or detect_edge_model(roles) or detect_pwm_model(roles):
            return None
        return {"d": d, "q": q}
    return None


def detect_wishbone_model(roles: Dict[str, Any]) -> Optional[dict]:
    cyc = _by_name(roles["inputs"], "cyc", "wb_cyc")
    stb = _by_name(roles["inputs"], "stb", "wb_stb")
    we = _by_name(roles["inputs"], "we", "wb_we")
    ack = _by_name(roles["outputs"], "ack", "wb_ack")
    adr = _by_name(roles["inputs"], "adr", "addr", "wb_adr", "wb_addr")
    wdat = _by_name(roles["inputs"], "dat_i", "dat_mosi", "wdata", "wb_dat_i")
    rdat = _by_name(roles["outputs"], "dat_o", "dat_miso", "rdata", "wb_dat_o")
    if cyc and stb and we and ack and adr and wdat and rdat:
        return {
            "cyc": cyc,
            "stb": stb,
            "we": we,
            "ack": ack,
            "adr": adr,
            "wdat": wdat,
            "rdat": rdat,
        }
    return None


def detect_avalon_model(roles: Dict[str, Any]) -> Optional[dict]:
    addr = _by_name(roles["inputs"], "address", "avs_address")
    wdata = _by_name(roles["inputs"], "writedata", "avs_writedata")
    rdata = _by_name(roles["outputs"], "readdata", "avs_readdata")
    wr = _by_name(roles["inputs"], "write", "avs_write")
    rd = _by_name(roles["inputs"], "read", "avs_read")
    if addr and wdata and rdata and wr:
        return {
            "addr": addr,
            "wdata": wdata,
            "rdata": rdata,
            "write": wr,
            "read": rd,
            "waitrequest": _by_name(roles["outputs"], "waitrequest", "avs_waitrequest"),
        }
    return None


def detect_fsm_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Clocked FSM with a visible state bus — safety golden only (one-hot / no-X)."""
    state = _by_name(roles["outputs"], "state", "fsm_state", "curr_state", "cs")
    if not state:
        return None
    n = width_bits(state.get("width", ""), state)
    if n < 3:
        return None
    if detect_alu_model(roles) or detect_prio_enc_model(roles):
        return None
    return {
        "state": state,
        "stim": _by_name(roles["inputs"], "in", "din", "ev", "event", "cmd"),
        "width": n,
    }


def detect_ahb_model(roles: Dict[str, Any]) -> Optional[dict]:
    haddr = _by_name(roles["inputs"], "haddr")
    htrans = _by_name(roles["inputs"], "htrans")
    hwrite = _by_name(roles["inputs"], "hwrite")
    hwdata = _by_name(roles["inputs"], "hwdata")
    hrdata = _by_name(roles["outputs"], "hrdata")
    if haddr and htrans and hwrite and hwdata and hrdata:
        return {
            "haddr": haddr,
            "htrans": htrans,
            "hwrite": hwrite,
            "hwdata": hwdata,
            "hrdata": hrdata,
            "hsel": _by_name(roles["inputs"], "hsel"),
            "hready": _by_name(roles["inputs"], "hready"),
            "hreadyout": _by_name(roles["outputs"], "hreadyout"),
            "hresp": _by_name(roles["outputs"], "hresp"),
        }
    return None


def detect_spi_model(roles: Dict[str, Any]) -> Optional[dict]:
    mosi = _by_name(roles["inputs"], "mosi")
    cs = _by_name(roles["inputs"], "cs_n", "ss_n", "csb", "nss")
    rx = _by_name(roles["outputs"], "rx_byte", "rx_data", "data_out")
    if mosi and cs and rx:
        return {
            "mosi": mosi,
            "cs": cs,
            "miso": _by_name(roles["outputs"], "miso"),
            "rx": rx,
            "rx_valid": _by_name(roles["outputs"], "rx_valid", "done"),
        }
    return None


def detect_uart_model(roles: Dict[str, Any]) -> Optional[dict]:
    din = _by_name(roles["inputs"], "din", "tx_data", "data")
    start = _by_name(roles["inputs"], "start", "tx_start", "wr")
    tx = _by_name(roles["outputs"], "tx", "txd")
    if din and start and tx:
        return {
            "din": din,
            "start": start,
            "tx": tx,
            "busy": _by_name(roles["outputs"], "busy"),
            "done": _by_name(roles["outputs"], "done"),
            "last": _by_name(roles["outputs"], "last_byte", "tx_byte"),
        }
    return None


def detect_uart_rx_model(roles: Dict[str, Any]) -> Optional[dict]:
    rx = _by_name(roles["inputs"], "rx", "rxd", "uart_rx")
    dout = _by_name(roles["outputs"], "dout", "rx_data", "rx_byte", "data_out")
    if not (rx and dout):
        return None
    if detect_uart_model(roles):
        return None
    return {
        "rx": rx,
        "dout": dout,
        "valid": _by_name(roles["outputs"], "rx_valid", "valid", "done"),
    }


def detect_i2c_model(roles: Dict[str, Any]) -> Optional[dict]:
    sda = _by_name(roles["inputs"], "sda_in", "sda")
    start = _by_name(roles["inputs"], "start")
    last = _by_name(roles["outputs"], "last_data", "rx_byte", "data_out")
    if sda and start and last:
        return {
            "sda": sda,
            "start": start,
            "last": last,
            "got": _by_name(roles["outputs"], "got_write", "done", "ack"),
            "sda_out": _by_name(roles["outputs"], "sda_out"),
        }
    return None


def detect_i2c_master_model(roles: Dict[str, Any]) -> Optional[dict]:
    """Master DUT: TB is slave. Skip slave golden (needs a start pin)."""
    if detect_i2c_model(roles):
        return None
    scl_out = _by_name(roles["outputs"], "scl_out", "scl")
    sda_out = _by_name(roles["outputs"], "sda_out", "sda")
    if scl_out and sda_out:
        return {"scl_out": scl_out, "sda_out": sda_out, "role": "master"}
    return None


def detect_can_model(roles: Dict[str, Any]) -> Optional[dict]:
    rx = _by_name(roles["inputs"], "can_rx", "canrx", "rx")
    tx = _by_name(roles["outputs"], "can_tx", "cantx", "tx")
    names_in = {p["name"].lower() for p in roles["inputs"]}
    names_out = {p["name"].lower() for p in roles["outputs"]}
    canish = bool(names_in & {"can_rx", "canrx"}) or bool(names_out & {"can_tx", "cantx"})
    if not canish:
        return None
    if not (rx and tx):
        return None
    # Do not steal UART TX (din+start+tx)
    if detect_uart_model(roles):
        return None
    return {"rx": rx, "tx": tx}


def _rand_field(p: dict) -> str:
    bits = width_bits(p.get("width", ""), p)
    if bits <= 1:
        return f"  rand bit {p['name']};"
    return f"  rand bit [{bits - 1}:0] {p['name']};"


def render_combo_layered_tb(
    module: dict,
    *,
    txn_fields: List[str],
    constraint: str,
    check_fn: List[str],
    drive_ports: List[dict],
    out_ports: List[dict],
    check_args: str,
    cycles: int = 32,
    seed: int = 1,
    tag: str = "combo",
    module_body: str = "",
    extra_mon_fields: Optional[List[str]] = None,
    extra_mon_sample: str = "",
    mismatch_display: str = "",
    drive_via_modnet: bool = False,
    stim_in_initial: bool = False,
) -> str:
    """Layered Pure SV TB for combinational DUTs without virtual-interface handles."""
    name = module.get("name") or "dut"
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
    hier = tb_name
    all_ports = list(drive_ports) + list(out_ports)
    if_sigs = [f"  {sv_type(p.get('width', ''), p)} {p['name']};" for p in all_ports]
    mon_fields = list(if_sigs) + list(extra_mon_fields or [])
    if drive_via_modnet:
        dut_ports = [f"    .{p['name']}({p['name']})" for p in all_ports]
        mod_decls = "\n".join(
            f"  {sv_type(p.get('width', ''), p)} {p['name']};" for p in all_ports
        )
        vif_connect = "\n".join(
            f"  assign vif.{p['name']} = {p['name']};" for p in all_ports
        )
        zeros = "\n".join(f"    {p['name']} = '0;" for p in drive_ports)
        task_args = ", ".join(
            f"input {sv_type(p.get('width', ''), p)} {p['name']}_i" for p in drive_ports
        )
        call_args = ", ".join(f"t.{p['name']}" for p in drive_ports)
        task_body = "\n".join(
            f"    {p['name']} = {p['name']}_i;" for p in drive_ports
        )
        drive_task = (
            f"  task automatic drive_in({task_args});\n{task_body}\n  endtask\n"
        )
        drive_assigns = f"      {hier}.drive_in({call_args});"
        module_nets = f"{mod_decls}\n{vif_connect}\n{drive_task}"
        mon_sample = "\n".join(
            f"      p.{p['name']} = {hier}.{p['name']};" for p in all_ports
        )
    else:
        drive_assigns = "\n".join(
            f"      {hier}.vif.{p['name']} = t.{p['name']};" for p in drive_ports
        )
        dut_ports = [f"    .{p['name']}(vif.{p['name']})" for p in all_ports]
        zeros = "\n".join(f"    vif.{p['name']} = '0;" for p in drive_ports)
        module_nets = ""
        mon_sample = "\n".join(
            f"      p.{p['name']} = {hier}.vif.{p['name']};" for p in all_ports
        )
    if extra_mon_sample:
        mon_sample = mon_sample + "\n" + extra_mon_sample
    dut_mapped = [
        line + ("," if i < len(dut_ports) - 1 else "") for i, line in enumerate(dut_ports)
    ]
    mismatch_sv = mismatch_display or f'        $display("[%0t] {tag} mismatch", $time);'
    if stim_in_initial:
        drive_init = " ".join(
            f"{p['name']} = tx.{p['name']};" for p in drive_ports
        )
        initial_run = f"""    t.env.build({cycles});
    t.env.gen.run();
    begin
      {txn_cls} tx;
      repeat ({cycles}) begin
        t.env.gen2drv.get(tx);
        t.env.drv2sb.put(tx);
        {drive_init}
        #1;
        @(posedge clk);
        #1;
        t.env.mon.run(1);
        t.env.sb.run(1);
      end
    end
    t.env.report();"""
    else:
        initial_run = f"    t.run({cycles});"
    return f"""// ChipSutra Pure SV class TB for {tag} (combo-safe; no VIF handles)
// Components: interface, generator, driver, monitor, scoreboard, env, test
`timescale 1ns / 1ps

interface {if_name};
{chr(10).join(if_sigs)}
endinterface

class {txn_cls};
{chr(10).join(txn_fields)}
  constraint legal_c {{
    {constraint}
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
      if (!check({check_args})) begin
{mismatch_sv}
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
    gen.run();
    repeat (n) begin
      drv.run(1);
      #1;
      @(posedge {hier}.clk);
      #1;
      mon.run(1);
      sb.run(1);
    end
  endtask
  function void report();
    if (sb.errors == 0)
      $display("PASS: {tb_name} {tag} class SV OK");
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
  logic clk = 1'b0;
  {if_name} vif();
{module_nets}
  {name} dut (
{chr(10).join(dut_mapped)}
  );
{module_body}
  always #5 clk = ~clk;

  initial begin
    {test_cls} t;
    $dumpfile("{tb_name}.vcd");
    $dumpvars(0, {tb_name});
    void'($urandom({seed}));
    clk = 0;
{zeros}
    t = new();
{initial_run}
    $finish;
  end
endmodule
"""


def render_alu_class_tb(module: dict, alu: dict, *, cycles: int = 32, seed: int = 1) -> str:
    a, b, op, y = alu["a"], alu["b"], alu["op"], alu["y"]
    at, bt, ot, yt = (
        sv_type(a.get("width", ""), a),
        sv_type(b.get("width", ""), b),
        sv_type(op.get("width", ""), op),
        sv_type(y.get("width", ""), y),
    )
    an, bn, on, yn = a["name"], b["name"], op["name"], y["name"]
    op_max = (1 << width_bits(op.get("width", ""), op)) - 1
    check_fn = [
        f"  function bit check({ot} {on}, {at} {an}, {bt} {bn}, {yt} {yn});",
        f"    {yt} exp;",
        f"    case ({on})",
        f"      0: exp = {an} + {bn};",
        f"      1: exp = {an} - {bn};",
        f"      2: exp = {an} & {bn};",
        f"      default: exp = {an} | {bn};",
        "    endcase",
        f"    return ({yn} === exp);",
        "  endfunction",
    ]
    return render_combo_layered_tb(
        module,
        txn_fields=[_rand_field(a), _rand_field(b), _rand_field(op)],
        constraint=f"{on} inside {{[0:{op_max}]}};",
        check_fn=check_fn,
        drive_ports=[a, b, op],
        out_ports=[y],
        check_args=f"t.{on}, t.{an}, t.{bn}, p.{yn}",
        cycles=cycles,
        seed=seed,
        tag="alu",
    )


def render_prio_class_tb(module: dict, enc: dict, *, cycles: int = 32, seed: int = 1) -> str:
    req, grant = enc["req"], enc["grant"]
    n = int(enc["width"])
    rn, gn = req["name"], grant["name"]
    rt, gt = sv_type(req.get("width", ""), req), sv_type(grant.get("width", ""), grant)
    vld = enc.get("valid")
    args = f"{rt} {rn}, {gt} {gn}" + (f", logic {vld['name']}" if vld else "")
    body = [
        f"  function bit check({args});",
        f"    {gt} exp;",
        "    exp = '0;",
    ]
    for i in range(n - 1, -1, -1):
        kw = "if" if i == n - 1 else "else if"
        body.append(f"    {kw} ({rn} >= {1 << i}) exp = {i};")
    if vld:
        body.append(
            f"    return ({gn} === exp) && ({vld['name']} === ({rn} != '0));"
        )
    else:
        body.append(f"    return ({gn} === exp);")
    body.append("  endfunction")
    outs = [grant] + ([vld] if vld else [])
    carg = f"t.{rn}, p.{gn}" + (f", p.{vld['name']}" if vld else "")
    return render_combo_layered_tb(
        module,
        txn_fields=[_rand_field(req)],
        constraint=f"soft {rn} dist {{ 0 := 1, [1:{(1 << n) - 1}] := 3 }};",
        check_fn=body,
        drive_ports=[req],
        out_ports=outs,
        check_args=carg,
        cycles=cycles,
        seed=seed,
        tag="prio_enc",
        drive_via_modnet=True,
        stim_in_initial=True,
    )


def render_shifter_class_tb(module: dict, sh: dict, *, cycles: int = 32, seed: int = 1) -> str:
    din, shamt, dout = sh["din"], sh["shamt"], sh["dout"]
    dirp = sh.get("dir")
    dn, sn, on = din["name"], shamt["name"], dout["name"]
    dt, st, ot = (
        sv_type(din.get("width", ""), din),
        sv_type(shamt.get("width", ""), shamt),
        sv_type(dout.get("width", ""), dout),
    )
    drive = [din, shamt] + ([dirp] if dirp else [])
    if dirp:
        drn = dirp["name"]
        check_fn = [
            f"  function bit check({dt} {dn}, {st} {sn}, bit {drn}, {ot} {on});",
            f"    {ot} exp;",
            f"    exp = {drn} ? ({dn} >> {sn}) : ({dn} << {sn});",
            f"    return ({on} === exp);",
            "  endfunction",
        ]
        carg = f"t.{dn}, t.{sn}, t.{drn}, p.{on}"
        fields = [_rand_field(din), _rand_field(shamt), _rand_field(dirp)]
    else:
        check_fn = [
            f"  function bit check({dt} {dn}, {st} {sn}, {ot} {on});",
            f"    return ({on} === ({dn} << {sn}));",
            "  endfunction",
        ]
        carg = f"t.{dn}, t.{sn}, p.{on}"
        fields = [_rand_field(din), _rand_field(shamt)]
    return render_combo_layered_tb(
        module,
        txn_fields=fields,
        constraint=f"soft {sn} inside {{[0:{(1 << width_bits(shamt.get('width', ''), shamt)) - 1}]}};",
        check_fn=check_fn,
        drive_ports=drive,
        out_ports=[dout],
        check_args=carg,
        cycles=cycles,
        seed=seed,
        tag="shifter",
    )


def render_gray_class_tb(module: dict, g: dict, *, cycles: int = 32, seed: int = 1) -> str:
    src, dst = g["src"], g["dst"]
    sn, dn = src["name"], dst["name"]
    bits = width_bits(src.get("width", ""), src)
    st, dt = sv_type(src.get("width", ""), src), sv_type(dst.get("width", ""), dst)
    if g.get("kind") == "bin2gray":
        body = [
            f"  function bit check({st} {sn}, {dt} {dn});",
            f"    return ({dn} === ({sn} ^ ({sn} >> 1)));",
            "  endfunction",
        ]
        tag = "bin2gray"
    else:
        # Same bit-chain as the DUT, in the TB module (not a class function).
        # Verilator UNOPTFLAT on gray2bin's self-referential `bin` bus then
        # evaluates DUT and reference identically.
        assigns = [f"  {dt} exp_{dn};"]
        assigns.append(f"  assign exp_{dn}[{bits - 1}] = vif.{sn}[{bits - 1}];")
        for i in range(bits - 2, -1, -1):
            assigns.append(
                f"  assign exp_{dn}[{i}] = exp_{dn}[{i + 1}] ^ vif.{sn}[{i}];"
            )
        module_body = "\n" + "\n".join(assigns) + "\n"
        tb_name = f"{(module.get('name') or 'dut')}_tb"
        body = [
            f"  function bit check({dt} {dn}, {dt} exp_{dn});",
            f"    return ({dn} === exp_{dn});",
            "  endfunction",
        ]
        tag = "gray2bin"
        carg = f"p.{dn}, p.exp_{dn}"
        extra_fields = [f"  {dt} exp_{dn};"]
        extra_sample = f"      p.exp_{dn} = {tb_name}.exp_{dn};"
        mismatch = (
            f'        $display("[%0t] gray2bin mismatch gray=%b bin=%b exp=%b",'
            f" $time, p.{sn}, p.{dn}, p.exp_{dn});"
        )
    kwargs = {}
    if g.get("kind") != "bin2gray":
        kwargs["module_body"] = module_body
        kwargs["extra_mon_fields"] = extra_fields
        kwargs["extra_mon_sample"] = extra_sample
        kwargs["mismatch_display"] = mismatch
        check_args = carg
    else:
        check_args = f"t.{sn}, p.{dn}"
    return render_combo_layered_tb(
        module,
        txn_fields=[_rand_field(src)],
        constraint=f"soft {sn} != '0;",
        check_fn=body,
        drive_ports=[src],
        out_ports=[dst],
        check_args=check_args,
        cycles=cycles,
        seed=seed,
        tag=tag,
        **kwargs,
    )


def render_wishbone_class_tb(module: dict, wb: dict, *, cycles: int = 12, seed: int = 1) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "clk"
    rst = (roles["rst"] or {}).get("name")
    cyc, stb, we = wb["cyc"]["name"], wb["stb"]["name"], wb["we"]["name"]
    ack, adr = wb["ack"]["name"], wb["adr"]["name"]
    wdat, rdat = wb["wdat"]["name"], wb["rdat"]["name"]
    extra = f"""
class {name}_scoreboard;
  logic [31:0] model_reg [0:3];
  int errors;
  function new();
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
    errors = 0;
  endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  int timeout;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task wb_write(bit [1:0] sel, logic [31:0] data);
    vif.{adr} = {{6'b0, sel}} << 2; vif.{wdat} = data;
    vif.{we} = 1'b1; vif.{cyc} = 1'b1; vif.{stb} = 1'b1;
    timeout = 0;
    @(posedge vif.clk);
    while (!vif.{ack} && timeout < 40) begin @(posedge vif.clk); timeout++; end
    sb.model_reg[sel] = data;
    vif.{stb} = 1'b0; vif.{we} = 1'b0; vif.{cyc} = 1'b0;
    @(posedge vif.clk);
  endtask
  task wb_read(bit [1:0] sel);
    vif.{adr} = {{6'b0, sel}} << 2; vif.{we} = 1'b0;
    vif.{cyc} = 1'b1; vif.{stb} = 1'b1;
    timeout = 0;
    @(posedge vif.clk);
    while (!vif.{ack} && timeout < 40) begin @(posedge vif.clk); timeout++; end
    if (vif.{rdat} !== sb.model_reg[sel]) begin
      $display("[%0t] wb mismatch sel=%0d exp=%h got=%h", $time, sel, sb.model_reg[sel], vif.{rdat});
      sb.errors++;
    end
    vif.{stb} = 1'b0; vif.{cyc} = 1'b0;
    @(posedge vif.clk);
  endtask
  task run(int n);
    {name}_txn t;
    vif.{cyc} = 0; vif.{stb} = 0; vif.{we} = 0; vif.{wdat} = '0;
    repeat (n) begin
      gen2drv.get(t);
      wb_write(t.sel, t.data);
      wb_read(t.sel);
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand bit [1:0] sel;\n  rand logic [31:0] data;",
        constraint="sel inside {[0:3]};",
        cycles=max(4, cycles // 2),
        seed=seed,
        tag="wishbone",
        clk_name=clk,
        rst_name=rst,
        active_low=True,
        post_reset_check=f"    if (vif.{rdat} !== '0 && !$isunknown(vif.{rdat})) ;",
    )


def render_avalon_class_tb(module: dict, av: dict, *, cycles: int = 12, seed: int = 1) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "clk"
    rst = (roles["rst"] or {}).get("name")
    addr, wdata, rdata = av["addr"]["name"], av["wdata"]["name"], av["rdata"]["name"]
    wr = av["write"]["name"]
    rd = (av.get("read") or {}).get("name")
    waitr = (av.get("waitrequest") or {}).get("name")
    wait_w = (
        f"    timeout = 0;\n    while (vif.{waitr} && timeout < 40) begin @(posedge vif.clk); timeout++; end\n"
        if waitr
        else ""
    )
    rd_drive = f"    vif.{rd} = 1'b1;\n" if rd else ""
    rd_clear = f"    vif.{rd} = 1'b0;\n" if rd else ""
    extra = f"""
class {name}_scoreboard;
  logic [31:0] model_reg [0:3];
  int errors;
  function new();
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
    errors = 0;
  endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  int timeout;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task av_write(bit [1:0] sel, logic [31:0] data);
    vif.{addr} = {{6'b0, sel}} << 2; vif.{wdata} = data; vif.{wr} = 1'b1;
{rd_clear}    @(posedge vif.clk);
{wait_w}    sb.model_reg[sel] = data;
    vif.{wr} = 1'b0;
    @(posedge vif.clk);
  endtask
  task av_read(bit [1:0] sel);
    vif.{addr} = {{6'b0, sel}} << 2; vif.{wr} = 1'b0;
{rd_drive}    @(posedge vif.clk);
{wait_w}    if (vif.{rdata} !== sb.model_reg[sel]) begin
      $display("[%0t] avalon mismatch sel=%0d exp=%h got=%h", $time, sel, sb.model_reg[sel], vif.{rdata});
      sb.errors++;
    end
{rd_clear}    @(posedge vif.clk);
  endtask
  task run(int n);
    {name}_txn t;
    vif.{wr} = 0; vif.{wdata} = '0;
    repeat (n) begin
      gen2drv.get(t);
      av_write(t.sel, t.data);
      av_read(t.sel);
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand bit [1:0] sel;\n  rand logic [31:0] data;",
        constraint="sel inside {[0:3]};",
        cycles=max(4, cycles // 2),
        seed=seed,
        tag="avalon",
        clk_name=clk,
        rst_name=rst,
        active_low=True,
        post_reset_check=f"    if ($isunknown(vif.{rdata})) env.sb.errors++;",
    )


def render_fsm_class_tb(module: dict, fsm: dict, *, cycles: int = 24, seed: int = 1) -> str:
    state = fsm["state"]
    stim = fsm.get("stim")
    stn = state["name"]
    stt = sv_type(state.get("width", ""), state)
    drive = [stim] if stim else []
    fields = [_rand_field(stim)] if stim else ["  rand bit unused;"]
    constraint = f"{stim['name']} inside {{[0:1]}};" if stim and width_bits(stim.get("width", ""), stim) == 1 else "1;"
    if constraint == "1;":
        constraint = "soft unused == 0;" if not stim else f"soft {stim['name']} dist {{ 0 := 1, [1:3] := 1 }};"
    check_fn = [
        f"  function bit check({stt} {stn});",
        f"    return (!$isunknown({stn})) && $onehot0({stn});",
        "  endfunction",
    ]
    carg = f"p.{stn}"
    return render_combo_layered_tb(
        module,
        txn_fields=fields,
        constraint=constraint,
        check_fn=check_fn,
        drive_ports=drive,
        out_ports=[state],
        check_args=carg,
        cycles=cycles,
        seed=seed,
        tag="fsm",
        drive_via_modnet=True,
        stim_in_initial=True,
    )


def try_render_special_class_tb(module: dict, *, cycles: int = 32, seed: int = 1) -> Optional[str]:
    """Return a specialized class TB, or None to use the generic layered emitter."""
    try:
        from dv_user_config import knobs_of
        knobs = knobs_of(module)
    except Exception:
        knobs = {}
    try:
        from tb_vip_stub import needs_user_vip, render_class_sv_vip_stub

        need, cls_dut = needs_user_vip(module)
        if need:
            return render_class_sv_vip_stub(
                module,
                protocol=str(cls_dut.get("protocol") or "vip"),
                cycles=cycles,
                seed=seed,
            )
    except Exception:
        pass
    roles = classify_ports(module.get("ports") or [])
    sv: Optional[str] = None
    alu = detect_alu_model(roles)
    enc = detect_prio_enc_model(roles)
    sh = detect_shifter_model(roles)
    g = detect_gray_model(roles)
    if alu:
        sv = render_alu_class_tb(module, alu, cycles=cycles, seed=seed)
    elif enc:
        sv = render_prio_class_tb(module, enc, cycles=cycles, seed=seed)
    elif sh:
        sv = render_shifter_class_tb(module, sh, cycles=cycles, seed=seed)
    elif g:
        sv = render_gray_class_tb(module, g, cycles=cycles, seed=seed)
    else:
        from tb_skeleton import detect_axi_lite_model, detect_apb_model

        ahb = detect_ahb_model(roles)
        wb = detect_wishbone_model(roles)
        av = detect_avalon_model(roles)
        can = detect_can_model(roles)
        uart_dir = str(knobs.get("uart_dir") or "").lower()
        uart_rx = detect_uart_rx_model(roles)
        uart = detect_uart_model(roles)
        spi = detect_spi_model(roles)
        i2c_role = str(knobs.get("i2c_role") or "").lower()
        i2c = detect_i2c_model(roles)
        fsm = detect_fsm_model(roles)
        if detect_axi_lite_model(roles):
            sv = render_axi_class_tb(module, cycles=cycles, seed=seed)
        elif detect_apb_model(roles):
            sv = render_apb_class_tb(module, cycles=cycles, seed=seed)
        elif ahb:
            sv = render_ahb_class_tb(module, ahb, cycles=cycles, seed=seed)
        elif wb:
            sv = render_wishbone_class_tb(module, wb, cycles=cycles, seed=seed)
        elif av:
            sv = render_avalon_class_tb(module, av, cycles=cycles, seed=seed)
        elif can:
            sv = render_can_class_tb(module, can, cycles=cycles, seed=seed, knobs=knobs)
        elif uart_rx and (uart_dir == "rx" or not uart):
            sv = render_uart_rx_class_tb(module, uart_rx, cycles=cycles, seed=seed, knobs=knobs)
        elif uart and uart_dir != "rx":
            sv = render_uart_class_tb(module, uart, cycles=cycles, seed=seed)
        elif spi:
            sv = render_spi_class_tb(module, spi, cycles=cycles, seed=seed, knobs=knobs)
        elif i2c_role == "master" and detect_i2c_master_model(roles):
            sv = None
        elif i2c and i2c_role != "master":
            sv = render_i2c_class_tb(module, i2c, cycles=cycles, seed=seed)
        elif fsm:
            sv = render_fsm_class_tb(module, fsm, cycles=cycles, seed=seed)
    if sv:
        try:
            from tb_scale_emit import apply_scale_emit

            sv = apply_scale_emit(sv, module)
        except Exception:
            pass
    return sv


def _layered_shell(
    module: dict,
    *,
    extra_classes: str,
    env_run: str,
    txn_fields: str,
    constraint: str,
    cycles: int,
    seed: int,
    tag: str,
    clk_name: str,
    rst_name: Optional[str],
    active_low: bool,
    post_reset_check: str = "",
) -> str:
    """Shared IF/gen/drv/mon/sb/env/test wrapper for directed bus TBs."""
    name = module.get("name") or "dut"
    ports = module.get("ports") or []
    tb_name = f"{name}_tb"
    if_name = f"{name}_if"
    roles = classify_ports(ports)
    clk = roles["clk"]
    clk_n = (clk or {}).get("name") or clk_name
    if_sigs = []
    dut_map = []
    for p in ports:
        pn = p["name"]
        if clk and pn == clk["name"]:
            dut_map.append(f"    .{pn}({clk_n})")
            continue
        if_sigs.append(f"  {sv_type(p.get('width', ''), p)} {pn};")
        dut_map.append(f"    .{pn}(vif.{pn})")
    dut_mapped = [
        line + ("," if i < len(dut_map) - 1 else "") for i, line in enumerate(dut_map)
    ]
    rst_assert = "1'b0" if active_low else "1'b1"
    rst_deassert = "1'b1" if active_low else "1'b0"
    in_zeros = "\n".join(
        f"    vif.{p['name']} = '0;" for p in (roles.get("inputs") or [])
    ) or "    ;"
    rst_block = ""
    if rst_name:
        rst_block = f"""    vif.{rst_name} = {rst_assert};
{in_zeros}
    repeat (4) @(posedge vif.clk);
    vif.{rst_name} = {rst_deassert};
    @(posedge vif.clk);
    #1;"""
    return f"""// ChipSutra Pure SV layered class TB — {tag}
`timescale 1ns / 1ps

interface {if_name}(input logic clk);
{chr(10).join(if_sigs)}
endinterface

class {name}_txn;
{txn_fields}
  constraint legal_c {{ {constraint} }}
endclass

{extra_classes}

class {name}_env;
  virtual {if_name} vif;
  mailbox #({name}_txn) gen2drv;
  {name}_generator gen;
  {name}_driver drv;
  {name}_scoreboard sb;
  function new(virtual {if_name} vif);
    this.vif = vif;
  endfunction
  function void build(int n);
    gen2drv = new();
    gen = new(gen2drv, n);
    drv = new(vif, gen2drv);
    sb = new();
    drv.sb = sb;
  endfunction
  task run(int n);
{env_run}
  endtask
  function void report();
    if (sb.errors == 0) $display("PASS: {tb_name} {tag} class SV OK");
    else $display("FAIL: {tb_name} - %0d error(s)", sb.errors);
  endfunction
endclass

class {name}_test;
  virtual {if_name} vif;
  {name}_env env;
  function new(virtual {if_name} vif);
    this.vif = vif;
    env = new(vif);
  endfunction
  task run(int n = {cycles});
    env.build(n);
{rst_block}
{post_reset_check}
    env.run(n);
    env.report();
  endtask
endclass

module {tb_name};
  logic {clk_n};
  {if_name} vif({clk_n});
  {name} dut (
{chr(10).join(dut_mapped)}
  );
  always #5 {clk_n} = ~{clk_n};
  initial begin
    {name}_test t;
    $dumpfile("{tb_name}.vcd");
    $dumpvars(0, {tb_name});
    void'($urandom({seed}));
    {clk_n} = 0;
    t = new(vif);
    t.run({cycles});
    $finish;
  end
endmodule
"""


def render_axi_class_tb(module: dict, *, cycles: int = 16, seed: int = 1) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "aclk"
    rst = (roles["rst"] or {}).get("name") or "aresetn"
    use_map = False
    csrs: List[dict] = []
    try:
        from tb_ral import addr_inside_constraint, csr_list_of, render_sv_reg_model, wants_ral

        csrs = csr_list_of(module)
        use_map = wants_ral(module) and bool(csrs)
    except Exception:
        use_map = False
    if use_map:
        sb = (
            render_sv_reg_model(name, csrs)
            + f"""
class {name}_scoreboard;
  {name}_reg_model ral;
  int errors;
  function new(); ral = new(); errors = 0; endfunction
  function void predict_write(logic [31:0] addr, logic [31:0] data);
    ral.predict_write(addr, data);
  endfunction
  function bit check_read(logic [31:0] addr, logic [31:0] rdata);
    return ral.check_read(addr, rdata);
  endfunction
endclass
"""
        )
        wr_sig = "logic [31:0] addr"
        wr_addr = "addr"
        txn_fields = "  rand logic [31:0] addr;\n  rand logic [31:0] data;"
        constraint = addr_inside_constraint(csrs)
        tag = "axi_lite_ral"
        run_call = "      axi_write(t.addr, t.data);\n      axi_read(t.addr);"
    else:
        sb = f"""
class {name}_scoreboard;
  logic [31:0] model_reg [0:3];
  int errors;
  function new();
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
    errors = 0;
  endfunction
  function void predict_write(bit [1:0] sel, logic [31:0] data);
    model_reg[sel] = data;
  endfunction
  function bit check_read(bit [1:0] sel, logic [31:0] rdata);
    return (rdata === model_reg[sel]);
  endfunction
endclass
"""
        wr_sig = "bit [1:0] sel"
        wr_addr = "{sel, 2'b00}"
        txn_fields = "  rand bit [1:0] sel;\n  rand logic [31:0] data;"
        constraint = "sel inside {[0:3]};"
        tag = "axi_lite"
        run_call = "      axi_write(t.sel, t.data);\n      axi_read(t.sel);"
    extra = f"""
{sb}
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n);
    gen2drv = mb; n_txns = n;
  endfunction
  task run();
    {name}_txn t;
    repeat (n_txns) begin
      t = new();
      assert(t.randomize());
      gen2drv.put(t);
    end
  endtask
endclass

class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  int timeout;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task axi_write({wr_sig}, logic [31:0] data);
    vif.s_axi_awaddr = {wr_addr}; vif.s_axi_wdata = data; vif.s_axi_wstrb = 4'hF;
    vif.s_axi_awprot = '0; vif.s_axi_awvalid = 1; vif.s_axi_wvalid = 1;
    timeout = 0;
    @(posedge vif.clk);
    while (!(vif.s_axi_awready && vif.s_axi_wready) && timeout < 40) begin
      @(posedge vif.clk); timeout++;
    end
    @(posedge vif.clk);
    vif.s_axi_awvalid = 0; vif.s_axi_wvalid = 0; vif.s_axi_bready = 1;
    timeout = 0;
    while (!vif.s_axi_bvalid && timeout < 40) begin @(posedge vif.clk); timeout++; end
    @(posedge vif.clk);
    vif.s_axi_bready = 0;
    sb.predict_write({wr_addr if use_map else "sel"}, data);
  endtask
  task axi_read({wr_sig});
    logic [31:0] rdata;
    vif.s_axi_araddr = {wr_addr}; vif.s_axi_arprot = '0; vif.s_axi_arvalid = 1;
    timeout = 0;
    @(posedge vif.clk);
    while (!vif.s_axi_arready && timeout < 40) begin @(posedge vif.clk); timeout++; end
    @(posedge vif.clk);
    vif.s_axi_arvalid = 0; vif.s_axi_rready = 1;
    timeout = 0;
    while (!vif.s_axi_rvalid && timeout < 40) begin @(posedge vif.clk); timeout++; end
    rdata = vif.s_axi_rdata;
    if (!sb.check_read({wr_addr if use_map else "sel"}, rdata) || vif.s_axi_rresp !== 2'b00) sb.errors++;
    @(posedge vif.clk);
    vif.s_axi_rready = 0;
  endtask
  task run(int n);
    {name}_txn t;
    vif.s_axi_awvalid = 0; vif.s_axi_wvalid = 0; vif.s_axi_arvalid = 0;
    vif.s_axi_bready = 0; vif.s_axi_rready = 0; vif.s_axi_wstrb = 4'hF;
    repeat (n) begin
      gen2drv.get(t);
{run_call}
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    env_run = f"""    gen.run();
    drv.run(n);"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run=env_run,
        txn_fields=txn_fields,
        constraint=constraint,
        cycles=max(4, cycles // 2),
        seed=seed,
        tag=tag,
        clk_name=clk,
        rst_name=rst,
        active_low=True,
        post_reset_check="    if (vif.s_axi_rdata !== '0) env.sb.errors++;",
    )


def render_apb_class_tb(module: dict, *, cycles: int = 16, seed: int = 1) -> str:
    from tb_skeleton import detect_apb_model

    roles = classify_ports(module.get("ports") or [])
    apb = detect_apb_model(roles) or {}
    name = module.get("name") or "dut"
    clk = (roles["clk"] or {}).get("name") or "PCLK"
    rst = (roles["rst"] or {}).get("name") or "PRESETn"
    psel, pen, pw = apb.get("psel", "PSEL"), apb.get("penable", "PENABLE"), apb.get("pwrite", "PWRITE")
    pa, pwd = apb.get("paddr", "PADDR"), apb.get("pwdata", "PWDATA")
    prd, pry = apb.get("prdata", "PRDATA"), apb.get("pready", "PREADY")
    use_map = False
    csrs: List[dict] = []
    try:
        from tb_ral import addr_inside_constraint, csr_list_of, render_sv_reg_model, wants_ral

        csrs = csr_list_of(module)
        use_map = wants_ral(module) and bool(csrs)
    except Exception:
        use_map = False
    if use_map:
        sb = (
            render_sv_reg_model(name, csrs)
            + f"""
class {name}_scoreboard;
  {name}_reg_model ral;
  int errors;
  function new(); ral = new(); errors = 0; endfunction
endclass
"""
        )
        wr_sig = "logic [31:0] addr"
        wr_addr = "addr"
        pred = "sb.ral.predict_write(addr, data);"
        chk = f"if (!sb.ral.check_read(addr, vif.{prd})) sb.errors++;"
        txn_fields = "  rand logic [31:0] addr;\n  rand logic [31:0] data;"
        constraint = addr_inside_constraint(csrs)
        tag = "apb_ral"
        run_call = "      apb_write(t.addr, t.data);\n      apb_read(t.addr);"
    else:
        sb = f"""
class {name}_scoreboard;
  logic [31:0] model_reg [0:3];
  int errors;
  function new();
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
    errors = 0;
  endfunction
endclass
"""
        wr_sig = "bit [1:0] sel"
        wr_addr = "{sel, 2'b00}"
        pred = "sb.model_reg[sel] = data;"
        chk = f"if (vif.{prd} !== sb.model_reg[sel]) sb.errors++;"
        txn_fields = "  rand bit [1:0] sel;\n  rand logic [31:0] data;"
        constraint = "sel inside {[0:3]};"
        tag = "apb"
        run_call = "      apb_write(t.sel, t.data);\n      apb_read(t.sel);"
    extra = f"""
{sb}

class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n);
    gen2drv = mb; n_txns = n;
  endfunction
  task run();
    {name}_txn t;
    repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass

class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  int timeout;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task apb_write({wr_sig}, logic [31:0] data);
    vif.{pa} = {wr_addr}; vif.{pwd} = data;
    vif.{psel} = 1; vif.{pen} = 0; vif.{pw} = 1;
    @(posedge vif.clk);
    vif.{pen} = 1; timeout = 0;
    @(posedge vif.clk);
    while (!vif.{pry} && timeout < 40) begin @(posedge vif.clk); timeout++; end
    #1;
    {pred}
    vif.{psel} = 0; vif.{pen} = 0; vif.{pw} = 0;
    @(posedge vif.clk);
  endtask
  task apb_read({wr_sig});
    vif.{pa} = {wr_addr};
    vif.{psel} = 1; vif.{pen} = 0; vif.{pw} = 0;
    @(posedge vif.clk);
    vif.{pen} = 1; timeout = 0;
    @(posedge vif.clk);
    while (!vif.{pry} && timeout < 40) begin @(posedge vif.clk); timeout++; end
    #1;
    {chk}
    vif.{psel} = 0; vif.{pen} = 0;
    @(posedge vif.clk);
  endtask
  task run(int n);
    {name}_txn t;
    vif.{psel} = 0; vif.{pen} = 0; vif.{pw} = 0;
    repeat (n) begin
      gen2drv.get(t);
{run_call}
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields=txn_fields,
        constraint=constraint,
        cycles=max(4, cycles // 2),
        seed=seed,
        tag=tag,
        clk_name=clk,
        rst_name=rst,
        active_low=True,
        post_reset_check=f"    if (vif.{prd} !== '0) env.sb.errors++;",
    )


def render_ahb_class_tb(module: dict, ahb: dict, *, cycles: int = 16, seed: int = 1) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "HCLK"
    rst = (roles["rst"] or {}).get("name") or "HRESETn"
    extra = f"""
class {name}_scoreboard;
  logic [31:0] model_reg [0:3];
  int errors;
  function new();
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
    errors = 0;
  endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task ahb_write(bit [1:0] sel, logic [31:0] data);
    logic [7:0] addr;
    addr = {{6'b0, sel}} << 2;
    vif.HSEL = 1'b1; vif.HREADY = 1'b1;
    vif.HADDR = addr; vif.HWRITE = 1'b1; vif.HTRANS = 2'b10; vif.HWDATA = data;
    @(posedge vif.clk);
    #1;
    vif.HWDATA = data; vif.HTRANS = 2'b00;
    @(posedge vif.clk);
    #1;
    vif.HWRITE = 1'b0;
    @(posedge vif.clk);
    #1;
    sb.model_reg[sel] = data;
  endtask
  task ahb_read(bit [1:0] sel);
    logic [7:0] addr;
    addr = sel * 8'd4;
    vif.HSEL = 1; vif.HREADY = 1;
    vif.HADDR = addr; vif.HWRITE = 0; vif.HTRANS = 2'b10;
    @(posedge vif.clk);
    vif.HTRANS = 2'b00;
    @(posedge vif.clk);
    #1;
    if (vif.HRDATA !== sb.model_reg[sel]) begin
      $display("[%0t] ahb mismatch sel=%0d exp=%h got=%h", $time, sel, sb.model_reg[sel], vif.HRDATA);
      sb.errors++;
    end
  endtask
  task run(int n);
    {name}_txn t;
    vif.HSEL = 1; vif.HREADY = 1; vif.HTRANS = 2'b00; vif.HWRITE = 0; vif.HWDATA = '0;
    repeat (n) begin
      gen2drv.get(t);
      ahb_write(t.sel, t.data);
      ahb_read(t.sel);
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand bit [1:0] sel;\n  rand logic [31:0] data;",
        constraint="sel inside {[0:3]};",
        cycles=max(4, cycles // 2),
        seed=seed,
        tag="ahb",
        clk_name=clk,
        rst_name=rst,
        active_low=True,
        post_reset_check="    if (vif.HRDATA !== '0) env.sb.errors++;",
    )


def render_uart_class_tb(module: dict, uart: dict, *, cycles: int = 16, seed: int = 1) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "clk"
    rst = (roles["rst"] or {}).get("name") or "rst_n"
    last = (uart.get("last") or {}).get("name") or "last_byte"
    extra = f"""
class {name}_scoreboard;
  int errors;
  function new(); errors = 0; endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  int timeout;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task run(int n);
    {name}_txn t;
    vif.start = 0;
    repeat (n) begin
      gen2drv.get(t);
      timeout = 0;
      while (vif.busy === 1'b1 && timeout < 200) begin
        @(posedge vif.clk); #1; timeout++;
      end
      vif.din = t.din;
      vif.start = 1;
      @(posedge vif.clk);
      #1;
      vif.start = 0;
      if (vif.{last} !== t.din) sb.errors++;
      timeout = 0;
      while (vif.busy === 1'b1 && timeout < 200) begin
        @(posedge vif.clk); #1; timeout++;
      end
      @(posedge vif.clk); #1;
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand logic [7:0] din;",
        constraint="soft din != 8'h00;",
        cycles=max(2, min(cycles // 8, 4)),
        seed=seed,
        tag="uart",
        clk_name=clk,
        rst_name=rst,
        active_low=True,
    )


def render_spi_class_tb(
    module: dict, spi: dict, *, cycles: int = 16, seed: int = 1, knobs: Optional[dict] = None
) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "sclk"
    cs = spi["cs"]["name"]
    mosi = spi["mosi"]["name"]
    rx = spi["rx"]["name"]
    mode = 0
    if knobs and knobs.get("spi_mode") is not None:
        try:
            mode = int(knobs["spi_mode"]) & 3
        except (TypeError, ValueError):
            mode = 0
    if mode in (1, 2):
        drive, sample = "posedge", "negedge"
    else:
        drive, sample = "negedge", "posedge"
    # Mode 0 keeps the historical unroll (eval spi_slave). Other modes use the same
    # bit order with swapped edges from the user knob.
    if mode == 0:
        shift = f"""      @(negedge vif.clk);
      vif.{cs} = 0;
      vif.{mosi} = d[7];
      @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[6]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[5]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[4]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[3]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[2]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[1]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{mosi} = d[0]; @(posedge vif.clk);"""
    else:
        rest = "\n".join(
            f"      @({drive} vif.clk); vif.{mosi} = d[{i}]; @({sample} vif.clk);"
            for i in range(6, -1, -1)
        )
        shift = f"""      // SPI mode {mode} (user knob)
      @({drive} vif.clk);
      vif.{cs} = 0;
      vif.{mosi} = d[7];
      @({sample} vif.clk);
{rest}"""
    extra = f"""
class {name}_scoreboard;
  int errors;
  function new(); errors = 0; endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task run(int n);
    {name}_txn t;
    logic [7:0] d;
    vif.{cs} = 1; vif.{mosi} = 0;
    repeat (2) @(posedge vif.clk);
    repeat (n) begin
      gen2drv.get(t);
      d = t.data;
{shift}
      #1;
      if (vif.{rx} !== t.data) begin
        $display("[%0t] spi mismatch exp=%h got=%h", $time, t.data, vif.{rx});
        sb.errors++;
      end
      vif.{cs} = 1;
      @(posedge vif.clk);
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand logic [7:0] data;",
        constraint="soft data != 8'h00;",
        cycles=max(2, min(cycles // 4, 6)),
        seed=seed,
        tag="spi" if mode == 0 else f"spi_mode{mode}",
        clk_name=clk,
        rst_name=None,
        active_low=True,
    )


def render_i2c_class_tb(module: dict, i2c: dict, *, cycles: int = 16, seed: int = 1) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "scl"
    sda = i2c["sda"]["name"]
    start = i2c["start"]["name"]
    last = i2c["last"]["name"]
    got = (i2c.get("got") or {}).get("name")
    got_chk = f" || vif.{got} !== 1'b1" if got else ""
    extra = f"""
class {name}_scoreboard;
  int errors;
  function new(); errors = 0; endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task run(int n);
    {name}_txn t;
    logic [7:0] d;
    vif.{start} = 0; vif.{sda} = 0;
    @(negedge vif.clk);
    repeat (n) begin
      gen2drv.get(t);
      d = t.data;
      vif.{start} = 1;
      #2;
      vif.{start} = 0;
      vif.{sda} = d[7];
      @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[6]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[5]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[4]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[3]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[2]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[1]; @(posedge vif.clk);
      @(negedge vif.clk); vif.{sda} = d[0]; @(posedge vif.clk);
      #1;
      if (vif.{last} !== t.data{got_chk}) begin
        $display("[%0t] i2c mismatch exp=%h got=%h", $time, t.data, vif.{last});
        sb.errors++;
      end
      @(negedge vif.clk);
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand logic [7:0] data;",
        constraint="soft data != 8'h00;",
        cycles=max(2, min(cycles // 4, 6)),
        seed=seed,
        tag="i2c",
        clk_name=clk,
        rst_name=None,
        active_low=True,
    )


def render_uart_rx_class_tb(
    module: dict, uart: dict, *, cycles: int = 16, seed: int = 1, knobs: Optional[dict] = None
) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "clk"
    rst = (roles["rst"] or {}).get("name") or "rst_n"
    rx = uart["rx"]["name"]
    dout = uart["dout"]["name"]
    valid = (uart.get("valid") or {}).get("name")
    div = 1
    if knobs and knobs.get("uart_baud_div"):
        try:
            div = max(1, int(knobs["uart_baud_div"]))
        except (TypeError, ValueError):
            div = 1
    valid_chk = (
        f" || vif.{valid} !== 1'b1" if valid else ""
    )
    extra = f"""
class {name}_scoreboard;
  int errors;
  function new(); errors = 0; endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  int baud_div;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb; baud_div = {div};
  endfunction
  task bit_hold();
    repeat (baud_div) @(posedge vif.clk);
  endtask
  task run(int n);
    {name}_txn t;
    logic [7:0] d;
    vif.{rx} = 1'b1;
    repeat (2) @(posedge vif.clk);
    repeat (n) begin
      gen2drv.get(t);
      d = t.data;
      vif.{rx} = 1'b0;
      bit_hold();
      vif.{rx} = d[0]; bit_hold();
      vif.{rx} = d[1]; bit_hold();
      vif.{rx} = d[2]; bit_hold();
      vif.{rx} = d[3]; bit_hold();
      vif.{rx} = d[4]; bit_hold();
      vif.{rx} = d[5]; bit_hold();
      vif.{rx} = d[6]; bit_hold();
      vif.{rx} = d[7]; bit_hold();
      vif.{rx} = 1'b1;
      bit_hold();
      #1;
      if (vif.{dout} !== t.data{valid_chk}) begin
        $display("[%0t] uart_rx mismatch exp=%h got=%h", $time, t.data, vif.{dout});
        sb.errors++;
      end
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand logic [7:0] data;",
        constraint="soft data != 8'h00;",
        cycles=max(2, min(cycles // 8, 4)),
        seed=seed,
        tag="uart_rx",
        clk_name=clk,
        rst_name=rst,
        active_low=True,
    )


def render_can_class_tb(
    module: dict, can: dict, *, cycles: int = 8, seed: int = 1, knobs: Optional[dict] = None
) -> str:
    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles["clk"] or {}).get("name") or "clk"
    rst = (roles["rst"] or {}).get("name")
    rx = can["rx"]["name"]
    tx = can["tx"]["name"]
    bit_clocks = 0
    if knobs and knobs.get("can_bit_clocks"):
        try:
            bit_clocks = max(0, int(knobs["can_bit_clocks"]))
        except (TypeError, ValueError):
            bit_clocks = 0
    sof = ""
    if bit_clocks:
        sof = f"""
      vif.{rx} = 1'b0;
      repeat ({bit_clocks}) @(posedge vif.clk);
      vif.{rx} = 1'b1;
      @(posedge vif.clk);"""
    extra = f"""
class {name}_scoreboard;
  int errors;
  function new(); errors = 0; endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t; repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
  endtask
endclass
class {name}_driver;
  virtual {name}_if vif;
  mailbox #({name}_txn) gen2drv;
  {name}_scoreboard sb;
  function new(virtual {name}_if vif, mailbox #({name}_txn) mb);
    this.vif = vif; gen2drv = mb;
  endfunction
  task run(int n);
    {name}_txn t;
    vif.{rx} = 1'b1;
    repeat (4) @(posedge vif.clk);
    repeat (n) begin
      gen2drv.get(t);
      // Recessive idle. SOF only if user provided can_bit_clocks — never invent bit-time.
{sof}
      if ($isunknown(vif.{tx})) begin
        $display("[%0t] can_tx unknown after idle/SOF", $time);
        sb.errors++;
      end
    end
  endtask
endclass
class {name}_monitor;
endclass
"""
    return _layered_shell(
        module,
        extra_classes=extra,
        env_run="    gen.run();\n    drv.run(n);",
        txn_fields="  rand bit dummy;",
        constraint="soft dummy == 1'b0;",
        cycles=max(2, min(cycles, 4)),
        seed=seed,
        tag="can",
        clk_name=clk,
        rst_name=rst,
        active_low=True,
    )
