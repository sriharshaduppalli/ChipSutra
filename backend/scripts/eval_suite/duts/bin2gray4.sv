module bin2gray4 (
  input  wire [3:0] bin,
  output wire [3:0] gray
);
  assign gray = bin ^ (bin >> 1);
endmodule
