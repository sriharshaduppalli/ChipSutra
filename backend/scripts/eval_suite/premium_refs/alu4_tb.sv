`timescale 1ns / 1ps
module alu4_tb;
  logic [3:0] a, b, y; logic [1:0] op; int i, errors; logic [3:0] exp;
  alu4 dut (.a(a), .b(b), .op(op), .y(y));
  initial begin
    $dumpfile("alu4_tb.vcd"); $dumpvars(0, alu4_tb);
    errors=0;
    for (i=0;i<64;i++) begin
      a=$urandom_range(0,15); b=$urandom_range(0,15); op=i[1:0];
      #1;
      case (op)
        2'b00: exp = a + b;
        2'b01: exp = a - b;
        2'b10: exp = a & b;
        default: exp = a | b;
      endcase
      if (y !== exp) errors++;
    end
    if (errors==0) $display("PASS: alu4_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
