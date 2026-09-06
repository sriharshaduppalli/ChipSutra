module mux_4to1 (
    input  wire [1:0] sel,
    input  wire       d0,
    input  wire       d1,
    input  wire       d2,
    input  wire       d3,
    output wire       y
);
  assign y = (sel == 2'b00) ? d0 :
             (sel == 2'b01) ? d1 :
             (sel == 2'b10) ? d2 : d3;
endmodule
