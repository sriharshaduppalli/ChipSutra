// Gold reference: class-based Pure SV AXI4-Lite TB (txn + scoreboard classes)
// ChipSutra eval gold — NOT LLM output / NOT UVM
`timescale 1ns / 1ps

class axi_lite_txn;
  rand bit [1:0]  sel;   // register index (address = {sel, 2'b00})
  rand bit [31:0] data;
  constraint legal_c { sel inside {[0:3]}; }
endclass

class axi_lite_scoreboard;
  logic [31:0] model_reg [0:3];
  function new();
    for (int k = 0; k < 4; k++) model_reg[k] = '0;
  endfunction
  function void predict_write(bit [1:0] sel, logic [31:0] data);
    model_reg[sel] = data;
  endfunction
  function bit check_read(bit [1:0] sel, logic [31:0] rdata, logic [1:0] rresp);
    return (rresp === 2'b00) && (rdata === model_reg[sel]);
  endfunction
endclass

module axi_lite_class_sv_tb;
  logic        aclk, aresetn;
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

  integer errors;
  integer timeout;
  integer i;
  logic [31:0] rd_data;
  logic [1:0]  rd_resp;
  axi_lite_txn txn;
  axi_lite_scoreboard sb;

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

  // AW+W handshake, then B response — every wait has a timeout guard
  task automatic axi_write(input bit [3:0] addr, input logic [31:0] data);
    s_axi_awaddr = addr; s_axi_wdata = data; s_axi_wstrb = 4'hF;
    s_axi_awvalid = 1'b1; s_axi_wvalid = 1'b1;
    timeout = 0;
    @(posedge aclk);
    while (!(s_axi_awready && s_axi_wready) && timeout < 40) begin
      @(posedge aclk); timeout = timeout + 1;
    end
    if (!(s_axi_awready && s_axi_wready)) begin
      $error("[%0t] AXI write: AWREADY/WREADY timeout", $time);
      errors = errors + 1;
    end
    @(posedge aclk);
    s_axi_awvalid = 1'b0; s_axi_wvalid = 1'b0; s_axi_bready = 1'b1;
    timeout = 0;
    while (!s_axi_bvalid && timeout < 40) begin
      @(posedge aclk); timeout = timeout + 1;
    end
    if (!s_axi_bvalid || s_axi_bresp !== 2'b00) begin
      $error("[%0t] AXI write: bad BVALID/BRESP", $time);
      errors = errors + 1;
    end
    @(posedge aclk); s_axi_bready = 1'b0;
  endtask

  // AR handshake, then R data — timeout-guarded
  task automatic axi_read(input bit [3:0] addr,
                          output logic [31:0] data, output logic [1:0] resp);
    s_axi_araddr = addr; s_axi_arvalid = 1'b1;
    timeout = 0;
    @(posedge aclk);
    while (!s_axi_arready && timeout < 40) begin
      @(posedge aclk); timeout = timeout + 1;
    end
    @(posedge aclk);
    s_axi_arvalid = 1'b0; s_axi_rready = 1'b1;
    timeout = 0;
    while (!s_axi_rvalid && timeout < 40) begin
      @(posedge aclk); timeout = timeout + 1;
    end
    if (!s_axi_rvalid) begin
      $error("[%0t] AXI read: RVALID timeout", $time);
      errors = errors + 1;
    end
    data = s_axi_rdata; resp = s_axi_rresp;
    @(posedge aclk); s_axi_rready = 1'b0;
  endtask

  initial begin
    $dumpfile("axi_lite_class_sv_tb.vcd");
    $dumpvars(0, axi_lite_class_sv_tb);
    errors = 0;
    txn = new(); sb = new();
    aclk = 1'b0; aresetn = 1'b0;
    s_axi_awaddr = '0; s_axi_awprot = '0; s_axi_awvalid = 1'b0;
    s_axi_wdata = '0; s_axi_wstrb = 4'hF; s_axi_wvalid = 1'b0;
    s_axi_bready = 1'b0;
    s_axi_araddr = '0; s_axi_arprot = '0; s_axi_arvalid = 1'b0;
    s_axi_rready = 1'b0;

    repeat (3) @(posedge aclk);
    aresetn = 1'b1;
    @(posedge aclk);
    // Post-reset: response channels must be idle
    if (s_axi_bvalid !== 1'b0 || s_axi_rvalid !== 1'b0) begin
      $error("[%0t] response channel not idle after reset", $time);
      errors = errors + 1;
    end

    for (i = 0; i < 12; i = i + 1) begin
      assert(txn.randomize()) else $fatal(1, "randomize failed");
      axi_write({txn.sel, 2'b00}, txn.data);
      sb.predict_write(txn.sel, txn.data);
      axi_read({txn.sel, 2'b00}, rd_data, rd_resp);
      if (!sb.check_read(txn.sel, rd_data, rd_resp)) begin
        $error("[%0t] AXI RDATA mismatch sel=%0d got=%0h exp=%0h resp=%0b",
               $time, txn.sel, rd_data, sb.model_reg[txn.sel], rd_resp);
        errors = errors + 1;
      end
    end

    if (errors == 0)
      $display("PASS: axi_lite_class_sv_tb OK");
    else
      $display("FAIL: axi_lite_class_sv_tb - %0d error(s)", errors);
    $finish;
  end
endmodule
