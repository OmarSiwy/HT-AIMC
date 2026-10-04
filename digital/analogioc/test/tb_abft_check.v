// tb_abft_check: randomized column sums, checksum with injected error,
// vs behavioral reference (integer math).
`timescale 1ns/1ps
module tb_abft_check;
    reg  [16*20-1:0]     y_flat;
    reg  signed [19:0]   y_chk;
    reg  [15:0]          budget;
    wire signed [24:0]   residual;
    wire                 flag;

    abft_check #(.W(20)) dut (.y_flat(y_flat), .y_chk(y_chk), .budget(budget),
                              .residual(residual), .flag(flag));

    integer trial, i, sum, err, exp_res, got_res, exp_flag;
    reg signed [19:0] v;

    task check;
        begin
            #1;
            exp_res  = sum - y_chk;
            got_res  = residual;
            exp_flag = ((exp_res < 0 ? -exp_res : exp_res) > budget) ? 1 : 0;
            if (got_res !== exp_res)
                $fatal(1, "abft residual: got=%0d exp=%0d (trial %0d)",
                       got_res, exp_res, trial);
            if (flag !== exp_flag[0])
                $fatal(1, "abft flag: got=%b exp=%0d res=%0d budget=%0d (trial %0d)",
                       flag, exp_flag, exp_res, budget, trial);
        end
    endtask

    initial begin
        // extreme: all most-negative, checksum most-positive
        sum = 0;
        for (i = 0; i < 16; i = i + 1) begin
            v = -20'sd524288; y_flat[i*20 +: 20] = v; sum = sum + v;
        end
        y_chk = 20'sd524287; budget = 16'd0; trial = -1; check;

        // extreme: all most-positive, checksum most-negative
        sum = 0;
        for (i = 0; i < 16; i = i + 1) begin
            v = 20'sd524287; y_flat[i*20 +: 20] = v; sum = sum + v;
        end
        y_chk = -20'sd524288; budget = 16'hFFFF; trial = -2; check;

        // randomized: clean / small error / large error vs random budget
        // (|v| < 20000 so sum+err always fits the 20b y_chk port: no truncation)
        for (trial = 0; trial < 1000; trial = trial + 1) begin
            sum = 0;
            for (i = 0; i < 16; i = i + 1) begin
                v = $random % 20000;
                y_flat[i*20 +: 20] = v;
                sum = sum + v;
            end
            case (trial % 3)
                0: err = 0;
                1: err = ($random % 8);            // small
                2: err = 1000 + ({$random} % 50000); // large
            endcase
            y_chk  = sum + err;   // residual = -err
            budget = {$random} % 2000;
            check;
        end
        $display("PASS");
        $finish;
    end
endmodule
