"""UVM TB lint — fake APIs and missing boilerplate."""
from rtl_ports import extract_modules
from tb_lint import choose_testbench_output
from tb_uvm_lint import lint_uvm_tb, repair_uvm_hints, repair_uvm_tb
from tb_uvm_skeleton import render_uvm_smoke_tb

FAKE_UVM = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class my_driver extends uvm_driver #(txn);
  virtual task run_phase(uvm_phase phase);
    seq_item_port.put(req);  // fake
    driver.start(this);
  endtask
endclass
module tb;
  initial begin
    vif.configure(vif);
    void'(cast(rhs));
  end
endmodule
"""


def test_detects_fake_apis_and_missing():
    ok, issues = lint_uvm_tb(FAKE_UVM)
    assert not ok
    assert "uvm_fake_api:put" in issues
    assert "uvm_fake_api:driver_start" in issues
    assert "uvm_fake_api:configure" in issues
    assert "uvm_fake_api:cast" in issues
    assert "uvm_missing_config_db" in issues
    assert "uvm_missing_run_test" in issues


def test_soft_missing_utils():
    sv = """
    class my_agent extends uvm_agent;
      function new(string name, uvm_component parent); super.new(name, parent); endfunction
    endclass
    module tb; initial run_test(); endmodule
    """
    # config_db still missing → hard fail; utils soft
    ok, issues = lint_uvm_tb(sv)
    assert "uvm_missing_component_utils" in issues
    assert "uvm_missing_config_db" in issues


def test_repair_appends_hints_only():
    out = repair_uvm_hints(FAKE_UVM)
    assert "CHIP_SUTRA_UVM_HINTS" in out
    assert "run_test" in out
    assert "uvm_config_db" in out
    # idempotent
    assert repair_uvm_hints(out).count("CHIP_SUTRA_UVM_HINTS") == 1


BROKEN_UVM_STRUCT = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_scoreboard extends uvm_component;
  `uvm_component_utils(counter_en_scoreboard)
  uvm_analysis_port #(int) mon_ap;
  task run_phase(uvm_phase phase);
    forever begin int t; mon_ap.get(t); end
  endtask
endclass
class counter_en_env extends uvm_env;
  `uvm_component_utils(counter_en_env)
  counter_en_agent agent;
  counter_en_scoreboard scoreboard;
  function void build_phase(uvm_phase phase);
    agent = counter_en_agent::type_id::create("agent", this);
    scoreboard = counter_en_scoreboard::type_id::create("scoreboard", this);
    agent.mon.ap.connect(scoreboard.mon_ap);
  endfunction
endclass
class counter_en_agent extends uvm_agent;
  `uvm_component_utils(counter_en_agent)
  counter_en_monitor mon;
endclass
class counter_en_tb extends uvm_test_top;
  `uvm_component_utils(counter_en_tb)
  task run_test();
    run_phase.raise_objection(this);
  endtask
endclass
module testbench;
  initial run_test("counter_en_tb");
endmodule
"""


def test_uvm_structural_gates():
    ok, issues = lint_uvm_tb(BROKEN_UVM_STRUCT)
    assert not ok
    assert "uvm_fake_base:test_top" in issues
    assert "uvm_fake_api:phase_objection" in issues
    assert "uvm_connect_in_build" in issues
    assert "uvm_sb_analysis_port_get" in issues
    out = repair_uvm_hints(BROKEN_UVM_STRUCT)
    assert "connect_phase" in out
    assert "uvm_analysis_imp" in out or "analysis_imp" in out


def test_phase_raise_objection_is_not_fake():
    """Correct UVM: phase.raise_objection(this) — must not flag as fake API."""
    sv = """
    import uvm_pkg::*;
    `include "uvm_macros.svh"
    class t extends uvm_test;
      `uvm_component_utils(t)
      task run_phase(uvm_phase phase);
        phase.raise_objection(this);
        phase.drop_objection(this);
      endtask
    endclass
    module tb;
      logic clk; dut_if vif(clk);
      my_dut dut (.clk(clk), .d(vif.d));
      initial begin
        uvm_config_db#(virtual dut_if)::set(null, "*", "vif", vif);
        run_test("t");
      end
    endmodule
    """
    ok, issues = lint_uvm_tb(sv)
    assert "uvm_fake_api:phase_objection" not in issues
    assert "uvm_missing_dut_instance" not in issues


