`timescale 1ns / 1ps
module ahb_slave_tb;
  logic HCLK, HRESETn, HWRITE, HSEL, HREADY, HREADYOUT;
  logic [7:0] HADDR; logic [1:0] HTRANS, HRESP; logic [31:0] HWDATA, HRDATA;
  logic [31:0] model [0:3];
  int i, errors, sel;
  ahb_slave dut (
    .HCLK(HCLK), .HRESETn(HRESETn), .HADDR(HADDR), .HTRANS(HTRANS),
    .HWRITE(HWRITE), .HWDATA(HWDATA), .HSEL(HSEL), .HREADY(HREADY),
    .HRDATA(HRDATA), .HREADYOUT(HREADYOUT), .HRESP(HRESP)
  );
  always #5 HCLK = ~HCLK;
  initial begin
    $dumpfile("ahb_slave_tb.vcd"); $dumpvars(0, ahb_slave_tb);
    errors=0; HCLK=0; HRESETn=0; HSEL=0; HREADY=1; HTRANS=2'b00; HWRITE=0;
    HADDR='0; HWDATA='0;
    for (i=0;i<4;i++) model[i]='0;
    repeat(3) @(posedge HCLK); HRESETn=1; @(posedge HCLK);
    for (i=0;i<8;i++) begin
      sel = i[1:0];
      // address phase write
      HSEL=1; HTRANS=2'b10; HWRITE=1; HADDR={sel[1:0],2'b00}; HWDATA=32'hA0000000|i;
      @(posedge HCLK);
      // data phase
      HTRANS=2'b00; HWRITE=0;
      @(posedge HCLK);
      if (HREADYOUT) model[sel] = HWDATA;
      else errors++;
      // read address
      HSEL=1; HTRANS=2'b10; HWRITE=0; HADDR={sel[1:0],2'b00};
      @(posedge HCLK);
      HTRANS=2'b00;
      @(posedge HCLK); #1;
      if (HRDATA !== model[sel] || HRESP !== 2'b00) errors++;
      HSEL=0;
      @(posedge HCLK);
    end
    if (errors==0) $display("PASS: ahb_slave_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
