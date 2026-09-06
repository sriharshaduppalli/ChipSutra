// Gold reference: layered Pure SV for counter_rtl (IF/gen/drv/mon/sb/env/test)
// ChipSutra eval gold
// ChipSutra Pure SV layered class TB (NO UVM)
// Components: interface, generator, driver, monitor, scoreboard, env, test
// DUT: counter_rtl | cycles=32 | seed=1
`timescale 1ns / 1ps

interface counter_rtl_if(input logic clk);
  logic rst_n;
  logic enable;
  logic [3:0] count;
  modport DRV(input clk, output enable, rst_n, input count);
  modport MON(input clk, input rst_n, enable, count);
endinterface

class counter_rtl_txn;
  rand bit enable;
  constraint legal_c {
    enable inside {[0:1]};
  }
endclass

class counter_rtl_mon_pkt;
  logic enable;
  logic [3:0] count;
endclass

class counter_rtl_generator;
  mailbox #(counter_rtl_txn) gen2drv;
  int n_txns;
  function new(mailbox #(counter_rtl_txn) mb, int n);
    gen2drv = mb;
    n_txns = n;
  endfunction
  task run();
    counter_rtl_txn t;
    repeat (n_txns) begin
      t = new();
      assert(t.randomize()) else $fatal(1, "generator randomize failed");
      gen2drv.put(t);
    end
  endtask
endclass

class counter_rtl_driver;
  virtual counter_rtl_if vif;
  mailbox #(counter_rtl_txn) gen2drv;
  mailbox #(counter_rtl_txn) drv2sb;
  function new(virtual counter_rtl_if vif,
               mailbox #(counter_rtl_txn) gen2drv,
               mailbox #(counter_rtl_txn) drv2sb);
    this.vif = vif;
    this.gen2drv = gen2drv;
    this.drv2sb = drv2sb;
  endfunction
  task reset();
    vif.rst_n = 1'b0;
        vif.enable = '0;
    repeat (4) @(posedge vif.clk);
    vif.rst_n = 1'b1;
    @(posedge vif.clk);
  endtask
  task run(int n);
    counter_rtl_txn t;
    repeat (n) begin
      gen2drv.get(t);
      @(posedge vif.clk);
      vif.enable = t.enable;
      drv2sb.put(t);
    end
    vif.enable = '0;
  endtask
endclass

class counter_rtl_monitor;
  virtual counter_rtl_if vif;
  mailbox #(counter_rtl_mon_pkt) mon2sb;
  function new(virtual counter_rtl_if vif, mailbox #(counter_rtl_mon_pkt) mb);
    this.vif = vif;
    mon2sb = mb;
  endfunction
  task run(int n);
    counter_rtl_mon_pkt p;
    repeat (n) begin
      @(posedge vif.clk);
      #1;
      p = new();
      p.enable = vif.enable;
      p.count = vif.count;
      mon2sb.put(p);
    end
  endtask
endclass

class counter_rtl_scoreboard;
  mailbox #(counter_rtl_txn) drv2sb;
  mailbox #(counter_rtl_mon_pkt) mon2sb;
  logic [3:0] expected;
  int errors;
  function new();
    expected = '0;
    errors = 0;
  endfunction
  function void predict(bit enable);
    if (enable) expected = expected + 1'b1;
  endfunction
  function bit check(logic [3:0] actual);
    return (actual === expected);
  endfunction
  function void connect(mailbox #(counter_rtl_txn) d2s, mailbox #(counter_rtl_mon_pkt) m2s);
    drv2sb = d2s;
    mon2sb = m2s;
  endfunction
  task run(int n);
    counter_rtl_txn t;
    counter_rtl_mon_pkt p;
    repeat (n) begin
      drv2sb.get(t);
      mon2sb.get(p);
      predict(t.enable);
      if (!check(p.count)) begin
        $error("[%0t] SB mismatch count=%0h expected=%0h", $time, p.count, expected);
        errors++;
      end
    end
  endtask
endclass

class counter_rtl_env;
  virtual counter_rtl_if vif;
  mailbox #(counter_rtl_txn) gen2drv;
  mailbox #(counter_rtl_txn) drv2sb;
  mailbox #(counter_rtl_mon_pkt) mon2sb;
  counter_rtl_generator gen;
  counter_rtl_driver drv;
  counter_rtl_monitor mon;
  counter_rtl_scoreboard sb;
  function new(virtual counter_rtl_if vif);
    this.vif = vif;
  endfunction
  function void build(int n);
    gen2drv = new();
    drv2sb = new();
    mon2sb = new();
    gen = new(gen2drv, n);
    drv = new(vif, gen2drv, drv2sb);
    mon = new(vif, mon2sb);
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
      $display("PASS: counter_rtl_tb layered Pure SV OK");
    else
      $display("FAIL: counter_rtl_tb - %0d error(s)", sb.errors);
  endfunction
endclass

class counter_rtl_test;
  virtual counter_rtl_if vif;
  counter_rtl_env env;
  function new(virtual counter_rtl_if vif);
    this.vif = vif;
    env = new(vif);
  endfunction
  task run(int n = 32);
    env.build(n);
    env.drv.reset();
    if (vif.count !== '0) begin
      $error("post-reset count not 0");
      env.sb.errors++;
    end
    env.run(n);
    env.report();
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

  always #5 clk = ~clk;

  initial begin
    counter_rtl_test t;
    $dumpfile("counter_rtl_tb.vcd");
    $dumpvars(0, counter_rtl_tb);
    void'($urandom(1));
    clk = 0;
    t = new(vif);
    t.run(32);
    $finish;
  end
endmodule
