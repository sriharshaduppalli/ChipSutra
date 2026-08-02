// ChipSutra sample DUT: sync FIFO (DEPTH=4, WIDTH=8)
module sample_fifo #(
    parameter int WIDTH = 8,
    parameter int DEPTH = 4
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             wr_en,
    input  wire [WIDTH-1:0] wr_data,
    input  wire             rd_en,
    output logic [WIDTH-1:0] rd_data,
    output logic            full,
    output logic            empty
);
  logic [WIDTH-1:0] mem [0:DEPTH-1];
  logic [$clog2(DEPTH)-1:0] wr_ptr, rd_ptr;
  logic [$clog2(DEPTH):0]   count;

  assign full  = (count == DEPTH);
  assign empty = (count == 0);
  assign rd_data = mem[rd_ptr];

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wr_ptr <= '0;
      rd_ptr <= '0;
      count  <= '0;
    end else begin
      case ({wr_en && !full, rd_en && !empty})
        2'b10: begin
          mem[wr_ptr] <= wr_data;
          wr_ptr <= wr_ptr + 1'b1;
          count  <= count + 1'b1;
        end
        2'b01: begin
          rd_ptr <= rd_ptr + 1'b1;
          count  <= count - 1'b1;
        end
        2'b11: begin
          mem[wr_ptr] <= wr_data;
          wr_ptr <= wr_ptr + 1'b1;
          rd_ptr <= rd_ptr + 1'b1;
        end
        default: ;
      endcase
    end
  end
endmodule
