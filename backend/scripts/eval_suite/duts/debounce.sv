module debounce (
  input  wire clk,
  input  wire rst_n,
  input  wire noisy,
  output reg  clean
);
  reg [2:0] cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin cnt <= 3'd0; clean <= 1'b0; end
    else if (noisy == clean) cnt <= 3'd0;
    else if (cnt == 3'd7) begin clean <= noisy; cnt <= 3'd0; end
    else cnt <= cnt + 1'b1;
  end
endmodule
