`timescale 1ns / 1ps
module edge_detect_tb;
  logic clk, rst_n, din, rise, fall; int errors;
  edge_detect dut (.clk(clk), .rst_n(rst_n), .din(din), .rise(rise), .fall(fall));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("edge_detect_tb.vcd"); $dumpvars(0, edge_detect_tb);
    errors=0; clk=0; rst_n=0; din=0;
    repeat(3) @(posedge clk); rst_n=1; @(posedge clk);
    if (rise!==0 || fall!==0) errors++;
    din=1; @(posedge clk); #1; if (rise!==1) errors++;
    @(posedge clk); #1; if (rise!==0) errors++;
    din=0; @(posedge clk); #1; if (fall!==1) errors++;
    if (errors==0) $display("PASS: edge_detect_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
