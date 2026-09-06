`timescale 1ns / 1ps
module shifter8_tb;
  logic [7:0] din, dout; logic [2:0] shamt; logic dir; int i, errors; logic [7:0] exp;
  shifter8 dut (.din(din), .shamt(shamt), .dir(dir), .dout(dout));
  initial begin
    $dumpfile("shifter8_tb.vcd"); $dumpvars(0, shifter8_tb);
    errors=0;
    for (i=0;i<32;i++) begin
      din=$urandom_range(0,255); shamt=i[2:0]; dir=i[3];
      #1; exp = dir ? (din >> shamt) : (din << shamt);
      if (dout !== exp) errors++;
    end
    if (errors==0) $display("PASS: shifter8_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
