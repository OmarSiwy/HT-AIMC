// sar_ctrl: 4b successive-approximation controller for the fine (residue)
// conversion. Self-timed 4-phase req/ack handshake toward the async
// StrongARM comparator; synchronous FSM on clk with 2FF synchronizers on
// cmp_ack and cmp_result (result is quasi-static: the analog must hold
// cmp_result stable from before cmp_ack rises until after cmp_req falls,
// so the synchronized sample is glitch-free).
//
// Per trial bit i = 3..0:
//   1. dac_code = code | (1<<i)   (trial; stable >= 1 clk before req)
//   2. cmp_req = 1; wait cmp_ack (synced)
//   3. sample cmp_result: 1 => residue >= DAC trial => keep the bit
//   4. cmp_req = 0; wait !cmp_ack (synced); next bit
// After bit 0: done (level, cleared on next start), code holds the result,
// dac_code parks on the final code.
module sar_ctrl (
    input  wire       clk,
    input  wire       rst_n,       // async active-low reset
    input  wire       start,       // 1-cycle pulse
    output reg        busy,
    output reg        done,        // level until next start
    output reg  [3:0] code,        // conversion result
    // async comparator interface
    output reg        cmp_req,
    input  wire       cmp_ack,     // async
    input  wire       cmp_result,  // stable while cmp_ack high
    output reg  [3:0] dac_code     // cap-DAC trial code
);
    // 2FF synchronizers (equal depth so result aligns with ack)
    reg ack_m, ack_s, res_m, res_s;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ack_m <= 1'b0; ack_s <= 1'b0;
            res_m <= 1'b0; res_s <= 1'b0;
        end else begin
            ack_m <= cmp_ack;    ack_s <= ack_m;
            res_m <= cmp_result; res_s <= res_m;
        end
    end

    localparam [2:0] S_IDLE  = 3'd0,
                     S_TRIAL = 3'd1,
                     S_REQ   = 3'd2,
                     S_FALL  = 3'd3;
    reg [2:0] state;
    reg [1:0] bit_i;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= S_IDLE;
            busy     <= 1'b0;
            done     <= 1'b0;
            code     <= 4'd0;
            dac_code <= 4'd0;
            cmp_req  <= 1'b0;
            bit_i    <= 2'd3;
        end else begin
            case (state)
                S_IDLE: if (start) begin
                    code  <= 4'd0;
                    bit_i <= 2'd3;
                    busy  <= 1'b1;
                    done  <= 1'b0;
                    state <= S_TRIAL;
                end
                S_TRIAL: begin
                    dac_code <= code | (4'b0001 << bit_i);
                    state    <= S_REQ;
                end
                S_REQ: begin
                    cmp_req <= 1'b1;
                    if (ack_s && cmp_req) begin       // require our own req seen
                        if (res_s) code <= code | (4'b0001 << bit_i);
                        cmp_req <= 1'b0;
                        state   <= S_FALL;
                    end
                end
                S_FALL: if (!ack_s) begin
                    if (bit_i == 2'd0) begin
                        dac_code <= code;  // park DAC on final code (committed in S_REQ)
                        busy     <= 1'b0;
                        done     <= 1'b1;
                        state    <= S_IDLE;
                    end else begin
                        bit_i <= bit_i - 2'd1;
                        state <= S_TRIAL;
                    end
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
