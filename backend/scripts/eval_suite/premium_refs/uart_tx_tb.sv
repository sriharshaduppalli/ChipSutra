`timescale 1ns / 1ps
module uart_tx_tb;
  logic clk, rst_n, start, tx, busy, done;
  logic [7:0] din, last_byte;
  int errors;
  uart_tx dut (.clk(clk), .rst_n(rst_n), .din(din), .start(start),
               .tx(tx), .busy(busy), .done(done), .last_byte(last_byte));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("uart_tx_tb.vcd"); $dumpvars(0, uart_tx_tb);
    errors=0; clk=0; rst_n=0; start=0; din=8'h5A;
    repeat(3) @(posedge clk); rst_n=1; @(posedge clk);
    if (busy !== 0 || done !== 0) errors++;
    start=1; @(posedge clk); start=0;
    wait (busy);
    wait (done);
    #1;
    if (last_byte !== 8'h5A) errors++;
    if (errors==0) $display("PASS: uart_tx_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
