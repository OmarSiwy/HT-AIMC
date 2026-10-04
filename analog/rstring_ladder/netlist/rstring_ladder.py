"""4b R-string ladder + transmission-gate tap mux — topology + sizing. Prints the bare deck.

AnalogIOC components/rstring_ladder, device for device. A reference ladder between two
EXTERNAL rails: 15 equal segments, tap_k = vrn + k*(vrp - vrn)/15 (tap0 = vrn,
tap15 = vrp), monotone by construction. The 4b code b3..b0 one-hots one TG onto `out`
through the write_dac decoder idiom (NAND2 / NOR2 / NAND2 + INV per tap). Serves the
coarse comparator thresholds (vcm +- 15.5*D*u) and the SAR CDAC span rails
(vcm +- 16*D*u). The tap set is static during a conversion, so ladder kickback comes only
from CDAC/comparator sampling; a per-tap decap holds it.

Sizing (spec: analog/rstring_ladder/docs/architecture.md):
  segments  poly R = specs.r_seg() (static-power budget), low-tempco poly (a reference).
  decaps    MIM, specs.c_tap() on tap1..tap14 (charge-sharing droop of the CDAC kick
            C_KICK*V_KICK/c_tap <= V_TAP_TOL/2); the rails are external.
  tap TG    triode, no gm/ID coordinate: sized from the kick-recovery budget. After the
            CDAC (C_KICK, precharged V_KICK away) is slammed onto `out`, `out` must be
            back inside V_TAP_TOL within T_KICK. Half the band is the decap's settled
            droop, so the transient decays from V_KICK to V_TAP_TOL/2 through the mux
            TG and the CDAC's own sampling switch (KICK_SCALE x the mux width, so
            R_kick = R_mux / KICK_SCALE):
                R_mux (1 + 1/KICK_SCALE) C_KICK ln(V_KICK / (V_TAP_TOL/2)) <= T_KICK
            W_p/W_n = un_cox/up_cox (cmos_switch's flat-R_on ratio). R_on peaks near
            mid-rail, where square law is ~20x optimistic (cmos_switch doc), so W_n comes
            from the TG's MEASURED peak R_on over (0, VDD) at the typical corner:
            R_on * W is constant, W_n = W_REF * R_peak(W_REF) / R_mux, times
            CORNER_GUARD for the slow/cold corners (see there).
  logic     inverter, NAND2, NOR2 all at Wn = min W, Wp = Wn * sqrt(J_n/J_p) at |VGS| =
            VDD (async_ctrl's min-average-delay P/N ratio), L = min. The code is static
            during a conversion; speed is not a budget. AnalogIOC: 0.42/0.84 everywhere.
"""
import math
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "cmos_switch" / "netlist")]
import cmos_switch  # noqa: E402
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, mim_cap, poly_res  # noqa: E402
from pdk_char import ngspice  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["b0", "b1", "b2", "b3", "out", "vrn", "vrp", "vdd", "vss"]
N_BITS = 4
N_TAPS = 1 << N_BITS

T_KICK = 5e-9       # s, AnalogIOC tb_rstring: tap outside the band < 5 ns after a kick
KICK_SCALE = 0.5    # CDAC sampling switch width / mux TG width (AnalogIOC: 4x vs 8x write_tg)
W_REF_MULT = 10     # R_on*W measured at W_REF = 10 * min W (clear of narrow-width effects)
DV = 5e-3           # V across the on TG when measuring R_on (small-signal)
# ponytail: calibration knob. The typical-corner budget leaves the kick check failing at
# ss/-40 C (12.9 ns), fs/-40 C (11.0 ns), ss/27 C (7.2 ns): mid-rail TG R_on is 28x its
# tt value at ss/-40 C, but the kick settles far better than that ratio (the wider TG's
# own C on `out` absorbs part of it). Measured on tb_rstring, worst-corner time outside
# the band / tt tap error: x2 4.50 ns / 0.30 mV, x3 2.95 / 0.43, x6 1.66 / 0.81 (the error
# grows with the switch C on `out` that the decaps have to refill; 2 mV ceiling ~ x15).
# x3 keeps >40 % margin on both. A per-corner characterisation replaces this if the
# ladder moves to another PDK/supply.
CORNER_GUARD = 3


def r_mux_budget():
    """Mux TG R_on ceiling [ohm] from the kick-recovery budget (module docstring)."""
    n_tau = math.log(specs.V_KICK / (specs.V_TAP_TOL / 2))
    return T_KICK / ((1 + 1 / KICK_SCALE) * specs.C_KICK_CDAC * n_tau)


def tg_peak_r_on(w_n, w_p, pdk=None, corner=""):
    """Peak R_on [ohm] of an on TG (L = min) over v_in in (0, VDD), one ngspice op."""
    pdk = pdk or get_pdk()
    vs = [pdk.vdd * k / 36 for k in range(1, 36)]
    lines = ["* tg peak R_on", pdk.lib_line(corner or pdk.typical), f"Vdd vdd 0 {pdk.vdd}"]
    for k, v in enumerate(vs):
        card = dict(s=f"o{k}", d=f"i{k}", l=pdk.um(pdk.min_l), extra="")
        lines += [f"Vi{k} i{k} 0 {v}",
                  pdk.fet_card.format(name=f"n{k}", g="vdd", b="0", model=pdk.nfet,
                                      w=pdk.um(w_n), **card),
                  pdk.fet_card.format(name=f"p{k}", g="0", b="vdd", model=pdk.pfet,
                                      w=pdk.um(w_p), **card),
                  f"Vd{k} i{k} o{k} {DV}"]
    lines += [".control", "op"] + [f"let r{k} = {DV}/abs(i(Vd{k}))\nprint r{k}"
                                   for k in range(len(vs))] + [".endc"]
    r = ngspice(lines)
    return max(r[f"r{k}"] for k in range(len(vs)))


