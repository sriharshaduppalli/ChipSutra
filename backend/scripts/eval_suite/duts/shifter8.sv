module shifter8 (
  input  wire [7:0] din,
  input  wire [2:0] shamt,
  input  wire       dir, // 0=left 1=right logical
  output wire [7:0] dout
);
  assign dout = dir ? (din >> shamt) : (din << shamt);
endmodule
