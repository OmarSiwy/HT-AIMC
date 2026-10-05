// analogioc blackbox (* blackbox *): port view of the analog macro for synthesis and
// LibreLane. Ports = analog/analogioc/netlist/analogioc.ports (INTERFACE.md §2), signal
// ports only; supplies are analog_supplies in digital/analogioc/build/macros.toml.
// Simulation uses va/analogioc_beh.v (same module name and ports).
(* blackbox *)
module analogioc (
    input  wire         seq_rst_n,
    input  wire         integ_req,
    output wire         integ_ack,
    input  wire         win_hi,
    input  wire [63:0]  x_mag,
    input  wire [15:0]  x_neg,
    input  wire [2:0]   pkt_d,
    input  wire         lora_en,
    output wire [16:0]  col_sign,
    input  wire [16:0]  coarse_en,
    output wire [16:0]  cb_req,
    output wire [16:0]  cb_cross,
    input  wire [16:0]  cb_ack,
    input  wire [16:0]  cmp_req,
    output wire [16:0]  cmp_ack,
    output wire [16:0]  cmp_result,
    input  wire [67:0]  dac_code,
    input  wire [16:0]  ota_en,
    input  wire [15:0]  lora_wa_sel,
    input  wire [15:0]  lora_wb_sel,
    input  wire [3:0]   lora_da,
    input  wire [3:0]   lora_db,
    input  wire [15:0]  w_wl,
    input  wire [135:0] w_data,
    inout  wire         vcm,
    inout  wire         vrn_thrp,
    inout  wire         vrp_thrp,
    inout  wire         vrn_thrn,
    inout  wire         vrp_thrn,
    inout  wire         vrn_sarp,
    inout  wire         vrp_sarp,
    inout  wire         vrn_sarn,
    inout  wire         vrp_sarn,
    inout  wire         vb_nc,
    inout  wire         vb_pc,
    inout  wire         vb_tail,
    inout  wire         vb_ramp
);
endmodule
