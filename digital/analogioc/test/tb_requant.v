// tb_requant: randomized affine requantization vs behavioral reference
// implementing the spec independently in integer math:
//   q = sat8( ((y*scale + (shift?1<<(shift-1):0)) >>> shift) + offset )
`timescale 1ns/1ps
module tb_requant;
    reg  signed [19:0] y;
    reg  [7:0]  scale;
    reg  [4:0]  shift;
    reg  signed [7:0]  offset;
    wire signed [7:0]  q;

    requant dut (.y(y), .scale(scale), .shift(shift), .offset(offset), .q(q));

    integer trial, yi, si, shi, offi, prod, half, shifted, res, got;

    task check;
        begin
            #1;
            yi = y; si = scale; shi = shift; offi = offset;  // all-signed integer math
            prod = yi * si;                         // |y*scale| < 2^27: fits integer
            half = (shi == 0) ? 0 : (1 << (shi - 1));
            shifted = (prod + half) >>> shi;        // integer is signed: arithmetic
            res = shifted + offi;
            if (res >  127) res =  127;
            if (res < -128) res = -128;
            got = q;
            if (got !== res)
                $fatal(1, "requant: y=%0d s=%0d sh=%0d off=%0d got=%0d exp=%0d",
                       y, scale, shift, offset, got, res);
        end
    endtask

    initial begin
        // corners
        y = -20'sd524288; scale = 8'd255; shift = 5'd0;  offset =  8'sd0;    check;
        y =  20'sd524287; scale = 8'd255; shift = 5'd0;  offset =  8'sd127;  check;
        y = -20'sd524288; scale = 8'd255; shift = 5'd24; offset = -8'sd128;  check;
        y =  20'sd1;      scale = 8'd1;   shift = 5'd1;  offset =  8'sd0;    check; // rounding at .5
        y = -20'sd1;      scale = 8'd1;   shift = 5'd1;  offset =  8'sd0;    check; // -0.5 rounds up to 0
        y = -20'sd3;      scale = 8'd1;   shift = 5'd1;  offset =  8'sd0;    check; // -1.5 -> -1
        y =  20'sd0;      scale = 8'd0;   shift = 5'd7;  offset = -8'sd5;    check;
        // random
        for (trial = 0; trial < 3000; trial = trial + 1) begin
            y      = $random;
            scale  = $random;
            shift  = {$random} % 25;   // 0..24
            offset = $random;
            check;
        end
        $display("PASS");
        $finish;
    end
endmodule
