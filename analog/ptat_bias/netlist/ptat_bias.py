"""PTAT current reference -> softmax tail bias. Prints the bare .subckt deck.

Delta-VGS-over-R PTAT (AnalogIOC components/ptat_bias, device for device). Two
subthreshold NMOS of equal W with tied gates carry a K:1 current ratio forced by a
PMOS mirror (K units on the diode leg), so the source of the 1x leg sits
    V(src_r) = I_ptat * R ~ UT * ln(K) (weak inversion, bulk at vss)   -> I ~ T
A 1-unit PMOS copies I_ptat into a diode-connected replica of the softmax tail device
and exports its gate as vb_tail, so the softmax tail mirrors I_ptat 1:1.

Sizing (spec: analog/ptat_bias/docs/architecture.md), W = I / J_D(gm/ID, L) through
docs/gmid.py, L = 1 um everywhere (AnalogIOC's L: long channel for mirror gds/matching):
  tail replica  (25, 1.0) nfet  softmax tail coordinate at I_B (translinear_softmax)
  core mnl/mnr  (25, 1.0) nfet  the tail device (AnalogIOC): the 1x (R) leg deep in weak
                                inversion at I_B so the ln(K) law holds; the Kx diode
                                leg shares its W at K x the density. (26, 1.0) was
                                tried: no MC gain (the tail/replica pair dominates),
                                worse line regulation (DIBL share of V(src_r) grows)
  mirror units  (18, 1.0) pfet  matching range: sigma(I)/I = gm/ID * A_vt / sqrt(WL);
                                MC 3sigma: (16) 2.7 um 31 %, (17) 5.3 um 28 %, (18)
                                48.5 um 19.5 %; 4x (18)'s area gives no further gain
  R             V(src_r) = [VGS(K*J) - VGS(J)] / n from the same nfet table, n from
                its weak-inversion gm/ID ceiling (body effect of mnr's raised source).
                First order: the table is VDS = 0.9 V, so mnr's DIBL (VDS ~0.7 vs mnl
                ~0.5 V) is missing and I_b lands ~21 % above I_B — R is the trim knob
                (AnalogIOC trimmed it too), and the spec band is centred there.
  startup       self-disabling: mstart (min size) pulls vb_p to vss while its gate su is
                high; a weak gate-grounded pfet pulls su up, msn (a copy of mnl, gate nl,
                K*I_B at the op point) pulls it down once the loop runs. The pull-up is
                sized for I_B (square law, up_cox, Vov = VDD - VGS_p(mirror)) so msn
                wins K:1, and split into two series halves: Philis lays a long-L device
                out ~3L wide (L = 64.8 um became a 196 um cell, outside the die).
                Rejected: a diode vb_p -> nl (cannot pull vb_p under nl + VT_n, which at
                -40 C is above VDD - VT_p, so the loop stays off; leaks at 125 C, line
                regulation 23 %); a min-L pull-up gated by nl (stays on at the op point:
                I_dd 11 uA and line 23 % at ff 125 C).
Topology changes vs AnalogIOC: `Rstart 50meg` (8.7 mm of xhigh poly) -> the 4-FET startup
(AnalogIOC's own docstring describes an `Mstart` that self-shuts); `Rtie nout vb_tail 1`
(a 1-ohm wire) -> one net.

Ports: vb_tail vdd vss
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, poly_res  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import numpy as np  # noqa: E402
import spicerack as ps  # noqa: E402

PORTS = ["vb_tail", "vdd", "vss"]

# ponytail: softmax architecture constants — belong in specs.py once translinear_softmax
# migrates (both blocks read them); kept here meanwhile.
I_B = specs.I_B
GMID_TAIL = specs.gmid_softmax()
K = 4               # PMOS-mirror current ratio -> V(src_r) ~ UT ln K

L_CORE = specs.L_SOFTMAX
GMID_MIR = 18.0     # mirror: matching range (I_b spread is mirror-dominated)
UT0 = 1.380649e-23 * 300.15 / 1.602176634e-19   # kT/q at 27 C (physics)


def _vgs_at(j, L, dev="nfet"):
    """|VGS| at drain current density j [A/um], log-interpolated on the gm/ID table."""
    t = gmid.load_table(dev, L)
    keep = np.concatenate([[True], np.diff(t["ID_per_W"]) > 0])   # monotone part
    return float(gmid.pchip(np.log(t["ID_per_W"][keep]), t["VGS"][keep], np.log(j)))


def sizes(pdk=None):
    """{device: (W, L)} in um plus 'r_ptat' [ohm]. AnalogIOC hand values (ptat_bias.py):
    tail 47.4/1.0, core 47.4/1.0, mirror unit 10/1.0, R 86k (trimmed in its tb),
    Rstart 50 Mohm."""
    pdk = pdk or get_pdk()
    L = L_CORE
    w_core = I_B / float(gmid.J_D(GMID_TAIL, L, "nfet"))   # = tail W
    j_r = I_B / w_core
    n = 1 / (float(gmid.load_table("nfet", L)["gm_ID"].max()) * UT0)   # slope factor
    v_src = (_vgs_at(K * j_r, L) - _vgs_at(j_r, L)) / n
    # startup pull-up: I_B with its gate at vss (square law), as two series halves
    vov = pdk.vdd - float(gmid.VGS(GMID_MIR, L, "pfet"))
    l_pu = pdk.up_cox * 1e-6 / 2 * pdk.min_w * vov ** 2 / I_B / 2
    return {
        "tail": (round(w_core, 2), L),
        "core": (round(w_core, 2), L),
        "mirror": (round(I_B / float(gmid.J_D(GMID_MIR, L, "pfet")), 2), L),
        "pullup": (pdk.min_w, round(l_pu, 1)),
        "startup": (pdk.min_w, L),
        "r_ptat": v_src / I_B,
    }


def build(pdk=None, name="ptat_bias", sz=None):
    pdk = pdk or get_pdk()
    sz = sz or sizes(pdk)
    s = ps.Subcircuit(name, PORTS)
    # PMOS mirror: mpr = 1-unit reference (diode, R leg), K units feed the diode leg nl,
    # mpo copies the 1-unit current into the tail replica.
    for u in range(K):
        fet(s, f"mpl{u}", "nl", "vb_p", "vdd", "vdd", "pfet", *sz["mirror"], pdk=pdk)
    fet(s, "mpr", "vb_p", "vb_p", "vdd", "vdd", "pfet", *sz["mirror"], pdk=pdk)
    fet(s, "mpo", "vb_tail", "vb_p", "vdd", "vdd", "pfet", *sz["mirror"], pdk=pdk)
    # NMOS core, gates tied to the Kx diode leg; the 1x leg's source drops UT ln K on R.
    fet(s, "mnl", "nl", "nl", "vss", "vss", "nfet", *sz["core"], pdk=pdk)
    fet(s, "mnr", "vb_p", "nl", "src_r", "vss", "nfet", *sz["core"], pdk=pdk)
    # low-tempco poly: sky130's dense xhigh_po (tc1 -1.47e-3/K) adds +9 % over 27->85 C
    # and broke AnalogIOC's slope band (+31 %); AnalogIOC's R was ideal (tc = 0)
    poly_res(s, "rptat", "src_r", "vss", sz["r_ptat"], "vss", pdk=pdk, kind="res_poly_lotc")
    fet(s, "mtailrep", "vb_tail", "vb_tail", "vss", "vss", "nfet", *sz["tail"], pdk=pdk)
    # startup: su high only while nl (the core current) is low
    fet(s, "mpu0", "pu", "vss", "vdd", "vdd", "pfet", *sz["pullup"], pdk=pdk)
    fet(s, "mpu1", "su", "vss", "pu", "vdd", "pfet", *sz["pullup"], pdk=pdk)
    fet(s, "msn", "su", "nl", "vss", "vss", "nfet", *sz["core"], pdk=pdk)
    fet(s, "mstart", "vb_p", "su", "vss", "vss", "nfet", *sz["startup"], pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