# Latest chipsutra-vlsi:7b UVM output (counter) — illegal SV + broken TLM.
USER_COUNTER_UVM = r"""
import uvm_pkg::*;

class counter_rtl_txn extends uvm_sequence_item;
  rand bit enable;
  `uvm_object_utils(counter_rtl_txn)
  function new(string name = "counter_rtl_txn");
    super.new(name);
  endfunction
endclass

class counter_rtl_monitor extends uvm_subscriber #(counter_rtl_txn);
  `uvm_component_utils(counter_rtl_monitor)
  virtual counter_rtl_if vif;
  function new(string name, uvm_component parent = null);
    super.new(name, parent);
  endfunction
  task run_phase(uvm_phase phase);
    forever begin
      @(posedge vif.clk) begin
        counter_rtl_txn t = counter_rtl_txn::type_id::create("t");
        t.enable = vif.enable;
        write(t);
      end
    end
  endtask
endclass

class counter_rtl_driver extends uvm_driver #(counter_rtl_txn);
  `uvm_component_utils(counter_rtl_driver)
  virtual counter_rtl_if vif;
  function new(string name, uvm_component parent = null);
    super.new(name, parent);
  endfunction
  task run_phase(uvm_phase phase);
    forever begin
      seq_item_port.get_next_item(req);
      drive_item(req);
      seq_item_port.item_done();
    end
  endtask
  protected virtual void drive_item(counter_rtl_txn t) begin
    @(posedge vif.clk);
    vif.enable = t.enable;
  endprotected
endclass

class counter_rtl_agent extends uvm_agent;
  `uvm_component_utils(counter_rtl_agent)
  counter_rtl_driver driver;
  counter_rtl_monitor monitor;
  function new(string name, uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual counter_rtl_if)::get(this, "", "vif", vif))
      `uvm_fatal("NOVIF", "Failed to get virtual interface")
    driver = counter_rtl_driver::type_id::create("driver", this);
    monitor = counter_rtl_monitor::type_id::create("monitor", this);
  endfunction
  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    driver.seq_item_port.connect(monitor.analysis_export);
  endfunction
endclass

class counter_rtl_scoreboard extends uvm_component;
  `uvm_component_utils(counter_rtl_scoreboard)
  int count = 0;
  function new(string name, uvm_component parent = null);
    super.new(name, parent);
  endfunction
  task run_phase(uvm_phase phase);
    forever begin
      counter_rtl_txn t;
      seq_item_port.get(t);
      if (t.enable) begin
        count++;
      end else begin
        count = 0;
      end
    end
  endtask
endclass

class counter_rtl_env extends uvm_env;
  `uvm_component_utils(counter_rtl_env)
  counter_rtl_agent agent;
  counter_rtl_scoreboard scoreboard;
  function new(string name, uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    agent = counter_rtl_agent::type_id::create("agent", this);
    scoreboard = counter_rtl_scoreboard::type_id::create("scoreboard", this);
  endfunction
  virtual function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent.seq_item_port.connect(scoreboard.seq_item_export);
  endfunction
endclass

class counter_rtl_test extends uvm_test;
  `uvm_component_utils(counter_rtl_test)
  counter_rtl_env env;
  function new(string name, uvm_component parent = null);
    super.new(name, parent);
  endfunction
  virtual function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    env = counter_rtl_env::type_id::create("env", this);
  endfunction
  task run_phase(uvm_phase phase);
    uvm_sequence#(counter_rtl_txn) seq;
    seq = new();
    phase.raise_objection(this);
    seq.start(env.agent.sequencer);
    #100;
    phase.drop_objection(this);
  endtask
endclass

module counter_rtl_tb;
  logic clk;
  counter_rtl_if vif(clk);
  counter_rtl dut (
    .clk(clk),
    .rst_n(vif.rst_n),
    .enable(vif.enable),
    .count(vif.count)
  );
  initial begin
    clk = 0;
    forever #5 clk = ~clk;
  end
  initial begin
    uvm_config_db#(virtual counter_rtl_if)::set(null, "*", "vif", vif);
    run_test("counter_rtl_test");
  end
endmodule
"""


def test_user_counter_uvm_is_hard_fail():
    ok, issues = lint_uvm_tb(USER_COUNTER_UVM)
    assert not ok
    for tag in (
        "uvm_illegal_sv:endprotected",
        "uvm_illegal_sv:virtual_void",
        "uvm_missing_interface",
        "uvm_missing_sequencer",
        "uvm_wrong_tlm",
        "uvm_sb_seq_item_get",
        "uvm_monitor_is_subscriber",
        "uvm_generic_seq_new",
    ):
        assert tag in issues, issues


