`timescale 1ns / 1ps
module sync_ff_tb;
  logic clk, rst_n, d, q; int errors;
  sync_ff dut (.clk(clk), .rst_n(rst_n), .d(d), .q(q));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("sync_ff_tb.vcd"); $dumpvars(0, sync_ff_tb);
    errors=0; clk=0; rst_n=0; d=0;
    repeat(2) @(posedge clk); rst_n=1; @(posedge clk);
    if (q!==0) errors++;
    d=1; @(posedge clk); #1; // meta captures
    @(posedge clk); #1; if (q!==1) errors++;
    if (errors==0) $display("PASS: sync_ff_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
