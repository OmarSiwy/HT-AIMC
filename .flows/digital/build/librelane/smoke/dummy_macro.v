// Verilog blackbox for the smoke test's dummy analog macro (gen_dummy_macro.py).
// No power pins: the digital ones are hooked up by PDN_MACRO_CONNECTIONS, the
// analog ones (VDDA/VSSA) on purpose are not.
(* blackbox *)
module dummy_macro (
    input  wire en,
    input  wire c0,
    input  wire c1,
    input  wire c2,
    input  wire c3,
    output wire done,
    inout  wire ana
);
endmodule
