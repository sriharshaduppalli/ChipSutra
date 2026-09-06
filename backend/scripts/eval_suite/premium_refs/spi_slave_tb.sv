`timescale 1ns / 1ps
module spi_slave_tb;
  logic sclk, cs_n, mosi, miso, rx_valid;
  logic [7:0] rx_byte, tx_byte;
  int b, errors;
  spi_slave dut (.sclk(sclk), .cs_n(cs_n), .mosi(mosi), .miso(miso),
                 .rx_byte(rx_byte), .rx_valid(rx_valid));
  initial begin
    $dumpfile("spi_slave_tb.vcd"); $dumpvars(0, spi_slave_tb);
    errors=0; sclk=0; cs_n=1; mosi=0; tx_byte=8'h3C;
    // reset path while selected inactive
    repeat (2) begin #5; sclk=1; #5; sclk=0; end
    cs_n=0;
    for (b=7; b>=0; b=b-1) begin
      mosi = tx_byte[b];
      #5; sclk=1; #5; sclk=0;
    end
    #1;
    if (!rx_valid || rx_byte !== tx_byte) errors++;
    cs_n=1;
    if (errors==0) $display("PASS: spi_slave_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
