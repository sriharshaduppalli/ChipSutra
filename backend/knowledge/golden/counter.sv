// Golden DUT — 8-bit counter (regression / lint smoke)
module counter (
    input  wire       clk,
    input  wire       rst,
    output reg  [7:0] q
);
  always @(posedge clk or posedge rst) begin
    if (rst)
      q <= 8'd0;
    else
      q <= q + 8'd1;
  end
endmodule
