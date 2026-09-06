`timescale 1ns / 1ps
module gray2bin4_tb;
  logic [3:0] gray, bin, exp; int i, errors;
  gray2bin4 dut (.gray(gray), .bin(bin));
  initial begin
    $dumpfile("gray2bin4_tb.vcd"); $dumpvars(0, gray2bin4_tb);
    errors=0;
    for (i=0;i<16;i++) begin
      gray=i[3:0]; #1;
      exp[3]=gray[3]; exp[2]=exp[3]^gray[2]; exp[1]=exp[2]^gray[1]; exp[0]=exp[1]^gray[0];
      if (bin!==exp) errors++;
    end
    if (errors==0) $display("PASS: gray2bin4_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
