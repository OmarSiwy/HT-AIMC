// tb_sign_exit: exhaustive truth table.
`timescale 1ns/1ps
module tb_sign_exit;
    reg relu_en, sign_neg, sign_valid;
    wire exit, force_zero;

    sign_exit dut (.relu_en(relu_en), .sign_neg(sign_neg),
                   .sign_valid(sign_valid), .exit(exit), .force_zero(force_zero));

    integer k;
    reg exp;

    initial begin
        for (k = 0; k < 8; k = k + 1) begin
            {relu_en, sign_neg, sign_valid} = k[2:0];
            #1;
            exp = relu_en & sign_neg & sign_valid;
            if (exit !== exp || force_zero !== exp)
                $fatal(1, "sign_exit: in=%b exit=%b fz=%b exp=%b",
                       k[2:0], exit, force_zero, exp);
        end
        $display("PASS");
        $finish;
    end
endmodule
