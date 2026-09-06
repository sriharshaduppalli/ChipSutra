// Gold reference: class-based Pure SV for sync FIFO (premium-model shape)
// ChipSutra eval gold — NOT LLM output
`timescale 1ns / 1ps

class sync_fifo_txn;
  rand bit wr_en;
  rand bit rd_en;
  rand logic [7:0] wr_data;
  constraint legal_c {
    // avoid simultaneous empty pop / full push at randomize; TB may also clamp
    !(wr_en && rd_en);
  }
endclass

class sync_fifo_scoreboard;
  logic [7:0] q[$];
  localparam int DEPTH = 8;
  function new();
    q.delete();
  endfunction
  function void predict(bit wr, bit rd, logic [7:0] wdata);
    bit do_read  = rd && (q.size() > 0);
    bit do_write = wr && (q.size() < DEPTH);
    if (do_read)  void'(q.pop_front());
    if (do_write) q.push_back(wdata);
  endfunction
  function bit check(logic [7:0] rd_data, bit full, bit empty, logic [3:0] count);
    bit ok = 1'b1;
    if (empty !== (q.size() == 0)) ok = 1'b0;
    if (full  !== (q.size() >= DEPTH)) ok = 1'b0;
    if (count !== q.size()) ok = 1'b0;
    if (q.size() > 0 && rd_data !== q[0]) ok = 1'b0;
    return ok;
  endfunction
endclass

module sync_fifo_tb;
  logic clk, rst_n, wr_en, rd_en;
  logic [7:0] wr_data, rd_data;
  logic full, empty;
  logic [3:0] count;

  sync_fifo #(.WIDTH(8), .DEPTH(8)) dut (
    .clk(clk), .rst_n(rst_n),
    .wr_en(wr_en), .wr_data(wr_data),
    .rd_en(rd_en), .rd_data(rd_data),
    .full(full), .empty(empty), .count(count)
  );

  always #5 clk = ~clk;

  initial begin
    automatic sync_fifo_txn txn = new();
    automatic sync_fifo_scoreboard sb = new();
    int i, errors;
    $dumpfile("sync_fifo_tb.vcd");
    $dumpvars(0, sync_fifo_tb);
    errors = 0;
    clk = 0; rst_n = 0; wr_en = 0; rd_en = 0; wr_data = '0;
    repeat (4) @(posedge clk);
    rst_n = 1;
    @(posedge clk);

    for (i = 0; i < 40; i++) begin
      assert(txn.randomize()) else $fatal(1, "randomize failed");
      if (sb.q.size() >= 8) txn.wr_en = 0;
      if (sb.q.size() == 0) txn.rd_en = 0;
      wr_en = txn.wr_en;
      rd_en = txn.rd_en;
      wr_data = txn.wr_data;
      @(posedge clk);
      #1;
      sb.predict(txn.wr_en, txn.rd_en, txn.wr_data);
      if (!sb.check(rd_data, full, empty, count)) begin
        $error("[%0t] fifo mismatch i=%0d", $time, i);
        errors++;
      end
    end

    if (errors == 0)
      $display("PASS: sync_fifo_tb class-based Pure SV OK");
    else
      $display("FAIL: sync_fifo_tb - %0d error(s)", errors);
    $finish;
  end
endmodule
