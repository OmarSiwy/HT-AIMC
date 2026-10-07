// SAR code capture, per-column affine calibration (B6), the 24-b accumulator chain across the
// K-adjacent tiles (B10, T2) and the chain-end requant (B6').
//
// Chain alignment: tile t converts element e at pass e + t + 1, so at each conversion-done the
// value tile t-1 left in its psum register is the same element tile t just converted:
//     psum[t] <= psum[t-1] + cal_t(code_t)        (psum[-1] = 0, chain head)
// Elements whose K spans more groups than the chain has tiles are summed at the chain end in the
// edge buffer (one entry per token of the m-chunk); the last group requantizes and emits the row.
//
//   cal:     c = (g * code + o + 2^(CalF-1)) >>> CalF        g unsigned 16 b, o signed 20 b
//   requant: y8 = sat8(((acc <<< CodeShift) * scale + half) >>> shift + offset)
//            (golden.model.requant_int8 on the MAC-domain sum; scale u8, shift 0..24, offset s8)
`timescale 1ns/1ps
module imc_chain #(
    parameter integer Cols     = 8,
    parameter integer NTiles   = 2,
    parameter integer AdcShare = 4,
    parameter integer Bits     = 12,
    parameter integer CalF     = 14,
    parameter integer AccW     = 24,
    parameter integer CodeShift = 6,
    parameter integer AccDepth = 16,
    parameter integer CW       = 16,
    parameter integer DW       = 5 * 16 + 3      // descriptor width, see imc_driver
) (
    input  wire                                    clk_i,
    input  wire                                    rst_ni,
    input  wire                                    cap_i,
    input  wire [3:0]                              cap_round_i,
    input  wire [NTiles*(Cols/AdcShare)*Bits-1:0]  codes_i,
    input  wire                                    conv_done_i,
    input  wire [NTiles*DW-1:0]                    desc_cv_i,   // element each tile's sample holds
    input  wire                                    cal_we_i,
    input  wire [CW-1:0]                           cal_addr_i,  // tile * Cols + column
    input  wire [15:0]                             cal_g_i,
    input  wire [19:0]                             cal_o_i,
    output wire [CW-1:0]                           rq_addr_o,
    input  wire [Cols*21-1:0]                      rq_data_i,
    output wire                                    out_valid_o,
    output wire [CW-1:0]                           out_m_o,
    output wire [CW-1:0]                           out_nb_o,
    output wire [Cols*8-1:0]                       out_y_o,
    output wire [Cols*AccW-1:0]                    out_acc_o,
    output wire                                    busy_o
);
    localparam integer NConv = Cols / AdcShare;
    localparam integer DmW   = (AccDepth > 1) ? $clog2(AccDepth) : 1;

    // descriptor fields (imc_driver packs {valid, gseq, nb, kg, mc, mi, first, last})
    function        d_valid; input [DW-1:0] d; d_valid = d[DW-1]; endfunction
    function [CW-1:0] d_nb;  input [DW-1:0] d; d_nb  = d[2 + 3*CW +: CW]; endfunction
    function [CW-1:0] d_mc;  input [DW-1:0] d; d_mc  = d[2 + CW +: CW]; endfunction
    function [CW-1:0] d_mi;  input [DW-1:0] d; d_mi  = d[2 +: CW]; endfunction
    function        d_first; input [DW-1:0] d; d_first = d[1]; endfunction
    function        d_last;  input [DW-1:0] d; d_last  = d[0]; endfunction

    reg signed [Bits-1:0] code_q [0:NTiles*Cols-1];
    reg [15:0]            calg_q [0:NTiles*Cols-1];
    reg signed [19:0]     calo_q [0:NTiles*Cols-1];
    reg signed [AccW-1:0] psum_q [0:NTiles*Cols-1];
    reg [DW-1:0]          pdesc_q [0:NTiles-1];
    reg [NTiles*DW-1:0]   dsc_q;                      // descriptors of the conversion in flight
    reg signed [AccW-1:0] edge_q [0:AccDepth*Cols-1];
    reg                   estep_q;                    // chain end holds a valid element
    reg                   ovalid_q;
    reg [CW-1:0]          om_q, onb_q;
    reg [Cols*AccW-1:0]   oacc_q;
    reg [Cols*8-1:0]      oy_q;

    // calibrated codes, chain sums and the edge sum (combinational)
    wire signed [AccW-1:0] calv [0:NTiles*Cols-1];
    wire signed [AccW-1:0] esum [0:Cols-1];
    wire [DW-1:0]          eend = pdesc_q[NTiles-1];
    wire [DmW-1:0]         emi  = d_mi(eend);
    genvar t, c;
    generate
        for (t = 0; t < NTiles * Cols; t = t + 1) begin : g_cal
            wire signed [Bits+17:0] prod = code_q[t] * $signed({1'b0, calg_q[t]});
            wire signed [Bits+18:0] sum  = prod + calo_q[t] + (1 <<< (CalF - 1));
            wire signed [Bits+18:0] shr  = sum >>> CalF;
            assign calv[t] = shr[AccW-1:0];
        end
        for (c = 0; c < Cols; c = c + 1) begin : g_edge
            assign esum[c] = (d_first(eend) ? {AccW{1'b0}} : edge_q[emi * Cols + c]) + psum_q[(NTiles-1)*Cols + c];
        end
    endgenerate

    integer i, j, r;
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            for (i = 0; i < NTiles * Cols; i = i + 1) begin
                code_q[i] <= {Bits{1'b0}}; calg_q[i] <= 16'd1 << CalF; calo_q[i] <= 20'sd0;
                psum_q[i] <= {AccW{1'b0}};
            end
            for (i = 0; i < NTiles; i = i + 1) pdesc_q[i] <= {DW{1'b0}};
            dsc_q <= {NTiles*DW{1'b0}};
            estep_q <= 1'b0; ovalid_q <= 1'b0;
            om_q <= {CW{1'b0}}; onb_q <= {CW{1'b0}}; oacc_q <= {Cols*AccW{1'b0}}; oy_q <= {Cols*8{1'b0}};
        end else begin
            if (cal_we_i) begin
                calg_q[cal_addr_i] <= cal_g_i;
                calo_q[cal_addr_i] <= cal_o_i;
            end
            // capture: converter j of tile t, round r -> column j*AdcShare + r
            // the next sample may overwrite desc_cv before this conversion is done: hold it from round 0
            if (cap_i && cap_round_i == 4'd0) dsc_q <= desc_cv_i;
            if (cap_i)
                for (i = 0; i < NTiles; i = i + 1)
                    for (j = 0; j < NConv; j = j + 1)
                        code_q[i * Cols + j * AdcShare + cap_round_i] <= codes_i[(i * NConv + j) * Bits +: Bits];
            // chain step, once per pass
            estep_q <= 1'b0;
            if (conv_done_i) begin
                for (i = 0; i < NTiles; i = i + 1) begin
                    pdesc_q[i] <= d_valid(dsc_q[i*DW +: DW]) ? dsc_q[i*DW +: DW] : {DW{1'b0}};
                    for (j = 0; j < Cols; j = j + 1)
                        psum_q[i * Cols + j] <= ((i == 0) ? {AccW{1'b0}} : psum_q[(i - 1) * Cols + j]) + calv[i * Cols + j];
                end
                estep_q <= 1'b1;
            end
            // chain end: edge accumulate, emit on the last K-group
            ovalid_q <= 1'b0;
            if (estep_q && d_valid(eend)) begin
                for (j = 0; j < Cols; j = j + 1) begin
                    edge_q[emi * Cols + j] <= esum[j];
                    oacc_q[j*AccW +: AccW] <= esum[j];
                end
                if (d_last(eend)) begin
                    ovalid_q <= 1'b1;
                    om_q  <= d_mc(eend) * AccDepth + d_mi(eend);
                    onb_q <= d_nb(eend);
                    for (j = 0; j < Cols; j = j + 1) oy_q[j*8 +: 8] <= requant8(esum[j], rq_data_i[j*21 +: 21]);
                end
            end
        end
    end

    // y8 = sat8(((a << CodeShift) * scale + half) >>> shift + offset); rq = {offset, shift, scale}
    function [7:0] requant8;
        input signed [AccW-1:0] a;
        input [20:0]            rq;
        reg signed [AccW+CodeShift+9:0] p;
        reg signed [AccW+CodeShift+9:0] v;
        reg [4:0]                       sh;
        begin
            sh = rq[12:8];
            p  = ($signed({{(CodeShift+10){a[AccW-1]}}, a}) <<< CodeShift) * $signed({1'b0, rq[7:0]});
            if (sh != 5'd0) p = p + ($signed({{(AccW+CodeShift+9){1'b0}}, 1'b1}) <<< (sh - 1));
            v  = (p >>> sh) + $signed(rq[20:13]);
            requant8 = (v > 127) ? 8'sd127 : (v < -128) ? 8'h80 : v[7:0];
        end
    endfunction

    assign rq_addr_o   = d_nb(eend);
    assign out_valid_o = ovalid_q;
    assign out_m_o     = om_q;
    assign out_nb_o    = onb_q;
    assign out_y_o     = oy_q;
    assign out_acc_o   = oacc_q;
    assign busy_o      = estep_q || ovalid_q;
endmodule
