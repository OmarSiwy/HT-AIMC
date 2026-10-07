// IMC tile-array driver: the controller a weight-stationary systolic array would have, mapped onto
// the charge-domain tile of ARCH_CHOSEN.md (B1-B6, B10).
//
//   schedule   for n-block nb: for m-chunk mc (AccDepth tokens): for k-group kg (NTiles x Rows of
//              K): for token mi: one element. Element e enters tile 0 at pass e+1 and tile t at
//              pass e+t+1 (the activation skew of a systolic array), so tile t's partial sum meets
//              tile t-1's on the accumulator chain one pass later.
//   weights    a group (nb, mc, kg) is staged from the HBM stream into the tiles' ping-pong banks
//              and written into the gain-cell array in the merge slot right before the pass that
//              first uses it: just in time, and a pass that would run ahead of its weights stalls.
//   activations INT8 per token (Hadamard-rotated upstream), Rows per tile per pass, read from the
//              activation buffer one word per tile per pass.
//   drive      sign-magnitude rows: |x| clipped to 127; ml2 (Mode 0) slot s drives the 2-b digit
//              (2|x| >> 2s) & 3, bitserial (Mode 1) slot s drives bit s of |x|; the sign picks rail rp/rn.
//              drive_o per row: {sgn, d1, d0}, zero outside the drive window.
//
// Verilog-2001 so that the same source runs as a VerA .v device inside ESPice.
`timescale 1ns/1ps
module imc_driver #(
    parameter integer Rows       = 8,
    parameter integer Cols       = 8,
    parameter integer NTiles     = 2,
    parameter integer AdcShare   = 4,
    parameter integer Bits       = 12,
    parameter integer Mode       = 0,      // 0 ml2 (4 slots), 1 bitserial (7 slots)
    parameter integer SlotTicks  = 8,
    parameter integer RstTicks   = 1,
    parameter integer ShTicks    = 3,
    parameter integer MergeTicks = 8,
    parameter integer RoundTicks = 11,
    parameter integer CalF       = 14,
    parameter integer AccW       = 24,
    parameter integer CodeShift  = 6,
    parameter integer AccDepth   = 16,
    parameter integer CW         = 16,
    parameter integer RefreshPasses = 128
) (
    input  wire                                   clk_i,
    input  wire                                   rst_ni,
    input  wire                                   start_i,
    input  wire [CW-1:0]                          cfg_m_i,     // tokens
    input  wire [CW-1:0]                          cfg_g_i,     // k-groups (K / (NTiles*Rows))
    input  wire [CW-1:0]                          cfg_nb_i,    // n-blocks (N / Cols)
    // HBM weight stream: INT8 row words, group order, tile 0..NTiles-1, row 0..Rows-1
    input  wire                                   w_valid_i,
    output wire                                   w_ready_o,
    input  wire [Cols*8-1:0]                      w_data_i,
    // activation buffer: one read per tile, word = Rows INT8, address = token * (G*NTiles) + chunk
    output wire [NTiles*2*CW-1:0]                 x_addr_o,
    input  wire [NTiles*Rows*8-1:0]               x_data_i,
    // requant table, per n-block: Cols x {offset s8, shift u5, scale u8}
    output wire [CW-1:0]                          rq_addr_o,
    input  wire [Cols*21-1:0]                     rq_data_i,
    // calibration words, written once
    input  wire                                   cal_we_i,
    input  wire [CW-1:0]                          cal_addr_i,
    input  wire [15:0]                            cal_g_i,
    input  wire [19:0]                            cal_o_i,
    // tile interface
    output wire [NTiles*Rows-1:0]                 wl_o,
    output wire [Cols*8-1:0]                      wbl_o,
    output wire [NTiles*Rows*3-1:0]               drive_o,
    output wire                                   phi_drv_o,
    output wire                                   phi_rst_o,
    output wire                                   phi_sh_o,
    output wire                                   phi_mrg_o,
    output wire                                   phi_samp_o,
    output wire                                   sar_clk_o,
    input  wire [NTiles*(Cols/AdcShare)*Bits-1:0] codes_i,
    // results
    output wire                                   out_valid_o,
    output wire [CW-1:0]                          out_m_o,
    output wire [CW-1:0]                          out_nb_o,
    output wire [Cols*8-1:0]                      out_y_o,
    output wire [Cols*AccW-1:0]                   out_acc_o,
    output wire                                   done_o,
    output wire [31:0]                            stall_ticks_o,
    output wire [31:0]                            passes_o,
    output wire [31:0]                            refreshes_o
);
    localparam integer NSlots = (Mode == 0) ? 4 : 7;
    localparam integer DW     = 5 * CW + 3;            // {valid, gseq, nb, kg, mc, mi, first, last}

    // ---- descriptor generator (the element tile 0 runs next pass)
    reg            gvalid_q;
    reg [CW-1:0]   gnb_q, gmc_q, gkg_q, gmi_q, ggs_q;
    reg            started_q;
    reg [DW-1:0]   desc_q [0:NTiles-1];                 // element of each tile in this pass
    reg [Rows*8-1:0] xr_q [0:NTiles-1];
    reg [DW-1:0]   dcv_q [0:NTiles-1];                  // element each tile's sample belongs to
    reg [31:0]     stall_q, pass_q;

    wire [CW-1:0]  mrem   = cfg_m_i - gmc_q * AccDepth;
    wire [CW-1:0]  mlen   = (mrem > AccDepth) ? AccDepth : mrem;
    wire           g_lmi  = (gmi_q == mlen - 1'b1);
    wire           g_lkg  = (gkg_q == cfg_g_i - 1'b1);
    wire           g_lmc  = ((gmc_q + 1'b1) * AccDepth >= cfg_m_i);
    wire           g_lnb  = (gnb_q == cfg_nb_i - 1'b1);
    wire [DW-1:0]  gdesc  = {gvalid_q, ggs_q, gnb_q, gkg_q, gmc_q, gmi_q, (gkg_q == {CW{1'b0}}), g_lkg};

    wire pass_go, merge_start, cap, conv_done, stall, seq_done, row_en, wr_busy, ready, chain_busy, drv_cut;
    wire [3:0] slot, cap_round;

    integer i;
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            gvalid_q <= 1'b0; gnb_q <= {CW{1'b0}}; gmc_q <= {CW{1'b0}}; gkg_q <= {CW{1'b0}};
            gmi_q <= {CW{1'b0}}; ggs_q <= {CW{1'b0}}; started_q <= 1'b0;
            for (i = 0; i < NTiles; i = i + 1) begin
                desc_q[i] <= {DW{1'b0}}; xr_q[i] <= {Rows*8{1'b0}}; dcv_q[i] <= {DW{1'b0}};
            end
            stall_q <= 32'd0; pass_q <= 32'd0;
        end else begin
            if (start_i && !started_q) begin started_q <= 1'b1; gvalid_q <= 1'b1; end
            if (stall) stall_q <= stall_q + 32'd1;
            if (pass_go) begin
                pass_q <= pass_q + 32'd1;
                for (i = 0; i < NTiles; i = i + 1) begin
                    dcv_q[i]  <= desc_q[i];
                    desc_q[i] <= (i == 0) ? gdesc : desc_q[i-1];
                    xr_q[i]   <= x_data_i[i*Rows*8 +: Rows*8];
                end
                if (gvalid_q) begin
                    gmi_q <= gmi_q + 1'b1;
                    if (g_lmi) begin
                        gmi_q <= {CW{1'b0}};
                        ggs_q <= ggs_q + 1'b1;
                        gkg_q <= gkg_q + 1'b1;
                        if (g_lkg) begin
                            gkg_q <= {CW{1'b0}};
                            gmc_q <= gmc_q + 1'b1;
                            if (g_lmc) begin
                                gmc_q <= {CW{1'b0}};
                                gnb_q <= gnb_q + 1'b1;
                                if (g_lnb) gvalid_q <= 1'b0;
                            end
                        end
                    end
                end
            end
        end
    end

    // ---- row codes: a flop per pin, so they land on the same tick as the registered phases
    wire [NTiles*Rows*3-1:0] drive_d;
    reg  [NTiles*Rows*3-1:0] drive_q;
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) drive_q <= {NTiles*Rows*3{1'b0}};
        else         drive_q <= drive_d;
    end
    assign drive_o = drv_cut ? {NTiles*Rows*3{1'b0}} : drive_q;

    // ---- what each tile runs next pass: its weights (gseq) and its activation word
    wire [NTiles-1:0]    nxt_valid;
    wire [NTiles*CW-1:0] nxt_gseq;
    genvar t, r;
    generate
        for (t = 0; t < NTiles; t = t + 1) begin : g_nxt
            wire [DW-1:0]   nd = (t == 0) ? gdesc : desc_q[(t == 0) ? 0 : t - 1];
            wire [CW-1:0]   nkg = nd[2 + 2*CW +: CW];
            wire [CW-1:0]   nmc = nd[2 + CW +: CW];
            wire [CW-1:0]   nmi = nd[2 +: CW];
            assign nxt_valid[t]         = nd[DW-1];
            assign nxt_gseq[t*CW +: CW] = nd[2 + 4*CW +: CW];
            assign x_addr_o[t*2*CW +: 2*CW] = (nmc * AccDepth + nmi) * (cfg_g_i * NTiles) + nkg * NTiles + t;
        end
        // ---- row codes
        for (t = 0; t < NTiles; t = t + 1) begin : g_tile
            for (r = 0; r < Rows; r = r + 1) begin : g_row
                wire [7:0] x   = xr_q[t][r*8 +: 8];
                wire       sgn = x[7];
                wire [6:0] mag = sgn ? ((x == 8'h80) ? 7'd127 : 7'd0 - x[6:0]) : x[6:0];
                wire [7:0] v2  = {mag, 1'b0};
                wire [1:0] dig = (Mode == 0) ? (v2 >> (2 * slot)) : {1'b0, mag[slot]};
                wire       on  = row_en && desc_q[t][DW-1] && (dig != 2'd0);
                assign drive_d[(t*Rows + r)*3 +: 3] = on ? {sgn, dig} : 3'b000;
            end
        end
    endgenerate

    imc_seq #(.NSlots(NSlots), .SlotTicks(SlotTicks), .RstTicks(RstTicks), .ShTicks(ShTicks),
              .MergeTicks(MergeTicks), .RoundTicks(RoundTicks), .AdcShare(AdcShare),
              .DrainPass(NTiles + 1)) u_seq (
        .clk_i(clk_i), .rst_ni(rst_ni), .start_i(started_q), .more_i(gvalid_q), .ready_i(ready),
        .wr_busy_i(wr_busy), .row_en_o(row_en), .phi_drv_o(phi_drv_o), .drv_cut_o(drv_cut), .slot_o(slot), .phi_rst_o(phi_rst_o),
        .phi_sh_o(phi_sh_o), .phi_mrg_o(phi_mrg_o), .phi_samp_o(phi_samp_o), .sar_clk_o(sar_clk_o),
        .merge_start_o(merge_start), .pass_go_o(pass_go), .cap_o(cap), .cap_round_o(cap_round),
        .conv_done_o(conv_done), .conv_busy_o(), .stall_o(stall), .done_o(seq_done));

    imc_wstage #(.Rows(Rows), .Cols(Cols), .NTiles(NTiles), .CW(CW), .RefreshPasses(RefreshPasses)) u_wst (
        .clk_i(clk_i), .rst_ni(rst_ni), .w_valid_i(w_valid_i), .w_ready_o(w_ready_o),
        .w_data_i(w_data_i), .nxt_valid_i(nxt_valid), .nxt_gseq_i(nxt_gseq),
        .merge_start_i(merge_start), .ready_o(ready), .wr_busy_o(wr_busy), .refreshes_o(refreshes_o),
        .wl_o(wl_o), .wbl_o(wbl_o));

    wire [NTiles*DW-1:0] dcv_flat;
    generate
        for (t = 0; t < NTiles; t = t + 1) begin : g_dcv
            assign dcv_flat[t*DW +: DW] = dcv_q[t];
        end
    endgenerate

    imc_chain #(.Cols(Cols), .NTiles(NTiles), .AdcShare(AdcShare), .Bits(Bits), .CalF(CalF),
                .AccW(AccW), .CodeShift(CodeShift), .AccDepth(AccDepth), .CW(CW), .DW(DW)) u_chain (
        .clk_i(clk_i), .rst_ni(rst_ni), .cap_i(cap), .cap_round_i(cap_round), .codes_i(codes_i),
        .conv_done_i(conv_done), .desc_cv_i(dcv_flat), .cal_we_i(cal_we_i), .cal_addr_i(cal_addr_i),
        .cal_g_i(cal_g_i), .cal_o_i(cal_o_i), .rq_addr_o(rq_addr_o), .rq_data_i(rq_data_i),
        .out_valid_o(out_valid_o), .out_m_o(out_m_o), .out_nb_o(out_nb_o), .out_y_o(out_y_o),
        .out_acc_o(out_acc_o), .busy_o(chain_busy));

    assign done_o        = seq_done && !chain_busy;
    assign stall_ticks_o = stall_q;
    assign passes_o      = pass_q;
endmodule
