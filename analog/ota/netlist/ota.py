"""Telescopic-cascode OTA — column-integrator amplifier. Prints the bare .subckt deck.

Single-ended output, NMOS input pair, cascoded PMOS mirror load (AnalogIOC
library/ota.py `ota_spice`, device for device). inp is the non-inverting input (the
feedback network goes to inn). Used by integrator_conv and lora_sidecar.

Sizing (spec: analog/ota/docs/architecture.md): specs.ota() is the single source —
gm/ID coordinates specs.OTA_COORDS at ID = specs.I_SIDE per side, W = ID / J_D(gm/ID, L)
through docs/gmid.py:
  in     (12, 0.3) nfet  moderate inversion: gm per uA for settling
  ncasc  (10, 0.3) nfet  cascode, gain boost; short L keeps its pole high
  pcasc  (10, 0.5) pfet  cascode of the load
  pmirr  (10, 0.5) pfet  mirror, long L for matching / gds
  tail   (18, 0.5) nfet  weak inversion: small Vdsat under the input pair
Telescopic (not 5T): 0.5 % settling needs loop gain > 200 and gm/gds(12, 0.3) ~ 57
alone cannot give it; the cascode stack does.

Bias (`bias()`, ideal sources in the testbenches — AnalogIOC `BIAS`/`bias_spice`): gate
voltages from the same gm/ID coordinates, VGS(gm/ID, L) lookups, with every stacked
device given Vds = Vdsat + V_HEADROOM, Vdsat ~ 2/(gm/ID). The tables are VSB = 0, so the
headroom also absorbs the cascodes' body effect.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["inp", "inn", "out", "vb_nc", "vb_pc", "vb_tail", "vdd", "vss"]
ROLES = ("ota_in", "ota_ncasc", "ota_pcasc", "ota_pmirr", "ota_tail")

# Vds margin over Vdsat for the input pair and the mirror. AnalogIOC tuned its biases
# by hand for ">= ~0.25 V of Vds margin"; 0.15 V over 2/(gm/ID) lands on them
# (vb_nc 1.25 V, vb_pc 0.29 V) — the difference is the body effect the VSB = 0 tables
# do not see.
V_HEADROOM = 0.15


def sizes(pdk=None):
    """{role: (W, L)} in um — specs.ota() at specs.I_SIDE, W floored at pdk.min_w
    (ncasc: 0.37 -> 0.42 um; Philis widens anything narrower, and the extracted device
    then no longer matches the deck). The widened cascode runs at gm/ID ~ 10.4 instead of
    10 — a cascode, so only its Vdsat moves, by ~10 mV.
    AnalogIOC hand values (sky130 `sizing`): in 0.54/0.3, ncasc 0.37/0.3,
    pcasc 2.63/0.5, pmirr 2.63/0.5, tail 7.06/0.5."""
    pdk = pdk or get_pdk()
    o = specs.ota(pdk)
    return {r: (max(o[r][0], pdk.min_w), o[r][1]) for r in ROLES}


def vsd_pm():
    """Mirror Vsd: its drain (the load cascode's source) sits this far below vdd."""
    return 2 / specs.OTA_COORDS["ota_pmirr"][0] + V_HEADROOM


def bias(pdk=None):
    """{port: V} for the three bias ports."""
    pdk = pdk or get_pdk()
    c = specs.OTA_COORDS
    vgs = {r: float(gmid.VGS(c[r][0], specs.ota_L(r, pdk), c[r][2])) for r in ROLES}
    vcm = specs.VCM_FRAC * pdk.vdd
    vds_in = 2 / c["ota_in"][0] + V_HEADROOM          # input-pair drain above ts
    return {
        # d1 = vcm - VGS_in + Vds_in; cascode gate one VGS above. AnalogIOC 1.25
        "vb_nc": round(vcm - vgs["ota_in"] + vds_in + vgs["ota_ncasc"], 3),
        # y = vdd - Vsd_pm; cascode gate one |VGS| below. AnalogIOC 0.29
        "vb_pc": round(pdk.vdd - vsd_pm() - vgs["ota_pcasc"], 3),
        # tail at its own coordinate: VGS(18, 0.5). AnalogIOC 0.665
        "vb_tail": round(vgs["ota_tail"], 3),
    }


def build(pdk=None, name="ota", nfet="nfet", pfet="pfet", sz=None):
    """The OTA subckt. `nfet`/`pfet` pick the device flavour (devices.fet kinds) and
    `sz` overrides sizes() — tb_ota_swing builds an LVT variant this way."""
    pdk = pdk or get_pdk()
    sz = sz or sizes(pdk)
    s = ps.Subcircuit(name, PORTS)
    fet(s, "tail", "ts", "vb_tail", "vss", "vss", nfet, *sz["ota_tail"], pdk=pdk)
    fet(s, "in_p", "d1", "inp", "ts", "vss", nfet, *sz["ota_in"], pdk=pdk)
    fet(s, "in_n", "d2", "inn", "ts", "vss", nfet, *sz["ota_in"], pdk=pdk)
    fet(s, "nc_l", "x1", "vb_nc", "d1", "vss", nfet, *sz["ota_ncasc"], pdk=pdk)
    fet(s, "nc_r", "out", "vb_nc", "d2", "vss", nfet, *sz["ota_ncasc"], pdk=pdk)
    fet(s, "pc_l", "x1", "vb_pc", "y1", "vdd", pfet, *sz["ota_pcasc"], pdk=pdk)
    fet(s, "pc_r", "out", "vb_pc", "y2", "vdd", pfet, *sz["ota_pcasc"], pdk=pdk)
    fet(s, "pm_l", "y1", "x1", "vdd", "vdd", pfet, *sz["ota_pmirr"], pdk=pdk)
    fet(s, "pm_r", "y2", "x1", "vdd", "vdd", pfet, *sz["ota_pmirr"], pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
