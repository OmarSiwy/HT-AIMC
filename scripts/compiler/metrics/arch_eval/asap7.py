"""ASAP7 constants: asap7_constants.json (owned by another agent) over literature fallbacks.

Every key -> {"value", "unit", "label": measured|derived|projected, "source"}.
`get(key)` returns the value; `get(key, vdd=V)` interpolates a '<key>@<V>' table when
one exists, else falls back to the documented law for that key. `report()` lists
which keys came from the file and which fell back, so the CLI can say so.
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
FILE = HERE / "asap7_constants.json"
GMID = HERE.parents[3] / "analog/docs/asap7/results.json"

P = "projected"


def _e(value, unit, label, source):
    return dict(value=value, unit=unit, label=label, source=source)


# Fallbacks. 'projected' = literature/law only; nfet_* from this repo's ASAP7 gm/Id run.
FALLBACK = {
    "vdd_nom": _e(0.7, "V", P, "ASAP7 nominal (Clark 2016, mej_paper_asap7.pdf)"),
    "kT_300K_J": _e(1.380649e-23 * 300.0, "J", "derived", "k_B x 300 K"),
    "fo4_delay_ps": _e(10.0, "ps", P, "7 nm-class FO4 at 0.7 V, literature ~8-12 ps"),
    "inv_switch_energy_fJ": _e(0.3, "fJ", P, "~0.6 fF switched x 0.49 V^2 (INVx1 in+out)"),
    "dff_energy_fJ": _e(1.5, "fJ", P, "7 nm DFF per clock incl. clock pin, literature"),
    "dff_area_um2": _e(0.29, "um2", P, "ASAP7 DFFHQNx1 ~20 CPP x 0.27 um"),
    "nand2_area_um2": _e(0.087, "um2", P, "ASAP7 NAND2x1 ~6 CPP x 0.27 um"),
    "sram6t_bitcell_um2": _e(0.027, "um2", P, "N7 HD 6T bitcell (industry)"),
    "sram8t_bitcell_um2": _e(0.045, "um2", P, "~1.6x 6T (8T read port)"),
    "mom_cap_density_fF_per_um2": _e(5.0, "fF/um2", P, "M1-M5 MOM finger stack at 36-48 nm pitch, literature"),
    "unit_cap_min_fF": _e(0.5, "fF", P, "smallest matched MOM unit reported at FinFET nodes"),
    "cap_match_sigma_pct_at_1fF": _e(0.5, "%", P, "MOM matching ~0.3-1 % at 1 fF, literature"),
    "avt_mV_um": _e(1.2, "mV*um", P, "FinFET A_VT ~1-1.5 mV*um"),
    "nfet_ileak_per_fin_nA": _e(0.5, "nA", P, "RVT Ioff per fin at 0.7 V, literature"),
    "vt_rvt_V": _e(0.37, "V", P, "results.json lin-extrap fallback"),
    "vt_lvt_V": _e(0.30, "V", P, "results.json lin-extrap fallback"),
    "vt_slvt_V": _e(0.24, "V", P, "results.json lin-extrap fallback"),
    "nfet_id_per_fin_uA": _e(31.4, "uA", P, "results.json fallback"),
    "nfet_cgg_per_fin_aF": _e(59.8, "aF", P, "results.json fallback"),
    "nfet_gm_over_id_max_per_V": _e(37.6, "1/V", P, "results.json fallback"),
    "nfet_ft_GHz": _e(306.8, "GHz", P, "results.json fallback"),
    "switch_ron_ohm_per_fin": _e(1.0e4, "ohm", P, "triode Ron ~ 1/(mu Cox W/L (VDD-Vt)) at 0.7 V"),
    "switch_coff_aF_per_fin": _e(20.0, "aF", P, "overlap + junction per fin"),
    "wire_c_fF_per_um": _e(0.2, "fF/um", P, "generic min-pitch wire"),
    "wire_r_ohm_per_um": _e(40.0, "ohm/um", P, "M2 36 nm pitch, literature"),
    "comparator_energy_fJ": _e(10.0, "fJ", P, "StrongARM at FinFET nodes, ~mV noise"),
    "comparator_offset_sigma_mV": _e(5.0, "mV", P, "uncalibrated min-size StrongARM"),
    "sar_adc_fom_fJ_per_step": _e(1.0, "fJ/step", P, "Walden FoM of 7-16 nm SARs (Murmann survey)"),
    "sky130_fo4_delay_ps": _e(45.0, "ps", P, "sky130 hd FO4 at 1.8 V, used only to port sky130 timing"),
}
# Alpha-power law (alpha=1.3, Vt_eff=0.25 V) and CV^2 for the VDD tables.
_VS = (0.45, 0.5, 0.6, 0.7)


def _alpha(v):
    return v / (v - 0.25) ** 1.3


for _v in _VS:
    FALLBACK[f"fo4_delay_ps@{_v}"] = _e(10.0 * _alpha(_v) / _alpha(0.7), "ps", P, "alpha-power law from fo4_delay_ps")
    FALLBACK[f"inv_switch_energy_fJ@{_v}"] = _e(0.3 * (_v / 0.7) ** 2, "fJ", P, "CV^2 from inv_switch_energy_fJ")


def _gmid():
    try:
        g = json.loads(GMID.read_text())["gmid"]["nmos_rvt"]
    except (OSError, KeyError, ValueError):
        return {}
    src = "ESPice BSIM-CMG sweep, analog/docs/asap7/results.json (nmos_rvt)"
    return {"nfet_id_per_fin_uA": _e(g["id_per_fin_vdd_uA"], "uA", "measured", src),
            "nfet_cgg_per_fin_aF": _e(g["cgg_per_fin_vdd_aF"], "aF", "measured", src),
            "nfet_gm_over_id_max_per_V": _e(g["gm_id_max"], "1/V", "measured", src),
            "nfet_ft_GHz": _e(g["ft_peak_GHz"], "GHz", "measured", src),
            "vt_rvt_V": _e(g["vt_lin_extrap_V"], "V", "measured", src)}


def _load():
    table = dict(FALLBACK, **_gmid())
    origin = {k: "fallback" for k in table}
    err = None
    try:
        raw = json.loads(FILE.read_text())
        for k, e in raw.items():
            if isinstance(e, dict) and isinstance(e.get("value"), (int, float)):
                table[k], origin[k] = e, "file"
    except FileNotFoundError:
        err = "asap7_constants.json absent: all keys on fallbacks"
    except (OSError, ValueError) as x:
        err = f"asap7_constants.json unreadable ({x}): all keys on fallbacks"
    return table, origin, err


TABLE, ORIGIN, LOAD_ERROR = _load()


def entry(key):
    return TABLE[key]


def get(key, vdd=None):
    if vdd is None:
        return float(TABLE[key]["value"])
    pts = sorted((float(k.split("@")[1]), float(e["value"])) for k, e in TABLE.items()
                 if k.startswith(key + "@"))
    if not pts:
        raise KeyError(f"{key}@V table missing")
    v, y = np.array(pts).T
    return float(np.interp(vdd, v, y))


def label(key):
    return TABLE[key]["label"]


def report():
    n_file = sum(o == "file" for o in ORIGIN.values())
    return dict(file=str(FILE), load_error=LOAD_ERROR, keys_from_file=n_file,
                keys_on_fallback=sorted(k for k, o in ORIGIN.items() if o == "fallback"))


REQUIRED = [k for k in FALLBACK if k != "sky130_fo4_delay_ps"]
