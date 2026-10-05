// analogioc_top: digital top around the analogioc IMC macro (contract:
// analog/analogioc/docs/INTERFACE.md §7.4, §8). Not a TinyTapeout top.
//
//   17 tile_fsm (column 16 = ABFT checksum, relu forced 0), joined into one
//   integ_req by a registered C-element; 17 datapath slices (nibble_combine ->
//   ReLU clamp -> slice_combine (p_hi = 0) -> bacc_accum W=20); abft_check;
//   16 requant; the pass sequencer (HI window, then LO window); the LoRA cell
//   writer; and the weight-load controller (wt_* row stream -> w_wl/w_data).
//
// Per pass: latch pass_x -> HI window (x_mag = |x|>>4, win_hi = 1) -> all 17
// col_valid -> LO window (x_mag = |x|&15, relu only where code_hi == 0) -> code
// assembly (code_lo forced 0 where HI exited, golden.tile_mvm(relu=True)) ->
// bacc d_valid. After cfg_tile_cnt passes: abft_check + requant on res_*.
//
// Weights: 16 row beats on wt_* make the set of the next pass. They are written
// while !tile_busy && !w_loaded, 2 clk per row (WL high, then WL low with data
// held). tile_busy covers the HI start .. the synchronized LO integ_ack↑, so the
// write for pass N+1 overlaps pass N's LO conversion, and the HI window of a pass
// starts only once its set is loaded (T_WSU >= 2 clk by construction).
module analogioc_top #(
    parameter WR_CYCLES = 6           // LoRA write strobe: ceil(120 ns / T_clk), T_clk = 20 ns
) (
    input  wire         clk,
    input  wire         rst_n,
    // static config, may change only while idle
    input  wire         cfg_relu_en,
    input  wire [2:0]   cfg_pkt_d,
    input  wire [3:0]   cfg_tile_cnt,
    input  wire [15:0]  cfg_abft_s,
    input  wire [15:0]  cfg_abft_budget,
    input  wire [127:0] cfg_rq_scale,
    input  wire [79:0]  cfg_rq_shift,
    input  wire [127:0] cfg_rq_offset,
    input  wire         cfg_lora_en,
    output wire         idle,
    // one tile pass
    input  wire         pass_valid,
    output wire         pass_ready,
    input  wire [127:0] pass_x,
    input  wire [15:0]  pass_abft_corr,
    output wire         code_valid,
    output reg  [135:0] code_hi,
    output reg  [135:0] code_lo,
    // one output after cfg_tile_cnt passes
    output wire         res_valid,
    input  wire         res_ready,
    output wire [127:0] res_q,
    output wire [339:0] res_acc,
    output wire [24:0]  res_residual,
    output wire         res_abft_flag,
    // LoRA sidecar cell write
    input  wire         lw_valid,
    output wire         lw_ready,
    input  wire         lw_b,
    input  wire [3:0]   lw_idx,
    input  wire [3:0]   lw_code,
    // weight row stream
    input  wire         wt_valid,
    output wire         wt_ready,
    input  wire [135:0] wt_data,
    // analog nets, straight through to the macro
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
    // ------------------------------------------------------------ pass sequencer
    localparam [3:0] S_IDLE    = 4'd0,
                     S_HI      = 4'd1,   // HI window start pending (weights, all idle)
                     S_HI_RUN  = 4'd2,
                     S_LO      = 4'd3,
                     S_LO_RUN  = 4'd4,
                     S_ACC     = 4'd5,   // code_valid, bacc d_valid
                     S_CHK     = 4'd6,   // bacc done?
                     S_RES     = 4'd7,   // res_valid until res_ready
                     S_LW_SEL  = 4'd8,
                     S_LW_HOLD = 4'd9,
                     S_LW_DONE = 4'd10;
    reg [3:0] st;

    // column bundles
    wire [16:0]  start_rdy, col_vld, col_exit, fsm_req;
    wire [135:0] col_code;
    wire [16:0]  col_sign, coarse_en, cb_req, cb_cross, cb_ack;
    wire [16:0]  cmp_req, cmp_ack, cmp_result, ota_en;
    wire [67:0]  dac_code;
    wire         integ_ack;

    reg  [63:0]  x_mag_q;
    reg  [15:0]  x_neg_q;
    reg          win_hi_q;
    reg  [63:0]  x_lo_q;              // LO nibbles of the pass in flight
    reg  [16:0]  exit_hi;
    reg  signed [15:0] corr_q;
    reg  signed [19:0] corr_sum;

    // weight-load controller state (§7.4)
    reg  [3:0]   w_row;
    reg          w_loaded, tile_busy;
    reg  [15:0]  w_wl_q;
    reg  [135:0] w_data_q;

    wire all_rdy   = &start_rdy;
    wire all_vld   = &col_vld;
    wire fsm_start = ((st == S_HI && w_loaded) || st == S_LO) && all_rdy;
    wire col_rdy   = (st == S_HI_RUN || st == S_LO_RUN) && all_vld;
    wire d_valid   = (st == S_ACC);
    wire acc_clear = (st == S_RES) && res_ready;
    wire [16:0] acc_done;

    // relu per column, sampled by tile_fsm at start accept
    wire [16:0] relu_vec;
    genvar j;
    generate for (j = 0; j < 17; j = j + 1) begin : g_relu
        if (j < 16) begin : g_data
            assign relu_vec[j] = cfg_relu_en & ((st == S_HI) | (code_hi[8*j +: 8] == 8'd0));
        end else begin : g_chk
            assign relu_vec[j] = 1'b0;
        end
    end endgenerate

    assign idle       = (st == S_IDLE);
    assign pass_ready = (st == S_IDLE);
    assign code_valid = (st == S_ACC);
    assign res_valid  = (st == S_RES);
    assign lw_ready   = (st == S_LW_DONE);

    // split pass_x into sign + nibbles (golden.pwm_nibbles)
    wire [63:0] px_hi, px_lo;
    wire [15:0] px_neg;
    generate for (j = 0; j < 16; j = j + 1) begin : g_split
        wire [7:0] x = pass_x[8*j +: 8];
        wire [7:0] m = x[7] ? (~x + 8'd1) : x;
        assign px_neg[j]       = x[7];
        assign px_hi[4*j +: 4] = m[7:4];
        assign px_lo[4*j +: 4] = m[3:0];
    end endgenerate

    // LoRA write
    reg  [15:0] lora_wa_sel_q, lora_wb_sel_q;
    reg  [3:0]  lora_da_q, lora_db_q;
    reg         lw_b_q;
    reg  [3:0]  lw_idx_q;
    reg  [3:0]  lw_cnt;

    // code_lo of a column that exited in HI is forced to 0
    wire [135:0] code_lo_masked;
    generate for (j = 0; j < 17; j = j + 1) begin : g_mask
        assign code_lo_masked[8*j +: 8] = exit_hi[j] ? 8'd0 : col_code[8*j +: 8];
    end endgenerate

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st            <= S_IDLE;
            x_mag_q       <= 64'd0;
            x_neg_q       <= 16'd0;
            win_hi_q      <= 1'b0;
            x_lo_q        <= 64'd0;
            exit_hi       <= 17'd0;
            code_hi       <= 136'd0;
            code_lo       <= 136'd0;
            corr_q        <= 16'sd0;
            corr_sum      <= 20'sd0;
            lora_wa_sel_q <= 16'd0;
            lora_wb_sel_q <= 16'd0;
            lora_da_q     <= 4'd0;
            lora_db_q     <= 4'd0;
            lw_b_q        <= 1'b0;
            lw_idx_q      <= 4'd0;
            lw_cnt        <= 4'd0;
        end else begin
            case (st)
                S_IDLE: if (pass_valid) begin
                    x_mag_q  <= px_hi;           // bundled data: stable >= 2 clk before integ_req
                    x_neg_q  <= px_neg;
                    win_hi_q <= 1'b1;
                    x_lo_q   <= px_lo;
                    corr_q   <= pass_abft_corr;
                    st       <= S_HI;
                end else if (lw_valid) begin
                    if (lw_b) lora_db_q <= lw_code; else lora_da_q <= lw_code;
                    lw_b_q   <= lw_b;
                    lw_idx_q <= lw_idx;
                    lw_cnt   <= 4'd0;
                    st       <= S_LW_SEL;
                end
                S_HI: if (fsm_start) st <= S_HI_RUN;
                S_HI_RUN: if (all_vld) begin
                    code_hi  <= col_code;
                    exit_hi  <= col_exit;
                    x_mag_q  <= x_lo_q;
                    win_hi_q <= 1'b0;
                    st       <= S_LO;
                end
                S_LO: if (fsm_start) st <= S_LO_RUN;
                S_LO_RUN: if (all_vld) begin
                    code_lo <= code_lo_masked;
                    st      <= S_ACC;
                end
                S_ACC: begin
                    corr_sum <= corr_sum + {{4{corr_q[15]}}, corr_q};
                    st       <= S_CHK;
                end
                S_CHK: st <= (&acc_done) ? S_RES : S_IDLE;
                S_RES: if (res_ready) begin
                    corr_sum <= 20'sd0;
                    st       <= S_IDLE;
                end
                S_LW_SEL: begin                  // sel high for WR_CYCLES clk, 1 clk after the code
                    lw_cnt <= lw_cnt + 4'd1;
                    if (lw_cnt == 4'd0) begin
                        if (lw_b_q) lora_wb_sel_q <= 16'd1 << lw_idx_q;
                        else        lora_wa_sel_q <= 16'd1 << lw_idx_q;
                    end
                    if (lw_cnt == WR_CYCLES) begin
                        lora_wa_sel_q <= 16'd0;
                        lora_wb_sel_q <= 16'd0;
                        st            <= S_LW_HOLD;
                    end
                end
                S_LW_HOLD: st <= S_LW_DONE;      // data held 1 clk after the strobe
                S_LW_DONE: st <= S_IDLE;
                default:   st <= S_IDLE;
            endcase
        end
    end

    // ------------------------------------------------------------ weight-load controller
    // 2FF-synchronized integ_ack; its rising edge in the LO window ends tile_busy.
    reg ia_m, ia_s, ia_d;
    wire lo_ack_rise = ia_s & ~ia_d & (st == S_LO_RUN);

    assign wt_ready = !tile_busy && !w_loaded && (w_wl_q == 16'd0);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ia_m <= 1'b0; ia_s <= 1'b0; ia_d <= 1'b0;
            w_row     <= 4'd0;
            w_loaded  <= 1'b0;
            tile_busy <= 1'b0;
            w_wl_q    <= 16'd0;
            w_data_q  <= 136'd0;
        end else begin
            ia_m <= integ_ack; ia_s <= ia_m; ia_d <= ia_s;
            if (wt_valid && wt_ready) begin
                w_data_q <= wt_data;
                w_wl_q   <= 16'd1 << w_row;
            end else if (w_wl_q != 16'd0) begin
                w_wl_q <= 16'd0;                 // WL falls, data held: the cell stores
                w_row  <= w_row + 4'd1;
                if (w_row == 4'd15) w_loaded <= 1'b1;
            end
            if (st == S_HI && fsm_start) tile_busy <= 1'b1;
            if (lo_ack_rise) begin
                tile_busy <= 1'b0;
                w_loaded  <= 1'b0;
            end
        end
    end

    // ------------------------------------------------------------ integrate join
    reg integ_req_q;
    always @(posedge clk or negedge rst_n)
        if (!rst_n) integ_req_q <= 1'b0;
        else        integ_req_q <= (&fsm_req) ? 1'b1 : (~|fsm_req) ? 1'b0 : integ_req_q;

    // ------------------------------------------------------------ 17 columns
    wire [339:0] acc_flat;
    generate for (j = 0; j < 17; j = j + 1) begin : g_col
        tile_fsm u_fsm (
            .clk(clk), .rst_n(rst_n),
            .start_valid(fsm_start), .start_ready(start_rdy[j]), .relu_en(relu_vec[j]),
            .col_code(col_code[8*j +: 8]), .col_valid(col_vld[j]), .col_ready(col_rdy),
            .evt_count_gray(),
            .integ_req(fsm_req[j]), .integ_ack(integ_ack), .col_sign(col_sign[j]),
            .coarse_en(coarse_en[j]),
            .cb_req(cb_req[j]), .cb_cross(cb_cross[j]), .cb_ack(cb_ack[j]),
            .cmp_req(cmp_req[j]), .cmp_ack(cmp_ack[j]), .cmp_result(cmp_result[j]),
            .dac_code(dac_code[4*j +: 4]),
            .ota_en(ota_en[j]), .col_exit(col_exit[j])
        );

        wire signed [11:0] y12, y12r;
        wire signed [13:0] y14;
        nibble_combine u_nib (.lsb_code(code_lo[8*j +: 8]), .msb_code(code_hi[8*j +: 8]),
                              .partial(y12));
        // free digital ReLU clamp on data columns
        assign y12r = (cfg_relu_en && j < 16 && y12 < 0) ? 12'sd0 : y12;
        slice_combine u_slice (.p_lo(y12r), .p_hi(12'sd0), .y(y14));
        bacc_accum #(.W(20)) u_acc (
            .clk(clk), .rst_n(rst_n), .clear(acc_clear),
            .d(y14), .d_valid(d_valid), .tile_cnt(cfg_tile_cnt),
            .acc(acc_flat[20*j +: 20]), .done(acc_done[j])
        );
    end endgenerate

    // ------------------------------------------------------------ ABFT + requant
    // FORMATS.md abft_wiring: y_flat[j] = s_j * acc_j, y_chk = (acc_16 <<< 3) + sum corr
    wire [319:0] y_flat;
    generate for (j = 0; j < 16; j = j + 1) begin : g_rq
        wire signed [19:0] a = acc_flat[20*j +: 20];
        assign y_flat[20*j +: 20] = cfg_abft_s[j] ? -a : a;
        requant u_rq (
            .y(a), .scale(cfg_rq_scale[8*j +: 8]), .shift(cfg_rq_shift[5*j +: 5]),
            .offset(cfg_rq_offset[8*j +: 8]), .q(res_q[8*j +: 8])
        );
    end endgenerate
    wire signed [19:0] acc_chk = acc_flat[320 +: 20];
    wire signed [19:0] y_chk   = (acc_chk <<< 3) + corr_sum;

    abft_check #(.W(20)) u_abft (
        .y_flat(y_flat), .y_chk(y_chk), .budget(cfg_abft_budget),
        .residual(res_residual), .flag(res_abft_flag)
    );
    assign res_acc = acc_flat;

    // ------------------------------------------------------------ the macro
    analogioc u_analogioc (
        .seq_rst_n(rst_n),
        .integ_req(integ_req_q), .integ_ack(integ_ack),
        .win_hi(win_hi_q), .x_mag(x_mag_q), .x_neg(x_neg_q),
        .pkt_d(cfg_pkt_d), .lora_en(cfg_lora_en),
        .col_sign(col_sign), .coarse_en(coarse_en),
        .cb_req(cb_req), .cb_cross(cb_cross), .cb_ack(cb_ack),
        .cmp_req(cmp_req), .cmp_ack(cmp_ack), .cmp_result(cmp_result),
        .dac_code(dac_code), .ota_en(ota_en),
        .lora_wa_sel(lora_wa_sel_q), .lora_wb_sel(lora_wb_sel_q),
        .lora_da(lora_da_q), .lora_db(lora_db_q),
        .w_wl(w_wl_q), .w_data(w_data_q),
        .vcm(vcm),
        .vrn_thrp(vrn_thrp), .vrp_thrp(vrp_thrp), .vrn_thrn(vrn_thrn), .vrp_thrn(vrp_thrn),
        .vrn_sarp(vrn_sarp), .vrp_sarp(vrp_sarp), .vrn_sarn(vrn_sarn), .vrp_sarn(vrp_sarn),
        .vb_nc(vb_nc), .vb_pc(vb_pc), .vb_tail(vb_tail), .vb_ramp(vb_ramp)
    );
endmodule
