`timescale 1ns / 1ps
module bin2gray4_tb;
  logic [3:0] bin, gray; int i, errors;
  bin2gray4 dut (.bin(bin), .gray(gray));
  initial begin
    $dumpfile("bin2gray4_tb.vcd"); $dumpvars(0, bin2gray4_tb);
    errors=0;
    for (i=0;i<16;i++) begin
      bin=i[3:0]; #1;
      if (gray !== (bin ^ (bin >> 1))) errors++;
    end
    if (errors==0) $display("PASS: bin2gray4_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
