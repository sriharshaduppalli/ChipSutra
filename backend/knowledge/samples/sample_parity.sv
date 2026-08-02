// ChipSutra sample DUT: XOR parity + valid pipeline
module sample_parity (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       valid,
    input  wire [7:0] data,
    output reg        parity,
    output reg        valid_out
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      parity    <= 1'b0;
      valid_out <= 1'b0;
    end else begin
      valid_out <= valid;
      if (valid)
        parity <= ^data;
    end
  end
endmodule
