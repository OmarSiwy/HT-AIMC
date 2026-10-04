"""Translinear rescale ratio pair (AnalogIOC Chip 2 B5) — topology + gm/ID sizing.
Prints the bare .subckt deck.

Online-softmax rescale g = ilo/ihi = exp(beta*(vlo - vhi)) <= 1 for vlo <= vhi.
Two NMOS branches share a source node s over one tail sink (a softmax bank of N=2):
KCL splits the tail current as I_hi : I_lo = e^(beta*vhi) : e^(beta*vlo). Each branch
drain is mirrored out by a PMOS diode + mirror that sources into the VDD/2 loads.
Port order and devices are AnalogIOC's (components/rescale/rescale.py).

Sizing (spec: analog/rescale/docs/architecture.md). Every L is stepped up from
pdk.min_l (doubling) until the device meets its share of the offset budget; W follows
from gm/ID at that L:
  tail    translinear coordinate: gm/ID = specs.gmid_softmax() (shared with the bank), at
          I_B. The SAME coordinate and vb_tail as the softmax bank (translinear_softmax)
          is what makes beta match between exp bank and rescale (CHIP2_SPEC R1/R2).
  branch  same coordinate and W: a branch carrying the whole I_B sits at the
          coordinate, the losing branch deeper in weak inversion.
  mirror  the lowest gm/ID whose |VGS| still leaves the branch V_DS_MIN at the top of
          the score window (current mismatch = gm/ID * dVt, so lowest is best
          matched), W = (I_B/2) / J_D at the balanced point.
Offset budget: sigma = VOS_3SIG / 3, variance split half to the branch pair, a quarter
to each mirror. Each share is checked against the PDK's own mismatch at the candidate geometry and
current (docs/mismatch.py): Pelgrom on pdk.a_vt under-predicts here, because sky130
also varies voff, which dominates in weak inversion. A mirror's dVGS refers to the input
as (gm/ID)_p / beta.
"""
import math
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import mismatch  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["vhi", "vlo", "ihi", "ilo", "vb_tail", "vdd", "vss"]

# Architecture constants shared with translinear_softmax / wta / softmax_combine (specs.py).
I_B = specs.I_B
SCORE_SPAN = specs.SCORE_SPAN
V_DS_MIN = 6 * specs.KB_T / 1.602176634e-19   # weak-inversion saturation, 6 kT/q
VOS_3SIG = specs.VOS_SOFTMAX   # MC spec: 3-sigma input-referred offset (CHIP2_SPEC T2)
L_STEPS = 7         # L = min_l * 2^k, k < L_STEPS (sky130: 0.15 .. 9.6 um)


def _l_grid(pdk):
    return [round(pdk.min_l * 2 ** k, 3) for k in range(L_STEPS)]


def _ceiling(dev, L):
    return float(gmid.load_table(dev, L)["gm_ID"].max())


def _translinear(pdk, share):
    """(W, L, gm/ID) of the tail/branch coordinate meeting the pair's offset share."""
    g = specs.gmid_softmax(pdk)   # the bank's coordinate: one gm/ID along the whole path
    for L in _l_grid(pdk):
        W = float(I_B / gmid.J_D(g, L, "nfet"))
        if mismatch.pair_offset("nfet", round(W, 2), L, I_B / 2, pdk) * 1e-3 <= share:
            return W, L, g
    raise ValueError(f"branch pair misses its offset share {share * 1e3:.2f} mV "
                     f"up to L = {_l_grid(pdk)[-1]} um")


def score_window(pdk=None):
    """(bottom, top) of the score window: bottom leaves the tail V_DS_MIN under a
    branch at the translinear coordinate. AnalogIOC 0.6-0.85 V."""
    pdk = pdk or get_pdk()
    bottom = vb_tail(pdk) + V_DS_MIN
    return round(bottom, 3), round(bottom + SCORE_SPAN, 3)


