module sync_ff (
  input  wire clk,
  input  wire rst_n,
  input  wire d,
  output reg  q
);
  reg meta;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin meta <= 1'b0; q <= 1'b0; end
    else begin meta <= d; q <= meta; end
  end
endmodule
