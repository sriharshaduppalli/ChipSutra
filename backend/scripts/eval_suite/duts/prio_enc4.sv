module prio_enc4 (
  input  wire [3:0] req,
  output reg  [1:0] grant,
  output reg        valid
);
  always @* begin
    valid = |req;
    casez (req)
      4'b1???: grant = 2'd3;
      4'b01??: grant = 2'd2;
      4'b001?: grant = 2'd1;
      4'b0001: grant = 2'd0;
      default: grant = 2'd0;
    endcase
  end
endmodule
