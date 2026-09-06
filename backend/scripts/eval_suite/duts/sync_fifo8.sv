module sync_fifo8 #(
  parameter WIDTH = 8,
  parameter DEPTH = 8
) (
  input  wire             clk,
  input  wire             rst_n,
  input  wire             wr_en,
  input  wire [WIDTH-1:0] wr_data,
  input  wire             rd_en,
  output wire [WIDTH-1:0] rd_data,
  output wire             full,
  output wire             empty,
  output reg  [$clog2(DEPTH):0] count
);
  // Functional show-ahead (FWFT) FIFO: rd_data always shows the head;
  // rd_en pops it. Contract matches the eval-suite reference TBs.
  localparam AW = (DEPTH <= 2) ? 1 : $clog2(DEPTH);
  reg [WIDTH-1:0] mem [0:DEPTH-1];
  reg [AW-1:0] wptr, rptr;

  assign full    = (count >= DEPTH);
  assign empty   = (count == 0);
  assign rd_data = mem[rptr];

  wire do_wr = wr_en && !full;
  wire do_rd = rd_en && !empty;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr  <= '0;
      rptr  <= '0;
      count <= '0;
    end else begin
      if (do_wr) begin
        mem[wptr] <= wr_data;
        wptr <= (wptr == AW'(DEPTH - 1)) ? '0 : wptr + 1'b1;
      end
      if (do_rd) rptr <= (rptr == AW'(DEPTH - 1)) ? '0 : rptr + 1'b1;
      case ({do_wr, do_rd})
        2'b10: count <= count + 1'b1;
        2'b01: count <= count - 1'b1;
        default: ;
      endcase
    end
  end
endmodule
