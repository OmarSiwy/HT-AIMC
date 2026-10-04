"""StrongARM latch comparator — topology + gm/ID sizing. Prints the bare .subckt deck.

Used by the column readout (integrator_conv: event-rate coarse loop + SAR fine).
Convention (drain-side outputs): vinp > vinn -> outp resolves LOW; clk low precharges
both outputs to vdd.

Sizing (spec: analog/strongarm/docs/architecture.md):
  tail   clocked switch, min size, VGS = VDD: sets I_TAIL, the current the pair and
         the latch share at the clock edge.
  input  gm/ID = 13 (moderate inversion: gm for noise/offset per uA while staying
         fast), I_TAIL/2 per side at the edge. L is searched up from Lmin until the
         pair's MEASURED offset (docs/mismatch.py, the PDK's own mismatch at that W/L
         and current) fits the 3-sigma budget (W re-derived from gm/ID at each L).
         Pelgrom was tried first and under-predicted sky130 short-L mismatch ~1.7x.
  latch  gm/ID = 8 (strong inversion: regeneration speed), L = Lmin. Same I_TAIL/2 per
         side once the pair hands over; PMOS sized for the same gm at that current.
         (A 4x-longer latch left the Monte Carlo sigma unchanged, 4.71 -> 4.57 mV, and
         broke the 125 C corners: the pair, not the latch, sets the offset.)
  reset  precharge switch (triode, no gm/ID coordinate). The node it charges is set by
         the latch, so it scales with the latch PMOS at AnalogIOC's ratio (1.0/4.5 um),
         which met outputs-high in < 0.5 ns.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import mismatch  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["vinp", "vinn", "outp", "outn", "clk", "vdd", "vss"]

GMID_IN = 13.0   # moderate inversion
VOS_3SIGMA = 10e-3   # spec: 3-sigma input offset (docs/architecture.md)
PAIR_SHARE = 0.9     # of the offset variance allotted to the input pair
GMID_LATCH = 8.0  # strong inversion
RESET_RATIO = 1.0 / 4.5   # reset W / latch PMOS W (AnalogIOC sizing, PDK-independent)


def sizes(pdk=None):
    """{device: (W, L)} in um, derived from the active PDK's gm/ID tables."""
    pdk = pdk or get_pdk()
    L = pdk.min_l
    # Tail: min-size switch driven to VDD. I_TAIL = J_D(VGS=VDD) * W_min.
    t = gmid.load_table("nfet", L)
    j_tail = float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd))
    i_side = j_tail * pdk.min_w / 2
    # Input pair: smallest L (in Lmin steps) meeting the budget on measured mismatch.
    sigma_max = VOS_3SIGMA / 3 * PAIR_SHARE ** 0.5 * 1e3      # mV
    for k in range(1, 21):
        L_in = round(k * L, 3)
        W_in = round(float(i_side / gmid.J_D(GMID_IN, L_in, "nfet")), 2)
        if mismatch.pair_offset("nfet", W_in, L_in, i_side, pdk) <= sigma_max:
            break
    else:
        raise ValueError("input pair cannot meet the offset budget within 20*Lmin")
    L_lt = L
    w_ln = round(float(i_side / gmid.J_D(GMID_LATCH, L_lt, "nfet")), 2)
    w_lp = round(float(i_side / gmid.J_D(GMID_LATCH, L_lt, "pfet")), 2)
    return {
        "tail": (pdk.min_w, L),
        "input": (W_in, L_in),
        "latch_n": (w_ln, L_lt),
        "latch_p": (w_lp, L_lt),
        "reset": (max(pdk.min_w, round(RESET_RATIO * w_lp, 2)), L),
    }


def build(pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit("strongarm", PORTS)
    fet(s, "tail", "tail", "clk", "vss", "vss", "nfet", *sz["tail"], pdk=pdk)
    fet(s, "inp", "drn_p", "vinp", "tail", "vss", "nfet", *sz["input"], pdk=pdk)
    fet(s, "inn", "drn_n", "vinn", "tail", "vss", "nfet", *sz["input"], pdk=pdk)
    fet(s, "xnp", "outp", "outn", "drn_p", "vss", "nfet", *sz["latch_n"], pdk=pdk)
    fet(s, "xnn", "outn", "outp", "drn_n", "vss", "nfet", *sz["latch_n"], pdk=pdk)
    fet(s, "xpp", "outp", "outn", "vdd", "vdd", "pfet", *sz["latch_p"], pdk=pdk)
    fet(s, "xpn", "outn", "outp", "vdd", "vdd", "pfet", *sz["latch_p"], pdk=pdk)
    fet(s, "rstp", "outp", "clk", "vdd", "vdd", "pfet", *sz["reset"], pdk=pdk)
    fet(s, "rstn", "outn", "clk", "vdd", "vdd", "pfet", *sz["reset"], pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
