"""N9 circuits & operating point at ASAP7.

VDD scaling (derived from asap7 tables): dynamic energy x (V/0.7)^2, delay x
FO4(V)/FO4(0.7), leakage power x (V/0.7) x 10^((V-0.7) DIBL/SS) with DIBL 70 mV/V,
SS 65 mV/dec (projected FinFET values). Clock = clk_nom_GHz / delay scale x clk_frac.
"""
from arch_eval import asap7 as k

OPTIONS = {
    "asap7_rvt": dict(params=dict(clk_nom_GHz=1.0, dibl_V_per_V=0.07, ss_V_per_dec=0.065),
                      provenance="asap7 FO4/energy tables; DIBL/SS projected"),
}
DEFAULT = "asap7_rvt"
SWEEP = dict(vdd=[0.45, 0.5, 0.6, 0.7], clk_frac=[1.0, 0.5, 0.25])


def op(p, vdd, clk_frac=1.0):
    v0 = k.get("vdd_nom")
    ds = k.get("fo4_delay_ps", vdd) / k.get("fo4_delay_ps", v0)
    return dict(vdd=vdd, clk_frac=clk_frac, e_scale=(vdd / v0) ** 2, delay_scale=ds,
                leak_scale=(vdd / v0) * 10 ** ((vdd - v0) * p["dibl_V_per_V"] / p["ss_V_per_dec"]),
                clk_GHz=p["clk_nom_GHz"] / ds * clk_frac)
