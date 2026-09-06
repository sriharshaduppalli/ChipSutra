`timescale 1ns / 1ps
module debounce_tb;
  logic clk, rst_n, noisy, clean; int errors, i;
  debounce dut (.clk(clk), .rst_n(rst_n), .noisy(noisy), .clean(clean));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("debounce_tb.vcd"); $dumpvars(0, debounce_tb);
    errors=0; clk=0; rst_n=0; noisy=0;
    repeat(2) @(posedge clk); rst_n=1; @(posedge clk);
    if (clean!==0) errors++;
    noisy=1;
    repeat(8) @(posedge clk); #1;
    if (clean!==1) errors++;
    if (errors==0) $display("PASS: debounce_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
