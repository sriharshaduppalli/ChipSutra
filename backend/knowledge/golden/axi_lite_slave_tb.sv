// Golden testbench — self-checking write/read of every register in axi_lite_slave.sv
//
// Run in ChipSutra (Simulate → run) or from a shell:
//   $ verilator --binary --timing --trace --top-module axi_lite_slave_tb \
//         axi_lite_slave.sv axi_lite_slave_tb.sv
//
// (the "$ " matters: Verilator reads a comment starting with "verilator" as a
//  lint pragma and errors on it)
`timescale 1ns / 1ps

module axi_lite_slave_tb;

  localparam logic [1:0] RESP_OKAY = 2'b00;

  logic        aclk = 1'b0;
  logic        aresetn;

  logic [3:0]  awaddr;
  logic [2:0]  awprot;
  logic        awvalid;
  logic        awready;

  logic [31:0] wdata;
  logic [3:0]  wstrb;
  logic        wvalid;
  logic        wready;

  logic [1:0]  bresp;
  logic        bvalid;
  logic        bready;

  logic [3:0]  araddr;
  logic [2:0]  arprot;
  logic        arvalid;
  logic        arready;

  logic [31:0] rdata;
  logic [1:0]  rresp;
  logic        rvalid;
  logic        rready;

  int errors = 0;

  axi_lite_slave dut (
      .aclk         (aclk),
      .aresetn      (aresetn),
      .s_axi_awaddr (awaddr),
      .s_axi_awprot (awprot),
      .s_axi_awvalid(awvalid),
      .s_axi_awready(awready),
      .s_axi_wdata  (wdata),
      .s_axi_wstrb  (wstrb),
      .s_axi_wvalid (wvalid),
      .s_axi_wready (wready),
      .s_axi_bresp  (bresp),
      .s_axi_bvalid (bvalid),
      .s_axi_bready (bready),
      .s_axi_araddr (araddr),
      .s_axi_arprot (arprot),
      .s_axi_arvalid(arvalid),
      .s_axi_arready(arready),
      .s_axi_rdata  (rdata),
      .s_axi_rresp  (rresp),
      .s_axi_rvalid (rvalid),
      .s_axi_rready (rready)
  );

  always #5 aclk = ~aclk;

  task automatic check(input logic cond, input string msg);
    if (!cond) begin
      errors = errors + 1;
      $display("[%0t] ERROR: %s", $time, msg);
    end
  endtask

  task automatic axi_write(input logic [3:0] addr, input logic [31:0] data, input logic [3:0] strb);
    @(negedge aclk);
    awaddr  = addr;
    awvalid = 1'b1;
    wdata   = data;
    wstrb   = strb;
    wvalid  = 1'b1;
    bready  = 1'b1;
    while (!(awready && wready)) @(negedge aclk);
    @(negedge aclk);  // the transfer lands on the posedge in between
    awvalid = 1'b0;
    wvalid  = 1'b0;
    while (!bvalid) @(negedge aclk);
    check(bresp === RESP_OKAY, $sformatf("BRESP != OKAY for addr %01h (got %02b)", addr, bresp));
    @(negedge aclk);
    bready = 1'b0;
  endtask

  task automatic axi_read(input logic [3:0] addr, output logic [31:0] data);
    @(negedge aclk);
    araddr  = addr;
    arvalid = 1'b1;
    rready  = 1'b1;
    while (!arready) @(negedge aclk);
    @(negedge aclk);
    arvalid = 1'b0;
    while (!rvalid) @(negedge aclk);
    data = rdata;
    check(rresp === RESP_OKAY, $sformatf("RRESP != OKAY for addr %01h (got %02b)", addr, rresp));
    @(negedge aclk);
    rready = 1'b0;
  endtask

  logic [31:0] got;
  logic [31:0] expected [4];

  initial begin
    $dumpfile("dump.vcd");
    $dumpvars(0, axi_lite_slave_tb);

    aresetn = 1'b0;
    awaddr  = '0;
    awprot  = '0;
    awvalid = 1'b0;
    wdata   = '0;
    wstrb   = 4'h0;
    wvalid  = 1'b0;
    bready  = 1'b0;
    araddr  = '0;
    arprot  = '0;
    arvalid = 1'b0;
    rready  = 1'b0;

    repeat (3) @(negedge aclk);
    aresetn = 1'b1;
    @(negedge aclk);

    // --- registers read back 0 after reset ---
    for (int unsigned i = 0; i < 4; i++) begin
      axi_read(4'(i * 4), got);
      check(got === 32'd0, $sformatf("reg%0d should be 0 after reset (got %08h)", i, got));
    end

    // --- write then read back each register ---
    expected[0] = 32'hDEAD_BEEF;
    expected[1] = 32'h0123_4567;
    expected[2] = 32'hA5A5_5A5A;
    expected[3] = 32'hFFFF_0000;
    for (int unsigned i = 0; i < 4; i++) begin
      axi_write(4'(i * 4), expected[i], 4'hF);
      axi_read(4'(i * 4), got);
      check(got === expected[i], $sformatf("reg%0d readback mismatch: got %08h exp %08h", i, got, expected[i]));
    end

    // --- registers are independent: re-read them all ---
    for (int unsigned i = 0; i < 4; i++) begin
      axi_read(4'(i * 4), got);
      check(got === expected[i], $sformatf("reg%0d disturbed: got %08h exp %08h", i, got, expected[i]));
    end

    // --- byte strobes: only lane 0 updates ---
    axi_write(4'h0, 32'h1122_3344, 4'h1);
    expected[0] = {expected[0][31:8], 8'h44};
    axi_read(4'h0, got);
    check(got === expected[0], $sformatf("wstrb byte-enable failed: got %08h exp %08h", got, expected[0]));

    repeat (2) @(negedge aclk);
    if (errors == 0) $display("TEST PASSED");
    else $display("TEST FAILED (%0d errors)", errors);
    $finish;
  end

  // Watchdog so a stalled handshake never blocks the regression
  initial begin
    #200000;
    $display("TEST FAILED (timeout)");
    $finish;
  end

endmodule
