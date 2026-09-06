// Minimal I2C-like byte latch: 8 strobed bits then commit
module i2c_slave (
  input  wire       scl,       // used as bit strobe
  input  wire       sda_in,    // serial bit
  input  wire       start,     // pulse to begin a byte capture
  output reg        sda_out,
  output reg [7:0]  last_data,
  output reg        got_write
);
  reg [2:0] bit_cnt;
  reg [7:0] shifter;
  reg       active;

  always @(posedge scl or posedge start) begin
    if (start) begin
      active    <= 1'b1;
      bit_cnt   <= 3'd0;
      got_write <= 1'b0;
      sda_out   <= 1'b1;
      shifter   <= 8'h0;
    end else if (active) begin
      shifter <= {shifter[6:0], sda_in};
      if (bit_cnt == 3'd7) begin
        last_data <= {shifter[6:0], sda_in};
        got_write <= 1'b1;
        sda_out   <= 1'b0; // ACK
        active    <= 1'b0;
        bit_cnt   <= 3'd0;
      end else begin
        bit_cnt <= bit_cnt + 1'b1;
        sda_out <= 1'b1;
      end
    end
  end
endmodule
