// Smoke-test top: a 4-bit counter driving the dummy analog macro.
`default_nettype none
module smoke_top (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    output wire [4:0] uo_out,   // {macro done, counter}
    inout  wire       ana       // analog pass-through, must stay unbuffered
);
    reg [3:0] count;
    always @(posedge clk or negedge rst_n)
        if (!rst_n)  count <= 4'd0;
        else if (en) count <= count + 4'd1;

    wire done;
    dummy_macro u_macro (
        .en(en), .c0(count[0]), .c1(count[1]), .c2(count[2]), .c3(count[3]),
        .done(done), .ana(ana)
    );

    assign uo_out = {done, count};
endmodule
