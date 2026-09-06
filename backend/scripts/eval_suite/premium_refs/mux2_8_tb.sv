`timescale 1ns / 1ps
// Premium-quality reference — mux2_8 (combinational; still clocked stimulus for dump)
class mux2_8_txn;
  rand bit sel; rand logic [7:0] a, b;
  constraint legal_c { sel inside {[0:1]}; }
endclass
class mux2_8_scoreboard;
  function bit check(bit sel, logic [7:0] a, logic [7:0] b, logic [7:0] y);
    return (y === (sel ? b : a));
  endfunction
endclass
module mux2_8_tb;
  logic clk, sel; logic [7:0] a, b, y;
  mux2_8 dut (.sel(sel), .a(a), .b(b), .y(y));
  always #5 clk = ~clk;
  initial begin
    automatic mux2_8_txn txn = new();
    automatic mux2_8_scoreboard sb = new();
    int i, errors;
    $dumpfile("mux2_8_tb.vcd"); $dumpvars(0, mux2_8_tb);
    errors = 0; clk = 0; sel = 0; a = '0; b = '0;
    for (i = 0; i < 32; i++) begin
      assert(txn.randomize());
      sel = txn.sel; a = txn.a; b = txn.b;
      @(posedge clk); #1;
      if (!sb.check(sel, a, b, y)) errors++;
    end
    if (errors == 0) $display("PASS: mux2_8_tb");
    else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
