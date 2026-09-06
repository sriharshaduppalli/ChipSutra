module mux2_8 (
  input  wire       sel,
  input  wire [7:0] a,
  input  wire [7:0] b,
  output wire [7:0] y
);
  assign y = sel ? b : a;
endmodule