def sizes(pdk=None):
    """{device: (W, L)} in um, plus the gm/ID coordinates, for the active PDK."""
    pdk = pdk or get_pdk()
    sigma = VOS_3SIG / 3
    # tail + branch. AnalogIOC 47.4/1.0 at gm/ID 25 (its tables: 10.6 nA/um)
    w_tl, l_tl, g_tl = _translinear(pdk, sigma / math.sqrt(2))
    beta = _ceiling("nfet", l_tl)
    # mirror headroom: branch drain = VDD - |VGS_p| must stay V_DS_MIN over the source,
    # which sits at top - VGS_tl = V_DS_MIN + SCORE_SPAN
    vsd_max = pdk.vdd - SCORE_SPAN - 2 * V_DS_MIN
    for L in _l_grid(pdk):
        g_p = next((g for g in range(5, int(_ceiling("pfet", L)))
                    if gmid.VGS(g, L, "pfet") <= vsd_max), None)
        if g_p is None:
            continue
        W = float(I_B / 2 / gmid.J_D(g_p, L, "pfet"))
        dv = mismatch.pair_offset("pfet", max(round(W, 2), pdk.min_w), L, I_B / 2, pdk)
        if g_p / beta * dv * 1e-3 <= sigma / 2:
            break
    else:
        raise ValueError(f"mirror misses its offset share up to L = {_l_grid(pdk)[-1]} um")
    # AnalogIOC mirror 5.0/1.0 (chosen for low diode-node cap, not matching)
    w_tl, W = max(round(w_tl, 2), pdk.min_w), max(round(W, 2), pdk.min_w)
    return {"tail": (w_tl, l_tl), "branch": (w_tl, l_tl), "mirror": (W, L),
            "gmid": {"tl": g_tl, "mirror": g_p, "beta": beta}}


def vb_tail(pdk=None):
    """Tail gate bias for I_B: VGS at the translinear coordinate. AnalogIOC 0.44 V."""
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    return round(float(gmid.VGS(sz["gmid"]["tl"], sz["tail"][1], "nfet")), 3)


def beta_ref(temp_c=27.0, pdk=None):
    """The bank's beta: weak-inversion gm/ID ceiling at the translinear L, scaled 1/T
    (beta = 1/(n kT/q)). AnalogIOC measured the bank at 27.0 /V (tt, 27 C)."""
    return sizes(pdk)["gmid"]["beta"] * 300.15 / (temp_c + 273.15)


def fingers(W, L):
    """Even finger count for a near-square footprint (nf^2 ~ W/L); 1 when W < 2 L.
    Layout only: nf keeps the full W*L in both PDKs' mismatch terms, where m would not
    (sky130 scales mismatch by `mult`, gf180 by `par`)."""
    return max(1, 2 * round(math.sqrt(W / L) / 2))


def _fingered(W, L):
    """(W, L, nf) with W rounded up to a whole 10 nm per finger, so the layout's
    fingers draw exactly the deck's W (Philis snaps each finger to the grid)."""
    nf = fingers(W, L)
    return round(math.ceil(round(W / nf * 100, 6)) / 100 * nf, 2), L, nf


def build(pdk=None, name="rescale"):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    tl, br, mi = (_fingered(*sz[k]) for k in ("tail", "branch", "mirror"))
    s = ps.Subcircuit(name, PORTS)
    fet(s, "tail", "s", "vb_tail", "vss", "vss", "nfet", *tl, pdk=pdk)
    for lbl in ("hi", "lo"):
        fet(s, f"b{lbl}", f"d{lbl}", f"v{lbl}", "s", "vss", "nfet", *br, pdk=pdk)
        fet(s, f"md{lbl}", f"d{lbl}", f"d{lbl}", "vdd", "vdd", "pfet", *mi, pdk=pdk)
        fet(s, f"mo{lbl}", f"i{lbl}", f"d{lbl}", "vdd", "vdd", "pfet", *mi, pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
