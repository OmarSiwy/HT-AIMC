// tile_fsm: per-column top controller. Sequences the conversion phases
//   INTEGRATE -> (sign-early-exit?) -> CONVERT_COARSE (event-rate loop)
//   -> CONVERT_FINE (4b SAR on residue) -> READOUT
// GALS boundary: everything toward the analog domain is async 4-phase
// req/ack passed through 2FF synchronizers (integ_* here; cb_*/cmp_* inside
// event_ctrl/sar_ctrl, which this module instantiates together with
// sign_exit). Toward the fabric everything is synchronous ready/valid on
// clk. The live event count is exported Gray-coded (evt_count_gray, at most
// one bit changes per event) so a different fabric clock domain may 2FF-
// sample it directly; col_code is quasi-static while col_valid is high.
//
// Column code assembly (coarse LSB = 16 fine LSBs, SAR carry implements
// the redundancy overlap):
//   mag      = 16*evt_count + sar_code          (0..255)
//   col_code = clamp(sign ? -mag : +mag, -127..+127), or 0 on early exit.
module tile_fsm (
    input  wire       clk,
    input  wire       rst_n,           // async active-low reset
    // fabric side (synchronous, ready/valid)
    input  wire       start_valid,     // request one column conversion
    output wire       start_ready,     // high in IDLE
    input  wire       relu_en,         // sign-early-exit enable, sampled at start
    output reg  [7:0] col_code,        // signed two's-complement column code
    output reg        col_valid,       // code valid; held until col_ready
    input  wire       col_ready,
    output wire [3:0] evt_count_gray,  // live Gray event count (fabric CDC safe)
    // analog side: integrate phase handshake (async 4-phase)
    output reg        integ_req,       // start PWM apply + integration window
    input  wire       integ_ack,       // async: integration window complete
    input  wire       col_sign,        // 1 = column negative; stable from before
                                       // integ_ack rises until end of conversion
    // analog side: charge-balance coarse loop (via event_ctrl)
    output wire       coarse_en,       // phase enable: analog may issue cb_req
                                       // decisions ONLY while high (on ReLU
                                       // early exit it never rises)
    input  wire       cb_req,
    input  wire       cb_cross,
    output wire       cb_ack,
    // analog side: SAR comparator (via sar_ctrl)
    output wire       cmp_req,
    input  wire       cmp_ack,
    input  wire       cmp_result,
    output wire [3:0] dac_code,
    // OTA bias gate (item S4 power hook): high while this column's
    // integrator amplifier must be awake — integrate/settle/decide and
    // the coarse loop UNTIL the event controller's early-termination
    // done. During S_FINE the analog wrapper ORs its own acq strobe
    // (CDAC sampling windows) into the bias gate; between acqs the
    // residue is held on the floating integrator node.
    output wire       ota_en
);
    // 2FF synchronizers for integrate handshake (sign aligned with ack)
    reg iack_m, iack_s, sign_m, sign_s;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            iack_m <= 1'b0; iack_s <= 1'b0; sign_m <= 1'b0; sign_s <= 1'b0;
        end else begin
            iack_m <= integ_ack; iack_s <= iack_m;
            sign_m <= col_sign;  sign_s <= sign_m;
        end
    end

    // sub-controllers
    reg        ev_start, sar_start;
    wire       ev_done;
    wire [3:0] ev_count;
    wire       sar_done;
    wire [3:0] sar_code;

    event_ctrl u_event (
        .clk(clk), .rst_n(rst_n), .start(ev_start),
        .done(ev_done), .count(ev_count), .count_gray(evt_count_gray),
        .cb_req(cb_req), .cb_cross(cb_cross), .cb_ack(cb_ack)
    );

    sar_ctrl u_sar (
        .clk(clk), .rst_n(rst_n), .start(sar_start),
        .busy(), .done(sar_done), .code(sar_code),
        .cmp_req(cmp_req), .cmp_ack(cmp_ack), .cmp_result(cmp_result),
        .dac_code(dac_code)
    );

    reg relu_r, sign_r, sign_seen;
    wire se_exit;
    sign_exit u_se (
        .relu_en(relu_r), .sign_neg(sign_r), .sign_valid(sign_seen),
        .exit(se_exit), .force_zero()
    );

    localparam [2:0] S_IDLE     = 3'd0,
                     S_INTEG    = 3'd1,
                     S_INTFALL  = 3'd2,
                     S_DECIDE   = 3'd3,
                     S_COARSE   = 3'd4,
                     S_FINE     = 3'd5,
                     S_ASSEMBLE = 3'd6,
                     S_READOUT  = 3'd7;
    reg [2:0] state;

    assign start_ready = (state == S_IDLE);
    // analog decision-issue window; registered state => glitch-free level.
    // event_ctrl arms 1 cycle after S_COARSE entry, but cb_req reaches it
    // through 2FF sync (>= 2 cycles), so no decision can be lost.
    assign coarse_en   = (state == S_COARSE);
    assign ota_en      = (state == S_INTEG) || (state == S_INTFALL) ||
                         (state == S_DECIDE) ||
                         ((state == S_COARSE) && !ev_done);

    // magnitude assembly (used in S_ASSEMBLE)
    wire [7:0] mag     = {ev_count, 4'b0000} + {4'b0000, sar_code};
    wire [6:0] mag_sat = (mag > 8'd127) ? 7'd127 : mag[6:0];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= S_IDLE;
            integ_req <= 1'b0;
            col_code  <= 8'd0;
            col_valid <= 1'b0;
            ev_start  <= 1'b0;
            sar_start <= 1'b0;
            relu_r    <= 1'b0;
            sign_r    <= 1'b0;
            sign_seen <= 1'b0;
        end else begin
            ev_start  <= 1'b0;  // default: single-cycle pulses
            sar_start <= 1'b0;
            case (state)
                S_IDLE: if (start_valid) begin
                    relu_r    <= relu_en;
                    sign_seen <= 1'b0;
                    integ_req <= 1'b1;
                    state     <= S_INTEG;
                end
                S_INTEG: if (iack_s) begin
                    sign_r    <= sign_s;
                    sign_seen <= 1'b1;
                    integ_req <= 1'b0;
                    state     <= S_INTFALL;
                end
                S_INTFALL: if (!iack_s)
                    state <= S_DECIDE;
                S_DECIDE: begin
                    if (se_exit) begin
                        col_code  <= 8'd0;      // ReLU-bound negative -> 0
                        col_valid <= 1'b1;
                        state     <= S_READOUT;
                    end else begin
                        ev_start <= 1'b1;
                        state    <= S_COARSE;
                    end
                end
                S_COARSE: if (ev_done && !ev_start) begin
                    sar_start <= 1'b1;
                    state     <= S_FINE;
                end
                S_FINE: if (sar_done && !sar_start)
                    state <= S_ASSEMBLE;
                S_ASSEMBLE: begin
                    col_code  <= sign_r ? (~{1'b0, mag_sat} + 8'd1)
                                        : {1'b0, mag_sat};
                    col_valid <= 1'b1;
                    state     <= S_READOUT;
                end
                S_READOUT: if (col_ready) begin
                    col_valid <= 1'b0;
                    state     <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
