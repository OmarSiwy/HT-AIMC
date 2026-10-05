// sa_edge: per-column K-tile accumulator + INT8 requantization, below the array.
//
// The array column delivers one partial sum per token per K-tile. The tag that
// travelled with the token says where it goes:
//   first : start a new output (acc = psum), else acc[idx] += psum
//   last  : this is the final K-tile, send acc + psum to requant instead of storing
// Requant matches scripts/golden/model.py:requant_int8 exactly:
//   y = sat8( ((acc * scale + half) >>> shift) + offset ),  half = shift ? 2^(shift-1) : 0
// Two pipeline stages (multiply, then round/shift/saturate) keep the 32x9 multiply
// off the accumulator loop. The requant parameters are double-banked like the
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

  localparam int ProdW = AccW + 10;             // acc * (9b signed scale) + rounding carry
  localparam logic signed [ProdW-1:0] OutMax = ProdW'((1 << (OutW - 1)) - 1);
  localparam logic signed [ProdW-1:0] OutMin = -ProdW'(1 << (OutW - 1));

  logic signed [AccW-1:0]  acc_q [AccDepth];
  logic signed [AccW-1:0]  sum;
  logic signed [AccW-1:0]  sum_q;
  logic signed [ProdW-1:0] prod_q;
  logic signed [ProdW-1:0] half, shifted, biased;
  logic signed [OutW-1:0]  y_q;
  logic                    sum_valid_q, prod_valid_q, y_valid_q;
  logic                    sum_sel_q, prod_sel_q;
  logic [7:0]              scale_q  [2];
  logic [4:0]              shift_q  [2];
  logic signed [7:0]       offset_q [2];
  logic [4:0]              shift_sel;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      sum_valid_q  <= 1'b0;
      prod_valid_q <= 1'b0;
      y_valid_q    <= 1'b0;
    end else begin
      sum_valid_q  <= valid_i && last_i;
      prod_valid_q <= sum_valid_q;
      y_valid_q    <= prod_valid_q;
    end
  end

  always_ff @(posedge clk_i) begin
    if (rq_we_i) begin
      scale_q[rq_wbank_i]  <= rq_scale_i;
      shift_q[rq_wbank_i]  <= rq_shift_i;
      offset_q[rq_wbank_i] <= rq_offset_i;
    end
    if (valid_i && !last_i) acc_q[idx_i] <= sum;
    if (valid_i &&  last_i) begin
      sum_q     <= sum;
      sum_sel_q <= rqsel_i;
    end
    if (sum_valid_q) begin
      prod_q     <= ProdW'(sum_q) * ProdW'($signed({1'b0, scale_q[sum_sel_q]}));
      prod_sel_q <= sum_sel_q;
    end
    if (prod_valid_q)       y_q          <= biased > OutMax ? OutMax[OutW-1:0] :
                                            biased < OutMin ? OutMin[OutW-1:0] :
                                                              biased[OutW-1:0];
  end

  assign sum     = first_i ? AccW'(psum_i) : acc_q[idx_i] + AccW'(psum_i);
  assign shift_sel = shift_q[prod_sel_q];
  assign half      = (shift_sel == 5'd0) ? '0 : (ProdW'(1) <<< (shift_sel - 5'd1));
  assign shifted   = (prod_q + half) >>> shift_sel;
  assign biased    = shifted + ProdW'(offset_q[prod_sel_q]);

  assign y_valid_o = y_valid_q;
  assign y_o       = y_q;

endmodule
