// bacc_accum: signed partial-sum accumulator across weight tiles.
// Width per contract: b_acc = 8 + 7 + s(S-1) + ceil(log2 T)
//                           = B_y + (b_x-1) + slice growth + tile growth.
// AnalogIOC-mini: B_y=8, b_x=8, s=2, S=2, T<=8  ->  W = 20 (instantiate 20b).
// Accumulates one 14b signed slice-combined partial per d_valid, for
// tile_cnt partials (tile-count T port, 1..15; W=20 is exact for T<=8).
// done goes high (level) after tile_cnt valids and further inputs are
// ignored until clear. Adds saturate at +/-2^(W-1) instead of wrapping
// (unreachable in-spec: 15 * 8192 = 122880 < 2^19).
module bacc_accum #(
    parameter W = 20
) (
    input  wire               clk,
    input  wire               rst_n,     // async active-low reset
    input  wire               clear,     // sync clear: restart accumulation
    input  wire signed [13:0] d,         // slice-combined partial
    input  wire               d_valid,
    input  wire        [3:0]  tile_cnt,  // number of partials to accumulate (>=1)
    output reg  signed [W-1:0] acc,
    output reg                done
);
    localparam signed [W:0] MAXV = {2'b00, {(W-1){1'b1}}};  //  2^(W-1)-1
    localparam signed [W:0] MINV = -MAXV - 1;               // -2^(W-1)

    reg [3:0] cnt;
    wire signed [W:0] nxt = acc + d;  // both sign-extended to W+1: exact

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc  <= {W{1'b0}};
            cnt  <= 4'd0;
            done <= 1'b0;
        end else if (clear) begin
            acc  <= {W{1'b0}};
            cnt  <= 4'd0;
            done <= 1'b0;
        end else if (d_valid && !done) begin
            acc  <= (nxt > MAXV) ? MAXV[W-1:0] :
                    (nxt < MINV) ? MINV[W-1:0] : nxt[W-1:0];
            cnt  <= cnt + 4'd1;
            done <= ((cnt + 4'd1) == tile_cnt);
        end
    end
endmodule
