"""8-input translinear (subthreshold) softmax (AnalogIOC Chip 2 B4) — topology + gm/ID
sizing. Prints the bare .subckt deck.

Shared-source NMOS bank: branch i conducts
    I_i = I_b * exp(beta*V_i) / sum_j exp(beta*V_j),   beta = 1/(n*UT)
because all branches share one source node whose voltage self-adjusts until the tail
sink's I_b is satisfied — the normalisation is KCL. Each branch drain is mirrored out
by a PMOS diode + mirror that sources into the ~VDD/2 column-side loads.
Topology, ports, port order and device names are AnalogIOC's
(schematics/components/translinear_softmax/translinear_softmax.py).

Sizing (spec: analog/translinear_softmax/docs/architecture.md):
  tail, branch  one coordinate: gm/ID = specs.GMID_SOFTMAX at I_B (a branch carrying
         the whole I_B sits at the tail's coordinate, losers go deeper into weak
         inversion). L starts at specs.L_SOFTMAX and steps up the min_l grid until
         (a) a branch meets its share of the input-referred offset budget and
         (b) the tail vs its bias replica (ptat_bias mtailrep, same W/L) meets the
         I_b spread share, both on MEASURED mismatch (docs/mismatch.py). W = I_B/J_D.
  mirror the lowest gm/ID (at the balanced branch current I_B/N) whose |VGS| still
         leaves the branch V_DS_MIN when the winner carries all of I_B at the top of
         the score window; W = (I_B/N)/J_D; L up the min_l grid until the md/mo pair
         meets its offset share, referred to the input as (gm/ID)_p / beta.
Offset budget: 3 sigma = VOS_MARGIN * specs.VOS_SOFTMAX input-referred per branch, variance
half to the branch device (against the other N-1: sqrt(1 - 1/N) of one device's sigma),
half to its mirror pair. Devices stay single instances with nf fingers (rescale's rule:
`m=` would not scale mismatch area).
"""
import math
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "rescale" / "netlist")]
import gmid  # noqa: E402
import mismatch  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from rescale import _fingered  # noqa: E402

import numpy as np  # noqa: E402
import spicerack as ps  # noqa: E402

N = 8
PORTS = ([f"vin{i}" for i in range(N)] + [f"iout{i}" for i in range(N)]
         + ["vb_tail", "vdd", "vss"])

I_B = specs.I_B
GMID = specs.GMID_SOFTMAX
VOS_MARGIN = 0.8        # size to 80 % of the 3-sigma spec: a 30-sample MC sigma is +-13 %
TAIL_3SIG = 0.10        # I_b spread share, tail vs replica: 3 sigma(dI)/I (ptat_bias MC
                        # spec 20 %; its mirrors/core take the rest)
V_DS_MIN = 6 * specs.KB_T / 1.602176634e-19   # weak-inversion saturation, 6 kT/q
L_STEPS = 7             # L grid up to min_l * 2^6 (sky130 9.6 um)


def _l_grid(pdk, floor=0.0):
    """floor, then min_l * 2^k above it: the L values the search may pick."""
    grid = [round(pdk.min_l * 2 ** k, 3) for k in range(L_STEPS)]
    return ([floor] if floor else []) + [L for L in grid if L > floor]


def _vgs_at(j, L, dev):
    """|VGS| at drain current density j [A/um] (log-interpolated gm/ID table)."""
    t = gmid.load_table(dev, L)
    keep = np.concatenate([[True], np.diff(t["ID_per_W"]) > 0])
    return float(gmid.pchip(np.log(t["ID_per_W"][keep]), t["VGS"][keep], np.log(j)))


def _gmid_at(j, L, dev):
    return float(gmid.gm_ID(_vgs_at(j, L, dev), L, dev))


def sizes(pdk=None):
    """{device: (W, L)} in um plus the gm/ID coordinates. AnalogIOC hand values:
    tail/branch 47.4/1.0 (gm/ID 25 on its own tables), mirror 5.0/1.0."""
    pdk = pdk or get_pdk()
    sigma = VOS_MARGIN * specs.VOS_SOFTMAX / 3
    share = sigma / math.sqrt(2)                 # per-branch share, branch or mirror
    for L in _l_grid(pdk, specs.L_SOFTMAX):
        W = round(float(I_B / gmid.J_D(GMID, L, "nfet")), 2)
        br = mismatch.sigma_vgs("nfet", W, L, I_B / N, pdk) * math.sqrt(1 - 1 / N) * 1e-3
        if br > share:
            continue
        tail = 3 * GMID * mismatch.pair_offset("nfet", W, L, I_B, pdk) * 1e-3
        if tail <= TAIL_3SIG:
            break
    else:
        raise ValueError("tail/branch coordinate misses its offset shares on the L grid")
    w_tl, l_tl = W, L
    beta = float(gmid.load_table("nfet", l_tl)["gm_ID"].max())   # weak-inversion ceiling
    vsd_max = pdk.vdd - specs.SCORE_SPAN - 2 * V_DS_MIN
    for L in _l_grid(pdk):
        g_p = next((g for g in range(5, int(gmid.load_table("pfet", L)["gm_ID"].max()))
                    if _vgs_at(I_B / max(pdk.min_w, I_B / N / gmid.J_D(g, L, "pfet")),
                               L, "pfet") <= vsd_max), None)
        if g_p is None:
            continue
        W = max(pdk.min_w, round(float(I_B / N / gmid.J_D(g_p, L, "pfet")), 2))
        g_act = _gmid_at(I_B / N / W, L, "pfet")
        if g_act / beta * mismatch.pair_offset("pfet", W, L, I_B / N, pdk) * 1e-3 <= share:
            break
    else:
        raise ValueError("mirror misses its offset share on the L grid")
    return {"tail": (w_tl, l_tl), "branch": (w_tl, l_tl), "mirror": (W, L),
            "gmid": {"tl": GMID, "mirror": g_act, "beta": beta}}


def vb_tail(pdk=None):
    """Tail gate bias for I_B at the coordinate (what a replica bias applies). AnalogIOC 0.44 V."""
    return round(float(gmid.VGS(GMID, sizes(pdk)["tail"][1], "nfet")), 3)


def score_window(pdk=None):
    """(bottom, top) of the score window: bottom leaves the tail V_DS_MIN under a winner
    at the coordinate, top = bottom + specs.SCORE_SPAN. AnalogIOC 0.6-0.85 V."""
    bottom = vb_tail(pdk) + V_DS_MIN
    return round(bottom, 3), round(bottom + specs.SCORE_SPAN, 3)


def build(pdk=None, name="translinear_softmax"):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    tl, br, mi = (_fingered(*sz[k]) for k in ("tail", "branch", "mirror"))
    s = ps.Subcircuit(name, PORTS)
    fet(s, "tail", "s", "vb_tail", "vss", "vss", "nfet", *tl, pdk=pdk)
    for i in range(N):
        fet(s, f"b{i}", f"d{i}", f"vin{i}", "s", "vss", "nfet", *br, pdk=pdk)
        fet(s, f"md{i}", f"d{i}", f"d{i}", "vdd", "vdd", "pfet", *mi, pdk=pdk)
        fet(s, f"mo{i}", f"iout{i}", f"d{i}", "vdd", "vdd", "pfet", *mi, pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
