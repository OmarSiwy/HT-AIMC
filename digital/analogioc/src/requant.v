// requant: per-channel affine requantization of an accumulated column sum
// to INT8:  q = sat8( round((y * scale) >> shift) + offset )
//   - scale : unsigned 8b multiplier (per-channel)
//   - shift : arithmetic right shift 0..24 (per-channel)
//   - round : round-half-up (add 2^(shift-1) before shifting; shift=0 adds 0)
//   - offset: signed 8b output zero-point, added AFTER the shift
//   - sat8  : clamp to [-128, 127]
// Pure combinational. 32b intermediates: |y*scale| < 2^27, half <= 2^23
// (shift<=24), so no internal overflow.
module requant (
    input  wire signed [19:0] y,       // accumulated column sum (b_acc = 20)
    input  wire        [7:0]  scale,   // unsigned per-channel scale
    input  wire        [4:0]  shift,   // 0..24 meaningful
    input  wire signed [7:0]  offset,  // signed output zero-point
    output wire signed [7:0]  q
);
    wire signed [31:0] prod    = y * $signed({1'b0, scale});
    wire signed [31:0] half    = (shift == 5'd0) ? 32'sd0
                                                 : (32'sd1 <<< (shift - 5'd1));
    wire signed [31:0] shifted = (prod + half) >>> shift;
    wire signed [31:0] biased  = shifted + offset;

    assign q = (biased >  32'sd127) ?  8'sd127 :
               (biased < -32'sd128) ? -8'sd128 : biased[7:0];
endmodule
