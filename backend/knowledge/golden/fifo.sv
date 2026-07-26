// Golden DUT — parameterized synchronous FIFO (regression / lint reference)
//
// Single clock domain, first-word-fall-through read data: rd_data always shows the
// head entry and rd_en pops it. Writes are dropped when full and reads ignored when
// empty, so overflow/underflow can never corrupt the pointers or the count.
`timescale 1ns / 1ps
`default_nettype none

module fifo #(
    parameter int WIDTH = 8,  // data width in bits
    parameter int DEPTH = 8   // number of entries (>= 2)
) (
    input  wire                        clk,
    input  wire                        rst_n,    // active-low synchronous reset
    input  wire                        wr_en,
    input  wire  [WIDTH-1:0]           wr_data,
    input  wire                        rd_en,
    output logic [WIDTH-1:0]           rd_data,
    output logic                       full,
    output logic                       empty,
    output logic [$clog2(DEPTH+1)-1:0] count
);

  localparam int ADDRW = (DEPTH > 1) ? $clog2(DEPTH) : 1;
  localparam int CNTW  = $clog2(DEPTH + 1);

  // Typed constants keep every comparison unsigned-vs-unsigned.
  localparam logic [CNTW-1:0]  CNT_ZERO = '0;
  localparam logic [CNTW-1:0]  CNT_FULL = CNTW'(DEPTH);
  localparam logic [ADDRW-1:0] PTR_ZERO = '0;
  localparam logic [ADDRW-1:0] PTR_LAST = ADDRW'(DEPTH - 1);

  logic [WIDTH-1:0] mem   [DEPTH];
  logic [ADDRW-1:0] wr_ptr;
  logic [ADDRW-1:0] rd_ptr;
  logic [CNTW-1:0]  count_q;

  logic do_write;
  logic do_read;

  always_comb begin
    empty    = (count_q == CNT_ZERO);
    full     = (count_q == CNT_FULL);
    do_write = wr_en && !full;
    do_read  = rd_en && !empty;
    count    = count_q;
    rd_data  = mem[rd_ptr];
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      wr_ptr  <= PTR_ZERO;
      rd_ptr  <= PTR_ZERO;
      count_q <= CNT_ZERO;
    end else begin
      if (do_write) begin
        mem[wr_ptr] <= wr_data;
        wr_ptr      <= (wr_ptr == PTR_LAST) ? PTR_ZERO : ADDRW'(wr_ptr + 1);
      end
      if (do_read) begin
        rd_ptr <= (rd_ptr == PTR_LAST) ? PTR_ZERO : ADDRW'(rd_ptr + 1);
      end
      case ({do_write, do_read})
        2'b10:   count_q <= CNTW'(count_q + 1);
        2'b01:   count_q <= CNTW'(count_q - 1);
        default: count_q <= count_q;
      endcase
    end
  end

endmodule

`default_nettype wire
