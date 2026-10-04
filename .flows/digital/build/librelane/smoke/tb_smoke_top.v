// Self-checking tb: smoke_top simulated with the dummy macro's behavioural model.
// done must rise exactly when the counter reaches 15 with en high.
`timescale 1ns/1ps
module tb_smoke_top;
    reg clk = 0, rst_n = 0, en = 0;
    wire [4:0] uo_out;
    wire ana;
    smoke_top dut (.clk(clk), .rst_n(rst_n), .en(en), .uo_out(uo_out), .ana(ana));
    always #5 clk = ~clk;

    integer i, errors = 0;
    initial begin
        #12 rst_n = 1; en = 1;
        for (i = 1; i <= 20; i = i + 1) begin
            @(posedge clk); #1;
            if (uo_out[3:0] !== i[3:0] || uo_out[4] !== (i[3:0] == 4'hF)) begin
                errors = errors + 1;
                $display("cycle %0d: uo_out=%b", i, uo_out);
            end
        end
        if (errors == 0) $display("PASS: tb_smoke_top");
        else $display("FAIL: tb_smoke_top (%0d errors)", errors);
        $finish;
    end
endmodule
