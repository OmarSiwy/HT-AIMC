// sa_ctrl: tile controller for y = requant(X[M,K] * W[K,N]) on sa_top.
//
// It is test/sched.py in hardware: three engines, each starting its next action at
// the earliest cycle every constraint holds, which is exactly the schedule sched.py
// computes greedily (the regression checks the cycle count against it).
//   loader   : writes one tile's Rows weight rows, one per cycle, into bank t%2
//   streamer : issues the tile's tokens (up to AccDepth rows of X), one per cycle
//   rq       : writes one output group's per-column requant params into bank g%2
// Tile order: for n-tile: for m-chunk (AccDepth rows): for k-tile. A group is one
// (n-tile, m-chunk); its tokens accumulate over k in sa_edge's AccDepth slots.
//
// Constraints (sa_top header):
//   load tile t   >= last issue of tile t-2 + Cols - 1   (bank reuse, bank_rel)
//   issue tile t  >= load start of tile t + 1             (tiles_ahead)
//   issue group g >= rq write of group g + 1              (rq_ahead)
//   rq group g    >= last issue of group g-2 + Lat + 1    (requant bank reuse, rq_rel)
//
// Buffer layouts (word = one Rows-, Cols- or rq-wide vector):
//   wbuf[(n*k_tiles + k)*Rows + r] = W[k*Rows + r][n*Cols +: Cols]
//   abuf[k*M + m]                  = X[m][k*Rows +: Rows]
//   rqbuf[n]                       = {offset, shift, scale} for columns n*Cols +: Cols
//   obuf[n*M + m]                  = y[m][n*Cols +: Cols]   (outputs leave in this order)
// Read enables are issue-cycle; the 1-cycle SRAM read is aligned in sa_sys.
module sa_ctrl #(
  parameter int Rows     = 16,
  parameter int Cols     = 16,
  parameter int AccDepth = 16,
  parameter int Lat      = 36,   // sa_top input -> y_valid_o, cycles
  parameter int CfgW     = 12,   // width of m_count / k_tiles / n_tiles
  parameter int WbufAw   = 12,
  parameter int AbufAw   = 12,
  parameter int RqAw     = 8,
  parameter int ObufAw   = 12,
  parameter int RowW     = $clog2(Rows),
  parameter int IdxW     = $clog2(AccDepth)
) (
  input  logic              clk_i,
  input  logic              rst_ni,
  input  logic              start_i,
  input  logic [CfgW-1:0]   m_count_i,   // >= 1
  input  logic [CfgW-1:0]   k_tiles_i,   // >= 1
  input  logic [CfgW-1:0]   n_tiles_i,   // >= 1
  input  logic              y_valid_i,   // sa_top output row
  // weight row read
  output logic              w_re_o,
  output logic [WbufAw-1:0] w_addr_o,
  output logic [RowW-1:0]   w_row_o,
  output logic              w_bank_o,
  // activation token read + tag
  output logic              a_re_o,
  output logic [AbufAw-1:0] a_addr_o,
  output logic              a_bank_o,
  output logic              a_first_o,
  output logic              a_last_o,
  output logic              a_rqsel_o,
  output logic [IdxW-1:0]   a_idx_o,
  // requant read
  output logic              rq_re_o,
  output logic [RqAw-1:0]   rq_addr_o,
  output logic              rq_bank_o,
  // output row write address (valid with y_valid_i)
  output logic [ObufAw-1:0] o_addr_o,
  output logic              busy_o,
  output logic              done_o
);
  localparam int RelW   = $clog2(Cols);
  localparam int RqRelW = $clog2(Lat + 1);
  localparam logic [RelW-1:0]   BankRel = RelW'(Cols - 2);  // set 1 cycle after last issue
  localparam logic [RqRelW-1:0] RqRel   = RqRelW'(Lat);
  localparam logic [CfgW-1:0]   Depth   = CfgW'(AccDepth);

  typedef enum logic { CtlIdle, CtlRun } ctl_state_e;

  // job
  ctl_state_e            state_q, state_d;
  logic [CfgW-1:0]       m_q, m_d, kt_q, kt_d, nt_q, nt_d;
  logic [ObufAw-1:0]     o_total_q, o_total_d, o_cnt_q, o_cnt_d;
  // bank bookkeeping
  logic [1:0]            bank_busy_q, bank_busy_d;
  logic [1:0][RelW-1:0]  bank_rel_q, bank_rel_d;
  logic [1:0]            rq_busy_q, rq_busy_d;
  logic [1:0][RqRelW-1:0] rq_rel_q, rq_rel_d;
  logic [1:0]            tiles_ahead_q, tiles_ahead_d;
  logic [1:0]            rq_ahead_q, rq_ahead_d;
  // loader
  logic                  ld_active_q, ld_active_d, ld_all_q, ld_all_d, ld_bank_q, ld_bank_d;
  logic [RowW-1:0]       ld_row_q, ld_row_d;
  logic [CfgW-1:0]       ld_k_q, ld_k_d, ld_m0_q, ld_m0_d, ld_n_q, ld_n_d;
  logic [WbufAw-1:0]     ld_addr_q, ld_addr_d, ld_base_q, ld_base_d, ld_nbase_q, ld_nbase_d;
  // streamer
  logic                  st_active_q, st_active_d, st_all_q, st_all_d, st_bank_q, st_bank_d;
  logic                  st_gb_q, st_gb_d, st_tgb_q, st_tgb_d;
  logic                  st_first_q, st_first_d, st_last_q, st_last_d;
  logic [IdxW-1:0]       st_m_q, st_m_d, st_mlast_q, st_mlast_d;
  logic [CfgW-1:0]       st_k_q, st_k_d, st_m0_q, st_m0_d, st_n_q, st_n_d;
  logic [AbufAw-1:0]     st_addr_q, st_addr_d, st_base_q, st_base_d;
  // rq engine
  logic                  rq_all_q, rq_all_d, rq_bank_q, rq_bank_d;
  logic [CfgW-1:0]       rq_m0_q, rq_m0_d;
  logic [RqAw-1:0]       rq_n_q, rq_n_d;
  // per-cycle events
  logic                  running, ld_go, ld_end, st_go, st_end, rq_go, o_done;
  logic [CfgW-1:0]       st_rem, st_mc;
  logic                  cur_bank, cur_gb, cur_first, cur_last;   // tile issuing now

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q       <= CtlIdle;
      m_q           <= '0;   kt_q <= '0;   nt_q <= '0;
      o_total_q     <= '0;   o_cnt_q <= '0;
      bank_busy_q   <= '0;   bank_rel_q <= '0;
      rq_busy_q     <= '0;   rq_rel_q   <= '0;
      tiles_ahead_q <= '0;   rq_ahead_q <= '0;
      ld_active_q   <= 1'b0; ld_all_q  <= 1'b0; ld_bank_q <= 1'b0; ld_row_q <= '0;
      ld_k_q        <= '0;   ld_m0_q   <= '0;   ld_n_q    <= '0;
      ld_addr_q     <= '0;   ld_base_q <= '0;   ld_nbase_q <= '0;
      st_active_q   <= 1'b0; st_all_q  <= 1'b0; st_bank_q <= 1'b0;
      st_gb_q       <= 1'b0; st_tgb_q <= 1'b0; st_first_q <= 1'b0; st_last_q <= 1'b0;
      st_m_q        <= '0;   st_mlast_q <= '0;
      st_k_q        <= '0;   st_m0_q   <= '0;   st_n_q    <= '0;
      st_addr_q     <= '0;   st_base_q <= '0;
      rq_all_q      <= 1'b0; rq_bank_q <= 1'b0; rq_m0_q   <= '0;   rq_n_q <= '0;
    end else begin
      state_q       <= state_d;
      m_q           <= m_d;   kt_q <= kt_d;   nt_q <= nt_d;
      o_total_q     <= o_total_d;   o_cnt_q <= o_cnt_d;
      bank_busy_q   <= bank_busy_d; bank_rel_q <= bank_rel_d;
      rq_busy_q     <= rq_busy_d;   rq_rel_q   <= rq_rel_d;
      tiles_ahead_q <= tiles_ahead_d; rq_ahead_q <= rq_ahead_d;
      ld_active_q   <= ld_active_d; ld_all_q  <= ld_all_d; ld_bank_q <= ld_bank_d;
      ld_row_q      <= ld_row_d;
      ld_k_q        <= ld_k_d;   ld_m0_q   <= ld_m0_d;   ld_n_q    <= ld_n_d;
      ld_addr_q     <= ld_addr_d; ld_base_q <= ld_base_d; ld_nbase_q <= ld_nbase_d;
      st_active_q   <= st_active_d; st_all_q <= st_all_d; st_bank_q <= st_bank_d;
      st_gb_q       <= st_gb_d;  st_tgb_q <= st_tgb_d; st_first_q <= st_first_d; st_last_q <= st_last_d;
      st_m_q        <= st_m_d;   st_mlast_q <= st_mlast_d;
      st_k_q        <= st_k_d;   st_m0_q   <= st_m0_d;   st_n_q    <= st_n_d;
      st_addr_q     <= st_addr_d; st_base_q <= st_base_d;
      rq_all_q      <= rq_all_d; rq_bank_q <= rq_bank_d; rq_m0_q <= rq_m0_d; rq_n_q <= rq_n_d;
    end
  end

  // Events. Each engine goes the first cycle it is idle and its constraint holds.
  assign running = (state_q == CtlRun);
  assign ld_go   = running && !ld_active_q && !ld_all_q
                   && !bank_busy_q[ld_bank_q] && (bank_rel_q[ld_bank_q] == '0);
  assign ld_end  = ld_active_q && (ld_row_q == RowW'(Rows - 1));
  assign st_go   = running && !st_active_q && !st_all_q
                   && (tiles_ahead_q != 2'd0) && (rq_ahead_q != 2'd0);
  assign st_rem  = m_q - st_m0_q;
  assign st_mc   = (st_rem > Depth) ? Depth : st_rem;
  // The streamer's *_q tile fields describe the next tile; on a go cycle the tile
  // issuing is that one, otherwise it is the one latched into st_t*/first/last.
  assign cur_bank  = st_go ? st_bank_q : !st_bank_q;
  assign cur_gb    = st_go ? st_gb_q : st_tgb_q;
  assign cur_first = st_go ? (st_k_q == '0) : st_first_q;
  assign cur_last  = st_go ? (st_k_q == kt_q - 1'b1) : st_last_q;
  // last token of the tile issues this cycle (a 1-token tile ends on its go cycle)
  assign st_end  = st_go ? (st_mc == CfgW'(1)) : (st_active_q && (st_m_q == st_mlast_q));
  assign rq_go   = running && !rq_all_q
                   && !rq_busy_q[rq_bank_q] && (rq_rel_q[rq_bank_q] == '0);
  assign o_done  = running && y_valid_i && (o_cnt_q == o_total_q - 1'b1);

  // job FSM
  always_comb begin
    state_d   = state_q;
    m_d       = m_q;
    kt_d      = kt_q;
    nt_d      = nt_q;
    o_total_d = o_total_q;
    o_cnt_d   = o_cnt_q;
    if (y_valid_i) o_cnt_d = o_cnt_q + 1'b1;
    unique case (state_q)
      CtlIdle: if (start_i) begin
        state_d   = CtlRun;
        m_d       = m_count_i;
        kt_d      = k_tiles_i;
        nt_d      = n_tiles_i;
        o_total_d = ObufAw'(m_count_i * n_tiles_i);
        o_cnt_d   = '0;
      end
      CtlRun: if (o_done) state_d = CtlIdle;
      default: state_d = CtlIdle;
    endcase
  end

  // bank bookkeeping, shared by the three engines
  always_comb begin
    bank_busy_d   = bank_busy_q;
    bank_rel_d    = bank_rel_q;
    rq_busy_d     = rq_busy_q;
    rq_rel_d      = rq_rel_q;
    for (int b = 0; b < 2; b++) begin
      if (bank_rel_q[b] != '0) bank_rel_d[b] = bank_rel_q[b] - 1'b1;
      if (rq_rel_q[b]   != '0) rq_rel_d[b]   = rq_rel_q[b] - 1'b1;
    end
    if (ld_go) bank_busy_d[ld_bank_q] = 1'b1;
    if (rq_go) rq_busy_d[rq_bank_q]   = 1'b1;
    if (st_end) begin
      bank_busy_d[cur_bank] = 1'b0;
      bank_rel_d[cur_bank]  = BankRel;
      if (cur_last) begin
        rq_busy_d[cur_gb] = 1'b0;
        rq_rel_d[cur_gb]  = RqRel;
      end
    end
    tiles_ahead_d = tiles_ahead_q + {1'b0, ld_go} - {1'b0, st_go};
    rq_ahead_d    = rq_ahead_q + {1'b0, rq_go}
                    - {1'b0, st_go && (st_k_q == kt_q - 1'b1)};
    if (state_q == CtlIdle) begin
      bank_busy_d   = '0;
      bank_rel_d    = '0;
      rq_busy_d     = '0;
      rq_rel_d      = '0;
      tiles_ahead_d = '0;
      rq_ahead_d    = '0;
    end
  end

  // loader: row 0 issues on the go cycle from ld_base_q, rows 1.. from ld_addr_q
  always_comb begin
    ld_active_d = ld_active_q;
    ld_all_d    = ld_all_q;
    ld_bank_d   = ld_bank_q;
    ld_row_d    = ld_row_q;
    ld_k_d      = ld_k_q;
    ld_m0_d     = ld_m0_q;
    ld_n_d      = ld_n_q;
    ld_addr_d   = ld_addr_q;
    ld_base_d   = ld_base_q;
    ld_nbase_d  = ld_nbase_q;
    if (ld_active_q) begin
      ld_row_d  = ld_row_q + 1'b1;
      ld_addr_d = ld_addr_q + 1'b1;
    end
    if (ld_end) ld_active_d = 1'b0;
    if (ld_go) begin
      ld_active_d = 1'b1;
      ld_bank_d   = !ld_bank_q;
      ld_row_d    = RowW'(1);
      ld_addr_d   = ld_base_q + 1'b1;
      ld_base_d   = ld_base_q + WbufAw'(Rows);
      if (ld_k_q != kt_q - 1'b1) begin
        ld_k_d = ld_k_q + 1'b1;
      end else begin
        ld_k_d = '0;
        if (m_q - ld_m0_q > Depth) begin
          ld_m0_d   = ld_m0_q + Depth;
          ld_base_d = ld_nbase_q;                  // same n-tile: reload its weights
        end else begin
          ld_m0_d    = '0;
          ld_n_d     = ld_n_q + 1'b1;
          ld_nbase_d = ld_base_q + WbufAw'(Rows);
          ld_all_d   = (ld_n_q == nt_q - 1'b1);
        end
      end
    end
    if (state_q == CtlIdle) begin
      ld_active_d = 1'b0;
      ld_all_d    = 1'b0;
      ld_bank_d   = 1'b0;
      ld_row_d    = '0;
      ld_k_d      = '0;
      ld_m0_d     = '0;
      ld_n_d      = '0;
      ld_addr_d   = '0;
      ld_base_d   = '0;
      ld_nbase_d  = '0;
    end
  end

  // streamer: token 0 issues on the go cycle from st_base_q, tokens 1.. from st_addr_q
  always_comb begin
    st_active_d = st_active_q;
    st_all_d    = st_all_q;
    st_bank_d   = st_bank_q;
    st_gb_d     = st_gb_q;
    st_tgb_d    = st_tgb_q;
    st_first_d  = st_first_q;
    st_last_d   = st_last_q;
    st_m_d      = st_m_q;
    st_mlast_d  = st_mlast_q;
    st_k_d      = st_k_q;
    st_m0_d     = st_m0_q;
    st_n_d      = st_n_q;
    st_addr_d   = st_addr_q;
    st_base_d   = st_base_q;
    if (st_active_q) begin
      st_m_d    = st_m_q + 1'b1;
      st_addr_d = st_addr_q + 1'b1;
    end
    if (st_end) st_active_d = 1'b0;
    if (st_go) begin
      st_active_d = (st_mc != CfgW'(1));
      st_bank_d   = !st_bank_q;
      st_tgb_d    = st_gb_q;
      st_first_d  = (st_k_q == '0);
      st_last_d   = (st_k_q == kt_q - 1'b1);
      st_m_d      = IdxW'(1);
      st_mlast_d  = IdxW'(st_mc - 1'b1);
      st_addr_d   = st_base_q + 1'b1;
      if (st_k_q != kt_q - 1'b1) begin
        st_k_d    = st_k_q + 1'b1;
        st_base_d = st_base_q + AbufAw'(m_q);
      end else begin
        st_k_d  = '0;
        st_gb_d = !st_gb_q;
        if (st_rem > Depth) begin
          st_m0_d   = st_m0_q + Depth;
          st_base_d = AbufAw'(st_m0_q + Depth);
        end else begin
          st_m0_d   = '0;
          st_n_d    = st_n_q + 1'b1;
          st_base_d = '0;
          st_all_d  = (st_n_q == nt_q - 1'b1);
        end
      end
    end
    if (state_q == CtlIdle) begin
      st_active_d = 1'b0;
      st_all_d    = 1'b0;
      st_bank_d   = 1'b0;
      st_gb_d     = 1'b0;
      st_tgb_d    = 1'b0;
      st_first_d  = 1'b0;
      st_last_d   = 1'b0;
      st_m_d      = '0;
      st_mlast_d  = '0;
      st_k_d      = '0;
      st_m0_d     = '0;
      st_n_d      = '0;
      st_addr_d   = '0;
      st_base_d   = '0;
    end
  end

  // rq engine: one group per go
  always_comb begin
    rq_all_d  = rq_all_q;
    rq_bank_d = rq_bank_q;
    rq_m0_d   = rq_m0_q;
    rq_n_d    = rq_n_q;
    if (rq_go) begin
      rq_bank_d = !rq_bank_q;
      if (m_q - rq_m0_q > Depth) begin
        rq_m0_d = rq_m0_q + Depth;
      end else begin
        rq_m0_d  = '0;
        rq_n_d   = rq_n_q + 1'b1;
        rq_all_d = (CfgW'(rq_n_q) == nt_q - 1'b1);
      end
    end
    if (state_q == CtlIdle) begin
      rq_all_d  = 1'b0;
      rq_bank_d = 1'b0;
      rq_m0_d   = '0;
      rq_n_d    = '0;
    end
  end

  assign w_re_o    = ld_go || ld_active_q;
  assign w_addr_o  = ld_go ? ld_base_q : ld_addr_q;
  assign w_row_o   = ld_go ? '0 : ld_row_q;
  assign w_bank_o  = ld_go ? ld_bank_q : !ld_bank_q;   // ld_bank_q already toggled
  assign a_re_o    = st_go || st_active_q;
  assign a_addr_o  = st_go ? st_base_q : st_addr_q;
  assign a_bank_o  = cur_bank;
  assign a_first_o = cur_first;
  assign a_last_o  = cur_last;
  assign a_rqsel_o = cur_gb;
  assign a_idx_o   = st_go ? '0 : st_m_q;
  assign rq_re_o   = rq_go;
  assign rq_addr_o = rq_n_q;
  assign rq_bank_o = rq_bank_q;
  assign o_addr_o  = o_cnt_q;
  assign busy_o    = (state_q != CtlIdle);
  assign done_o    = o_done;
endmodule
