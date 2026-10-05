// sa_top: Rows x Cols weight-stationary INT8 systolic array (TPU-MXU style) with
// double-buffered weights, input skew, per-column K accumulation + requant, and
// output de-skew. Computes, per issued token vector a (Rows elements of K):
//     y[c] = requant( sum over K-tiles of sum_r a[r] * W_bank[r][c] )
//
// Host contract (scripts in test/ and the README implement it as the scheduler):
//   * Weight port writes one row (Cols weights) of one bank per cycle.
//   * A tile = Rows x Cols weights in one bank, then M tokens issued with that bank.
//   * Reloading bank b: row r may be written no earlier than (last issue on bank b)
//     + Cols - 1 + r cycles; a token on bank b may issue no earlier than 1 cycle
//     after row 0 of that load was written. Writing rows 0..Rows-1 in order on
//     consecutive cycles meets both, so the steady-state tile period is
//     max(M, Rows) and the load of tile k+1 hides behind the compute of tile k.
//   * Requant parameters are double-banked per column: a token's a_rqsel_i picks the
//     bank; rewrite bank b only after the last output that used it has left (y_valid).
module sa_top #(
  parameter int Rows     = 16,
  parameter int Cols     = 16,
  parameter int AW       = 8,
  parameter int WW       = 8,
  parameter int AccW     = 32,
  parameter int AccDepth = 16,
  parameter bit PipeMul  = 1'b1,
  parameter int RowW     = $clog2(Rows),
  parameter int IdxW     = $clog2(AccDepth)
) (
  input  logic                   clk_i,
  input  logic                   rst_ni,
  // weight load port
  input  logic                   w_valid_i,
  input  logic [RowW-1:0]        w_row_i,
  input  logic                   w_bank_i,
  input  logic [Cols*WW-1:0]     w_data_i,
  // activation issue port (unskewed: element r is K-index r of this tile)
  input  logic                   a_valid_i,
  input  logic [Rows*AW-1:0]     a_data_i,
  input  logic                   a_bank_i,
  input  logic                   a_first_i,   // first K-tile of this output
  input  logic                   a_last_i,    // last K-tile: emit requantized result
  input  logic                   a_rqsel_i,   // requant bank for this output tile
  input  logic [IdxW-1:0]        a_idx_i,     // accumulator slot (token within tile)
  // per-column requant config, written one bank at a time
  input  logic                   rq_we_i,
  input  logic                   rq_bank_i,
  input  logic [Cols*8-1:0]      rq_scale_i,
  input  logic [Cols*5-1:0]      rq_shift_i,
  input  logic [Cols*8-1:0]      rq_offset_i,
  // de-skewed INT8 output row
  output logic                   y_valid_o,
  output logic [IdxW-1:0]        y_idx_o,
  output logic [Cols*8-1:0]      y_data_o
);

  localparam int PsumW   = AW + WW + $clog2(Rows);   // exact bound after Rows products
  localparam int TagW    = 4 + IdxW;                 // {valid, first, last, rqsel, idx}
  localparam int Pipe    = PipeMul ? 1 : 0;
  localparam int EdgeLat = 3;                        // sa_edge: sum, product, y stages

  // ---------------------------------------------------------------- input registers
  logic                 w_valid_q, w_bank_q;
  logic [RowW-1:0]      w_row_q;
  logic [Cols*WW-1:0]   w_data_q;
  logic                 in_valid_q, in_bank_q;
  logic [Rows*AW-1:0]   in_data_q;
  logic [TagW-1:0]      in_tag_q;
  logic                 rq_we_q, rq_bank_q;
  logic [Cols*8-1:0]    rq_scale_q, rq_offset_q;
  logic [Cols*5-1:0]    rq_shift_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      w_valid_q  <= 1'b0;
      rq_we_q    <= 1'b0;
      in_valid_q <= 1'b0;
      in_tag_q   <= '0;
      in_bank_q  <= 1'b0;
    end else begin
      w_valid_q  <= w_valid_i;
      rq_we_q    <= rq_we_i;
      in_valid_q <= a_valid_i;
      in_tag_q   <= {a_valid_i, a_first_i, a_last_i, a_rqsel_i, a_idx_i};
      in_bank_q  <= a_bank_i;
    end
  end

  always_ff @(posedge clk_i) begin
    if (w_valid_i) begin
      w_row_q  <= w_row_i;
      w_bank_q <= w_bank_i;
      w_data_q <= w_data_i;
    end
    if (rq_we_i) begin
      rq_bank_q   <= rq_bank_i;
      rq_scale_q  <= rq_scale_i;
      rq_shift_q  <= rq_shift_i;
      rq_offset_q <= rq_offset_i;
    end
    if (a_valid_i) in_data_q <= a_data_i;
  end

  // ---------------------------------------------------------------- array fabric
  // Horizontal (activation) and vertical (psum) nets; psum width grows by row.
  logic signed [AW-1:0]    a_net    [Rows][Cols+1];
  logic                    nz_net   [Rows][Cols+1];
  logic                    bank_net [Rows][Cols+1];
  logic signed [PsumW-1:0] psum_net [Rows+1][Cols];   // full width, sign-extended

  // Input skew: row r is delayed r cycles so token k meets row r at the same time
  // as the partial sum of rows 0..r-1. The data register only loads on a nonzero
  // valid element (zero operands keep the skew line quiet too).
  for (genvar r = 0; r < Rows; r++) begin : g_skew
    logic signed [AW-1:0] a_head;
    logic                 nz_head;
    assign a_head  = in_data_q[r*AW +: AW];
    assign nz_head = in_valid_q && (a_head != '0);

    if (r == 0) begin : g_direct
      assign a_net[r][0]    = a_head;
      assign nz_net[r][0]   = nz_head;
      assign bank_net[r][0] = in_bank_q;
    end else begin : g_delay
      logic signed [AW-1:0] a_dly_q   [r];
      logic                 nz_dly_q  [r];
      logic                 bank_dly_q[r];
      always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
          for (int i = 0; i < r; i++) begin
            nz_dly_q[i]   <= 1'b0;
            bank_dly_q[i] <= 1'b0;
          end
        end else begin
          nz_dly_q[0]   <= nz_head;
          bank_dly_q[0] <= in_bank_q;
          for (int i = 1; i < r; i++) begin
            nz_dly_q[i]   <= nz_dly_q[i-1];
            bank_dly_q[i] <= bank_dly_q[i-1];
          end
        end
      end
      always_ff @(posedge clk_i) begin
        if (nz_head) a_dly_q[0] <= a_head;
        for (int i = 1; i < r; i++) begin
          if (nz_dly_q[i-1]) a_dly_q[i] <= a_dly_q[i-1];
        end
      end
      assign a_net[r][0]    = a_dly_q[r-1];
      assign nz_net[r][0]   = nz_dly_q[r-1];
      assign bank_net[r][0] = bank_dly_q[r-1];
    end
  end

  for (genvar c = 0; c < Cols; c++) begin : g_col
    assign psum_net[0][c] = '0;
    for (genvar r = 0; r < Rows; r++) begin : g_row
      localparam int InW  = (r == 0) ? AW + WW : AW + WW + $clog2(r);
      localparam int OutW = AW + WW + $clog2(r + 1);
      logic signed [InW-1:0]  psum_in;
      logic signed [OutW-1:0] psum_out;

      sa_pe #(
        .AW(AW), .WW(WW), .PsumInW(InW), .PsumOutW(OutW), .PipeMul(PipeMul)
      ) u_pe (
        .clk_i,
        .rst_ni,
        .a_i     (a_net[r][c]),
        .nz_i    (nz_net[r][c]),
        .bank_i  (bank_net[r][c]),
        .psum_i  (psum_in),
        .w_we_i  (w_valid_q && (w_row_q == RowW'(r))),
        .w_bank_i(w_bank_q),
        .w_data_i(w_data_q[c*WW +: WW]),
        .a_o     (a_net[r][c+1]),
        .nz_o    (nz_net[r][c+1]),
        .bank_o  (bank_net[r][c+1]),
        .psum_o  (psum_out)
      );

      // Narrowing psum_net to InW is lossless: the row above produced only InW bits.
      assign psum_in           = psum_net[r][c][InW-1:0];
      assign psum_net[r+1][c]  = PsumW'(psum_out);
    end
  end

  // ---------------------------------------------------------------- tag alignment
  // The tag reaches column 0's edge Rows + Pipe cycles after issue (the same time as
  // that column's last-row psum), then walks right one column per cycle with the data.
  localparam int TagDly = Rows + Pipe;
  logic [TagW-1:0] tag_dly_q [TagDly];
  logic [TagW-1:0] tag_col_q [Cols-1];

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      for (int i = 0; i < TagDly; i++) tag_dly_q[i] <= '0;
      for (int i = 0; i < Cols-1; i++) tag_col_q[i] <= '0;
    end else begin
      tag_dly_q[0] <= in_tag_q;
      for (int i = 1; i < TagDly; i++) tag_dly_q[i] <= tag_dly_q[i-1];
      tag_col_q[0] <= tag_dly_q[TagDly-1];
      for (int i = 1; i < Cols-1; i++) tag_col_q[i] <= tag_col_q[i-1];
    end
  end

  // tag_dly_q[TagDly-1] lines up with column 0's bottom psum; tag_col_q[c] is one
  // cycle later per column, i.e. aligned with column c+1. Column c uses the tag that was
  // aligned with it.
  logic [TagW-1:0] edge_tag [Cols];
  assign edge_tag[0] = tag_dly_q[TagDly-1];
  for (genvar c = 1; c < Cols; c++) begin : g_tagmap
    assign edge_tag[c] = tag_col_q[c-1];
  end

  // ---------------------------------------------------------------- edges + de-skew
  logic                y_valid_col [Cols];
  logic signed [7:0]   y_col       [Cols];

  for (genvar c = 0; c < Cols; c++) begin : g_edge
    sa_edge #(
      .PsumW(PsumW), .AccW(AccW), .AccDepth(AccDepth), .IdxW(IdxW), .OutW(8)
    ) u_edge (
      .clk_i,
      .rst_ni,
      .psum_i     (psum_net[Rows][c]),
      .valid_i    (edge_tag[c][TagW-1]),
      .first_i    (edge_tag[c][TagW-2]),
      .last_i     (edge_tag[c][TagW-3]),
      .rqsel_i    (edge_tag[c][TagW-4]),
      .idx_i      (edge_tag[c][IdxW-1:0]),
      .rq_we_i    (rq_we_q),
      .rq_wbank_i (rq_bank_q),
      .rq_scale_i (rq_scale_q[c*8 +: 8]),
      .rq_shift_i (rq_shift_q[c*5 +: 5]),
      .rq_offset_i(rq_offset_q[c*8 +: 8]),
      .y_valid_o  (y_valid_col[c]),
      .y_o        (y_col[c])
    );

    // Column c finishes c cycles after column 0: delay it Cols-1-c more.
    localparam int Dly = Cols - 1 - c;
    if (Dly == 0) begin : g_nodly
      assign y_data_o[c*8 +: 8] = y_col[c];
    end else begin : g_dly
      logic [7:0] y_dly_q [Dly];
      always_ff @(posedge clk_i) begin
        if (y_valid_col[c]) y_dly_q[0] <= y_col[c];
        for (int i = 1; i < Dly; i++) y_dly_q[i] <= y_dly_q[i-1];
      end
      assign y_data_o[c*8 +: 8] = y_dly_q[Dly-1];
    end
  end

  // Output tag: the last column's tag, carried through the edge latency.
  logic [IdxW-1:0] y_idx_q [EdgeLat];
  always_ff @(posedge clk_i) begin
    y_idx_q[0] <= edge_tag[Cols-1][IdxW-1:0];
    for (int i = 1; i < EdgeLat; i++) y_idx_q[i] <= y_idx_q[i-1];
  end

  assign y_valid_o = y_valid_col[Cols-1];
  assign y_idx_o   = y_idx_q[EdgeLat-1];

endmodule
