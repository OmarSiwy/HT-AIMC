// Behavioural model of the smoke test's dummy analog macro, for simulation only
// (harden uses the dummy_macro.v blackbox). Same module name and ports.
// "Conversion" finishes (done=1) when enabled and the input code is all ones.
// `ana` is analog: the model leaves it undriven.
module dummy_macro (
    input  wire en,
    input  wire c0,
    input  wire c1,
    input  wire c2,
    input  wire c3,
    output wire done,
    inout  wire ana
);
    assign done = en & c0 & c1 & c2 & c3;
endmodule
