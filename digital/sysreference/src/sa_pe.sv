// sa_pe: one weight-stationary systolic MAC cell.
//
// Activations enter from the left and leave registered to the right; partial sums
// enter from above and leave registered below. Two weight banks: the activation
// carries the bank it was issued against (bank_i), so a whole tile's wavefront reads
// one bank while the host writes the other (double buffering with no global swap).
//
// Operand isolation: nz_i = "valid and nonzero". On a zero/bubble the activation
// register holds (no toggle into the next cell's multiplier) and the product is
// masked to 0, so a zero operand costs one flag flop of switching, not a multiply.
module sa_pe #(
  parameter int AW       = 8,                // activation width (signed)
  parameter int WW       = 8,                // weight width (signed)
  parameter int PsumInW  = AW + WW,          // psum width arriving from above
  parameter int PsumOutW = AW + WW + 1,      // psum width leaving below
  parameter bit PipeMul  = 1'b1              // register the product before the add
) (
  input  logic                       clk_i,
  input  logic                       rst_ni,
  input  logic signed [AW-1:0]       a_i,
  input  logic                       nz_i,
  input  logic                       bank_i,
  input  logic signed [PsumInW-1:0]  psum_i,
  input  logic                       w_we_i,     // write this cell's weight (row selected)
  input  logic                       w_bank_i,
  input  logic signed [WW-1:0]       w_data_i,
  output logic signed [AW-1:0]       a_o,
  output logic                       nz_o,
  output logic                       bank_o,
  output logic signed [PsumOutW-1:0] psum_o
);

  localparam int ProdW = AW + WW;

  logic signed [AW-1:0]       a_q;
  logic                       nz_q, bank_q;
  logic signed [WW-1:0]       w0_q, w1_q;
  logic signed [WW-1:0]       w_sel;
  logic signed [ProdW-1:0]    prod;
  logic signed [ProdW-1:0]    prod_term;     // masked product entering the adder
  logic signed [PsumOutW-1:0] psum_q, psum_d;

  // Control flops reset; datapath flops do not (every consumer is qualified by nz/valid).
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      nz_q   <= 1'b0;
      bank_q <= 1'b0;
    end else begin
      nz_q   <= nz_i;
      bank_q <= bank_i;
    end
  end

  always_ff @(posedge clk_i) begin
    if (nz_i) a_q <= a_i;
    if (w_we_i && !w_bank_i) w0_q <= w_data_i;
    if (w_we_i &&  w_bank_i) w1_q <= w_data_i;
    psum_q <= psum_d;
  end

  assign w_sel = bank_i ? w1_q : w0_q;
  assign prod  = a_i * w_sel;

  if (PipeMul) begin : g_pipe
    // The product register adds one cycle; the psum arriving from above is one
    // cycle later too (every row has the stage), so the wavefront stays aligned.
    logic signed [ProdW-1:0] prod_q;
    always_ff @(posedge clk_i) begin
      if (nz_i) prod_q <= prod;
    end
    assign prod_term = nz_q ? prod_q : '0;
  end else begin : g_comb
    assign prod_term = nz_i ? prod : '0;
  end

  assign psum_d = PsumOutW'(psum_i) + PsumOutW'(prod_term);

  assign a_o    = a_q;
  assign nz_o   = nz_q;
  assign bank_o = bank_q;
  assign psum_o = psum_q;

endmodule
