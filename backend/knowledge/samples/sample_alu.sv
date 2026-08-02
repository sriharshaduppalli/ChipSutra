// ChipSutra sample DUT: tiny ALU (unknown protocol → universal auto-TB)
module sample_alu (
    input  wire       clk,
    input  wire       rst_n,
    input  wire [1:0] op,
    input  wire [7:0] a,
    input  wire [7:0] b,
    output reg  [7:0] result
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      result <= 8'd0;
    else begin
      unique case (op)
        2'b00: result <= a + b;
        2'b01: result <= a - b;
        2'b10: result <= a & b;
        2'b11: result <= a | b;
      endcase
    end
  end
endmodule
