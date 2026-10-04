"""Level-1 group combine stage (AnalogIOC Chip 2 B4/B5, cross-bank) — topology + sizing.
Prints the bare .subckt deck.

A second shared-source translinear stage, driven by the G banks' V_ls readouts instead
of raw scores: one tail sink on the group source node, one NMOS branch per bank (gate =
that bank's level-shifted V_ls). KCL on the group node splits the tail as
    I_b = I_B * e^(beta*V_ls,b) / sum_c e^(beta*V_ls,c) = I_B * l_b / l_group
so the mirrored branch currents are the per-bank rescale weights g_b, and the group
source node itself (port vls_group) carries ln l_group = logsumexp of logsumexps, in the
same log code as the level-0 banks. Topology, ports and port order are AnalogIOC's
(schematics/components/softmax_combine/softmax_combine.py); G = 2 (mini scale; the
120 mV window holds G <= 16).

Sizing (spec: analog/softmax_combine/docs/architecture.md). The stage is a softmax bank
of N = G, so every device takes the level-0 bank's coordinate: beta must be identical
across levels (CHIP2_SPEC R1/R2), and the same vb_tail drives both. The coordinate is
derived once, in rescale.sizes() (the B5 pair, the same two-branch circuit), and
imported, not re-derived:
  tail, branch  gm/ID = 0.91 x weak-inversion ceiling at I_B; L stepped up from min_l
                until the pair meets its share of VOS_SOFTMAX on the PDK's measured
                mismatch. AnalogIOC 47.4/1.0 (hand, gm/ID 25).
  mirror        lowest gm/ID leaving the branch V_DS_MIN at the window top; L stepped
                until it meets its offset share. AnalogIOC 5.0/1.0 (hand).
Offset: a group weight g_b errs exactly like a rescale g, so the rescale's offset
budget (VOS_SOFTMAX, same devices, same currents) is this stage's too.
"""
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "rescale" / "netlist")]
import rescale  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

G = 2                   # mini group size (AnalogIOC; window holds G <= 16)


def ports(g=G):
    return ([f"vls{b}" for b in range(g)] + [f"igrp{b}" for b in range(g)]
            + ["vls_group", "vb_tail", "vdd", "vss"])


PORTS = ports()


def sizes(pdk=None):
    """{device: (W, L, nf)} in um: the level-0 bank coordinate (rescale.sizes)."""
    sz = rescale.sizes(pdk or get_pdk())
    return {k: rescale._fingered(*sz[src]) for k, src in
            (("tail", "tail"), ("branch", "branch"), ("mirror", "mirror"))}


def build(pdk=None, name="softmax_combine", g=G):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    s = ps.Subcircuit(name, ports(g))
    fet(s, "tail", "vls_group", "vb_tail", "vss", "vss", "nfet", *sz["tail"], pdk=pdk)
    for b in range(g):
        fet(s, f"b{b}", f"d{b}", f"vls{b}", "vls_group", "vss", "nfet", *sz["branch"], pdk=pdk)
        fet(s, f"md{b}", f"d{b}", f"d{b}", "vdd", "vdd", "pfet", *sz["mirror"], pdk=pdk)
        fet(s, f"mo{b}", f"igrp{b}", f"d{b}", "vdd", "vdd", "pfet", *sz["mirror"], pdk=pdk)
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
