// analogioc_beh: behavioural model of the analogioc macro, simulation only.
// Contract: analog/analogioc/docs/INTERFACE.md §9 (ports §2, handshakes §4/§6,
// weight write §7). Bit-true to scripts/golden/model.py:
//   - weights are what was written on w_wl/w_data (captured on w_wl[i] falling),
//     W[j][i] = Cp - Cn (golden.wq_from_caps), j = 16 is the checksum column;
//   - mac_j = sum_i W[j][i] * (x_neg_i ? -1 : 1) * m_i (+ LoRA, real arithmetic);
//   - golden.eventrate_convert: q = floor((2|mac| + D) / 2D), mag = min(q, 255),
//     count = mag >> 4 (coarse crossings), fine = mag & 15 (SAR residue),
//     col_sign = mac < 0.
// The macro never counts: decision k of a conversion crosses iff k < count, and a
// SAR trial answers fine >= dac_code. Delays are parameters (ns, sim grid);
// JITTER > 0 scales each analog delay by U[1-JITTER, 1+JITTER] (seed: +seed=N,
// or write `jitter`/`seed` from the testbench). Protocol violations call $error,
// count in n_prot_err, and are fatal under +strict.
`timescale 1ns/1ps
module analogioc #(
    parameter real TQ         = 10.0,
    parameter real T_RST      = 40.0,
    parameter real T_RG       = 10.0,
    parameter real T_SETTLE   = 80.0,
    parameter real T_RAMP0    = 40.0,
    parameter real T_RAMPW    = 500.0,
    parameter real T_SETTLE_L = 100.0,
    parameter real T_SIGN     = 6.0,
    parameter real T_BUNDLE   = 2.0,
    parameter real T_DEC      = 6.0,
    parameter real T_ABS      = 40.0,
    parameter real T_CLK_MAX  = 20.0,
    parameter real T_ACQ1     = 80.0,
    parameter real T_ACQ      = 14.0,
    parameter real T_HOLD     = 15.0,
    parameter real T_FSTROBE  = 6.0,
    parameter real T_WSU      = 20.0,
    parameter real T_WR       = 5.0,
    parameter real T_WH       = 2.0,
    parameter real LORA_RHO   = 0.0,
    parameter real JITTER     = 0.0,
    parameter integer MAC_MAX = 185
) (
`ifdef USE_POWER_PINS
    inout  wire         vdd,
    inout  wire         vdd_ota,
    inout  wire         vdd_cmp,
    inout  wire         vdd_pkt,
    inout  wire         vss,
