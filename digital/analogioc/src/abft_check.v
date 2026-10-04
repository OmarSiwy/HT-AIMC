// abft_check: algorithm-based fault-tolerance compare for the checksum
// column. residual = sum_{i=0}^{15} y_i - y_chk (exact, signed, W+5 bits);
// flag = |residual| > budget. Pure combinational (it is a check, sample
// residual/flag when the accumulators' done is high).
// Sign convention for random-sign checksum rows is absorbed by the compiler
// when it programs the checksum column; the rail computes a plain sum.
module abft_check #(
    parameter W = 20
) (
    input  wire [16*W-1:0]      y_flat,  // 16 signed W-bit column sums, y_i = y_flat[i*W +: W]
    input  wire signed [W-1:0]  y_chk,   // checksum-column sum
    input  wire [15:0]          budget,  // unsigned residual budget (LSBs of acc)
    output wire signed [W+4:0]  residual,
    output wire                 flag
);
    // sum of 16 W-bit signed values: exact in W+4 bits
    reg signed [W+3:0] sum;
    integer i;
    always @* begin
        sum = {(W+4){1'b0}};
        for (i = 0; i < 16; i = i + 1)
            sum = sum + $signed(y_flat[i*W +: W]);
    end

    assign residual = sum - y_chk;  // exact in W+5 bits

    // |residual|: negation cannot overflow (|residual| <= 17*2^(W-1) < 2^(W+4))
    wire [W+4:0] absres = residual[W+4] ? (~residual + 1'b1) : residual;

    assign flag = (absres > {{(W-11){1'b0}}, budget});  // zero-extend budget to W+5
endmodule
