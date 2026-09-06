// Gold reference: class-based Pure SV for sample_parity (what a strong model should emit)
// ChipSutra eval gold — NOT LLM output
`timescale 1ns / 1ps

class sample_parity_txn;
  rand bit valid;
  rand logic [7:0] data;
  constraint legal_c { valid inside {[0:1]}; }
endclass

class sample_parity_scoreboard;
  logic expected_parity;
  bit   expected_valid;
  function new();
    expected_parity = 1'b0;
    expected_valid  = 1'b0;
  endfunction
  function void predict(bit v, logic [7:0] d);
    expected_valid = v;
    if (v) expected_parity = ^d;
  endfunction
  function bit check(logic parity, logic valid_out);
    return (valid_out === expected_valid) &&
           (!expected_valid || (parity === expected_parity));
  endfunction
endclass

module sample_parity_tb;
  logic clk;
  logic rst_n;
  logic valid;
  logic [7:0] data;
  logic parity;
  logic valid_out;

  sample_parity dut (
    .clk(clk),
    .rst_n(rst_n),
    .valid(valid),
    .data(data),
    .parity(parity),
    .valid_out(valid_out)
  );

  always #5 clk = ~clk;

  initial begin
    automatic sample_parity_txn txn = new();
    automatic sample_parity_scoreboard sb = new();
    int i, errors;
    $dumpfile("sample_parity_tb.vcd");
    $dumpvars(0, sample_parity_tb);
    errors = 0;
    clk = 1'b0;
    rst_n = 1'b0;
    valid = 1'b0;
    data = '0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    @(posedge clk);

    for (i = 0; i < 32; i++) begin
      assert(txn.randomize()) else $fatal(1, "randomize failed");
      valid = txn.valid;
      data  = txn.data;
      @(posedge clk);
      #1;
      sb.predict(txn.valid, txn.data);
      if (!sb.check(parity, valid_out)) begin
        $error("[%0t] mismatch i=%0d valid=%b data=%0h parity=%b expected=%b",
               $time, i, valid, data, parity, sb.expected_parity);
        errors++;
      end
    end

    if (errors == 0)
      $display("PASS: sample_parity_tb class-based Pure SV OK");
    else
      $display("FAIL: sample_parity_tb - %0d error(s)", errors);
    $finish;
  end
endmodule
