// tb_event_ctrl: behavioral async charge-balance model with random delays.
// Sends n crossing decisions then a no-cross; checks count == min(n,15),
// early termination (done), Gray coding, and handshake completion.
`timescale 1ns/1ps
module tb_event_ctrl;
    reg clk = 0, rst_n = 0, start = 0;
    wire done;
    wire [3:0] count, count_gray;
    reg  cb_req = 0, cb_cross = 0;
    wire cb_ack;

    event_ctrl dut (.clk(clk), .rst_n(rst_n), .start(start),
                    .done(done), .count(count), .count_gray(count_gray),
                    .cb_req(cb_req), .cb_cross(cb_cross), .cb_ack(cb_ack));

    always #5 clk = ~clk;

    integer trial, n, j, exp, fired;

    // one async 4-phase decision handshake; returns after completion
    task decision;
        input xing;
        begin
            #(4 + {$random} % 30);
            cb_cross = xing;
            #2;
            cb_req = 1;
            wait (cb_ack === 1'b1);
            #(2 + {$random} % 11);
            cb_req = 0;
            wait (cb_ack === 1'b0);
            repeat (2) @(posedge clk);  // let done settle before caller reads it
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (trial = 0; trial < 60; trial = trial + 1) begin
            n = (trial < 20) ? trial : ({$random} % 20);  // 0..19 crossings offered
            @(posedge clk); start <= 1; @(posedge clk); start <= 0;
            @(posedge clk);
            if (done !== 1'b0) $fatal(1, "evt: done not cleared on start");

            fired = 0;
            for (j = 0; j < n; j = j + 1)
                if (!done) begin decision(1); fired = fired + 1; end
            if (!done) decision(0);          // no-cross -> early termination

            @(posedge clk); @(posedge clk);  // let done settle through FSM
            exp = (n > 15) ? 15 : n;
            if (done !== 1'b1) $fatal(1, "evt: no done, trial %0d n=%0d", trial, n);
            if (count !== exp[3:0])
                $fatal(1, "evt: count=%0d exp=%0d (n=%0d)", count, exp, n);
            if (count_gray !== (exp[3:0] ^ (exp[3:0] >> 1)))
                $fatal(1, "evt: gray=%b exp=%b", count_gray, exp[3:0] ^ (exp[3:0] >> 1));
            if (cb_ack !== 1'b0) $fatal(1, "evt: ack stuck high");
        end
        $display("PASS");
        $finish;
    end
endmodule
