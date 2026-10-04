// tb_slice_combine: randomized + corner vectors vs behavioral reference.
`timescale 1ns/1ps
module tb_slice_combine;
    reg  signed [11:0] lo, hi;
    wire signed [13:0] y;

    slice_combine dut (.p_lo(lo), .p_hi(hi), .y(y));

    integer k, exp, got;

    task check;
        begin
            #1;
            exp = 4*hi + lo;                      // reference: exact then clamp
            if (exp >  8191) exp =  8191;
            if (exp < -8192) exp = -8192;
            got = y;
            if (got !== exp)
                $fatal(1, "slice_combine: lo=%0d hi=%0d got=%0d exp=%0d",
                       lo, hi, got, exp);
        end
    endtask

    initial begin
        lo = -12'sd2048; hi = -12'sd2048; check;
        lo =  12'sd2047; hi =  12'sd2047; check;
        lo = -12'sd2048; hi =  12'sd2047; check;
        lo =  12'sd2047; hi = -12'sd2048; check;
        lo =  12'sd0;    hi =  12'sd0;    check;
        lo = -12'sd1;    hi =  12'sd1;    check;
        for (k = 0; k < 2000; k = k + 1) begin
            lo = $random; hi = $random; check;
        end
        $display("PASS");
        $finish;
    end
endmodule
