// Weight staging (double-buffered, per tile) and the gain-cell array writer (B1 write port).
//
// The HBM stream delivers row words in use order: for each weight group g (one (n-block, m-chunk,
// k-group) of the schedule), tile 0 rows 0..Rows-1, tile 1 rows ..., so the loader fills
// bank g%2 of every tile. A bank stays full while its group is in the array (the refresh source)
// and is released when the next group is written, so the loader runs one group ahead.
// Refresh (B1 retention): a tile whose group has been in the array for RefreshPasses passes is
// rewritten from its bank in the next merge slot, the same write as a just-in-time load. Default
// 128 passes = 0.76 us at 5.94 ns, inside the 1.32 us 6-sigma retention (ARCH B1, P) and the
// 2.08 us nominal design retention (N3_r2, M).
// At the end of pass p (merge_start, every pass) the writer latches which tiles need their array
// rewritten for pass p+1; if any, the sequencer opens its write window (StWrite) and the writer copies
// those banks into the array, one row per tick, tile after tile, on the shared bit lines (WBL). The
// rails are at 0 V during the window, so moving a unit between rail and ground moves no charge.
//
// Bit-line format per column: [7] sign, [6:0] |w|, -128 written as -127 (sign-magnitude cell).
// WL is high for the first half of its tick (negedge pulse shaper) so WBL is stable at WL fall.
`timescale 1ns/1ps
module imc_wstage #(
    parameter integer Rows   = 8,
    parameter integer Cols   = 8,
    parameter integer NTiles = 2,
    parameter integer CW     = 16,
    parameter integer RefreshPasses = 128
) (
    input  wire                   clk_i,
    input  wire                   rst_ni,
    // HBM stream
    input  wire                   w_valid_i,
    output wire                   w_ready_o,
    input  wire [Cols*8-1:0]      w_data_i,
    // what the next pass needs, per tile
    input  wire [NTiles-1:0]      nxt_valid_i,
    input  wire [NTiles*CW-1:0]   nxt_gseq_i,
    input  wire                   merge_start_i,
    output wire                   ready_o,       // every needed bank is staged
    output wire                   wr_need_o,     // the next pass needs array writes (new group or refresh)
    output wire                   wr_busy_o,
    output wire [31:0]            refreshes_o,   // refresh rewrites (tile-groups), for the testbench
    // array write port
    output wire [NTiles*Rows-1:0] wl_o,
    output wire [Cols*8-1:0]      wbl_o
);
    localparam integer TW = (NTiles > 1) ? $clog2(NTiles) : 1;
    localparam integer RW = (Rows > 1) ? $clog2(Rows) : 1;

    reg [Cols*8-1:0] mem [0:NTiles*2*Rows-1];   // [tile][bank][row]
    reg [NTiles-1:0] full0_q, full1_q;           // bank holds a complete group
    reg [CW-1:0]     bgseq_q [0:NTiles*2-1];     // group held by each bank
    reg [CW:0]       agseq_q [0:NTiles-1];       // group in the array (CW+1 b: -1 = none)
    reg [15:0]       age_q   [0:NTiles-1];       // passes since the array rows were last written
    reg [31:0]       nref_q;
    // loader
    reg [CW-1:0]     fg_q;
    reg [TW-1:0]     ft_q;
    reg [RW-1:0]     fr_q;
    // writer
    reg [NTiles-1:0] wmask_q;
    reg [RW-1:0]     wr_q;
    reg              wl_q;
    reg [NTiles*Rows-1:0] wlh_q, wln_q;     // one-hot WL, posedge copy and negedge copy
    reg [TW-1:0]     wt_q;
    reg [Cols*8-1:0] wbl_q;

    wire             fbank = fg_q[0];
    wire             fbusy = fbank ? full1_q[ft_q] : full0_q[ft_q];
    wire             accept = w_valid_i && !fbusy;

    // need / ready per tile
    wire [NTiles-1:0] need, staged, refr;
    genvar t;
    generate
        for (t = 0; t < NTiles; t = t + 1) begin : g_need
            wire [CW-1:0] g = nxt_gseq_i[t*CW +: CW];
            assign need[t]   = nxt_valid_i[t] && (agseq_q[t] != {1'b0, g});
            assign refr[t]   = nxt_valid_i[t] && !need[t] && (age_q[t] >= RefreshPasses - 1);
            assign staged[t] = (g[0] ? full1_q[t] : full0_q[t]) && (bgseq_q[2*t + g[0]] == g);
        end
    endgenerate
    assign ready_o   = &(~need | staged);
    assign wr_need_o = |(need | refr);
    assign w_ready_o = !fbusy;

    function [31:0] cnt1(input [NTiles-1:0] v);
        integer b;
        begin cnt1 = 0; for (b = 0; b < NTiles; b = b + 1) cnt1 = cnt1 + v[b]; end
    endfunction

    // lowest set bit of the remaining write mask
    reg [TW-1:0] wsel;
    integer k;
    always @* begin
        wsel = {TW{1'b0}};
        for (k = NTiles - 1; k >= 0; k = k - 1)
            if (wmask_q[k]) wsel = k;
    end
    wire [CW-1:0] wg = nxt_gseq_i[wsel*CW +: CW];

    integer i;
    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            full0_q <= {NTiles{1'b0}}; full1_q <= {NTiles{1'b0}};
            for (i = 0; i < NTiles; i = i + 1) begin agseq_q[i] <= {(CW+1){1'b1}}; age_q[i] <= 16'd0; end
            nref_q <= 32'd0;
            for (i = 0; i < 2 * NTiles; i = i + 1) bgseq_q[i] <= {CW{1'b0}};
            fg_q <= {CW{1'b0}}; ft_q <= {TW{1'b0}}; fr_q <= {RW{1'b0}};
            wmask_q <= {NTiles{1'b0}}; wr_q <= {RW{1'b0}}; wl_q <= 1'b0; wlh_q <= {NTiles*Rows{1'b0}}; wt_q <= {TW{1'b0}};
            wbl_q <= {Cols*8{1'b0}};
        end else begin
            // loader: one row per accepted beat
            if (accept) begin
                mem[(ft_q * 2 + fbank) * Rows + fr_q] <= w_data_i;
                fr_q <= fr_q + 1'b1;
                if (fr_q == Rows - 1) begin
                    fr_q <= {RW{1'b0}};
                    if (fbank) full1_q[ft_q] <= 1'b1; else full0_q[ft_q] <= 1'b1;
                    bgseq_q[ft_q * 2 + fbank] <= fg_q;
                    ft_q <= ft_q + 1'b1;
                    if (ft_q == NTiles - 1) begin ft_q <= {TW{1'b0}}; fg_q <= fg_q + 1'b1; end
                end
            end
            // writer: one row per tick, tiles in index order
            wl_q  <= 1'b0;
            wlh_q <= {NTiles*Rows{1'b0}};
            if (merge_start_i) begin
                wmask_q <= need | refr;
                wr_q    <= {RW{1'b0}};
                for (i = 0; i < NTiles; i = i + 1) if (!need[i] && !refr[i] && age_q[i] != 16'hFFFF) age_q[i] <= age_q[i] + 16'd1;
                nref_q  <= nref_q + cnt1(refr);
            end else if (wmask_q != {NTiles{1'b0}}) begin
                wl_q  <= 1'b1;
                wlh_q <= {{(NTiles*Rows-1){1'b0}}, 1'b1} << (wsel * Rows + wr_q);
                wt_q  <= wsel;
                wbl_q <= mem[(wsel * 2 + wg[0]) * Rows + wr_q];
                wr_q  <= wr_q + 1'b1;
                if (wr_q == Rows - 1) begin
                    wr_q <= {RW{1'b0}};
                    wmask_q[wsel] <= 1'b0;
                    agseq_q[wsel] <= {1'b0, wg};
                    age_q[wsel]   <= 16'd0;
                    // a new group releases the bank of the group it replaces (a refresh keeps it)
                    if (agseq_q[wsel] != {1'b0, wg} && !agseq_q[wsel][CW]) begin
                        if (agseq_q[wsel][0]) full1_q[wsel] <= 1'b0; else full0_q[wsel] <= 1'b0;
                    end
                end
            end
        end
    end
    // WL pulse shaper: the negedge copy ends each one-hot pulse half a tick in (glitch-free per bit)
    always @(negedge clk_i or negedge rst_ni) begin
        if (!rst_ni) wln_q <= {NTiles*Rows{1'b0}};
        else         wln_q <= wlh_q;
    end

    assign wr_busy_o = (wmask_q != {NTiles{1'b0}}) || wl_q;
    assign refreshes_o = nref_q;
    generate
        for (t = 0; t < NTiles * Rows; t = t + 1) begin : g_wl
            assign wl_o[t] = wlh_q[t] && !wln_q[t];
        end
        for (t = 0; t < Cols; t = t + 1) begin : g_wbl
            wire [7:0] w = wbl_q[t*8 +: 8];
            wire [6:0] m = w[7] ? ((w == 8'h80) ? 7'd127 : 7'd0 - w[6:0]) : w[6:0];
            assign wbl_o[t*8 +: 8] = {w[7], m};
        end
    endgenerate
endmodule
