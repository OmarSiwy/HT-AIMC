// tb_rail: integration test of the datapath rail through rail_top:
// fake per-pass column codes -> nibble_combine (x2 slices) -> slice_combine
// -> bacc_accum (T tiles) -> abft_check (16 cols + checksum) -> requant.
// Checked against an independent integer reference model in the tb.
// Runs clean sweeps at several tile counts plus fault-injection runs that
// must raise the ABFT flag.
`timescale 1ns/1ps
module tb_rail;
    reg clk = 0, rst_n = 0;
    reg  signed [7:0] lsb_lo, msb_lo, lsb_hi, msb_hi;
    reg  d_valid = 0, acc_clear = 0;
    reg  [3:0] tile_cnt;
    wire signed [19:0] acc;
    wire acc_done;
    reg  [16*20-1:0] y_flat;
    reg  signed [19:0] y_chk;
    reg  [15:0] budget = 16'd2;
    wire signed [24:0] residual;
    wire abft_flag;
    reg  [7:0] rq_scale;
    reg  [4:0] rq_shift;
    reg  signed [7:0] rq_offset;
    wire signed [7:0] q;

    rail_top dut (
        .clk(clk), .rst_n(rst_n),
        .lsb_lo(lsb_lo), .msb_lo(msb_lo), .lsb_hi(lsb_hi), .msb_hi(msb_hi),
        .d_valid(d_valid), .acc_clear(acc_clear), .tile_cnt(tile_cnt),
        .acc(acc), .acc_done(acc_done),
        .y_flat(y_flat), .y_chk(y_chk), .budget(budget),
        .residual(residual), .abft_flag(abft_flag),
        .rq_scale(rq_scale), .rq_shift(rq_shift), .rq_offset(rq_offset), .q(q),
        // tile_fsm side idle in this tb (covered by tb_tile_fsm)
        .start_valid(1'b0), .start_ready(), .relu_en(1'b0),
        .col_code(), .col_valid(), .col_ready(1'b0), .evt_count_gray(),
        .integ_req(), .integ_ack(1'b0), .col_sign(1'b0),
        .coarse_en(), .cb_req(1'b0), .cb_cross(1'b0), .cb_ack(),
        .cmp_req(), .cmp_ack(1'b0), .cmp_result(1'b0), .dac_code()
    );

    always #5 clk = ~clk;

    // codes[((c*8 + t)*2 + s)*2 + p]: col c 0..16 (16=checksum),
    // tile t, slice s (1=hi), pass p (1=msb nibble)
    reg signed [7:0] codes [0:17*8*4-1];
    integer y_ref [0:16];
    integer y_dut [0:16];

    function integer cidx;
        input integer c, t, s, p;
        begin cidx = ((c*8 + t)*2 + s)*2 + p; end
    endfunction

    function integer clampi;
        input integer v, lo, hi;
        begin clampi = (v < lo) ? lo : (v > hi) ? hi : v; end
    endfunction

    // independent reference: full rail math for one column
    task ref_column;
        input integer c, T;
        integer t, nlo, nhi, yt;
        begin
            y_ref[c] = 0;
            for (t = 0; t < T; t = t + 1) begin
                nlo = clampi(16*codes[cidx(c,t,0,1)] + codes[cidx(c,t,0,0)], -2048, 2047);
                nhi = clampi(16*codes[cidx(c,t,1,1)] + codes[cidx(c,t,1,0)], -2048, 2047);
                yt  = clampi(4*nhi + nlo, -8192, 8191);
                y_ref[c] = clampi(y_ref[c] + yt, -524288, 524287);
            end
        end
    endtask

    integer run_no, c, t, s, p, i, sum, exp_res;
    integer si, shi, offi, prod, half, shf, rq_exp;

    task run_rail;
        input integer T;
        input integer inject;   // 1: bump one code after checksum derivation
        begin
            // generate codes: cols 0..15 in [-7,7]; checksum col = column-wise sum
            for (c = 0; c < 16; c = c + 1)
                for (t = 0; t < T; t = t + 1)
                    for (s = 0; s < 2; s = s + 1)
                        for (p = 0; p < 2; p = p + 1)
                            codes[cidx(c,t,s,p)] = ($random % 8);
            for (t = 0; t < T; t = t + 1)
                for (s = 0; s < 2; s = s + 1)
                    for (p = 0; p < 2; p = p + 1) begin
                        sum = 0;
                        for (c = 0; c < 16; c = c + 1)
                            sum = sum + codes[cidx(c,t,s,p)];
                        codes[cidx(16,t,s,p)] = sum;  // |sum| <= 112, fits 8b
                    end
            if (inject)  // stuck/drifted cap model: one code off by +5
                codes[cidx(3, T-1, 1, 0)] = codes[cidx(3, T-1, 1, 0)] + 8'sd5;

            // per-column: DUT accumulate + requant, vs reference
            tile_cnt = T;
            for (c = 0; c < 17; c = c + 1) begin
                ref_column(c, T);
                @(posedge clk); acc_clear <= 1;
                @(posedge clk); acc_clear <= 0;
                for (t = 0; t < T; t = t + 1) begin
                    lsb_lo <= codes[cidx(c,t,0,0)];
                    msb_lo <= codes[cidx(c,t,0,1)];
                    lsb_hi <= codes[cidx(c,t,1,0)];
                    msb_hi <= codes[cidx(c,t,1,1)];
                    d_valid <= 1;
                    @(posedge clk);
                    d_valid <= 0;
                end
                @(posedge clk);
                if (acc_done !== 1'b1)
                    $fatal(1, "rail: no acc_done col=%0d run=%0d", c, run_no);
                y_dut[c] = acc;
                if (y_dut[c] !== y_ref[c])
                    $fatal(1, "rail: acc col=%0d got=%0d exp=%0d run=%0d",
                           c, y_dut[c], y_ref[c], run_no);

                // requant this column while acc holds it
                rq_scale  = 1 + ({$random} % 255);
                rq_shift  = {$random} % 9;
                rq_offset = $random % 51;
                #1;
                si = rq_scale; shi = rq_shift; offi = rq_offset;
                prod = y_ref[c] * si;
                half = (shi == 0) ? 0 : (1 << (shi - 1));
                shf  = (prod + half) >>> shi;
                rq_exp = clampi(shf + offi, -128, 127);
                if ($signed(q) !== rq_exp)
                    $fatal(1, "rail: requant col=%0d got=%0d exp=%0d run=%0d",
                           c, $signed(q), rq_exp, run_no);
            end

            // ABFT over the 16 columns vs checksum column
            for (i = 0; i < 16; i = i + 1)
                y_flat[i*20 +: 20] = y_dut[i];
            y_chk = y_dut[16];
            #1;
            sum = 0;
            for (i = 0; i < 16; i = i + 1) sum = sum + y_ref[i];
            exp_res = sum - y_ref[16];
            if (residual !== exp_res)
                $fatal(1, "rail: residual got=%0d exp=%0d run=%0d",
                       residual, exp_res, run_no);
            if (inject) begin
                if (abft_flag !== 1'b1)
                    $fatal(1, "rail: injected fault not flagged, run=%0d", run_no);
            end else begin
                if (exp_res !== 0)
                    $fatal(1, "rail: clean run residual nonzero (%0d)", exp_res);
                if (abft_flag !== 1'b0)
                    $fatal(1, "rail: false ABFT flag, run=%0d", run_no);
            end
            run_no = run_no + 1;
        end
    endtask

    initial begin
        run_no = 0;
        repeat (3) @(posedge clk);
        rst_n = 1;
        @(posedge clk);
        run_rail(1, 0);
        run_rail(2, 0);
        run_rail(4, 0);
        run_rail(8, 0);
        run_rail(8, 1);   // fault injection: ABFT must flag
        run_rail(3, 1);
        $display("PASS");
        $finish;
    end
endmodule
