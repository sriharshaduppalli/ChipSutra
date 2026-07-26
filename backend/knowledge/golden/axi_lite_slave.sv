// Golden DUT — AXI4-Lite slave with four 32-bit registers (regression / lint reference)
//
// 16-byte aperture: s_axi_*addr[3:2] selects reg0..reg3, byte strobes honoured on
// writes. All handshake outputs are registered, so there are no combinational paths
// from *VALID to *READY and no combinational loops. Every access returns OKAY.
`timescale 1ns / 1ps
`default_nettype none

module axi_lite_slave (
    input  wire         aclk,
    input  wire         aresetn,     // active-low synchronous reset

    // Write address channel
    input  wire  [3:0]  s_axi_awaddr,
    input  wire  [2:0]  s_axi_awprot,
    input  wire         s_axi_awvalid,
    output logic        s_axi_awready,

    // Write data channel
    input  wire  [31:0] s_axi_wdata,
    input  wire  [3:0]  s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output logic        s_axi_wready,

    // Write response channel
    output logic [1:0]  s_axi_bresp,
    output logic        s_axi_bvalid,
    input  wire         s_axi_bready,

    // Read address channel
    input  wire  [3:0]  s_axi_araddr,
    input  wire  [2:0]  s_axi_arprot,
    input  wire         s_axi_arvalid,
    output logic        s_axi_arready,

    // Read data channel
    output logic [31:0] s_axi_rdata,
    output logic [1:0]  s_axi_rresp,
    output logic        s_axi_rvalid,
    input  wire         s_axi_rready
);

  localparam logic [1:0] RESP_OKAY = 2'b00;
  localparam int         NUM_REGS  = 4;

  logic [31:0] regfile [NUM_REGS];
  logic [3:0]  awaddr_q;
  logic [3:0]  araddr_q;
  logic        aw_en;      // one outstanding write at a time
  logic        wr_commit;
  logic        rd_issue;

  always_comb begin
    wr_commit = s_axi_awready && s_axi_awvalid && s_axi_wready && s_axi_wvalid;
    rd_issue  = s_axi_arready && s_axi_arvalid && !s_axi_rvalid;
  end

  // --- write address channel ---
  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      s_axi_awready <= 1'b0;
      awaddr_q      <= 4'd0;
      aw_en         <= 1'b1;
    end else if (!s_axi_awready && s_axi_awvalid && s_axi_wvalid && aw_en) begin
      s_axi_awready <= 1'b1;
      awaddr_q      <= s_axi_awaddr;
      aw_en         <= 1'b0;
    end else if (s_axi_bvalid && s_axi_bready) begin
      s_axi_awready <= 1'b0;
      aw_en         <= 1'b1;
    end else begin
      s_axi_awready <= 1'b0;
    end
  end

  // --- write data channel ---
  always_ff @(posedge aclk) begin
    if (!aresetn) s_axi_wready <= 1'b0;
    else s_axi_wready <= !s_axi_wready && s_axi_wvalid && s_axi_awvalid && aw_en;
  end

  // --- register file ---
  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      for (int r = 0; r < NUM_REGS; r++) regfile[r] <= 32'd0;
    end else if (wr_commit) begin
      for (int b = 0; b < 4; b++) begin
        if (s_axi_wstrb[b]) regfile[awaddr_q[3:2]][8*b+:8] <= s_axi_wdata[8*b+:8];
      end
    end
  end

  // --- write response channel ---
  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      s_axi_bvalid <= 1'b0;
      s_axi_bresp  <= RESP_OKAY;
    end else if (wr_commit && !s_axi_bvalid) begin
      s_axi_bvalid <= 1'b1;
      s_axi_bresp  <= RESP_OKAY;  // all four addresses are legal registers
    end else if (s_axi_bvalid && s_axi_bready) begin
      s_axi_bvalid <= 1'b0;
    end
  end

  // --- read address channel ---
  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      s_axi_arready <= 1'b0;
      araddr_q      <= 4'd0;
    end else if (!s_axi_arready && s_axi_arvalid) begin
      s_axi_arready <= 1'b1;
      araddr_q      <= s_axi_araddr;
    end else begin
      s_axi_arready <= 1'b0;
    end
  end

  // --- read data channel ---
  always_ff @(posedge aclk) begin
    if (!aresetn) begin
      s_axi_rvalid <= 1'b0;
      s_axi_rresp  <= RESP_OKAY;
      s_axi_rdata  <= 32'd0;
    end else if (rd_issue) begin
      s_axi_rvalid <= 1'b1;
      s_axi_rresp  <= RESP_OKAY;
      s_axi_rdata  <= regfile[araddr_q[3:2]];
    end else if (s_axi_rvalid && s_axi_rready) begin
      s_axi_rvalid <= 1'b0;
    end
  end

  // Byte-lane and protection bits are ignored by design (word-aligned, non-secure).
  logic unused_ok;
  always_comb unused_ok = &{1'b0, s_axi_awprot, s_axi_arprot, awaddr_q[1:0], araddr_q[1:0], 1'b0};

endmodule

`default_nettype wire
