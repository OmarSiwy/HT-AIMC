// tb_nibble_combine: randomized + corner vectors vs behavioral reference.
`timescale 1ns/1ps
module tb_nibble_combine;
    reg  signed [7:0]  a, b;      // lsb_code, msb_code
    wire signed [11:0] p;

    nibble_combine dut (.lsb_code(a), .msb_code(b), .partial(p));

    integer k, exp, got;

    task check;
        begin
            #1;
            exp = 16*b + a;                       // reference: exact then clamp
            if (exp >  2047) exp =  2047;
            if (exp < -2048) exp = -2048;
            got = p;
            if (got !== exp)
                $fatal(1, "nibble_combine: lsb=%0d msb=%0d got=%0d exp=%0d",
                       a, b, got, exp);
        end
    endtask

    initial begin
        // corners (hit both saturation rails)
        a = -8'sd128; b = -8'sd128; check;
        a =  8'sd127; b =  8'sd127; check;
        a = -8'sd128; b =  8'sd127; check;
        a =  8'sd127; b = -8'sd128; check;
        a =  8'sd0;   b =  8'sd0;   check;
        a = -8'sd1;   b =  8'sd0;   check;
        a =  8'sd15;  b =  8'sd127; check;
        // random
        for (k = 0; k < 2000; k = k + 1) begin
            a = $random; b = $random; check;
        end
        $display("PASS");
        $finish;
    end
endmodule
