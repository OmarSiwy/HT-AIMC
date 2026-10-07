// sa_sys: the reference accelerator tile = sa_ctrl + sa_top + its four SRAM buffers.
//   wbuf  : weight rows (Cols*WW bits)       host-written, read by the loader
//   abuf  : activation tokens (Rows*8 bits)  host-written, read by the streamer
//   rqbuf : per-column requant (Cols*21 bits) host-written, read once per group
//   obuf  : INT8 output rows (Cols*8 bits)   written by the array, host-read
// The controller issues reads; the 1-cycle SRAM read is matched by flopping the
// tags once, so every sa_top port sees data and tag in the same cycle.
// Host writes and job runs share nothing but the SRAMs; double-buffering the
// SRAMs against DMA is the host's job (address halves), not this block's.
module sa_sys #(
  parameter int Rows     = 16,
  parameter int Cols     = 16,
  parameter int WW       = 8,
  parameter int AccDepth = 16,
  parameter bit PipeMul  = 1'b1,
  parameter int CfgW     = 12,
  parameter int WbufAw   = 12,
  parameter int AbufAw   = 12,
  parameter int RqAw     = 8,
  parameter int ObufAw   = 12,
  parameter int RowW     = $clog2(Rows),
  parameter int IdxW     = $clog2(AccDepth)
) (
  input  logic                clk_i,
  input  logic                rst_ni,
  // job
  input  logic                start_i,
  input  logic [CfgW-1:0]     m_count_i,
  input  logic [CfgW-1:0]     k_tiles_i,
  input  logic [CfgW-1:0]     n_tiles_i,
  output logic                busy_o,
  output logic                done_o,
  // host buffer ports
  input  logic                wbuf_we_i,
  input  logic [WbufAw-1:0]   wbuf_addr_i,
  input  logic [Cols*WW-1:0]  wbuf_data_i,
  input  logic                abuf_we_i,
  input  logic [AbufAw-1:0]   abuf_addr_i,
  input  logic [Rows*8-1:0]   abuf_data_i,
  input  logic                rqbuf_we_i,
  input  logic [RqAw-1:0]     rqbuf_addr_i,
  input  logic [Cols*21-1:0]  rqbuf_data_i,   // {offset[8], shift[5], scale[8]} per column
  input  logic                obuf_re_i,
  input  logic [ObufAw-1:0]   obuf_addr_i,
  output logic [Cols*8-1:0]   obuf_data_o
);
  localparam int Lat = Rows + Cols + (PipeMul ? 1 : 0) + 8;   // sa_top port -> y_valid_o

  // controller issue
  logic              w_re, a_re, rq_re;
  logic [WbufAw-1:0] w_addr;
  logic [AbufAw-1:0] a_addr;
  logic [RqAw-1:0]   rq_addr;
  logic [RowW-1:0]   w_row;
  logic              w_bank, a_bank, a_first, a_last, a_rqsel, rq_bank;
  logic [IdxW-1:0]   a_idx;
  logic [ObufAw-1:0] o_addr;
  // SRAM read data (one cycle after issue) and the tags aligned with it
  logic [Cols*WW-1:0] w_rdata;
  logic [Rows*8-1:0]  a_rdata;
  logic [Cols*21-1:0] rq_rdata;
  logic               w_re_q, a_re_q, rq_re_q;
  logic [RowW-1:0]    w_row_q;
  logic               w_bank_q, a_bank_q, a_first_q, a_last_q, a_rqsel_q, rq_bank_q;
  logic [IdxW-1:0]    a_idx_q;
  // array output
  logic               y_valid;
  logic [IdxW-1:0]    y_idx;
  logic [Cols*8-1:0]  y_data;
  // requant field split
  logic [Cols*8-1:0]  rq_scale, rq_offset;
  logic [Cols*5-1:0]  rq_shift;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      w_re_q  <= 1'b0;
      a_re_q  <= 1'b0;
      rq_re_q <= 1'b0;
    end else begin
      w_re_q  <= w_re;
      a_re_q  <= a_re;
      rq_re_q <= rq_re;
    end
  end

  always_ff @(posedge clk_i) begin
    w_row_q   <= w_row;
    w_bank_q  <= w_bank;
    a_bank_q  <= a_bank;
    a_first_q <= a_first;
    a_last_q  <= a_last;
    a_rqsel_q <= a_rqsel;
    a_idx_q   <= a_idx;
    rq_bank_q <= rq_bank;
  end

  for (genvar c = 0; c < Cols; c++) begin : g_rq
    assign rq_scale[c*8 +: 8]  = rq_rdata[c*21 +: 8];
    assign rq_shift[c*5 +: 5]  = rq_rdata[c*21 + 8 +: 5];
    assign rq_offset[c*8 +: 8] = rq_rdata[c*21 + 13 +: 8];
  end

  sa_ctrl #(
    .Rows(Rows), .Cols(Cols), .AccDepth(AccDepth), .Lat(Lat), .CfgW(CfgW),
    .WbufAw(WbufAw), .AbufAw(AbufAw), .RqAw(RqAw), .ObufAw(ObufAw)
  ) u_ctrl (
    .clk_i, .rst_ni, .start_i, .m_count_i, .k_tiles_i, .n_tiles_i,
    .y_valid_i (y_valid),
    .w_re_o    (w_re),    .w_addr_o (w_addr), .w_row_o (w_row), .w_bank_o (w_bank),
    .a_re_o    (a_re),    .a_addr_o (a_addr), .a_bank_o (a_bank),
    .a_first_o (a_first), .a_last_o (a_last), .a_rqsel_o (a_rqsel), .a_idx_o (a_idx),
    .rq_re_o   (rq_re),   .rq_addr_o (rq_addr), .rq_bank_o (rq_bank),
    .o_addr_o  (o_addr),  .busy_o, .done_o
  );

  sa_sram #(.Depth(2**WbufAw), .Width(Cols*WW)) u_wbuf (
    .clk_i, .re_i(w_re), .raddr_i(w_addr), .rdata_o(w_rdata),
    .we_i(wbuf_we_i), .waddr_i(wbuf_addr_i), .wdata_i(wbuf_data_i)
  );
  sa_sram #(.Depth(2**AbufAw), .Width(Rows*8)) u_abuf (
    .clk_i, .re_i(a_re), .raddr_i(a_addr), .rdata_o(a_rdata),
    .we_i(abuf_we_i), .waddr_i(abuf_addr_i), .wdata_i(abuf_data_i)
  );
  sa_sram #(.Depth(2**RqAw), .Width(Cols*21)) u_rqbuf (
    .clk_i, .re_i(rq_re), .raddr_i(rq_addr), .rdata_o(rq_rdata),
    .we_i(rqbuf_we_i), .waddr_i(rqbuf_addr_i), .wdata_i(rqbuf_data_i)
  );
  sa_sram #(.Depth(2**ObufAw), .Width(Cols*8)) u_obuf (
    .clk_i, .re_i(obuf_re_i), .raddr_i(obuf_addr_i), .rdata_o(obuf_data_o),
    .we_i(y_valid), .waddr_i(o_addr), .wdata_i(y_data)
  );

  sa_top #(
    .Rows(Rows), .Cols(Cols), .AW(8), .WW(WW), .AccW(32), .AccDepth(AccDepth),
    .PipeMul(PipeMul)
  ) u_top (
    .clk_i, .rst_ni,
    .w_valid_i (w_re_q),  .w_row_i (w_row_q), .w_bank_i (w_bank_q), .w_data_i (w_rdata),
    .a_valid_i (a_re_q),  .a_data_i (a_rdata), .a_bank_i (a_bank_q),
    .a_first_i (a_first_q), .a_last_i (a_last_q), .a_rqsel_i (a_rqsel_q), .a_idx_i (a_idx_q),
    .rq_we_i   (rq_re_q), .rq_bank_i (rq_bank_q),
    .rq_scale_i (rq_scale), .rq_shift_i (rq_shift), .rq_offset_i (rq_offset),
    .y_valid_o (y_valid), .y_idx_o (y_idx), .y_data_o (y_data)
  );
endmodule
