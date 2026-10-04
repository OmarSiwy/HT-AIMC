// tb_bacc_accum: randomized accumulation runs vs behavioral reference.
// W=20 instance: exact accumulation, done timing, post-done input ignore.
// W=16 instance: per-step saturation behavior (unreachable at W=20).
`timescale 1ns/1ps
module tb_bacc_accum;
    reg clk = 0, rst_n = 0, clear = 0, d_valid = 0;
    reg  signed [13:0] d;
    reg  [3:0] tile_cnt;
    wire signed [19:0] acc20;
    wire signed [15:0] acc16;
    wire done20, done16;

    bacc_accum #(.W(20)) dut20 (.clk(clk), .rst_n(rst_n), .clear(clear),
        .d(d), .d_valid(d_valid), .tile_cnt(tile_cnt), .acc(acc20), .done(done20));
    bacc_accum #(.W(16)) dut16 (.clk(clk), .rst_n(rst_n), .clear(clear),
        .d(d), .d_valid(d_valid), .tile_cnt(tile_cnt), .acc(acc16), .done(done16));

    always #5 clk = ~clk;

    integer trial, t, exp20, exp16, val;

    task step_ref16;  // per-step saturating reference for W=16
        input integer v;
        begin
            exp16 = exp16 + v;
            if (exp16 >  32767) exp16 =  32767;
            if (exp16 < -32768) exp16 = -32768;
        end
    endtask

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (trial = 0; trial < 100; trial = trial + 1) begin
            // clear both accumulators
            clear <= 1; @(posedge clk); clear <= 0; @(posedge clk);
            tile_cnt <= (trial % 8) + 1;
            @(posedge clk);
            exp20 = 0; exp16 = 0;

            for (t = 0; t < (trial % 8) + 1; t = t + 1) begin
                if (done20 !== 1'b0)
                    $fatal(1, "bacc: done20 high before %0d/%0d inputs",
                           t, (trial % 8) + 1);
                // saturating stimulus every 7th trial, else random
                if (trial % 7 == 3)      val =  8191;
                else if (trial % 7 == 5) val = -8192;
                else begin val = $random % 8192; end
                d <= val; d_valid <= 1;
                @(posedge clk);
                d_valid <= 0;
                exp20 = exp20 + val;      // W=20 never saturates for T<=8
                step_ref16(val);
                if (t % 3 == 0) @(posedge clk);  // random idle gaps
            end
            @(posedge clk);
            if (done20 !== 1'b1) $fatal(1, "bacc: done20 not set, trial %0d", trial);
            if (done16 !== 1'b1) $fatal(1, "bacc: done16 not set, trial %0d", trial);
            if (acc20 !== exp20)
                $fatal(1, "bacc W20: got=%0d exp=%0d trial=%0d", acc20, exp20, trial);
            if (acc16 !== exp16)
                $fatal(1, "bacc W16: got=%0d exp=%0d trial=%0d", acc16, exp16, trial);

            // inputs after done must be ignored
            d <= 14'sd1234; d_valid <= 1; @(posedge clk); d_valid <= 0; @(posedge clk);
            if (acc20 !== exp20) $fatal(1, "bacc: input after done not ignored");
        end
        $display("PASS");
        $finish;
    end
endmodule
