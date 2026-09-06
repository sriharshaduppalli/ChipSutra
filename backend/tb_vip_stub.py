"""VIP-bound protocol stubs — port-correct IF, no invented handshake golden.

AXI4 burst / ACE / CHI / PCIe / CXL / UCIe / DDR / USB / MIPI need a user VIP.
ChipSutra must not emit a fake ready/valid or TLP timing model.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

VIP_PROTOCOLS = frozenset(
    {
        "axi4",
        "ace",
        "chi",
        "pcie",
        "cxl",
        "ucie",
        "ddr",
        "usb",
        "mipi",
    }
)


def needs_user_vip(module: Optional[dict], rtl_text: str = "") -> Tuple[bool, Dict[str, Any]]:
    """True only for VIP-bound protocols (AXI4 burst / PCIe / CHI / …).

    Scale flags like ``require_user_vip`` on APB/AXI-Lite mean "overlay a VIP
    sketch" — they must not replace the pin-level golden with a stub.
    """
    cls: Dict[str, Any] = {}
    if not module:
        return False, cls
    knobs = module.get("_dv_knobs") if isinstance(module.get("_dv_knobs"), dict) else {}
    try:
        from dv_planner import classify_dut

        user_cfg = knobs if knobs else None
        cls = classify_dut([module], rtl_text=rtl_text or "", user_config=user_cfg)
    except Exception:
        cls = {}
    proto = str(
        knobs.get("design_protocol")
        or knobs.get("protocol")
        or (cls.get("protocol") if cls else "")
        or ""
    ).lower()
    if proto in VIP_PROTOCOLS:
        if cls:
            cls = {**cls, "protocol": proto}
        else:
            cls = {"protocol": proto, "tags": ["require_user_vip"]}
        return True, cls
    return False, cls or {"protocol": proto}


def render_class_sv_vip_stub(
    module: dict,
    *,
    protocol: str = "axi4",
    cycles: int = 8,
    seed: int = 1,
) -> str:
    """Layered Pure SV shell: reset + idle. No invented burst/TLP golden."""
    from tb_dut_goldens import _layered_shell
    from tb_skeleton import classify_ports

    name = module.get("name") or "dut"
    roles = classify_ports(module.get("ports") or [])
    clk = (roles.get("clk") or {}).get("name") or "clk"
    rst = (roles.get("rst") or {}).get("name")
    active_low = bool(roles.get("active_low_reset", True))
    proto = protocol or "vip"
    extra = f"""
class {name}_scoreboard;
  int errors;
  function new(); errors = 0; endfunction
  function void note();
    $display("ChipSutra VIP stub ({proto}): attach user VIP — no invented pin golden");
  endfunction
endclass
class {name}_generator;
  mailbox #({name}_txn) gen2drv;
  int n_txns;
  function new(mailbox #({name}_txn) mb, int n); gen2drv = mb; n_txns = n; endfunction
  task run();
    {name}_txn t;
    repeat (n_txns) begin t = new(); assert(t.randomize()); gen2drv.put(t); end
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
    sb.note();
    repeat (n) begin
      gen2drv.get(t);
      @(posedge vif.clk);
      // Idle the bus — do not invent {proto} ready/valid or TLP timing
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
        txn_fields="  rand bit pad;",
        constraint="soft pad == 1'b0;",
        cycles=max(2, min(int(cycles or 8), 8)),
        seed=seed,
        tag=f"vip_stub {proto} require_user_vip",
        clk_name=clk,
        rst_name=rst,
        active_low=active_low,
    )
