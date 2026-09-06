module counter_en (
  input  wire       clk,
  input  wire       rst_n,
  input  wire       enable,
  output reg  [3:0] count
);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) count <= 4'd0;
    else if (enable) count <= count + 4'd1;
  end
endmodule
