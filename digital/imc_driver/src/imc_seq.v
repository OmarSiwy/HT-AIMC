// Pass sequencer and phase generator for the IMC tile array (ARCH_CHOSEN.md §2-3, BS6H drive).
//
// One pass = DRIVE (NSlots slots of SlotTicks) on accumulator bank `bank`. At the end of the drive the
// bank is handed to the merge engine, and the next pass's drive starts at once on the other bank:
// the slice merge (phi_mrg) and the sample (phi_samp) of pass p run under the first slots of pass
// p+1 (DRIVE_ALT BS6H, ping-pong banks). The array-write window (StWrite) only opens on passes whose
// weights change or are refreshed. The SAR converts a sample in AdcShare rounds of RoundTicks on its
// own counter; the engine holds a merged bank until the converter is free, and the FSM waits
// (StWait) only when the previous bank has not been sampled yet, so
//     t_pass = max(drive word, conversion)
// falls out of the two handshakes. A pass that needs weights that are not staged yet stalls
// (StStall) and counts the ticks.
//
// Written in Verilog-2001 (not SystemVerilog): the same file runs inside ESPice as a VerA .v device,
// whose event engine is IEEE 1364 only. Flops keep the _d/_q discipline.
// Ticks come from the DLL replica timebase (t_slot / 6 for BS6H); every phase edge is a tick edge.
`timescale 1ns/1ps
module imc_seq #(
    parameter integer NSlots     = 7,     // bitserial: 7 planes; ml2 (replaced): 4
    parameter integer SlotTicks  = 6,
    parameter integer RstTicks   = 1,
    parameter integer ShTicks    = 3,
    parameter integer MrgTicks   = 2,     // phi_mrg high at least this long before the sample
    parameter integer RoundTicks = 13,
    parameter integer AdcShare   = 3,
    parameter integer DrainPass  = 3
) (
    input  wire       clk_i,
    input  wire       rst_ni,
    input  wire       start_i,
    input  wire       more_i,        // the descriptor generator still has elements
    input  wire       ready_i,       // every weight write the next pass needs is staged
    input  wire       wr_need_i,     // the next pass needs array writes (new weights or a refresh)
    input  wire       wr_busy_i,     // the array writer is still writing rows
    output wire       row_en_o,      // rails carry the slot's levels (FSM decode, for the driver's flops)
    output wire       phi_drv_o,     // the same window, registered (constant-charge dummies)
    output wire       drv_cut_o,     // rails released half a tick into each slot's last tick (negedge)
    output wire [3:0] slot_o,
    output wire       phi_rst_o,
    output wire       phi_sh_o,
    output wire       phi_mrg_o,
    output wire       phi_samp_o,
    output wire       sar_clk_o,
    output wire       bank_o,        // accumulator bank the shares go to (toggles one tick after a hand-off)
    output wire       hand_o,        // one tick: the bank just driven goes to the merge engine
    output wire       samp_o,        // one tick: the merged bank is sampled (descriptor capture)
    output wire       merge_start_o, // one tick: writer latches its need mask
    output wire       pass_go_o,     // one tick: descriptors advance, the next pass starts
    output wire       cap_o,         // one tick: end of a SAR round, codes valid
    output wire [3:0] cap_round_o,
    output wire       conv_done_o,   // one tick after the last round's capture
    output wire       conv_busy_o,
    output wire       stall_o,
    output wire       done_o
);
    localparam [2:0] StIdle = 3'd0, StDrive = 3'd1, StStall = 3'd2, StWrite = 3'd3,
                     StWait = 3'd4, StDone = 3'd5;
    localparam [1:0] EIdle = 2'd0, EMrg = 2'd1, ESamp = 2'd2;

    reg [2:0]  state_q, state_d;
    reg [7:0]  sub_q, sub_d;          // tick within slot
    reg [3:0]  slot_q, slot_d;
    reg [3:0]  drain_q, drain_d;
    // merge engine: holds the handed bank's merge until the converter can take the sample
    reg [1:0]  eng_q, eng_d;
    reg [3:0]  mt_q, mt_d;
    reg        bank_q, flip_q;
    // conversion counter (free of the pass FSM so stalls do not stretch a conversion)
    reg        cpend_q, cpend_d;      // the conversion starts one tick after the sample edge
    reg        cbusy_q, cbusy_d;
    reg [7:0]  csub_q, csub_d;
    reg [3:0]  crnd_q, crnd_d;
    reg        cdone_q, cdone_d;
    reg [3:0]  fin_q, fin_d;
    // registered phase outputs: every pin the tile sees edges on is a single flop (no decode glitches)
    reg        phi_drv_q, phi_rst_q, phi_sh_q, phi_mrg_q, phi_samp_q, sar_clk_q, cap_q, last_cap_q;
    reg [3:0]  cap_round_q;
    reg        rst_last_q, rst_cut_q;     // ends the top-plate reset half a tick before the rails move
    reg        slot_last_q, drv_cut_q;    // drops the rails half a tick after the share opens

    wire last_sub   = (sub_q == SlotTicks - 1);
    wire last_slot  = (slot_q == NSlots - 1);
    wire drive_end  = (state_q == StDrive) && last_sub && last_slot;
    // the next sample is timed so that the next conversion starts on the tick after the last round's
    // capture tick (no handoff gap: t_conv = AdcShare x RoundTicks exactly): the engine may leave
    // two ticks before the capture, the sample edge (phi_samp falling) lands on the capture tick's
    // end and the next sar_clk rise one tick later. The banks make this legal: the new sample is the
    // other bank while round AdcShare-1 converts.
    wire last_round = cbusy_q && (crnd_q == AdcShare - 1) && (csub_q >= RoundTicks - 3);
    wire conv_ok    = !cpend_q && (!cbusy_q || last_round);
    wire eng_free   = (eng_q == EIdle) || (eng_q == ESamp);
    wire hand       = (drive_end || (state_q == StWait)) && eng_free;
    wire at_next    = hand || (state_q == StStall);
    wire go         = (at_next && ready_i && !wr_need_i) || ((state_q == StWrite) && !wr_busy_i);
    wire cap_now    = cbusy_q && (csub_q == RoundTicks - 1);
    wire cont       = more_i || (drain_q != 4'd0);

    always @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            state_q <= StIdle; sub_q <= 8'd0; slot_q <= 4'd0; drain_q <= 4'd0;
            eng_q <= EIdle; mt_q <= 4'd0; bank_q <= 1'b0; flip_q <= 1'b0;
            cpend_q <= 1'b0; cbusy_q <= 1'b0; csub_q <= 8'd0; crnd_q <= 4'd0; cdone_q <= 1'b0; fin_q <= 4'd0;
            phi_drv_q <= 1'b0; phi_rst_q <= 1'b0; phi_sh_q <= 1'b0; phi_mrg_q <= 1'b0; phi_samp_q <= 1'b0;
            sar_clk_q <= 1'b0; cap_q <= 1'b0; last_cap_q <= 1'b0; cap_round_q <= 4'd0; rst_last_q <= 1'b0; slot_last_q <= 1'b0;
        end else begin
            phi_drv_q  <= (state_q == StDrive) && (sub_q >= RstTicks);
            phi_rst_q  <= (state_q == StDrive) && (sub_q < RstTicks);
            rst_last_q <= (state_q == StDrive) && (sub_q == RstTicks - 1);
            slot_last_q <= (state_q == StDrive) && last_sub;
            // share opens one tick before the slot ends: the rails hold their level past the share edge
            phi_sh_q   <= (state_q == StDrive) && (sub_q >= SlotTicks - 1 - ShTicks) && !last_sub;
            phi_mrg_q  <= (eng_q == EMrg);
            phi_samp_q <= (eng_q == ESamp);
            // the bank flips one tick after the hand-off: never on the edge that closes the last share
            flip_q     <= hand;
            if (flip_q) bank_q <= !bank_q;
            sar_clk_q  <= cbusy_q && (csub_q < RoundTicks / 2);
            // a round's code is captured when the next round starts (RoundTicks - 1 ticks after sar_clk)
            cap_q       <= cap_now;
            last_cap_q  <= cap_now && (crnd_q == AdcShare - 1);
            cap_round_q <= crnd_q;
            state_q <= state_d; sub_q <= sub_d; slot_q <= slot_d; drain_q <= drain_d;
            eng_q <= eng_d; mt_q <= mt_d;
            cpend_q <= cpend_d; cbusy_q <= cbusy_d; csub_q <= csub_d; crnd_q <= crnd_d; cdone_q <= cdone_d; fin_q <= fin_d;
        end
    end

    always @* begin
        state_d = state_q;
        sub_d   = sub_q;
        slot_d  = slot_q;
        drain_d = drain_q;
        case (state_q)
            StIdle: if (start_i) begin state_d = StDrive; sub_d = 8'd0; slot_d = 4'd0; drain_d = DrainPass; end
            StDrive: begin
                sub_d = sub_q + 8'd1;
                if (last_sub) begin
                    sub_d  = 8'd0;
                    slot_d = slot_q + 4'd1;
                end
                if (drive_end && !eng_free) state_d = StWait;
            end
            StWait, StStall, StWrite: ;
            StDone: ;
            default: state_d = StIdle;
        endcase
        if (at_next && !ready_i) state_d = StStall;
        if (at_next && ready_i && wr_need_i) state_d = StWrite;
        if (go) begin
            sub_d = 8'd0; slot_d = 4'd0;
            if (!more_i && drain_q != 4'd0) drain_d = drain_q - 4'd1;
            state_d = cont ? StDrive : StDone;
        end
    end

    always @* begin
        eng_d = eng_q;
        mt_d  = mt_q;
        case (eng_q)
            EMrg: begin
                if (mt_q != 4'hF) mt_d = mt_q + 4'd1;
                if (mt_q >= MrgTicks - 1 && conv_ok) eng_d = ESamp;
            end
            ESamp: eng_d = EIdle;
            default: ;
        endcase
        if (hand) begin eng_d = EMrg; mt_d = 4'd0; end
    end

    always @* begin
        cpend_d = (eng_q == ESamp);
        cbusy_d = cbusy_q;
        csub_d  = csub_q;
        crnd_d  = crnd_q;
        cdone_d = last_cap_q;
        fin_d   = fin_q;
        if (cpend_q) begin
            cbusy_d = 1'b1; csub_d = 8'd0; crnd_d = 4'd0;
        end else if (cbusy_q) begin
            csub_d = csub_q + 8'd1;
            if (cap_now) begin
                csub_d = 8'd0;
                crnd_d = crnd_q + 4'd1;
                if (crnd_q == AdcShare - 1) cbusy_d = 1'b0;
            end
        end
        // done a few ticks after the last conversion has left the chain
        if (state_q == StDone && eng_q == EIdle && !cbusy_q && !cpend_q && !cap_q && !cdone_q && fin_q != 4'd15)
            fin_d = fin_q + 4'd1;
    end

    // row_en / slot are decoded from the FSM (no delay): the driver registers the row codes, which
    // puts them on the same tick as the registered phases
    assign row_en_o      = (state_q == StDrive) && (sub_q >= RstTicks);
    assign slot_o        = slot_q;
    assign phi_drv_o     = phi_drv_q;
    // the rails return to 0 during the second half of each slot's last tick and the reset tick that
    // follows, so they are at 0 (to e^-8.8 at tau_row 16 ps) when the top plates are released
    assign drv_cut_o     = drv_cut_q;
    always @(negedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin rst_cut_q <= 1'b0; drv_cut_q <= 1'b0; end
        else         begin rst_cut_q <= rst_last_q; drv_cut_q <= slot_last_q; end
    end
    // the rails start moving at the next tick edge; the top plates are already floating by then
    assign phi_rst_o     = phi_rst_q && !rst_cut_q;
    assign phi_sh_o      = phi_sh_q;
    assign phi_mrg_o     = phi_mrg_q;
    assign phi_samp_o    = phi_samp_q;
    assign sar_clk_o     = sar_clk_q;
    assign bank_o        = bank_q;
    assign hand_o        = hand;
    assign samp_o        = (eng_q == ESamp);
    assign merge_start_o = at_next && ready_i;
    assign pass_go_o     = go;
    assign cap_o         = cap_q;
    assign cap_round_o   = cap_round_q;
    assign conv_done_o   = cdone_q;
    assign conv_busy_o   = cbusy_q;
    assign stall_o       = (state_q == StStall);
    assign done_o        = (fin_q == 4'd15);
endmodule
