// rail_top: synthesis/integration wrapper — one column slice of the
// near-tile digital rail (nibble combine x2 slices -> slice combine ->
// b_acc accumulator) + the tile-level ABFT check and per-channel requant
// + the tile_fsm conversion controller. Exists so `make synth` has a
// single top that instantiates every rail module; the real tile replicates
// the datapath per column pair. Not a functional chip top.
module rail_top (
    input  wire         clk,
    input  wire         rst_n,
    // datapath: per-pass column codes (from readout, fabric side)
    input  wire signed [7:0]   lsb_lo, msb_lo,   // LSB/MSB nibble, low weight slice
    input  wire signed [7:0]   lsb_hi, msb_hi,   // LSB/MSB nibble, high weight slice
    input  wire         d_valid,
    input  wire         acc_clear,
    input  wire [3:0]   tile_cnt,
    output wire signed [19:0]  acc,
    output wire         acc_done,
    // ABFT (tile level: 16 column sums + checksum column sum)
    input  wire [16*20-1:0]    y_flat,
    input  wire signed [19:0]  y_chk,
    input  wire [15:0]  budget,
    output wire signed [24:0]  residual,
    output wire         abft_flag,
    // requant (per channel)
    input  wire [7:0]   rq_scale,
    input  wire [4:0]   rq_shift,
    input  wire signed [7:0]   rq_offset,
    output wire signed [7:0]   q,
    // tile_fsm fabric side
    input  wire         start_valid,
    output wire         start_ready,
    input  wire         relu_en,
    output wire [7:0]   col_code,
    output wire         col_valid,
    input  wire         col_ready,
    output wire [3:0]   evt_count_gray,
    // tile_fsm analog side
    output wire         integ_req,
    input  wire         integ_ack,
    input  wire         col_sign,
    output wire         coarse_en,
    input  wire         cb_req,
    input  wire         cb_cross,
    output wire         cb_ack,
    output wire         cmp_req,
    input  wire         cmp_ack,
    input  wire         cmp_result,
    output wire [3:0]   dac_code
);
    wire signed [11:0] p_lo, p_hi;
    wire signed [13:0] y14;

    nibble_combine u_nib_lo (.lsb_code(lsb_lo), .msb_code(msb_lo), .partial(p_lo));
    nibble_combine u_nib_hi (.lsb_code(lsb_hi), .msb_code(msb_hi), .partial(p_hi));
    slice_combine  u_slice  (.p_lo(p_lo), .p_hi(p_hi), .y(y14));

    bacc_accum #(.W(20)) u_acc (
        .clk(clk), .rst_n(rst_n), .clear(acc_clear),
        .d(y14), .d_valid(d_valid), .tile_cnt(tile_cnt),
        .acc(acc), .done(acc_done)
    );

    abft_check #(.W(20)) u_abft (
        .y_flat(y_flat), .y_chk(y_chk), .budget(budget),
        .residual(residual), .flag(abft_flag)
    );

    requant u_rq (
        .y(acc), .scale(rq_scale), .shift(rq_shift), .offset(rq_offset), .q(q)
    );

    tile_fsm u_fsm (
        .clk(clk), .rst_n(rst_n),
        .start_valid(start_valid), .start_ready(start_ready), .relu_en(relu_en),
        .col_code(col_code), .col_valid(col_valid), .col_ready(col_ready),
        .evt_count_gray(evt_count_gray),
        .integ_req(integ_req), .integ_ack(integ_ack), .col_sign(col_sign),
        .coarse_en(coarse_en),
        .cb_req(cb_req), .cb_cross(cb_cross), .cb_ack(cb_ack),
        .cmp_req(cmp_req), .cmp_ack(cmp_ack), .cmp_result(cmp_result),
        .dac_code(dac_code)
    );
endmodule
