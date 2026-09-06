`timescale 1ns / 1ps
module axis_sink_tb;
  logic aclk, aresetn, s_axis_tvalid, s_axis_tlast, s_axis_tready, beat_count;
  logic [7:0] s_axis_tdata, last_data;
  int i, errors, timeout, sent;
  axis_sink dut (
    .aclk(aclk), .aresetn(aresetn),
    .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid),
    .s_axis_tlast(s_axis_tlast), .s_axis_tready(s_axis_tready),
    .last_data(last_data), .beat_count(beat_count)
  );
  always #5 aclk = ~aclk;
  initial begin
    $dumpfile("axis_sink_tb.vcd"); $dumpvars(0, axis_sink_tb);
    errors=0; aclk=0; aresetn=0; s_axis_tvalid=0; s_axis_tlast=0; s_axis_tdata='0; sent=0;
    repeat(3) @(posedge aclk); aresetn=1; @(posedge aclk);
    for (i=0; i<16; i++) begin
      s_axis_tdata = i[7:0]; s_axis_tlast = (i==15); s_axis_tvalid = 1;
      timeout=0;
      @(posedge aclk);
      while (!(s_axis_tvalid && s_axis_tready) && timeout < 40) begin
        @(posedge aclk); timeout++;
      end
      if (s_axis_tvalid && s_axis_tready) begin
        sent++;
        #1;
        if (last_data !== s_axis_tdata) errors++;
      end else errors++;
      s_axis_tvalid = 0; @(posedge aclk);
    end
    if (errors==0) $display("PASS: axis_sink_tb"); else $display("FAIL: %0d", errors);
    $finish;
  end
endmodule
