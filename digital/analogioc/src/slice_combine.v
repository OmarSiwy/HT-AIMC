// slice_combine: recombine two 12b signed nibble-combined partials from the
// two 2b weight-slice passes (hi slice carries x4 significance) into a 14b
// signed column partial:  y = 4*p_hi + p_lo, saturated to 14b.
// Pure combinational. Exact whenever |4*p_hi + p_lo| <= 8191; saturates
// otherwise instead of wrapping.
module slice_combine (
    input  wire signed [11:0] p_lo,  // partial from weight bits [1:0] pass
    input  wire signed [11:0] p_hi,  // partial from weight bits [3:2] pass (signed slice)
    output wire signed [13:0] y
);
    // exact sum needs 15 bits: |4*(-2048) + (-2048)| = 10240
    wire signed [14:0] full = {p_hi[11], p_hi, 2'b00}
                            + {{3{p_lo[11]}}, p_lo};

    assign y = (full >  15'sd8191) ?  14'sd8191 :
               (full < -15'sd8192) ? -14'sd8192 : full[13:0];
endmodule
