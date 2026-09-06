// Minimal AXI-Stream sink with ready backpressure + last/tkeep
module axis_sink (
  input  wire        aclk,
  input  wire        aresetn,
  input  wire [7:0]  s_axis_tdata,
  input  wire        s_axis_tvalid,
  input  wire        s_axis_tlast,
  output reg         s_axis_tready,
  output reg  [7:0]  last_data,
  output reg         beat_count
);
  always @(posedge aclk or negedge aresetn) begin
    if (!aresetn) begin
      s_axis_tready <= 1'b1;
      last_data     <= 8'h0;
      beat_count    <= 1'b0;
    end else begin
      s_axis_tready <= ~s_axis_tready; // toggle ready for backpressure coverage
      if (s_axis_tvalid && s_axis_tready) begin
        last_data  <= s_axis_tdata;
        beat_count <= beat_count + 1'b1;
      end
    end
  end
endmodule
