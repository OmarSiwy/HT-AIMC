// sign_exit: sign-early-exit gate. For ReLU-bound output channels the
// column polarity (MSB of the signed result, known from the integrator
// polarity decision at end of integration) decides the whole conversion:
// negative -> ReLU output is 0, so terminate conversion immediately and
// force the column code to 0. Pure combinational; tile_fsm registers the
// decision.
module sign_exit (
    input  wire relu_en,     // channel is ReLU-bound (per-tensor config)
    input  wire sign_neg,    // 1 = column result negative (MSB decision)
    input  wire sign_valid,  // polarity decision valid
    output wire exit,        // terminate conversion now (skip coarse+fine)
    output wire force_zero   // emit code 0 for this column
);
    assign exit       = relu_en & sign_neg & sign_valid;
    assign force_zero = exit;
endmodule