`endif
    input  wire         seq_rst_n,
    input  wire         integ_req,
    output wire         integ_ack,
    input  wire         win_hi,
    input  wire [63:0]  x_mag,
    input  wire [15:0]  x_neg,
    input  wire [2:0]   pkt_d,
    input  wire         lora_en,
    output wire [16:0]  col_sign,
    input  wire [16:0]  coarse_en,
    output wire [16:0]  cb_req,
    output wire [16:0]  cb_cross,
    input  wire [16:0]  cb_ack,
    input  wire [16:0]  cmp_req,
    output wire [16:0]  cmp_ack,
    output wire [16:0]  cmp_result,
    input  wire [67:0]  dac_code,
    input  wire [16:0]  ota_en,
    input  wire [15:0]  lora_wa_sel,
    input  wire [15:0]  lora_wb_sel,
    input  wire [3:0]   lora_da,
    input  wire [3:0]   lora_db,
    input  wire [15:0]  w_wl,
    input  wire [135:0] w_data,
    inout  wire         vcm,
    inout  wire         vrn_thrp,
    inout  wire         vrp_thrp,
    inout  wire         vrn_thrn,
    inout  wire         vrp_thrn,
    inout  wire         vrn_sarp,
    inout  wire         vrp_sarp,
    inout  wire         vrn_sarn,
    inout  wire         vrp_sarn,
    inout  wire         vb_nc,
    inout  wire         vb_pc,
    inout  wire         vb_tail,
    inout  wire         vb_ramp
);
    // ---------------------------------------------------------------- helpers
    integer seed       = 1;
    real    jitter     = JITTER;
    integer n_prot_err = 0;          // protocol assertions fired (tbs read it)
    initial if ($value$plusargs("seed=%d", seed)) ;

    function real u01;               // U[0, 1]
        input dummy;
        u01 = ($random(seed) & 32'h7fffffff) / 2147483647.0;
    endfunction
    function real dly;               // analog delay, jittered
        input real t;
        dly = (jitter > 0.0) ? t * (1.0 - jitter + 2.0 * jitter * u01(0)) : t;
    endfunction
    function real bdly;              // bundling delay: jitter only stretches it,
        input real t;                // T_BUNDLE is a minimum (INTERFACE.md §4)
        bdly = (jitter > 0.0) ? t * (1.0 + jitter * u01(0)) : t;
    endfunction

    task prot;
        input [8*72-1:0] msg;
        begin
            n_prot_err = n_prot_err + 1;
            $error("analogioc_beh: %0s (t=%0t)", msg, $realtime);
            if ($test$plusargs("strict")) $fatal(1, "analogioc_beh: +strict");
        end
    endtask

    // ---------------------------------------------------------------- state
    // Weight storage, 4'bx until written; seq_rst_n does not clear it.
    reg  [3:0] cp [0:16][0:15];
    reg  [3:0] cn [0:16][0:15];
    reg  [3:0] la [0:15];            // LoRA A_i / B_j gain-cell codes (signed 4b)
    reg  [3:0] lb [0:15];
    integer    cnt [0:16];           // per column coarse count / fine code of the
    integer    fin [0:16];           // conversion in flight
    integer    d_pass = 1;           // D of the pass in flight

    reg        iack_r    = 1'b0;
    reg [16:0] sign_r    = 17'd0;
    reg [16:0] cbreq_r   = 17'd0;
    reg [16:0] cbx_r     = 17'd0;
    reg [16:0] cmpack_r  = 17'd0;
    reg [16:0] cmpres_r  = 17'd0;
    reg [16:0] busy      = 17'd0;    // a coarse decision handshake is open
    reg        in_window = 1'b0;     // integ_req↑ .. integ_ack↑
    event      conv_go;              // I7: conversions may start

    wire run = (seq_rst_n === 1'b1);
    assign integ_ack  = run & iack_r;
    assign col_sign   = run ? sign_r   : 17'd0;
    assign cb_req     = run ? cbreq_r  : 17'd0;
    assign cb_cross   = run ? cbx_r    : 17'd0;
    assign cmp_ack    = run ? cmpack_r : 17'd0;
    assign cmp_result = run ? cmpres_r : 17'd0;

    // ---------------------------------------------------------------- weight write (§7)
    realtime   t_wl_fall = -1.0e9;   // last w_wl falling edge
    realtime   t_wd      = -1.0e9;   // last w_data change
    realtime   t_wl_rise [0:15];
    reg [15:0] wl_q = 16'd0;

    always @(w_wl) begin : wl_mon
        integer i, j;
        if ((w_wl & (w_wl - 16'd1)) != 16'd0) prot("more than one w_wl high");
        if (in_window && |(w_wl & ~wl_q)) prot("w_wl high inside the must-be-stable window");
        for (i = 0; i < 16; i = i + 1) begin
            if (w_wl[i] === 1'b1 && wl_q[i] !== 1'b1) t_wl_rise[i] = $realtime;
            if (w_wl[i] === 1'b0 && wl_q[i] === 1'b1) begin
                if ($realtime - t_wl_rise[i] < T_WR) prot("w_wl pulse shorter than T_WR");
                if ($realtime - t_wd < T_WR) prot("w_data not stable T_WR before w_wl fell");
                for (j = 0; j < 17; j = j + 1) begin
                    cp[j][i] = w_data[8*j +: 4];
                    cn[j][i] = w_data[8*j+4 +: 4];
                end
                t_wl_fall = $realtime;
            end
        end
        wl_q = w_wl;
    end

    always @(w_data) begin
        if ($realtime - t_wl_fall < T_WH) prot("w_data changed within T_WH after w_wl fell");
        t_wd = $realtime;
    end

    // ---------------------------------------------------------------- LoRA cell writes
    reg [15:0] wa_q = 16'd0, wb_q = 16'd0;
    integer li;
    initial for (li = 0; li < 16; li = li + 1) begin la[li] = 4'd0; lb[li] = 4'd0; end
    always @(lora_wa_sel) begin : wa_mon
        integer i;
        for (i = 0; i < 16; i = i + 1)
            if (wa_q[i] === 1'b1 && lora_wa_sel[i] === 1'b0) la[i] = lora_da;
        wa_q = lora_wa_sel;
    end
    always @(lora_wb_sel) begin : wb_mon
        integer i;
        for (i = 0; i < 16; i = i + 1)
            if (wb_q[i] === 1'b1 && lora_wb_sel[i] === 1'b0) lb[i] = lora_db;
        wb_q = lora_wb_sel;
    end

    // ---------------------------------------------------------------- bundled-data checks
    always @(x_mag or x_neg or win_hi)
        if (integ_req === 1'b1 && !iack_r) prot("x_mag/x_neg/win_hi changed during integrate");
    always @(pkt_d or lora_en)
        if (in_window || |busy || |cmp_req) prot("pkt_d/lora_en changed mid-pass");

    // ---------------------------------------------------------------- integrate (§6.2)
    always @(posedge integ_req) if (run) begin : integ
        integer i, j, w, m, imac, mag, unw;
        real    mac, amac, lsum, tint;
        reg [63:0] xm;
        reg [15:0] xn;
        reg        hi, le;
        reg [16:0] nsign;
        if (iack_r) prot("integ_req rose while integ_ack high");
        if (w_wl != 16'd0 || $realtime - t_wl_fall < T_WSU)
            prot("w_wl active or fell less than T_WSU before integ_req");
        in_window = 1'b1;
        sign_r    = 17'd0;                       // I1: clear the sign latches
        xm = x_mag; xn = x_neg; hi = win_hi; le = lora_en;
        d_pass = (pkt_d == 3'd0) ? 1 : pkt_d;
        unw = 0;
        for (j = 0; j < 17; j = j + 1)
            for (i = 0; i < 16; i = i + 1)
                if (^{cp[j][i], cn[j][i]} === 1'bx) unw = unw + 1;
        if (unw != 0) prot("integ_req with unwritten weight storage");
        lsum = 0.0;                              // sidecar A.x, unsigned |x| (Q6)
        for (i = 0; i < 16; i = i + 1)
            lsum = lsum + $signed(la[i]) * $itor(xm[4*i +: 4]);
        for (j = 0; j < 17; j = j + 1) begin
            imac = 0;
            for (i = 0; i < 16; i = i + 1) begin
                w = cp[j][i];
                w = w - cn[j][i];
                m = xm[4*i +: 4];
                imac = imac + (xn[i] ? -w * m : w * m);
            end
            mac = imac;
            if (le && j < 16) mac = mac + LORA_RHO * $signed(lb[j]) * lsum;
            amac = (mac < 0.0) ? -mac : mac;
            if (amac > MAC_MAX)
                $display("analogioc_beh: WARNING col %0d |mac| = %0.1f > MAC_MAX %0d (OTA compression in silicon)",
                         j, amac, MAC_MAX);
            mag = $rtoi($floor((2.0 * amac + d_pass) / (2.0 * d_pass)));
            if (mag > 255) mag = 255;
            cnt[j]   = mag / 16;
            fin[j]   = mag % 16;
            nsign[j] = (mac < 0.0);
        end
        tint = T_RST + T_RG + (hi ? 8 * 16 * TQ : 16 * TQ)
             + (le ? T_RAMP0 + T_RAMPW + T_SETTLE_L : T_SETTLE) + T_SIGN;
        #(dly(tint));
        sign_r = nsign;                          // I6: sign strobes resolved
        #(bdly(T_BUNDLE));
        iack_r    = 1'b1;                        // I7
        in_window = 1'b0;
        -> conv_go;
        wait (integ_req === 1'b0);
        #(dly(1.0));
        iack_r = 1'b0;                           // I8: integrators hold
    end

    // ---------------------------------------------------------------- per column conv_seq
    genvar gj;
    generate for (gj = 0; gj < 17; gj = gj + 1) begin : g_col
        integer k;
        reg [3:0] dsamp;
        reg       first = 1'b0;              // next SAR trial is the first one

        // coarse loop (§6.3)
        always begin : coarse
            @(conv_go);
            k = 0;
            first = 1'b1;
            wait (coarse_en[gj] === 1'b1);    // C0: idle until decisions are enabled
            while (coarse_en[gj] === 1'b1) begin
                busy[gj] = 1'b1;
                #(dly(T_DEC));                // C1-C2: strobe, resolve, latch
                cbx_r[gj] = (k < cnt[gj]);
                #(bdly(T_BUNDLE));
                if (coarse_en[gj] !== 1'b1) prot("cb_req raised while coarse_en = 0");
                cbreq_r[gj] = 1'b1;
                wait (cb_ack[gj] === 1'b1);   // C3
                if (cbx_r[gj]) #(dly(TQ * d_pass));   // fire one packet: pkt_d chop cycles
                cbreq_r[gj] = 1'b0;           // C4
                wait (cb_ack[gj] === 1'b0);   // C5
                k = k + 1;
                busy[gj] = 1'b0;
                #(dly((T_ABS > 2.0 * T_CLK_MAX) ? T_ABS : 2.0 * T_CLK_MAX));
            end
        end

        // SAR trial (§6.4)
        always begin : fine
            @(posedge cmp_req[gj]);
            if (!run) disable fine;
            if (cmpack_r[gj]) prot("cmp_req rose while cmp_ack high");
            #(dly(first ? T_ACQ1 : T_ACQ));   // F1: acquire the residue
            first = 1'b0;
            #(dly(T_HOLD));                   // F2: CDAC hold on dac_code
            dsamp = dac_code[4*gj +: 4];
            #(dly(T_FSTROBE));                // F3
            cmpres_r[gj] = (fin[gj] >= dsamp);
            #(bdly(T_BUNDLE));
            cmpack_r[gj] = 1'b1;              // F4
            wait (cmp_req[gj] === 1'b0);
            #(dly(1.0));
            cmpack_r[gj] = 1'b0;              // F5
        end

        always @(dac_code[4*gj +: 4])
            if (cmp_req[gj] === 1'b1 || cmpack_r[gj]) prot("dac_code changed during a SAR trial");

        // a new integrate ends this column's conversion; it must be idle by now
        always @(posedge integ_req) begin
            if (busy[gj] || cmp_req[gj] === 1'b1 || cmpack_r[gj])
                prot("integ_req while a column is mid-conversion");
            disable coarse;
            busy[gj] = 1'b0;
        end

        always @(negedge seq_rst_n) begin
            disable coarse;
            disable fine;
            busy[gj] = 1'b0; cbreq_r[gj] = 1'b0; cbx_r[gj] = 1'b0;
            cmpack_r[gj] = 1'b0; cmpres_r[gj] = 1'b0;
        end
    end endgenerate

    always @(negedge seq_rst_n) begin
        disable integ;
        iack_r = 1'b0; sign_r = 17'd0; in_window = 1'b0;
    end
endmodule
