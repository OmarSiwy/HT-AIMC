"""N7 dataflow & scheduling: the digital rail and on-die memory around the tiles.

Prefill runs as GEMM (each tile load serves B x 512 vectors), decode as GEMV (B
vectors per load); the schedule itself is in model.py. This node prices the digital
rail that runs QK^T, A.V (16-bit KV), softmax and the elementwise ops
(APPLICATION_ATTENTION.md: attention lives on the digital rail), the activation
SRAM buffer and the PHYs. All numbers projected (7 nm-class digital literature).
"""
from arch_eval import asap7 as k

OPTIONS = {
    "digital_rail": dict(params=dict(rail_frac=0.10, rail_mac_per_s_per_mm2=2e12, e_att_mac_pJ=0.4,
                                     e_exp_pJ=5.0, e_elem_pJ=0.3, buffer_MB=8.0, e_buf_pJ_per_byte=0.5,
                                     phy_hbm_mm2=12.0, phy_d2d_mm2=4.0, phy_pJ_per_bit=0.5,
                                     hop_ns=20.0, logic_leak_W_per_mm2=0.02, tile_util=0.85,
                                     pingpong=True),
                         provenance="projected: 7 nm digital MAC/SRAM/PHY literature; ping-pong readout as specs.pingpong_pass_time"),
}
DEFAULT = "digital_rail"
SWEEP = dict(rail_frac=[0.05, 0.1, 0.2], buffer_MB=[4, 8, 16])


def rail(p, vdd, op, knobs):
    e = op["e_scale"]
    sram_mm2 = p["buffer_MB"] * 8 * 2 ** 20 * k.get("sram6t_bitcell_um2") * 1.5 / 1e6
    area = dict(rail=p["rail_frac"] * knobs["die_mm2"], buffer=sram_mm2,
                phy=p["phy_hbm_mm2"] + p["phy_d2d_mm2"])
    return dict(area_mm2=area, att_mac_per_s=area["rail"] * p["rail_mac_per_s_per_mm2"] * op["clk_GHz"],
                e_att_mac_J=p["e_att_mac_pJ"] * e * 1e-12, e_exp_J=p["e_exp_pJ"] * e * 1e-12,
                e_elem_J=p["e_elem_pJ"] * e * 1e-12, e_buf_J_per_byte=p["e_buf_pJ_per_byte"] * e * 1e-12,
                phy_J_per_bit=p["phy_pJ_per_bit"] * 1e-12, hop_s=p["hop_ns"] * 1e-9,
                leak_W=(area["rail"] + area["buffer"]) * p["logic_leak_W_per_mm2"] * op["leak_scale"],
                tile_util=p["tile_util"], pingpong=bool(p["pingpong"]))
