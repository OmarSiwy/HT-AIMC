// nibble_combine: recombine two 8b signed column ADC codes from the
// LSB-nibble and MSB-nibble PWM passes (duration ratio 1:16) into a 12b
// signed partial:  partial = 16*msb_code + lsb_code, saturated to 12b.
// Pure combinational. Exact whenever |16*msb+lsb| <= 2047 (guaranteed by
// the compiler's B_y clip schedule); saturates otherwise instead of wrapping.
module nibble_combine (
    input  wire signed [7:0]  lsb_code,  // code from t_q (x1) nibble pass
    input  wire signed [7:0]  msb_code,  // code from 16*t_q (x16) nibble pass
    output wire signed [11:0] partial
);
    // exact sum needs 13 bits: |16*(-128) + (-128)| = 2176
    wire signed [12:0] full = {msb_code[7], msb_code, 4'b0000}
                            + {{5{lsb_code[7]}}, lsb_code};

    assign partial = (full >  13'sd2047) ?  12'sd2047 :
                     (full < -13'sd2048) ? -12'sd2048 : full[11:0];
endmodule
