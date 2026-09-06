module apb_regs (
  input  wire        PCLK,
  input  wire        PRESETn,
  input  wire        PSEL,
  input  wire        PENABLE,
  input  wire        PWRITE,
  input  wire [7:0]  PADDR,
  input  wire [31:0] PWDATA,
  output reg  [31:0] PRDATA,
  output wire        PREADY
);
  // 4 x 32-bit regs; word address = PADDR[3:2]
  reg [31:0] regs [0:3];
  integer k;
  assign PREADY = 1'b1;
  wire setup  = PSEL && !PENABLE;
  wire access = PSEL && PENABLE;

  always @(posedge PCLK or negedge PRESETn) begin
    if (!PRESETn) begin
      PRDATA <= 32'h0;
      for (k = 0; k < 4; k = k + 1) regs[k] <= 32'h0;
    end else if (access) begin
      if (PWRITE)
        regs[PADDR[3:2]] <= PWDATA;
      else
        PRDATA <= regs[PADDR[3:2]];
    end
  end
endmodule
