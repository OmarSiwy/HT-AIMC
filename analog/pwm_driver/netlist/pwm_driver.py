"""PWM row driver — topology + sizing. Prints the bare .subckt deck.

Chops the A5 PWM envelope (inp / inn, VDD pulses, width = code * t_chop) onto the
tile's two-phase switched-cap grid (AnalogIOC components/pwm_driver):

    outa = (inp & phi1e) | (inn & !phi1)   -> all C+ bottom plates of the row
    outb = (inp & !phi1) | (inn & phi1e)   -> all C- bottom plates of the row

phi1e is phi1 with a stretched fall, so every bottom edge lands in the phi1->phi2 gap
while the bank tops float: one C*VDD transfer per chop cycle, both signs by the same
mechanism. Logic = NAND-NAND (or-of-ands), then a 2-inverter buffer per line.

Sizing (spec: analog/pwm_driver/docs/architecture.md). No gm/ID coordinate here: every
device is a switch driven rail to rail, so the numbers are on-current budgets. J_ON is
the table drain-current density at |VGS| = VDD, L = min (docs/gmid.py, saturation).
  final  the row edge. 10-90 % of VDD into C_ROW is ~0.8*VDD*C_ROW / I_on; the budget
         is a third of the silicon PWM quantum, specs.t_q_floor()/3 (AnalogIOC's
         "edge < t_q/3", applied to the real t_q, not the 10 ns simulation grid).
         N and P each sized from their own J_ON -> equal rise / fall, which is what
         keeps the P-style and N-style charge fractions equal.
  logic  inv/NAND at min W for N; P = N * J_ON_n / J_ON_p (equal pull-up/down current).
  mid    tapered buffer: geometric mean of logic and final (equal fanout per stage).
"""
import math
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["inp", "inn", "phi1", "phi1e", "outa", "outb", "vdd", "vss"]

# Row load: 17 column banks + route, lumped. AnalogIOC tb_pwm_driver's value; the
# specs.t_q_floor() row model (16*15*C_u + 0.2 fF/um wire) gives ~53 fF, so 100 fF
# is the conservative design point.
C_ROW = 100e-15
EDGE_SWING = 0.8   # 10-90 %


def j_on(dev, pdk):
    """On-current density [A/um] at |VGS| = VDD, L = min."""
    t = gmid.load_table(dev, pdk.min_l)
    return float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd))


def sizes(pdk=None):
    """{stage: (Wn, Wp)} in um, L = min everywhere."""
    pdk = pdk or get_pdk()
    jn, jp = j_on("nfet", pdk), j_on("pfet", pdk)
    t_edge = specs.t_q_floor(pdk) / 3
    i_on = EDGE_SWING * pdk.vdd * C_ROW / t_edge
    final = (i_on / jn, i_on / jp)                  # AnalogIOC 4.0 / 8.0
    logic = (pdk.min_w, pdk.min_w * jn / jp)        # AnalogIOC 0.42 / 0.84 (2:1)
    mid = tuple(math.sqrt(a * b) for a, b in zip(logic, final))  # AnalogIOC min (0.42/0.84)
    return {k: tuple(round(w, 2) for w in v) for k, v in
            (("logic", logic), ("mid", mid), ("final", final))}


def build(name="pwm_driver", pdk=None):
    pdk = pdk or get_pdk()
    sz, L = sizes(pdk), pdk.min_l
    s = ps.Subcircuit(name, PORTS)

    def inv(n, out, a, stage):
        wn, wp = sz[stage]
        fet(s, f"{n}_n", out, a, "vss", "vss", "nfet", wn, L, pdk=pdk)
        fet(s, f"{n}_p", out, a, "vdd", "vdd", "pfet", wp, L, pdk=pdk)

    def nand2(n, out, a, b):
        wn, wp = sz["logic"]
        fet(s, f"{n}_p1", out, a, "vdd", "vdd", "pfet", wp, L, pdk=pdk)
        fet(s, f"{n}_p2", out, b, "vdd", "vdd", "pfet", wp, L, pdk=pdk)
        fet(s, f"{n}_n1", out, a, f"{n}_mid", "vss", "nfet", wn, L, pdk=pdk)
        fet(s, f"{n}_n2", f"{n}_mid", b, "vss", "vss", "nfet", wn, L, pdk=pdk)

    def line(n, pre, out):
        inv(f"{n}_i1", f"{n}_m", pre, "mid")
        inv(f"{n}_i2", out, f"{n}_m", "final")

    inv("ip1", "phi1_b", "phi1", "logic")
    nand2("na1", "na1", "inp", "phi1e")
    nand2("na2", "na2", "inn", "phi1_b")
    nand2("na3", "outa_pre", "na1", "na2")
    line("ba", "outa_pre", "outa")
    nand2("nb1", "nb1", "inp", "phi1_b")
    nand2("nb2", "nb2", "inn", "phi1e")
    nand2("nb3", "outb_pre", "nb1", "nb2")
    line("bb", "outb_pre", "outb")
    return s


if __name__ == "__main__":
    print(deck(build()), end="")
