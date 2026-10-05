// tb_sa_sys: end-to-end job on sa_sys (controller + SRAM buffers + array).
// The host loads wbuf/abuf/rqbuf through the write ports, pulses start, waits for
// done, then reads obuf back and compares every row with the numpy golden.
//   wbuf.hex / abuf.hex / rqbuf.hex : buffer images (layouts in sa_ctrl.sv header)
//   exp.hex                         : expected obuf rows, address order
// Prints PASS/FAIL and run_cycles (start -> done) for the scheduler check.
`timescale 1ns/1ps
module tb_sa_sys;
  parameter int Rows     = 16;
  parameter int Cols     = 16;
  parameter int WW       = 8;
  parameter int AccDepth = 16;
  parameter bit PipeMul  = 1'b1;
  parameter int M        = 1;
  parameter int KT       = 1;
  parameter int NT       = 1;
  parameter     Dir      = "build";

  localparam int NW = NT * KT * Rows;   // weight rows (one per K-tile reload group)
  localparam int NA = KT * M;
  localparam int NO = NT * M;

  logic clk = 1'b0, rst_n = 1'b0;
  always #1 clk = ~clk;

  logic [Cols*WW-1:0] wimg [NW];
  logic [Rows*8-1:0]  aimg [NA];
  logic [Cols*21-1:0] rimg [NT];
  logic [Cols*8-1:0]  eimg [NO];

  logic               start = 1'b0, busy, done;
  logic               wbuf_we = 1'b0, abuf_we = 1'b0, rqbuf_we = 1'b0, obuf_re = 1'b0;
  logic [11:0]        wbuf_addr = '0, abuf_addr = '0, obuf_addr = '0;
  logic [7:0]         rqbuf_addr = '0;
  logic [Cols*WW-1:0] wbuf_data = '0;
  logic [Rows*8-1:0]  abuf_data = '0;
  logic [Cols*21-1:0] rqbuf_data = '0;
  logic [Cols*8-1:0]  obuf_data;

  sa_sys #(.Rows(Rows), .Cols(Cols), .WW(WW), .AccDepth(AccDepth), .PipeMul(PipeMul)) dut (
    .clk_i(clk), .rst_ni(rst_n),
    .start_i(start), .m_count_i(12'(M)), .k_tiles_i(12'(KT)), .n_tiles_i(12'(NT)),
    .busy_o(busy), .done_o(done),
    .wbuf_we_i(wbuf_we), .wbuf_addr_i(wbuf_addr), .wbuf_data_i(wbuf_data),
    .abuf_we_i(abuf_we), .abuf_addr_i(abuf_addr), .abuf_data_i(abuf_data),
    .rqbuf_we_i(rqbuf_we), .rqbuf_addr_i(rqbuf_addr), .rqbuf_data_i(rqbuf_data),
    .obuf_re_i(obuf_re), .obuf_addr_i(obuf_addr), .obuf_data_o(obuf_data)
  );

  integer i, n_err = 0, run_cycles = 0;

  initial begin
    $readmemh({Dir, "/wbuf.hex"}, wimg);
    $readmemh({Dir, "/abuf.hex"}, aimg);
    $readmemh({Dir, "/rqbuf.hex"}, rimg);
    $readmemh({Dir, "/exp.hex"}, eimg);
    repeat (3) @(negedge clk);
    rst_n = 1'b1;
    for (i = 0; i < NW; i++) begin
      wbuf_we = 1'b1; wbuf_addr = 12'(i); wbuf_data = wimg[i]; @(negedge clk);
    end
    wbuf_we = 1'b0;
    for (i = 0; i < NA; i++) begin
      abuf_we = 1'b1; abuf_addr = 12'(i); abuf_data = aimg[i]; @(negedge clk);
    end
    abuf_we = 1'b0;
    for (i = 0; i < NT; i++) begin
      rqbuf_we = 1'b1; rqbuf_addr = 8'(i); rqbuf_data = rimg[i]; @(negedge clk);
    end
    rqbuf_we = 1'b0;
    start = 1'b1; @(negedge clk); start = 1'b0;
    run_cycles = 1;
    while (!done) begin
      @(negedge clk);
      run_cycles = run_cycles + 1;
      if (run_cycles > 2000000) begin
        $display("FAIL: timeout");
        $finish;
      end
    end
    @(negedge clk);
    if (busy) begin n_err = n_err + 1; $display("FAIL: busy after done"); end
    for (i = 0; i < NO; i++) begin
      obuf_re = 1'b1; obuf_addr = 12'(i); @(negedge clk);
      if (obuf_data !== eimg[i]) begin
        n_err = n_err + 1;
        if (n_err < 10) $display("FAIL: obuf[%0d] got %h exp %h", i, obuf_data, eimg[i]);
      end
    end
    if (n_err == 0) $display("PASS rows=%0d run_cycles=%0d", NO, run_cycles);
    else            $display("FAIL errors=%0d", n_err);
    $finish;
  end
endmodule
