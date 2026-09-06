`timescale 1ns / 1ps
// Premium-quality reference TB (Claude/GPT-class target) — counter_en
class counter_en_txn;
  rand bit enable;
  constraint legal_c { enable inside {[0:1]}; }
endclass
class counter_en_scoreboard;
  logic [3:0] expected;
  function new(); expected = '0; endfunction
  function void predict(bit en); if (en) expected = expected + 1'b1; endfunction
  function bit check(logic [3:0] actual); return (actual === expected); endfunction
endclass
module counter_en_tb;
  logic clk, rst_n, enable;
  logic [3:0] count;
  counter_en dut (.clk(clk), .rst_n(rst_n), .enable(enable), .count(count));
  always #5 clk = ~clk;
  initial begin
    automatic counter_en_txn txn = new();
    automatic counter_en_scoreboard sb = new();
    int i, errors;
    $dumpfile("counter_en_tb.vcd"); $dumpvars(0, counter_en_tb);
    errors = 0; clk = 0; rst_n = 0; enable = 0;
    repeat (4) @(posedge clk); rst_n = 1; @(posedge clk);
    for (i = 0; i < 32; i++) begin
      assert(txn.randomize()) else $fatal(1, "randomize failed");
      enable = txn.enable; @(posedge clk); #1;
      sb.predict(txn.enable);
      if (!sb.check(count)) begin $error("mismatch"); errors++; end
    end
    if (errors == 0) $display("PASS: counter_en_tb");
    else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
