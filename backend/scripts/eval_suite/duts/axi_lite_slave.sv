module axi_lite_slave (
  input  wire        aclk,
  input  wire        aresetn,
  // write address
  input  wire [3:0]  s_axi_awaddr,
  input  wire [2:0]  s_axi_awprot,
  input  wire        s_axi_awvalid,
  output reg         s_axi_awready,
  // write data
  input  wire [31:0] s_axi_wdata,
  input  wire [3:0]  s_axi_wstrb,
  input  wire        s_axi_wvalid,
  output reg         s_axi_wready,
  // write response
  output reg  [1:0]  s_axi_bresp,
  output reg         s_axi_bvalid,
  input  wire        s_axi_bready,
  // read address
  input  wire [3:0]  s_axi_araddr,
  input  wire [2:0]  s_axi_arprot,
  input  wire        s_axi_arvalid,
  output reg         s_axi_arready,
  // read data
  output reg  [31:0] s_axi_rdata,
  output reg  [1:0]  s_axi_rresp,
  output reg         s_axi_rvalid,
  input  wire        s_axi_rready
);
  // 4 x 32-bit register file, addr[3:2] selects the register.
  reg [31:0] regs [0:3];
  integer k;

  wire wr_start = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !s_axi_awready;
  wire wr_hs    = s_axi_awready && s_axi_awvalid && s_axi_wready && s_axi_wvalid;
  wire rd_start = s_axi_arvalid && !s_axi_rvalid && !s_axi_arready;
  wire rd_hs    = s_axi_arready && s_axi_arvalid;

  always @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      s_axi_awready <= 1'b0;
      s_axi_wready  <= 1'b0;
      s_axi_bvalid  <= 1'b0;
      s_axi_bresp   <= 2'b00;
      s_axi_arready <= 1'b0;
      s_axi_rvalid  <= 1'b0;
      s_axi_rresp   <= 2'b00;
      s_axi_rdata   <= 32'h0;
      for (k = 0; k < 4; k = k + 1) regs[k] <= 32'h0;
    end else begin
      // Write channel: 1-cycle ready pulse when both AW and W are valid
      s_axi_awready <= wr_start;
      s_axi_wready  <= wr_start;
      if (wr_hs) begin
        if (s_axi_wstrb[0]) regs[s_axi_awaddr[3:2]][7:0]   <= s_axi_wdata[7:0];
        if (s_axi_wstrb[1]) regs[s_axi_awaddr[3:2]][15:8]  <= s_axi_wdata[15:8];
        if (s_axi_wstrb[2]) regs[s_axi_awaddr[3:2]][23:16] <= s_axi_wdata[23:16];
        if (s_axi_wstrb[3]) regs[s_axi_awaddr[3:2]][31:24] <= s_axi_wdata[31:24];
        s_axi_bvalid <= 1'b1;
        s_axi_bresp  <= 2'b00;
      end else if (s_axi_bvalid && s_axi_bready) begin
        s_axi_bvalid <= 1'b0;
      end
      // Read channel: 1-cycle ready pulse, then hold RDATA until RREADY
      s_axi_arready <= rd_start;
      if (rd_hs) begin
        s_axi_rdata <= regs[s_axi_araddr[3:2]];
        s_axi_rvalid <= 1'b1;
        s_axi_rresp  <= 2'b00;
      end else if (s_axi_rvalid && s_axi_rready) begin
        s_axi_rvalid <= 1'b0;
      end
    end
  end
endmodule
