`timescale 1ns / 1ps
module prio_enc4_tb;
  logic [3:0] req; logic [1:0] grant; logic valid; int i, errors; logic [1:0] exp; logic evalid;
  prio_enc4 dut (.req(req), .grant(grant), .valid(valid));
  initial begin
    $dumpfile("prio_enc4_tb.vcd"); $dumpvars(0, prio_enc4_tb);
    errors=0;
    for (i=0;i<16;i++) begin
      req=i[3:0]; #1;
      evalid = |req;
      if (req[3]) exp=2'd3; else if (req[2]) exp=2'd2; else if (req[1]) exp=2'd1; else exp=2'd0;
      if (valid!==evalid || (evalid && grant!==exp)) errors++;
    end
    if (errors==0) $display("PASS: prio_enc4_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
