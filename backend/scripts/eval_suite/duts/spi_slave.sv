// Minimal SPI slave: pack 8 MOSI samples while cs_n low
module spi_slave (
  input  wire       sclk,
  input  wire       cs_n,
  input  wire       mosi,
  output wire       miso,
  output reg [7:0]  rx_byte,
  output reg        rx_valid
);
  reg [3:0] bit_cnt;
  reg [7:0] shift_in;
  assign miso = 1'b0;

  always @(posedge sclk) begin
    if (cs_n) begin
      bit_cnt  <= 4'd0;
      rx_valid <= 1'b0;
    end else begin
      shift_in <= {shift_in[6:0], mosi};
      bit_cnt  <= bit_cnt + 1'b1;
      if (bit_cnt == 4'd7) begin
        rx_byte  <= {shift_in[6:0], mosi};
        rx_valid <= 1'b1;
        bit_cnt  <= 4'd0;
      end else
        rx_valid <= 1'b0;
    end
  end
endmodule
