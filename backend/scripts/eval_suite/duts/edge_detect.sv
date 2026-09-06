module edge_detect (
  input  wire clk,
  input  wire rst_n,
  input  wire din,
  output reg  rise,
  output reg  fall
);
  reg din_d;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      din_d <= 1'b0; rise <= 1'b0; fall <= 1'b0;
    end else begin
      rise <= din & ~din_d;
      fall <= ~din & din_d;
      din_d <= din;
    end
  end
endmodule
