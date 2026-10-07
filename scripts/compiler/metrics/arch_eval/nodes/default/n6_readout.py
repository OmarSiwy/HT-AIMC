"""N6 readout & conversion.

Default "sar_27h1": one SAR per `adc_share` columns, energy from note 27h1
(Gonugondla 2022 fit): E = B x (comparator + SAR logic) + k2 (VDD/Vc)^2 4^B,
k2 = 1 aJ, Vc = the +-4 sigma column range (projected). The switching term uses
ASAP7 comparator/DFF energies instead of the fit's 100 fJ (fitted at older nodes).

"integrator_coarse_sar": the repo's measured sky130 chain (OTA integrator + event-rate
coarse + SAR fine: 1345.10 pJ / 17 columns = 79.1 pJ and 1.26 us per conversion,
METRICS.md) ported by VDD^2 and FO4 (derived; its OTA gain makes it independent of
the column range Vc). On the default tile it gives ~3x the TOPS/W of sar_27h1 (whose
thermal term pays (VDD/Vc)^2 for the tiny passive-column swing) but its 280-ns
conversions cut tok/s per die ~16x. Range/gain before the SAR is the open question.
"""
import math

from arch_eval import asap7 as k

OPTIONS = {
    "sar_27h1": dict(params=dict(adc="sar", adc_bits=8, k2_aJ=1.0, adc_area_fixed_um2=100.0,
                                 cu_adc_fF=0.5, digital_gates=60),
                     provenance="note 27h1 (Gonugondla 2022) energy law; ASAP7 constants projected"),
    "integrator_coarse_sar": dict(params=dict(adc="integrator", adc_bits=8, adc_area_fixed_um2=400.0,
                                              digital_gates=60),
                                  provenance="measured sky130 tb_tile_mvm chain (METRICS.md), ported VDD^2/FO4"),
}
DEFAULT = "sar_27h1"
SWEEP = dict(adc_bits=[6, 7, 8, 9])


def adc(p, vdd, v_fs_V):
    b = int(p["adc_bits"])
    e_dig = p["digital_gates"] * k.get("inv_switch_energy_fJ", vdd)   # shift-add + partial-sum accumulate
    fo4 = k.get("fo4_delay_ps", vdd) * 1e-3                          # ns
    if p["adc"] == "integrator":
        r = k.get("fo4_delay_ps", vdd) / k.get("sky130_fo4_delay_ps")
        return dict(bits=b, e_conv_fJ=79.12e3 * (vdd / 1.8) ** 2, t_conv_ns=1260 * r,
                    area_um2=p["adc_area_fixed_um2"], e_digital_fJ=e_dig)
    switching = b * (k.get("comparator_energy_fJ") * (vdd / k.get("vdd_nom")) ** 2
                     + 2 * k.get("dff_energy_fJ") * (vdd / k.get("vdd_nom")) ** 2)
    thermal = p["k2_aJ"] * 1e-3 * (vdd / v_fs_V) ** 2 * 4 ** b
    cdac_um2 = 2 ** b * p["cu_adc_fF"] / k.get("mom_cap_density_fF_per_um2")
    return dict(bits=b, e_conv_fJ=switching + thermal, t_conv_ns=b * 6 * fo4 + 10 * fo4,
                area_um2=p["adc_area_fixed_um2"] + cdac_um2 + 2 * b * k.get("dff_area_um2"),
                e_digital_fJ=e_dig, breakdown_fJ=dict(switching=switching, thermal=thermal))
