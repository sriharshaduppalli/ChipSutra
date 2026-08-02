// ChipSutra sample DUT: 2:1 mux (combinational)
module sample_mux2 (
    input  wire       sel,
    input  wire [7:0] a,
    input  wire [7:0] b,
    output wire [7:0] y
);
  assign y = sel ? b : a;
endmodule
