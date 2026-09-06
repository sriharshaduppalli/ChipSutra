// Minimal AHB-Lite single-cycle slave (4 words)
module ahb_slave (
  input  wire        HCLK,
  input  wire        HRESETn,
  input  wire [7:0]  HADDR,
  input  wire [1:0]  HTRANS,
  input  wire        HWRITE,
  input  wire [31:0] HWDATA,
  input  wire        HSEL,
  input  wire        HREADY,
  output reg  [31:0] HRDATA,
  output wire        HREADYOUT,
  output wire [1:0]  HRESP
);
  reg [31:0] mem [0:3];
  reg        pend_write;
  reg [1:0]  pend_sel;
  integer k;
  assign HREADYOUT = 1'b1;
  assign HRESP     = 2'b00;
  wire xfer = HSEL && HREADY && (HTRANS == 2'b10 || HTRANS == 2'b11);

  always @(posedge HCLK or negedge HRESETn) begin
    if (!HRESETn) begin
      HRDATA <= 32'h0;
      pend_write <= 1'b0;
      pend_sel <= 2'b00;
      for (k = 0; k < 4; k = k + 1) mem[k] <= 32'h0;
    end else begin
      if (pend_write) begin
        mem[pend_sel] <= HWDATA;
        pend_write <= 1'b0;
      end
      if (xfer) begin
        if (HWRITE) begin
          pend_write <= 1'b1;
          pend_sel   <= HADDR[3:2];
        end else
          HRDATA <= mem[HADDR[3:2]];
      end
    end
  end
endmodule
