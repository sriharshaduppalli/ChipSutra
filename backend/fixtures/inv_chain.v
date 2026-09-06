// ChipSutra demo netlist — maps to cells in chipsutra_demo.lib (not a foundry PDK).
module inv_chain (A, Y);
  input A;
  output Y;
  wire n1;
  INV u1 (.A(A), .Y(n1));
  INV u2 (.A(n1), .Y(Y));
endmodule
