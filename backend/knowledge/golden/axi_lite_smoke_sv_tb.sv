// Gold reference: compact Pure SV AXI-Lite 4-reg smoke (model_reg scoreboard)
// ChipSutra eval gold — NOT LLM output / NOT UVM
`timescale 1ns / 1ps

module axi_lite_smoke_sv_tb;
  logic        aclk;
  logic        aresetn;
  // Named s_axi_* ports (DUT axi_lite_slave)
  logic [3:0]  s_axi_awaddr;
  logic [2:0]  s_axi_awprot;
  logic        s_axi_awvalid, s_axi_awready;
  logic [31:0] s_axi_wdata;
  logic [3:0]  s_axi_wstrb;
  logic        s_axi_wvalid, s_axi_wready;
  logic [1:0]  s_axi_bresp;
  logic        s_axi_bvalid, s_axi_bready;
  logic [3:0]  s_axi_araddr;
  logic [2:0]  s_axi_arprot;
  logic        s_axi_arvalid, s_axi_arready;
  logic [31:0] s_axi_rdata;
  logic [1:0]  s_axi_rresp;
  logic        s_axi_rvalid, s_axi_rready;

  logic [31:0] model_reg [0:3];
  logic [1:0]  axi_sel;
  integer i, errors, timeout;

  axi_lite_slave dut (
    .aclk(aclk), .aresetn(aresetn),
    .s_axi_awaddr(s_axi_awaddr), .s_axi_awprot(s_axi_awprot),
    .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
    .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb),
    .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
    .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
    .s_axi_araddr(s_axi_araddr), .s_axi_arprot(s_axi_arprot),
    .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
    .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp),
    .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready)
  );

  always #5 aclk = ~aclk;

  initial begin
    $dumpfile("axi_lite_smoke_sv_tb.vcd");
    $dumpvars(0, axi_lite_smoke_sv_tb);
    errors = 0;
    aclk = 1'b0; aresetn = 1'b0;
    s_axi_awaddr = '0; s_axi_awprot = '0; s_axi_awvalid = 1'b0;
    s_axi_wdata = '0; s_axi_wstrb = 4'hF; s_axi_wvalid = 1'b0;
    s_axi_bready = 1'b0;
    s_axi_araddr = '0; s_axi_arprot = '0; s_axi_arvalid = 1'b0;
    s_axi_rready = 1'b0;
    for (timeout = 0; timeout < 4; timeout = timeout + 1) model_reg[timeout] = 32'h0;
    repeat (3) @(posedge aclk);
    aresetn = 1'b1;
    @(posedge aclk);

    // Smoke: write-then-read each of 4 regs via model_reg golden
    for (i = 0; i < 8; i = i + 1) begin
      axi_sel = i[1:0];
      s_axi_awaddr = {axi_sel, 2'b00};
      s_axi_araddr = {axi_sel, 2'b00};
      s_axi_wdata  = 32'hA5A50000 | {28'h0, axi_sel, 2'b00};
      s_axi_awvalid = 1'b1; s_axi_wvalid = 1'b1;
      timeout = 0;
      @(posedge aclk);
      while (!(s_axi_awready && s_axi_wready) && timeout < 40) begin
        @(posedge aclk); timeout = timeout + 1;
      end
      if (s_axi_awready && s_axi_wready) begin
        model_reg[axi_sel] = s_axi_wdata;
        @(posedge aclk);
        s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b0;
        s_axi_bready = 1'b1;
        timeout = 0;
        while (!s_axi_bvalid && timeout < 40) begin
          @(posedge aclk); timeout = timeout + 1;
        end
        if (!s_axi_bvalid || s_axi_bresp !== 2'b00) errors = errors + 1;
        @(posedge aclk); s_axi_bready = 1'b0;
      end else begin
        errors = errors + 1;
        s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b0;
      end
      s_axi_arvalid = 1'b1;
      timeout = 0;
      @(posedge aclk);
      while (!s_axi_arready && timeout < 40) begin
        @(posedge aclk); timeout = timeout + 1;
      end
      @(posedge aclk); s_axi_arvalid = 1'b0; s_axi_rready = 1'b1;
      timeout = 0;
      while (!s_axi_rvalid && timeout < 40) begin
        @(posedge aclk); timeout = timeout + 1;
      end
      if (!s_axi_rvalid || s_axi_rdata !== model_reg[axi_sel] || s_axi_rresp !== 2'b00) begin
        $error("[%0t] AXI RDATA mismatch sel=%0d got=%0h exp=%0h",
               $time, axi_sel, s_axi_rdata, model_reg[axi_sel]);
        errors = errors + 1;
      end
      @(posedge aclk); s_axi_rready = 1'b0;
    end

    if (errors == 0)
      $display("PASS: axi_lite_smoke_sv_tb OK");
    else
      $display("FAIL: axi_lite_smoke_sv_tb - %0d error(s)", errors);
    $finish;
  end
endmodule
