// Replay tile for the open-loop co-simulation: outputs, at each SAR round, the codes the Verilog-A
// tile produced in ESPice for that round (file: one line per round, NConv hex codes, converter 0
// first). The tile's inputs (weights, rows, phases) never depend on its outputs, so the driver run
// that produced the ESPice stimulus and this replay run see the same schedule.
`timescale 1ns/1ps
module imc_tile_replay #(
    parameter integer Rows = 8, Cols = 8, AdcShare = 4, Bits = 12, NRounds = 1,
    parameter FILE = "codes.hex"
) (
    input  wire [Rows-1:0]                  wl,
    input  wire [Cols*8-1:0]                wbl,
    input  wire [Rows*3-1:0]                drive,
    input  wire                             phi_rst,
    input  wire                             phi_sh,
    input  wire                             phi_mrg,
    input  wire                             phi_samp,
    input  wire                             sar_clk,
    output reg  [(Cols/AdcShare)*Bits-1:0]  codes
);
    reg [(Cols/AdcShare)*Bits-1:0] mem [0:NRounds-1];
    integer k;
    initial begin $readmemh(FILE, mem); k = 0; codes = 0; end
    always @(posedge sar_clk) begin
        if (k < NRounds) codes = mem[k];
        k = k + 1;
    end
endmodule
