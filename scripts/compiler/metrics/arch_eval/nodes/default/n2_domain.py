"""N2 compute domain.

Default "charge": port of the measured sky130 passive 128-row signed macro
(IMC_SIZING_RESEARCH.md: 4.4998 fJ per A8xW4 MAC of ideal-port delivery, 6-plane
mean A8 word of 366 ns, 4-fF units, +-0.45 V excitation on a 1.8 V supply, TT 27 C).
Scaling to ASAP7 (derived, stated assumptions):
  * delivery energy ~ Cu * V_exc^2 with V_exc = VDD/4 (same swing ratio) and
    ~ input planes / 6;
  * plus crosspoint bottom-plate switch gate drive (the anchor's ideal port excludes
    it): wbits switches x 2 fins x Cgg x VDD^2 x activity per plane;
  * plus row-wire drive: pitch x C_wire x VDD^2 per crosspoint per plane;
  * plane slot = max(61 ns x FO4(VDD)/FO4_sky130, 8 tau of the share switch on C_col).
"""
import math

from arch_eval import asap7 as k

ANCHOR = dict(e_fJ=4.4998, cu_fF=4.0, vdd=1.8, planes=6, slot_ns=61.0)
OPTIONS = {
    "charge": dict(params=dict(share_fins=8, sw_activity=0.5, settle_tau=8.0),
                   provenance="measured sky130 passive macro (IMC_SIZING_RESEARCH.md), ported by CV^2/FO4 laws"),
}
DEFAULT = "charge"
SWEEP = dict(settle_tau=[6.0, 8.0, 10.0])


def array(p, vdd, fmt, cell, rows):
    planes = fmt["input_planes"]
    cu = p["cu_fF"]
    deliver = ANCHOR["e_fJ"] * (cu / ANCHOR["cu_fF"]) * (vdd / ANCHOR["vdd"]) ** 2 * planes / ANCHOR["planes"]
    cgg = k.get("nfet_cgg_per_fin_aF") * 1e-3          # fF
    gate = min(4, fmt["wbits"]) * 2 * cgg * vdd ** 2 * p["sw_activity"] * planes
    pitch = math.sqrt(cell["area_um2_per_weight"])
    wire = pitch * k.get("wire_c_fF_per_um") * vdd ** 2 * planes
    c_col = rows * cell["c_weight_fF"]
    tau_ns = k.get("switch_ron_ohm_per_fin") / p["share_fins"] * c_col * 1e-15 * 1e9
    slot = max(ANCHOR["slot_ns"] * k.get("fo4_delay_ps", vdd) / k.get("sky130_fo4_delay_ps"),
               p["settle_tau"] * tau_ns)
    return dict(e_mac_fJ=deliver + gate + wire, t_word_ns=planes * slot, slot_ns=slot,
                v_exc_V=vdd / 4, c_col_fF=c_col,
                breakdown_fJ=dict(delivery=deliver, switch_gates=gate, row_wire=wire))
