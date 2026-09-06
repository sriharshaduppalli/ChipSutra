`timescale 1ns / 1ps
// Premium-quality reference — sample_parity
class sample_parity_txn;
  rand bit valid; rand logic [7:0] data;
  constraint legal_c { valid inside {[0:1]}; }
endclass
class sample_parity_scoreboard;
  logic expected_parity; bit expected_valid;
  function new(); expected_parity = 0; expected_valid = 0; endfunction
  function void predict(bit v, logic [7:0] d);
    expected_valid = v; if (v) expected_parity = ^d;
  endfunction
  function bit check(logic parity, logic valid_out);
    return (valid_out === expected_valid) && (!expected_valid || parity === expected_parity);
  endfunction
endclass
module sample_parity_tb;
  logic clk, rst_n, valid; logic [7:0] data; logic parity, valid_out;
  sample_parity dut (.clk(clk), .rst_n(rst_n), .valid(valid), .data(data),
                     .parity(parity), .valid_out(valid_out));
  always #5 clk = ~clk;
  initial begin
    automatic sample_parity_txn txn = new();
    automatic sample_parity_scoreboard sb = new();
    int i, errors;
    $dumpfile("sample_parity_tb.vcd"); $dumpvars(0, sample_parity_tb);
    errors = 0; clk = 0; rst_n = 0; valid = 0; data = '0;
    repeat (4) @(posedge clk); rst_n = 1; @(posedge clk);
    for (i = 0; i < 32; i++) begin
      assert(txn.randomize()); valid = txn.valid; data = txn.data;
      @(posedge clk); #1; sb.predict(txn.valid, txn.data);
      if (!sb.check(parity, valid_out)) errors++;
    end
    if (errors == 0) $display("PASS: sample_parity_tb");
    else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
