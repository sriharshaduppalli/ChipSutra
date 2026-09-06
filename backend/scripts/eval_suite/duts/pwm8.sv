module pwm8 (
  input  wire       clk,
  input  wire       rst_n,
  input  wire [7:0] duty,
  output reg        pwm
);
  reg [7:0] cnt;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin cnt <= 8'd0; pwm <= 1'b0; end
    else begin
      cnt <= cnt + 1'b1;
      pwm <= (cnt < duty);
    end
  end
endmodule