def test_user_counter_uvm_falls_back_to_skeleton():
    """7b llm_repaired UVM that looks complete but is illegal must not ship."""
    rtl = """
module counter_rtl (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""
    mods = extract_modules(rtl)
    skel = render_uvm_smoke_tb(mods[0])
    fixed = repair_uvm_tb(
        USER_COUNTER_UVM, dut_name="counter_rtl", port_specs=mods[0]["ports"]
    )
    assert "interface counter_rtl_if" in fixed
    assert "uvm_sequencer" in fixed
    assert "expected" in fixed
    assert "endprotected" not in fixed
    ok2, issues2 = lint_uvm_tb(fixed)
    assert ok2, issues2
    out, engine, _iss = choose_testbench_output(
        USER_COUNTER_UVM,
        skeleton=skel,
        dut_name="counter_rtl",
        force_uvm=True,
        port_specs=mods[0]["ports"],
    )
    assert engine in ("llm_repaired", "skeleton_fallback")
    assert "interface counter_rtl_if" in out
    assert "uvm_sequencer" in out
    assert "expected" in out
    assert "endprotected" not in out
    assert "virtual void" not in out


MIXED_UVM_PURE_SV = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_txn;
  rand bit enable;
endclass
class counter_en_generator;
  mailbox #(counter_en_txn) gen2drv;
  function new(mailbox #(counter_en_txn) mb); gen2drv = mb; endfunction
  task run(int n); counter_en_txn t; repeat (n) begin t = new(); gen2drv.put(t); end endtask
endclass
class counter_en_env extends uvm_env;
  `uvm_component_utils(counter_en_env)
  counter_en_generator gen;
  mailbox #(counter_en_txn) gen2drv;
  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction
  function void build_phase(uvm_phase phase);
    gen2drv = new();
    gen = new(gen2drv);
  endfunction
endclass
class counter_en_test extends uvm_test;
  `uvm_component_utils(counter_en_test)
  counter_en_env env;
  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    env.gen.run(8);
    phase.drop_objection(this);
  endtask
endclass
module counter_en_tb;
  logic clk;
  initial run_test("counter_en_test");
endmodule
"""


def test_mixed_uvm_pure_sv_is_hard_fail():
    ok, issues = lint_uvm_tb(MIXED_UVM_PURE_SV)
    assert not ok
    assert "uvm_mixed_pure_sv" in issues


def test_mixed_uvm_pure_sv_falls_back_to_skeleton():
    rtl = """
module counter_en (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""
    mods = extract_modules(rtl)
    fixed = repair_uvm_tb(
        MIXED_UVM_PURE_SV, dut_name="counter_en", port_specs=mods[0]["ports"]
    )
    assert "uvm_sequencer" in fixed
    assert "class counter_en_generator" not in fixed
    assert "mailbox gen2drv" not in fixed
    assert "ChipSutra UVM smoke" in fixed
    ok2, issues2 = lint_uvm_tb(fixed)
    assert ok2, issues2
    skel = render_uvm_smoke_tb(mods[0])
    out, engine, issues = choose_testbench_output(
        MIXED_UVM_PURE_SV,
        skeleton=skel,
        dut_name="counter_en",
        force_uvm=True,
        port_specs=mods[0]["ports"],
    )
    assert engine in ("llm_repaired", "skeleton_fallback")
    assert "uvm_sequencer" in out
    assert "class counter_en_generator" not in out
    assert "uvm_mixed_pure_sv" in (issues or []) or "expected" in out


def test_uvm_in_pure_sv_methodology_falls_back_to_sv_skeleton():
    from tb_skeleton import render_class_sv_tb

    rtl = """
module counter_en (
  input wire clk, input wire rst_n, input wire enable, output reg [3:0] count
);
endmodule
"""
    mods = extract_modules(rtl)
    sv_skel = render_class_sv_tb(mods[0])
    out, engine, issues = choose_testbench_output(
        MIXED_UVM_PURE_SV,
        skeleton=sv_skel,
        dut_name="counter_en",
        force_uvm=False,
        port_specs=mods[0]["ports"],
    )
    assert engine == "skeleton_fallback"
    assert "uvm_in_pure_sv" in issues
    assert "class counter_en_generator" in out
    assert "import uvm_pkg" not in out
    assert "run_test" not in out
    assert "uvm_env" not in out


def test_uvm_write_has_time_is_hard_fail():
    sv = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(counter_en_scoreboard)
  uvm_analysis_imp #(int, counter_en_scoreboard) imp;
  function new(string name, uvm_component parent);
    super.new(name, parent);
    imp = new("imp", this);
  endfunction
  function void write(int t);
    @(posedge vif.clk);
    #1;
  endfunction
endclass
module tb; initial run_test(); endmodule
"""
    ok, issues = lint_uvm_tb(sv)
    assert not ok
    assert "uvm_write_has_time" in issues


