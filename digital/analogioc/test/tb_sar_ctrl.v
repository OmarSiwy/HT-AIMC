// tb_sar_ctrl: behavioral async comparator model with random (non-clock-
// aligned) delays. Hidden 4b target; comparator answers residue>=trial.
// Binary search must return exactly the target for all 16 values + randoms.
`timescale 1ns/1ps
module tb_sar_ctrl;
    reg clk = 0, rst_n = 0, start = 0;
    wire busy, done, cmp_req;
    wire [3:0] code, dac_code;
    reg  cmp_ack = 0, cmp_result = 0;

    sar_ctrl dut (.clk(clk), .rst_n(rst_n), .start(start),
                  .busy(busy), .done(done), .code(code),
                  .cmp_req(cmp_req), .cmp_ack(cmp_ack),
                  .cmp_result(cmp_result), .dac_code(dac_code));

    always #5 clk = ~clk;

    reg [3:0] target;

    // async comparator model: 4-phase, result stable before ack rises and
    // held until req falls
    always begin
        wait (cmp_req === 1'b1);
        #(3 + {$random} % 27);            // comparator decision time (async)
        cmp_result = (target >= dac_code);
        #2;
        cmp_ack = 1;
        wait (cmp_req === 1'b0);
        #(2 + {$random} % 13);
        cmp_ack = 0;
    end

    integer t, k;

    task run_conv;
        input [3:0] tgt;
        begin
            target = tgt;
            @(posedge clk); start <= 1; @(posedge clk); start <= 0;
            @(posedge clk);
            if (done !== 1'b0) $fatal(1, "sar: done not cleared on start");
            wait (done === 1'b1);
            @(posedge clk);
            if (code !== tgt)
                $fatal(1, "sar: target=%0d code=%0d", tgt, code);
            if (dac_code !== tgt)
                $fatal(1, "sar: dac not parked: target=%0d dac=%0d", tgt, dac_code);
            if (busy !== 1'b0) $fatal(1, "sar: busy stuck after done");
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);
        for (t = 0; t < 16; t = t + 1) run_conv(t[3:0]);      // exhaustive
        for (k = 0; k < 50; k = k + 1) run_conv($random);     // random, b2b
        $display("PASS");
        $finish;
    end
endmodule
