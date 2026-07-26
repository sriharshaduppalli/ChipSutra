// Golden testbench — self-checking directed tests for fifo.sv
//
// Run in ChipSutra (Simulate → run) or from a shell:
//   $ verilator --binary --timing --trace --top-module fifo_tb fifo.sv fifo_tb.sv
//
// (the "$ " matters: Verilator reads a comment starting with "verilator" as a
//  lint pragma and errors on it)
`timescale 1ns / 1ps

module fifo_tb;

  localparam int WIDTH = 8;
  localparam int DEPTH = 4;
  localparam int CNTW  = $clog2(DEPTH + 1);

  localparam logic [CNTW-1:0] CNT_ZERO = '0;
  localparam logic [CNTW-1:0] CNT_TWO  = CNTW'(2);
  localparam logic [CNTW-1:0] CNT_FULL = CNTW'(DEPTH);

  logic             clk = 1'b0;
  logic             rst_n;
  logic             wr_en;
  logic [WIDTH-1:0] wr_data;
  logic             rd_en;
  logic [WIDTH-1:0] rd_data;
  logic             full;
  logic             empty;
  logic [CNTW-1:0]  count;

  int errors = 0;

  fifo #(
      .WIDTH(WIDTH),
      .DEPTH(DEPTH)
  ) dut (
      .clk    (clk),
      .rst_n  (rst_n),
      .wr_en  (wr_en),
      .wr_data(wr_data),
      .rd_en  (rd_en),
      .rd_data(rd_data),
      .full   (full),
      .empty  (empty),
      .count  (count)
  );

  always #5 clk = ~clk;

  task automatic check(input logic cond, input string msg);
    if (!cond) begin
      errors = errors + 1;
      $display("[%0t] ERROR: %s", $time, msg);
    end
  endtask

  task automatic push(input logic [WIDTH-1:0] data);
    @(negedge clk);
    wr_en   = 1'b1;
    wr_data = data;
    @(negedge clk);
    wr_en   = 1'b0;
  endtask

  task automatic pop(output logic [WIDTH-1:0] data);
    @(negedge clk);
    data  = rd_data;  // first-word-fall-through: the head is already visible
    rd_en = 1'b1;
    @(negedge clk);
    rd_en = 1'b0;
  endtask

  logic [WIDTH-1:0] got;
  logic [WIDTH-1:0] exp;

  initial begin
    $dumpfile("dump.vcd");
    $dumpvars(0, fifo_tb);

    rst_n   = 1'b0;
    wr_en   = 1'b0;
    rd_en   = 1'b0;
    wr_data = '0;
    repeat (2) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);

    // --- reset state ---
    check(empty === 1'b1, "FIFO should be empty after reset");
    check(full === 1'b0, "FIFO should not be full after reset");
    check(count === CNT_ZERO, "count should be 0 after reset");

    // --- underflow protection: read while empty is a no-op ---
    @(negedge clk);
    rd_en = 1'b1;
    @(negedge clk);
    rd_en = 1'b0;
    check(empty === 1'b1, "read while empty must not change empty");
    check(count === CNT_ZERO, "read while empty must not change count");

    // --- fill to full ---
    for (int unsigned i = 0; i < unsigned'(DEPTH); i++) push(8'hA0 + WIDTH'(i));
    check(full === 1'b1, "FIFO should be full after DEPTH writes");
    check(empty === 1'b0, "FIFO should not be empty when full");
    check(count === CNT_FULL, "count should equal DEPTH when full");

    // --- overflow protection: write while full is a no-op ---
    push(8'hFF);
    check(full === 1'b1, "write while full must keep full asserted");
    check(count === CNT_FULL, "write while full must not change count");

    // --- drain in FIFO order; the dropped 8'hFF must not appear ---
    for (int unsigned i = 0; i < unsigned'(DEPTH); i++) begin
      exp = 8'hA0 + WIDTH'(i);
      pop(got);
      check(got === exp, $sformatf("drain mismatch at %0d: got %02h exp %02h", i, got, exp));
    end
    check(empty === 1'b1, "FIFO should be empty after draining");
    check(count === CNT_ZERO, "count should be 0 after draining");

    // --- pointer wrap-around: push/pop past the end of the memory ---
    for (int unsigned i = 0; i < unsigned'(3 * DEPTH); i++) begin
      exp = WIDTH'(i);
      push(exp);
      pop(got);
      check(got === exp, $sformatf("wrap mismatch at %0d: got %02h", i, got));
      check(empty === 1'b1, "FIFO should return to empty each wrap iteration");
    end

    // --- interleaved partial occupancy ---
    push(8'h11);
    push(8'h22);
    check(count === CNT_TWO, "count should be 2 after two writes");
    pop(got);
    check(got === 8'h11, "interleaved pop should return 8'h11");
    push(8'h33);
    pop(got);
    check(got === 8'h22, "interleaved pop should return 8'h22");
    pop(got);
    check(got === 8'h33, "interleaved pop should return 8'h33");
    check(empty === 1'b1, "FIFO should be empty at end of test");

    repeat (2) @(negedge clk);
    if (errors == 0) $display("TEST PASSED");
    else $display("TEST FAILED (%0d errors)", errors);
    $finish;
  end

  // Watchdog so a hang never blocks the regression
  initial begin
    #100000;
    $display("TEST FAILED (timeout)");
    $finish;
  end

endmodule
