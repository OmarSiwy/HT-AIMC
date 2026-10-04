// event_ctrl: event-rate coarse-loop controller. The analog charge-balance
// comparator makes one decision per t_q window and presents it over an
// async 4-phase handshake:
//   analog raises cb_req with cb_cross valid (stable from before cb_req
//   rises until after cb_ack rises);
//   cb_cross=1: threshold crossed -> count++, cb_ack rising edge tells the
//               analog to fire one reference-charge packet;
//   cb_cross=0: no crossing -> EARLY TERMINATION: done, coarse phase over
//               (cb_ack still completes the handshake, no packet).
// Count saturates at 15 (4b); a crossing at count 15 still acks/fires but
// terminates the coarse phase. done is a level, cleared on next start.
// count_gray is a registered Gray-coded copy of count (successive values
// differ in one bit) for safe sampling from the fabric clock domain.
module event_ctrl (
    input  wire       clk,
    input  wire       rst_n,       // async active-low reset
    input  wire       start,       // 1-cycle pulse
    output reg        done,        // level until next start
    output reg  [3:0] count,       // binary event (packet) count
    output reg  [3:0] count_gray,  // Gray-coded count for fabric CDC
    // async charge-balance interface
    input  wire       cb_req,      // async: decision ready
    input  wire       cb_cross,    // decision value, stable while cb_req high
    output reg        cb_ack       // rising edge = fire packet (if cross)
);
    // 2FF synchronizers (equal depth so cross aligns with req)
    reg req_m, req_s, cross_m, cross_s;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            req_m <= 1'b0; req_s <= 1'b0; cross_m <= 1'b0; cross_s <= 1'b0;
        end else begin
            req_m <= cb_req;   req_s <= req_m;
            cross_m <= cb_cross; cross_s <= cross_m;
        end
    end

    localparam [1:0] S_IDLE  = 2'd0,
                     S_WAITH = 2'd1,   // wait req_s high, decide
                     S_WAITL = 2'd2;   // wait req_s low, drop ack
    reg [1:0] state;
    reg       ending;                  // this handshake terminates the phase

    wire [3:0] cnt_nxt = count + 4'd1;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state      <= S_IDLE;
            done       <= 1'b0;
            count      <= 4'd0;
            count_gray <= 4'd0;
            cb_ack     <= 1'b0;
            ending     <= 1'b0;
        end else begin
            case (state)
                S_IDLE: if (start) begin
                    count      <= 4'd0;
                    count_gray <= 4'd0;
                    done       <= 1'b0;
                    ending     <= 1'b0;
                    state      <= S_WAITH;
                end
                S_WAITH: if (req_s) begin
                    if (cross_s) begin
                        if (count != 4'd15) begin
                            count      <= cnt_nxt;
                            count_gray <= cnt_nxt ^ (cnt_nxt >> 1);
                            ending     <= (cnt_nxt == 4'd15);  // range exhausted
                        end else
                            ending <= 1'b1;
                    end else
                        ending <= 1'b1;                        // early termination
                    cb_ack <= 1'b1;
                    state  <= S_WAITL;
                end
                S_WAITL: if (!req_s) begin
                    cb_ack <= 1'b0;
                    if (ending) begin
                        done  <= 1'b1;
                        state <= S_IDLE;
                    end else
                        state <= S_WAITH;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
