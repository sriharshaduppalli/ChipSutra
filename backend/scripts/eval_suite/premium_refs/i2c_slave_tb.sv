`timescale 1ns / 1ps
module i2c_slave_tb;
  logic scl, sda_in, start, sda_out, got_write;
  logic [7:0] last_data, data_byte;
  int errors, k;
  i2c_slave dut (.scl(scl), .sda_in(sda_in), .start(start), .sda_out(sda_out),
                 .last_data(last_data), .got_write(got_write));
  initial begin
    $dumpfile("i2c_slave_tb.vcd"); $dumpvars(0, i2c_slave_tb);
    errors=0; scl=0; sda_in=0; start=0; data_byte=8'hA5;
    #5; start=1; #5; start=0; #5;
    for (k=7; k>=0; k=k-1) begin
      sda_in = data_byte[k];
      #5; scl=1; #5; scl=0;
    end
    #1;
    if (!got_write || last_data !== 8'hA5) errors++;
    if (errors==0) $display("PASS: i2c_slave_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
