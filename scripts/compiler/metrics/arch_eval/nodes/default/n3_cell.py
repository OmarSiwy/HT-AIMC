"""N3 storage cell, weight density and write.

Default: port of the measured sky130 passive macro cell (IMC_SIZING_RESEARCH.md):
SRAM bits select each binary-weighted capacitor's bottom plate (cm / +ref / -ref),
signed magnitude caps (2^(b-1)-1) Cu per 4-bit slice. ASAP7 area = max(FEOL, BEOL):
FEOL = bits x (6T bitcell + 3 bottom-plate TGs) x routing overhead, BEOL = caps / MOM
density (caps over the cells, the overlap imc_architecture_search.py also grants).
Write: SRAM bit write energy (projected, CV^2 of a 128-row bitline at VDD).
"""
from arch_eval import asap7 as k

OPTIONS = {
    "sram6t_binary_caps": dict(params=dict(cu_fF=1.0, tg_um2=0.02, route_overhead=1.3,
                                           bl_c_fF=25.0, sram_leak_pA_per_bit=50.0),
                               provenance="sky130 passive 128x8 macro cell (measured topology), ASAP7 areas projected"),
    "sram8t_unit_cap_per_bit": dict(params=dict(cu_fF=0.5, tg_um2=0.02, route_overhead=1.3,
                                                bl_c_fF=25.0, sram_leak_pA_per_bit=50.0, unit_caps=True),
                                    provenance="projected: one unit cap per bit (Jia/Verma-style), significance by charge share"),
}
DEFAULT = "sram6t_binary_caps"
SWEEP = dict(cu_fF=[0.5, 1.0, 2.0])


def caps_per_slice(p, bits):
    return bits if p.get("unit_caps") else 2 ** (bits - 1) - 1


def cell(p, vdd, fmt):
    wb = fmt["wbits"]
    slice_bits = [min(4, wb - 4 * i) for i in range(fmt["slices"])]
    n_caps = sum(caps_per_slice(p, b) for b in slice_bits)
    sram = k.get("sram8t_bitcell_um2" if p.get("unit_caps") else "sram6t_bitcell_um2")
    feol = wb * (sram + 3 * p["tg_um2"]) * p["route_overhead"]
    beol = n_caps * p["cu_fF"] / k.get("mom_cap_density_fF_per_um2")
    return dict(area_um2_per_weight=max(feol, beol), feol_um2=feol, beol_um2=beol,
                c_weight_fF=caps_per_slice(p, slice_bits[0]) * p["cu_fF"],   # per slice, on its column
                e_write_fJ_per_bit=p["bl_c_fF"] * vdd ** 2,
                t_write_row_ns=4 * k.get("fo4_delay_ps", vdd) * 1e-3,
                leak_nW_per_weight=wb * p["sram_leak_pA_per_bit"] * 1e-3 * k.get("vdd_nom"))  # at VDD_nom; model applies n9 leak_scale
