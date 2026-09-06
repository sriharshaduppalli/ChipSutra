// Minimal UART TX: 8N1, fixed baud divider=4 clocks/bit for fast sim
module uart_tx (
  input  wire       clk,
  input  wire       rst_n,
  input  wire [7:0] din,
  input  wire       start,
  output reg        tx,
  output reg        busy,
  output reg        done,
  output reg [7:0]  last_byte
);
  localparam int DIV = 4;
  reg [3:0] bit_idx;
  reg [7:0] shifter;
  reg [2:0] div_cnt;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tx <= 1'b1; busy <= 1'b0; done <= 1'b0; last_byte <= 8'h0;
      bit_idx <= 4'd0; div_cnt <= 3'd0; shifter <= 8'h0;
    end else begin
      done <= 1'b0;
      if (!busy) begin
        if (start) begin
          busy <= 1'b1; shifter <= din; last_byte <= din; bit_idx <= 4'd0;
          div_cnt <= 3'd0; tx <= 1'b0; // start bit
        end
      end else if (div_cnt == DIV-1) begin
        div_cnt <= 3'd0;
        if (bit_idx == 4'd0) begin
          tx <= shifter[0]; bit_idx <= 4'd1; shifter <= {1'b0, shifter[7:1]};
        end else if (bit_idx < 4'd8) begin
          tx <= shifter[0]; bit_idx <= bit_idx + 1'b1;
          shifter <= {1'b0, shifter[7:1]};
        end else if (bit_idx == 4'd8) begin
          tx <= 1'b1; bit_idx <= 4'd9; // stop
        end else begin
          busy <= 1'b0; done <= 1'b1; bit_idx <= 4'd0;
        end
      end else
        div_cnt <= div_cnt + 1'b1;
    end
  end
endmodule