def test_uvm_env_fork_generator_is_hard_fail():
    sv = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_env extends uvm_env;
  `uvm_component_utils(counter_en_env)
  counter_en_generator gen;
  task run_phase(uvm_phase phase);
    fork
      gen.run(8);
    join
  endtask
endclass
module tb; initial run_test(); endmodule
"""
    ok, issues = lint_uvm_tb(sv)
    assert not ok
    assert "uvm_env_fork_generator" in issues


def test_uvm_scoreboard_vif_is_hard_fail():
    sv = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(counter_en_scoreboard)
  virtual counter_en_if vif;
  uvm_analysis_imp #(int, counter_en_scoreboard) imp;
  function void write(int t); endfunction
endclass
module tb; initial run_test(); endmodule
"""
    ok, issues = lint_uvm_tb(sv)
    assert not ok
    assert "uvm_sb_has_vif" in issues


def test_uvm_monitor_drive_is_hard_fail():
    sv = """
import uvm_pkg::*;
`include "uvm_macros.svh"
class counter_en_monitor extends uvm_monitor;
  `uvm_component_utils(counter_en_monitor)
  virtual counter_en_if vif;
  task run_phase(uvm_phase phase);
    vif.enable = 1'b1;
  endtask
endclass
module tb; initial run_test(); endmodule
"""
    ok, issues = lint_uvm_tb(sv)
    assert not ok
    assert "uvm_monitor_drives" in issues


def test_uvm_phantom_include_is_hard_fail():
    sv = """
import uvm_pkg::*;
`include "uvm_macros.svh"
`include "counter_en_seq.svh"
module tb; initial run_test(); endmodule
"""
    ok, issues = lint_uvm_tb(sv)
    assert not ok
    assert "uvm_phantom_include" in issues


MUX2 = """
module mux2_8 (
  input wire sel, input wire [7:0] a, input wire [7:0] b, output wire [7:0] y
);
endmodule
"""

NARROW_MUX_UVM = """
import uvm_pkg::*;
`include "uvm_macros.svh"
interface mux2_8_if;
  logic sel, a, b;
  logic [7:0] y;
endinterface
class mux2_8_txn extends uvm_sequence_item;
  `uvm_object_utils(mux2_8_txn)
  rand bit sel; rand bit a; rand bit b; logic [7:0] y;
endclass
class mux2_8_driver extends uvm_driver #(mux2_8_txn);
  `uvm_component_utils(mux2_8_driver)
  virtual mux2_8_if vif;
  task run_phase(uvm_phase phase);
    forever begin seq_item_port.get_next_item(req); seq_item_port.item_done(); end
  endtask
endclass
class mux2_8_monitor extends uvm_monitor;
  `uvm_component_utils(mux2_8_monitor)
  virtual mux2_8_if vif;
  uvm_analysis_port #(mux2_8_txn) ap;
  function new(string name, uvm_component parent);
    super.new(name, parent); ap = new("ap", this);
  endfunction
endclass
class mux2_8_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(mux2_8_scoreboard)
  uvm_analysis_imp #(mux2_8_txn, mux2_8_scoreboard) imp;
  int unsigned errors;
  function new(string name, uvm_component parent);
    super.new(name, parent); imp = new("imp", this); errors = 0;
  endfunction
  function void write(mux2_8_txn t);
    if (t.y !== (t.sel ? t.b : t.a)) errors++;
  endfunction
endclass
class mux2_8_env extends uvm_env;
  `uvm_component_utils(mux2_8_env)
endclass
class mux2_8_test extends uvm_test;
  `uvm_component_utils(mux2_8_test)
  task run_phase(uvm_phase phase);
    phase.raise_objection(this); phase.drop_objection(this);
  endtask
endclass
module mux2_8_tb;
  logic clk;
  mux2_8_if vif();
  mux2_8 dut(.sel(vif.sel), .a(vif.a), .b(vif.b), .y(vif.y));
  initial begin
    uvm_config_db#(virtual mux2_8_if)::set(null, "*", "vif", vif);
    run_test("mux2_8_test");
  end
endmodule
"""


def test_uvm_if_width_mismatch_falls_back_to_skeleton():
    mods = extract_modules(MUX2)
    ok, issues = lint_uvm_tb(NARROW_MUX_UVM, port_specs=mods[0]["ports"])
    assert not ok
    assert "uvm_if_width_mismatch" in issues
    fixed = repair_uvm_tb(
        NARROW_MUX_UVM, dut_name="mux2_8", port_specs=mods[0]["ports"]
    )
    assert "logic [7:0] a" in fixed
    assert "logic [7:0] b" in fixed
    assert "logic sel, a, b" not in fixed
    ok2, issues2 = lint_uvm_tb(fixed, port_specs=mods[0]["ports"])
    assert ok2, issues2
    out, engine, _iss = choose_testbench_output(
        NARROW_MUX_UVM,
        skeleton=render_uvm_smoke_tb(mods[0]),
        dut_name="mux2_8",
        force_uvm=True,
        port_specs=mods[0]["ports"],
    )
    assert engine in ("llm_repaired", "skeleton_fallback")
    assert "logic [7:0] a" in out


