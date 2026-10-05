// tb_sa_top: replays a cycle-exact stimulus schedule (test/run_tests.py writes it)
// into sa_top and checks every output row against the numpy golden.
//   stim.hex : one packed input word per cycle (layout = the concatenation below)
//   exp.hex  : expected {y_idx, y_data} per output row, in order
// Prints PASS/FAIL and the cycle of the last output; also logs every column's INT32
// accumulator result (sums.txt) so the harness checks the pre-requant sums bit-exactly.
`timescale 1ns/1ps
module tb_sa_top;
  parameter int Rows     = 16;
  parameter int Cols     = 16;
  parameter int WW       = 8;
  parameter int AccDepth = 16;
  parameter bit PipeMul  = 1'b1;
  parameter int NCyc     = 1;
  parameter int NExp     = 1;
  parameter     Dir      = "build";

  localparam int AW    = 8;
  localparam int RowW  = $clog2(Rows);
  localparam int IdxW  = $clog2(AccDepth);
  localparam int StimW = (1 + RowW + 1 + Cols*WW) + (1 + Rows*AW + 4 + IdxW) + (2 + Cols*21);
  localparam int ExpW  = IdxW + Cols*8;

  logic clk = 1'b0, rst_n = 1'b0;
  always #1 clk = ~clk;

  logic [StimW-1:0] stim [NCyc];
  logic [ExpW-1:0]  expv [NExp];
  logic [StimW-1:0] cur;

  logic                 w_valid, w_bank, a_valid, a_bank, a_first, a_last, a_rqsel;
  logic                 rq_we, rq_bank;
  logic [RowW-1:0]      w_row;
  logic [Cols*WW-1:0]   w_data;
  logic [Rows*AW-1:0]   a_data;
  logic [IdxW-1:0]      a_idx;
  logic [Cols*8-1:0]    rq_scale, rq_offset;
  logic [Cols*5-1:0]    rq_shift;
  logic                 y_valid;
  logic [IdxW-1:0]      y_idx;
  logic [Cols*8-1:0]    y_data;

  assign {rq_offset, rq_shift, rq_scale, rq_bank, rq_we,
          a_idx, a_rqsel, a_last, a_first, a_bank, a_data, a_valid,
          w_data, w_bank, w_row, w_valid} = cur;

  sa_top #(.Rows(Rows), .Cols(Cols), .WW(WW), .AccDepth(AccDepth), .PipeMul(PipeMul)) dut (
    .clk_i(clk), .rst_ni(rst_n),
    .w_valid_i(w_valid), .w_row_i(w_row), .w_bank_i(w_bank), .w_data_i(w_data),
    .a_valid_i(a_valid), .a_data_i(a_data), .a_bank_i(a_bank), .a_first_i(a_first),
    .a_last_i(a_last), .a_rqsel_i(a_rqsel), .a_idx_i(a_idx),
    .rq_we_i(rq_we), .rq_bank_i(rq_bank),
    .rq_scale_i(rq_scale), .rq_shift_i(rq_shift), .rq_offset_i(rq_offset),
    .y_valid_o(y_valid), .y_idx_o(y_idx), .y_data_o(y_data)
  );

  integer cyc = 0, tick = -1, n_out = 0, n_err = 0, last_out = 0, fsum;

  // tick = index of the stimulus word sampled at this edge (one idle edge after reset)
  always @(posedge clk) if (rst_n) tick <= tick + 1;

  for (genvar c = 0; c < Cols; c++) begin : g_mon
    always @(posedge clk) begin
      if (dut.g_edge[c].u_edge.sum_valid_q)
        $fwrite(fsum, "%0d %0d\n", c, $signed(dut.g_edge[c].u_edge.sum_q));
    end
  end

  always @(posedge clk) begin
    if (rst_n && y_valid) begin
      if (n_out >= NExp) begin
        n_err = n_err + 1;
        $display("FAIL: extra output %0d", n_out);
      end else if ({y_idx, y_data} !== expv[n_out]) begin
        n_err = n_err + 1;
        if (n_err < 10) $display("FAIL: out %0d got %h exp %h", n_out, {y_idx, y_data}, expv[n_out]);
      end
      n_out    = n_out + 1;
      last_out = tick;
    end
  end

  initial begin
    $readmemh({Dir, "/stim.hex"}, stim);
    $readmemh({Dir, "/exp.hex"}, expv);
    fsum = $fopen({Dir, "/sums.txt"}, "w");
    if ($test$plusargs("vcd")) begin
      $dumpfile({Dir, "/sa.vcd"});
      $dumpvars(0, dut);
    end
    cur = '0;
    repeat (3) @(negedge clk);
    rst_n = 1'b1;
    for (cyc = 0; cyc < NCyc; cyc++) begin
      @(negedge clk);
      cur = stim[cyc];
    end
    @(negedge clk);
    cur = '0;
    repeat (Rows + Cols + 16) @(negedge clk);
    $fclose(fsum);
    if (n_out != NExp) begin
      n_err = n_err + 1;
      $display("FAIL: %0d outputs, expected %0d", n_out, NExp);
    end
    if (n_err == 0) $display("PASS outputs=%0d last_out_cycle=%0d", n_out, last_out);
    else            $display("FAIL errors=%0d", n_err);
    $finish;
  end
endmodule
