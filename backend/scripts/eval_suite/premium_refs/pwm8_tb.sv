`timescale 1ns / 1ps
module pwm8_tb;
  logic clk, rst_n, pwm; logic [7:0] duty; int errors, high, i;
  pwm8 dut (.clk(clk), .rst_n(rst_n), .duty(duty), .pwm(pwm));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("pwm8_tb.vcd"); $dumpvars(0, pwm8_tb);
    errors=0; clk=0; rst_n=0; duty=8'd64; high=0;
    repeat(2) @(posedge clk); rst_n=1;
    for (i=0;i<256;i++) begin @(posedge clk); #1; if (pwm) high++; end
    // duty=64 → expect ~64 highs per 256-cycle period
    if (high < 60 || high > 68) errors++;
    if (errors==0) $display("PASS: pwm8_tb"); else $display("FAIL: %0d high=%0d", errors, high);
    $finish;
  end
endmodule
