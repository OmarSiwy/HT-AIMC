// sa_edge: per-column K-tile accumulator + INT8 requantization, below the array.
//
// The array column delivers one partial sum per token per K-tile. The tag that
// travelled with the token says where it goes:
//   first : start a new output (acc = psum), else acc[idx] += psum
//   last  : this is the final K-tile, send acc + psum to requant instead of storing
// Requant matches scripts/golden/model.py:requant_int8 exactly:
//   y = sat8( ((acc * scale + half) >>> shift) + offset ),  half = shift ? 2^(shift-1) : 0
// computed as round-half-up after a shift of shift-1, which is the same integer:
//   (p + 2^(s-1)) >>> s == ((p >>> (s-1)) + 1) >>> 1     for s >= 1
// Seven stages (slot read | add | byte-slice products | product | shift | round | offset+sat), so no
// stage holds more than one carry chain, the barrel shifter or the slot read mux; the
// edge is per column, so its flops are amortized over Rows PEs. The read-modify-write
// of a slot spans two cycles: safe because one slot recurs at most once per K-tile, and
// K-tiles of the same token issue >= Rows >= 2 cycles apart (one weight row per cycle). The requant parameters are double-banked like the
// weights: the token's tag selects the bank (rqsel), the host writes the other one,
// so back-to-back output tiles with different per-channel scales never stall.
//
// Accumulator width: |psum| <= K * 2^14 for INT8 x INT8, so a 32-bit accumulator is
// wrap-free for K <= 131072 (largest 7B/70B projection K is 28672). No saturation
// logic is spent on an overflow that cannot happen; the host compiler checks K.
module sa_edge #(
  parameter int PsumW    = 20,
  parameter int AccW     = 32,
  parameter int AccDepth = 16,
  parameter int IdxW     = $clog2(AccDepth),
  parameter int OutW     = 8
) (
  input  logic                    clk_i,
  input  logic                    rst_ni,
  input  logic signed [PsumW-1:0] psum_i,
  input  logic                    valid_i,
  input  logic                    first_i,
  input  logic                    last_i,
  input  logic                    rqsel_i,
  input  logic [IdxW-1:0]         idx_i,
  input  logic                    rq_we_i,
  input  logic                    rq_wbank_i,
  input  logic [7:0]              rq_scale_i,   // unsigned per-column scale
  input  logic [4:0]              rq_shift_i,
  input  logic signed [7:0]       rq_offset_i,
  output logic                    y_valid_o,
  output logic signed [OutW-1:0]  y_o
);

  localparam int ProdW = AccW + 9;              // acc * unsigned 8b scale
  localparam int NSl   = AccW / 8;              // the multiply is split into byte slices
  // Saturation bounds at the 13-bit width of `biased`. OutMin is written as ~OutMax:
  // yosys 0.62 evaluates `-N'(x)` to +x (the gate-level netlist then saturated every
  // output to -128 while iverilog RTL passed), so no negated size cast here.
  localparam logic signed [12:0] OutMax = 13'((1 << (OutW - 1)) - 1);
  localparam logic signed [12:0] OutMin = ~OutMax;

  logic signed [AccW-1:0]  acc_q [AccDepth];
  logic signed [AccW-1:0]  rd_q;        // slot read, one cycle ahead of the add
  logic signed [PsumW-1:0] psum_q;
  logic [IdxW-1:0]         idx_q;
  logic                    in_v_q, first_q, last_q, rqsel_q;
  logic signed [AccW-1:0]  sum;
  logic signed [AccW-1:0]  sum_q;
  logic signed [17:0]      pp_q [NSl];  // byte slice * scale; top slice signed, rest unsigned
  logic signed [ProdW-1:0] pp_sum;
  logic signed [ProdW-1:0] prod_q, shr_q;
  logic signed [11:0]      rnd_q;       // rounded value; exact whenever !big_q
  logic                    big_q;       // |shr_q| >= 2048: saturates on its sign whatever the offset
  logic                    neg_q;
  logic                    shr_fits;    // shr_q fits 12 bits signed
  logic signed [12:0]      biased;
  logic                    rnd_en_q;
  logic signed [OutW-1:0]  y_q;
  logic [5:0]              v_q;         // stage valids: sum, half, prod, shr, rnd, y
  logic [4:0]              sel_q;       // requant bank, per stage: sum, half, prod, shr, rnd
  logic [7:0]              scale_q  [2];
  logic [4:0]              shift_q  [2];
  logic signed [7:0]       offset_q [2];
  logic [4:0]              shift_sel;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      in_v_q <= 1'b0;
      v_q    <= '0;
    end else begin
      in_v_q <= valid_i;
      v_q    <= {v_q[4:0], in_v_q && last_q};
    end
  end

  always_ff @(posedge clk_i) begin
    if (rq_we_i) begin
      scale_q[rq_wbank_i]  <= rq_scale_i;
      shift_q[rq_wbank_i]  <= rq_shift_i;
      offset_q[rq_wbank_i] <= rq_offset_i;
    end
    if (valid_i) begin
      psum_q  <= psum_i;
      idx_q   <= idx_i;
      first_q <= first_i;
      last_q  <= last_i;
      rqsel_q <= rqsel_i;
    end
    if (valid_i && !first_i) rd_q <= acc_q[idx_i];
    if (in_v_q && !last_q) acc_q[idx_q] <= sum;
    if (in_v_q &&  last_q) begin
      sum_q    <= sum;
      sel_q[0] <= rqsel_q;
    end
    if (v_q[0]) begin
      for (int j = 0; j < NSl; j++) begin
        pp_q[j] <= (j == NSl - 1 ? 18'($signed({sum_q[8*j+7], sum_q[8*j +: 8]}))
                                 : 18'($signed({1'b0, sum_q[8*j +: 8]})))
                   * 18'($signed({1'b0, scale_q[sel_q[0]]}));
      end
      sel_q[1] <= sel_q[0];
    end
    if (v_q[1]) begin
      prod_q   <= pp_sum;
      sel_q[2] <= sel_q[1];
    end
    if (v_q[2]) begin
      shr_q    <= prod_q >>> (shift_sel == 5'd0 ? 5'd0 : shift_sel - 5'd1);
      rnd_en_q <= shift_sel != 5'd0;
      sel_q[3] <= sel_q[2];
    end
    if (v_q[3]) begin
      // 12-bit round only: the 41-bit incrementer was the edge's critical path.
      rnd_q    <= rnd_en_q ? 12'((13'($signed(shr_q[11:0])) + 13'sd1) >>> 1) : $signed(shr_q[11:0]);
      big_q    <= !shr_fits;
      neg_q    <= shr_q[ProdW-1];
      sel_q[4] <= sel_q[3];
    end
    if (v_q[4]) y_q <= big_q ? (neg_q ? OutMin[OutW-1:0] : OutMax[OutW-1:0]) :
                       biased > OutMax ? OutMax[OutW-1:0] :
                       biased < OutMin ? OutMin[OutW-1:0] :
                                              biased[OutW-1:0];
  end

  assign sum       = first_q ? AccW'(psum_q) : rd_q + AccW'(psum_q);
  always_comb begin
    pp_sum = '0;
    for (int j = 0; j < NSl; j++) pp_sum = pp_sum + (ProdW'(pp_q[j]) <<< (8 * j));
  end

  assign shift_sel = shift_q[sel_q[2]];
  // Saturation without a full-width add: once |shr_q| >= 2048 the rounded value is
  // >= 1024 in magnitude and |offset| <= 128, so the output saturates on the sign alone;
  // otherwise a 12-bit round and a 13-bit offset add are exact.
  assign shr_fits  = &shr_q[ProdW-1:11] || !(|shr_q[ProdW-1:11]);
  assign biased    = 13'(rnd_q) + 13'(offset_q[sel_q[4]]);

  assign y_valid_o = v_q[5];
  assign y_o       = y_q;

endmodule
