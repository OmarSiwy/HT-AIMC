// sa_sram: behavioural 1R1W SRAM, 1-cycle registered read (the fakeram7 /
// OpenRAM read timing). Simulation model only: synthesis treats it as a
// blackbox and the PPA charges it from the SRAM model in scripts/ppa.py.
module sa_sram #(
  parameter int Depth = 1024,
  parameter int Width = 128,
  parameter int Aw    = $clog2(Depth)
) (
  input  logic             clk_i,
  input  logic             re_i,
  input  logic [Aw-1:0]    raddr_i,
  output logic [Width-1:0] rdata_o,
  input  logic             we_i,
  input  logic [Aw-1:0]    waddr_i,
  input  logic [Width-1:0] wdata_i
);
  logic [Width-1:0] mem [Depth];
  logic [Width-1:0] rdata_q;

  always_ff @(posedge clk_i) begin
    if (we_i) mem[waddr_i] <= wdata_i;
    if (re_i) rdata_q <= mem[raddr_i];
  end

  assign rdata_o = rdata_q;
endmodule
