`timescale 1ns / 1ps
// Premium-quality reference — APB SETUP+ACCESS with model_reg golden
module apb_regs_tb;
  logic        PCLK, PRESETn, PSEL, PENABLE, PWRITE, PREADY;
  logic [7:0]  PADDR;
  logic [31:0] PWDATA, PRDATA;
  logic [31:0] model_reg [0:3];
  int i, errors, sel, timeout;
  apb_regs dut (
    .PCLK(PCLK), .PRESETn(PRESETn), .PSEL(PSEL), .PENABLE(PENABLE),
    .PWRITE(PWRITE), .PADDR(PADDR), .PWDATA(PWDATA), .PRDATA(PRDATA), .PREADY(PREADY)
  );
  always #5 PCLK = ~PCLK;
  initial begin
    $dumpfile("apb_regs_tb.vcd"); $dumpvars(0, apb_regs_tb);
    errors = 0; PCLK = 0; PRESETn = 0; PSEL = 0; PENABLE = 0; PWRITE = 0;
    PADDR = '0; PWDATA = '0;
    for (i = 0; i < 4; i++) model_reg[i] = '0;
    repeat (4) @(posedge PCLK); PRESETn = 1; @(posedge PCLK);
    if (PRDATA !== '0) errors++;
    for (i = 0; i < 16; i++) begin
      sel = $urandom_range(0, 3);
      // SETUP
      PADDR = {sel[1:0], 2'b00}; PWDATA = $urandom(); PWRITE = 1; PSEL = 1; PENABLE = 0;
      @(posedge PCLK);
      // ACCESS
      PENABLE = 1;
      timeout = 0;
      @(posedge PCLK);
      while (!PREADY && timeout < 40) begin @(posedge PCLK); timeout++; end
      if (PREADY) model_reg[sel] = PWDATA;
      else errors++;
      PSEL = 0; PENABLE = 0; PWRITE = 0;
      @(posedge PCLK);
      // read SETUP+ACCESS
      PADDR = {sel[1:0], 2'b00}; PWRITE = 0; PSEL = 1; PENABLE = 0;
      @(posedge PCLK); PENABLE = 1;
      timeout = 0;
      @(posedge PCLK);
      while (!PREADY && timeout < 40) begin @(posedge PCLK); timeout++; end
      #1;
      if (PRDATA !== model_reg[sel]) errors++;
      PSEL = 0; PENABLE = 0;
      @(posedge PCLK);
    end
    if (errors == 0) $display("PASS: apb_regs_tb");
    else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