def j_on(dev, pdk):
    """On-current density [A/um] at |VGS| = VDD, L = min (gm/ID table)."""
    t = gmid.load_table(dev, pdk.min_l, pdk)
    return float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd))


def sizes(pdk=None):
    """{"tg": cmos_switch W/L kwargs, "logic": (Wn, Wp), "r_seg": ohm, "c_tap": F}."""
    pdk = pdk or get_pdk()
    L, ratio = pdk.min_l, pdk.un_cox / pdk.up_cox
    w_ref = W_REF_MULT * pdk.min_w
    w_n = CORNER_GUARD * w_ref * tg_peak_r_on(w_ref, ratio * w_ref, pdk) / r_mux_budget()
    return {
        # AnalogIOC write_tg x tg_scale 8: 3.36/6.72 (docstring says "4x"; code is 8x)
        "tg": {"w_n": round(w_n, 2), "l_n": L, "w_p": round(ratio * w_n, 2), "l_p": L},
        # AnalogIOC inv_n / inv_p 0.42 / 0.84
        "logic": (pdk.min_w, round(pdk.min_w * (j_on("nfet", pdk) / j_on("pfet", pdk)) ** 0.5, 2)),
        "r_seg": specs.r_seg(pdk),     # AnalogIOC 8k (A2 hand value 200 ohm)
        "c_tap": specs.c_tap(pdk),     # AnalogIOC 29 pF
    }


def build(name="rstring_ladder", caps=True, pdk=None, sz=None):
    """(child TG subckt, ladder subckt). caps=False drops the tap decaps (Philis deck)."""
    pdk = pdk or get_pdk()
    sz = sz or sizes(pdk)
    sw = cmos_switch.build(f"{name}_sw", pdk=pdk, **sz["tg"])
    s = ps.Subcircuit(name, PORTS)
    L, (wn, wp) = pdk.min_l, sz["logic"]

    def inv(n, out, a):
        fet(s, f"{n}_n", out, a, "vss", "vss", "nfet", wn, L, pdk=pdk)
        fet(s, f"{n}_p", out, a, "vdd", "vdd", "pfet", wp, L, pdk=pdk)

    def nand2(n, out, a, b):
        """AnalogIOC nand2 minus its 1 fF ideal stack-node cap (not layout-realisable)."""
        fet(s, f"{n}_p1", out, a, "vdd", "vdd", "pfet", wp, L, pdk=pdk)
        fet(s, f"{n}_p2", out, b, "vdd", "vdd", "pfet", wp, L, pdk=pdk)
        fet(s, f"{n}_n1", out, a, f"{n}_mid", "vss", "nfet", wn, L, pdk=pdk)
        fet(s, f"{n}_n2", f"{n}_mid", b, "vss", "vss", "nfet", wn, L, pdk=pdk)

    def nor2(n, out, a, b):
        fet(s, f"{n}_p1", out, a, f"{n}_mid", "vdd", "pfet", wp, L, pdk=pdk)
        fet(s, f"{n}_p2", f"{n}_mid", b, "vdd", "vdd", "pfet", wp, L, pdk=pdk)
        fet(s, f"{n}_n1", out, a, "vss", "vss", "nfet", wn, L, pdk=pdk)
        fet(s, f"{n}_n2", out, b, "vss", "vss", "nfet", wn, L, pdk=pdk)

    def tap(k):
        return "vrn" if k == 0 else "vrp" if k == N_TAPS - 1 else f"tap{k}"

    # ladder: tap k = vrn + k*(vrp - vrn)/15
    for k in range(1, N_TAPS):
        poly_res(s, f"seg{k}", tap(k), tap(k - 1), sz["r_seg"], "vss", pdk=pdk,
                 kind="res_poly_lotc")
    if caps:
        for k in range(1, N_TAPS - 1):
            mim_cap(s, f"tap{k}", f"tap{k}", "vss", sz["c_tap"], pdk=pdk)
    for b in range(N_BITS):
        inv(f"invb{b}", f"b{b}_n", f"b{b}")
    # 4:16 decoder + TG per tap (write_dac idiom)
    for k in range(N_TAPS):
        lit = [f"b{b}" if (k >> b) & 1 else f"b{b}_n" for b in range(N_BITS)]
        nand2(f"dh{k}", f"nh{k}", lit[3], lit[2])
        nor2(f"dl{k}", f"sel{k}", f"nh{k}", f"nl{k}")
        nand2(f"dg{k}", f"nl{k}", lit[1], lit[0])
        inv(f"dinv{k}", f"seln{k}", f"sel{k}")
        s.X(f"tg{k}", f"{name}_sw", tap(k), "out", f"sel{k}", f"seln{k}", "vdd", "vss")
    return sw, s


if __name__ == "__main__":
    # rstring_ladder.py [--no-caps]
    #   --no-caps  without the 14 MIM tap decaps: Philis's feedback extraction never
    #              finishes on a deck with several cap_mim devices, so the FETs and
    #              resistors are P&R'd alone and pex.py re-adds the caps from the full deck
    print(deck(*build(caps="--no-caps" not in sys.argv)), end="")
