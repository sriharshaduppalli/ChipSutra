`timescale 1ns / 1ps
// Premium-quality reference — sync_fifo8 class-based Pure SV
class sync_fifo8_txn;
  rand bit wr_en, rd_en;
  rand logic [7:0] wr_data;
  constraint legal_c { !(wr_en && rd_en); }
endclass
class sync_fifo8_scoreboard;
  logic [7:0] q[$];
  localparam int DEPTH = 8;
  function new(); q.delete(); endfunction
  function void predict(bit wr, bit rd, logic [7:0] wdata);
    if (rd && q.size() > 0) void'(q.pop_front());
    if (wr && q.size() < DEPTH) q.push_back(wdata);
  endfunction
  function bit check(logic [7:0] rd_data, bit full, bit empty, logic [3:0] count);
    return (empty === (q.size() == 0)) && (full === (q.size() >= DEPTH)) &&
           (count === q.size()) && (q.size() == 0 || rd_data === q[0]);
  endfunction
endclass
module sync_fifo8_tb;
  logic clk, rst_n, wr_en, rd_en;
  logic [7:0] wr_data, rd_data;
  logic full, empty; logic [3:0] count;
  sync_fifo8 #(.WIDTH(8), .DEPTH(8)) dut (
    .clk(clk), .rst_n(rst_n), .wr_en(wr_en), .wr_data(wr_data),
    .rd_en(rd_en), .rd_data(rd_data), .full(full), .empty(empty), .count(count));
  always #5 clk = ~clk;
  initial begin
    automatic sync_fifo8_txn txn = new();
    automatic sync_fifo8_scoreboard sb = new();
    int i, errors;
    $dumpfile("sync_fifo8_tb.vcd"); $dumpvars(0, sync_fifo8_tb);
    errors = 0; clk = 0; rst_n = 0; wr_en = 0; rd_en = 0; wr_data = '0;
    repeat (4) @(posedge clk); rst_n = 1; @(posedge clk);
    for (i = 0; i < 40; i++) begin
      assert(txn.randomize());
      if (sb.q.size() >= 8) txn.wr_en = 0;
      if (sb.q.size() == 0) txn.rd_en = 0;
      wr_en = txn.wr_en; rd_en = txn.rd_en; wr_data = txn.wr_data;
      @(posedge clk); #1;
      sb.predict(txn.wr_en, txn.rd_en, txn.wr_data);
      if (!sb.check(rd_data, full, empty, count)) errors++;
    end
    if (errors == 0) $display("PASS: sync_fifo8_tb");
    else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
