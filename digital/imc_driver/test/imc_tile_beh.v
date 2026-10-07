// Ideal behavioural tile for the driver's unit test: the bit-true golden of scripts/golden/imc_tile.py
// with every analog error off. Same pins as the analog tile netlist (one instance per tile).
//   write:  WL falling edge latches WBL ({sign, |w|}) into row r
//   share:  phi_sh falling edge adds the slot's signed digit sum, weighted 4^s (ml2) or 2^s (bitserial)
//   sample: phi_samp falling edge freezes S (ml2 digits carry 2|x|, so S = acc / 2) and resets the slot
//   SAR:    round k (k-th sar_clk rise after the sample) outputs converter j's column j*AdcShare + k:
//           code = clip(floor((S + 2^(CodeShift-1)) / 2^CodeShift))
`timescale 1ns/1ps
module imc_tile_beh #(
    parameter integer Rows = 8, Cols = 8, AdcShare = 4, Bits = 12, Mode = 0, CodeShift = 6
) (
    input  wire [Rows-1:0]                  wl,
    input  wire [Cols*8-1:0]                wbl,
    input  wire [Rows*3-1:0]                drive,
    input  wire                             phi_rst,
    input  wire                             phi_sh,
    input  wire                             phi_mrg,
    input  wire                             phi_samp,
    input  wire                             sar_clk,
    output reg  [(Cols/AdcShare)*Bits-1:0]  codes
);
    localparam integer NConv = Cols / AdcShare;
    reg [7:0]   w [0:Rows*Cols-1];
    integer     acc [0:Cols-1];
    integer     smp [0:Cols-1];
    integer     slot, rnd, r, c, j, s, d, v, h;
    initial begin
        for (r = 0; r < Rows * Cols; r = r + 1) w[r] = 8'd0;
        for (c = 0; c < Cols; c = c + 1) begin acc[c] = 0; smp[c] = 0; end
        slot = 0; rnd = 0; codes = 0;
    end
    genvar g;
    generate
        for (g = 0; g < Rows; g = g + 1) begin : g_wr
            always @(negedge wl[g]) for (c = 0; c < Cols; c = c + 1) w[g*Cols + c] = wbl[c*8 +: 8];
        end
    endgenerate
    always @(negedge phi_sh) begin
        for (c = 0; c < Cols; c = c + 1) begin
            s = 0;
            for (r = 0; r < Rows; r = r + 1) begin
                d = drive[r*3 +: 2];
                v = w[r*Cols + c][6:0] * d;
                s = s + (((drive[r*3 + 2] ^ w[r*Cols + c][7]) != 0) ? -v : v);
            end
            acc[c] = acc[c] + s * ((Mode == 0) ? (1 << (2 * slot)) : (1 << slot));
        end
        slot = slot + 1;
    end
    always @(negedge phi_samp) begin
        for (c = 0; c < Cols; c = c + 1) begin
            smp[c] = (Mode == 0) ? acc[c] / 2 : acc[c];
            acc[c] = 0;
        end
        slot = 0; rnd = 0;
    end
    always @(posedge sar_clk) begin
        h = 1 << (Bits - 1);
        for (j = 0; j < NConv; j = j + 1) begin
            v = smp[j*AdcShare + rnd] + (1 << (CodeShift - 1));
            v = (v >= 0) ? (v >> CodeShift) : -((-v + (1 << CodeShift) - 1) >> CodeShift);
            if (v > h - 1) v = h - 1;
            if (v < -h) v = -h;
            codes[j*Bits +: Bits] = v;
        end
        rnd = rnd + 1;
    end
endmodule
