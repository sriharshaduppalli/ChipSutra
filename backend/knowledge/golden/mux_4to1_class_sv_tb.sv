// ChipSutra Pure SV class TB for mux (combo-safe; avoids VIF converge bugs)
`timescale 1ns / 1ps
class mux_4to1_txn;
  rand bit [1:0] sel;
  rand bit d0;
  rand bit d1;
  rand bit d2;
  rand bit d3;
  constraint legal_c {
    sel inside {[0:3]};
  }
endclass

class mux_4to1_scoreboard;
  function bit check(logic [1:0] sel, logic d0, logic d1, logic d2, logic d3, logic y);
    logic exp;
    case (sel)
      0: exp = d0;
      1: exp = d1;
      2: exp = d2;
      3: exp = d3;
      default: exp = '0;
    endcase
    return (y === exp);
  endfunction
endclass

module mux_4to1_tb;
  logic clk;
  logic [1:0] sel;
  logic d0;
  logic d1;
  logic d2;
  logic d3;
  logic y;

  mux_4to1 dut (
    .sel(sel),
    .d0(d0),
    .d1(d1),
    .d2(d2),
    .d3(d3),
    .y(y)
  );

  always #5 clk = ~clk;

  initial begin
    automatic mux_4to1_txn t = new();
    automatic mux_4to1_scoreboard sb = new();
    int i, errors;
    $dumpfile("mux_4to1_tb.vcd");
    $dumpvars(0, mux_4to1_tb);
    errors = 0;
    clk = 0;
    sel = '0; d0 = '0; d1 = '0; d2 = '0; d3 = '0;
    void'($urandom(1));
    for (i = 0; i < 32; i++) begin
      assert(t.randomize()) else $fatal(1, "randomize failed");
      sel = t.sel;
      d0 = t.d0;
      d1 = t.d1;
      d2 = t.d2;
      d3 = t.d3;
      @(posedge clk);
      #1;
      if (!sb.check(sel, d0, d1, d2, d3, y)) errors++;
    end
    if (errors == 0)
      $display("PASS: mux_4to1_tb mux class SV OK");
    else
      $display("FAIL: mux_4to1_tb - %0d error(s)", errors);
    $finish;
  end
endmodule
