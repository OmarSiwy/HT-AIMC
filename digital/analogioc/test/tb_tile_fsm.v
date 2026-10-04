// tb_tile_fsm: full behavioral analog model (integrate handshake, event-rate
// coarse loop gated by coarse_en, SAR comparator) with random async delays.
// Checks assembled column codes, sign handling, ReLU early exit (code 0 and
// zero analog conversion activity), Gray count export, ready/valid handshake.
`timescale 1ns/1ps
module tb_tile_fsm;
    reg clk = 0, rst_n = 0;
    reg start_valid = 0, relu_en = 0, col_ready = 0;
    wire start_ready, col_valid;
    wire [7:0] col_code;
    wire [3:0] evt_count_gray, dac_code;
    wire integ_req, coarse_en, cb_ack, cmp_req;
    reg  integ_ack = 0, col_sign = 0;
    reg  cb_req = 0, cb_cross = 0;
    reg  cmp_ack = 0, cmp_result = 0;

    tile_fsm dut (.clk(clk), .rst_n(rst_n),
        .start_valid(start_valid), .start_ready(start_ready), .relu_en(relu_en),
        .col_code(col_code), .col_valid(col_valid), .col_ready(col_ready),
        .evt_count_gray(evt_count_gray),
        .integ_req(integ_req), .integ_ack(integ_ack), .col_sign(col_sign),
        .coarse_en(coarse_en), .cb_req(cb_req), .cb_cross(cb_cross), .cb_ack(cb_ack),
        .cmp_req(cmp_req), .cmp_ack(cmp_ack), .cmp_result(cmp_result),
        .dac_code(dac_code));

    always #5 clk = ~clk;

    // -------- per-trial hidden analog state --------
    integer n_cross;        // crossings the analog would produce
    reg [3:0] sar_target;   // residue value the SAR should find
    reg exp_exit;           // this trial must early-exit

    // -------- analog model: integrate phase --------
    always begin
        wait (integ_req === 1'b1);
        #(5 + {$random} % 40);          // integration window (col_sign preset)
        integ_ack = 1;
        wait (integ_req === 1'b0);
        #(2 + {$random} % 15);
        integ_ack = 0;
    end

    // -------- analog model: coarse loop (issues decisions while enabled) ----
    integer sent;
    always begin
        wait (coarse_en === 1'b1);
        sent = 0;
        while (coarse_en === 1'b1) begin
            #(4 + {$random} % 25);
            if (coarse_en === 1'b1) begin
                cb_cross = (sent < n_cross);
                #2;
                cb_req = 1;
                wait (cb_ack === 1'b1);
                #(2 + {$random} % 9);
                cb_req = 0;
                wait (cb_ack === 1'b0);
                sent = sent + 1;
                repeat (2) @(posedge clk);  // let coarse_en/done settle
            end
        end
    end

    // -------- analog model: SAR comparator --------
    always begin
        wait (cmp_req === 1'b1);
        #(3 + {$random} % 20);
        cmp_result = (sar_target >= dac_code);
        #2;
        cmp_ack = 1;
        wait (cmp_req === 1'b0);
        #(2 + {$random} % 9);
        cmp_ack = 0;
    end

    // -------- illegal-activity monitor for early-exit trials --------
    always @(posedge cb_ack)  if (exp_exit) $fatal(1, "tile_fsm: cb_ack during early exit");
    always @(posedge cmp_req) if (exp_exit) $fatal(1, "tile_fsm: cmp_req during early exit");
    always @(posedge coarse_en) if (exp_exit) $fatal(1, "tile_fsm: coarse_en during early exit");

    integer trial, cnt, mag, expc, got;

    initial begin
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);

        for (trial = 0; trial < 80; trial = trial + 1) begin
            // trial setup (mix directed + random)
            case (trial % 8)
                0: begin col_sign = 0; relu_en = 0; end
                1: begin col_sign = 1; relu_en = 0; end   // negative, full conv
                2: begin col_sign = 1; relu_en = 1; end   // EARLY EXIT
                3: begin col_sign = 0; relu_en = 1; end   // relu but positive
                default: begin col_sign = $random; relu_en = $random; end
            endcase
            n_cross    = {$random} % 18;                  // 0..17 (tests cap at 15)
            sar_target = $random;
            exp_exit   = relu_en & col_sign;

            // expected code (reference model, independent integer math)
            cnt  = (n_cross > 15) ? 15 : n_cross;
            mag  = 16*cnt + sar_target;
            if (mag > 127) mag = 127;
            expc = exp_exit ? 0 : (col_sign ? -mag : mag);

            // start handshake (ready/valid)
            wait (start_ready === 1'b1);
            @(posedge clk); start_valid <= 1;
            @(posedge clk); start_valid <= 0;

            // wait for result, random backpressure on col_ready
            wait (col_valid === 1'b1);
            #1;  // col_code updates in the same NBA region as col_valid
            got = $signed(col_code);
            if (got !== expc)
                $fatal(1, "tile_fsm: trial=%0d n=%0d sar=%0d sign=%b relu=%b got=%0d exp=%0d",
                       trial, n_cross, sar_target, col_sign, relu_en, got, expc);
            if (!exp_exit && (evt_count_gray !== (cnt[3:0] ^ (cnt[3:0] >> 1))))
                $fatal(1, "tile_fsm: gray=%b exp=%b", evt_count_gray,
                       cnt[3:0] ^ (cnt[3:0] >> 1));
            if (start_ready !== 1'b0)
                $fatal(1, "tile_fsm: start_ready high during readout");

            repeat (1 + {$random} % 5) @(posedge clk);
            col_ready <= 1; @(posedge clk); col_ready <= 0;
            @(posedge clk);
            if (col_valid !== 1'b0) $fatal(1, "tile_fsm: col_valid not dropped");
        end
        $display("PASS");
        $finish;
    end
endmodule
