"""4-bit R-string write DAC — topology + sizing. Prints the bare .subckt deck.

Programs gain-cell storage nodes (gain_cell_array, lora_sidecar). AnalogIOC
components/write_dac, device for device:
  ladder   15 equal poly segments vss..vref, tap k = k*vref/15 (monotone by construction)
  decoder  per bit an inverter (b_n); per tap nand2(b3,b2 literals) + nand2(b1,b0
           literals) -> nor2 -> sel_k, inv -> seln_k (one-hot)
  mux      16 transmission gates (cmos_switch, write-DAC tap role) tap_k -> out
Ports: b0 b1 b2 b3 out vref vdd vss (b3 MSB, VDD logic). vref = the write ceiling,
V_W = specs.VCM_FRAC*VDD (AnalogIOC 0.9 V).

Sizing (spec: analog/write_dac/docs/architecture.md). No gm/ID coordinate: the
segments are passives, the TGs are triode switches and the gates switch rail to rail.
  segment  RC budget. The whole write path (ladder Thevenin + tap TG + cell switch) must
           let c_store settle in the write slot: cmos_switch.r_on_budget(). The TG was
           sized to R_GUARD of it at its worst corner; the ladder takes the rest at its
           worst tap (mid-scale Thevenin ~15R/4 = (1 - R_GUARD) * budget). The budget
           is for B_Y-bit settling; the DAC needs only 1/2 LSB of 4 bits, which covers
           the gain-cell switch in series — tb_write_dac measures that path end to end.
           Larger R_SEG = lower ladder power (vref^2 / 15 R_SEG), so R_SEG = that ceiling.
  segment  mismatch. Level accuracy is set by segment matching: with independent
  kind     sigma_R per segment, sigma(v_k) = vref*sigma_R*sqrt(k(15-k)/15^3), worst at
           mid-scale. 3*sigma(v_mid) within LEVEL_3SIGMA (variance share RES_SHARE) sets
           a minimum area, A = (a_r/sigma_R)^2. A poly device has a fixed width, so area
           = R/R_sq * w^2: at a fixed R the only way to more area is a segment of
           n_par parallel devices of n_par*R_SEG each (area n_par^2 * A). Search: fewest
           devices first (n_par = 1, 2, ...), dense kind first. The target also carries
           MC_MARGIN, the 2-sd spread of a sigma estimated from the MC_N-sample Monte
           Carlo that signs it off (v1, n_par = 1 at 3.77 mV predicted, measured 5.16 mV
           at tap 5 on 30 samples: FAIL). PDK resistor mismatch is not simulated by
           ngspice (sky130 slope_spectre = 0; gf180 has only global terms), so a_r comes
           from pdk_specs (declared from the model files) and tb_write_dac_mc adds it.
           sky130: xhigh_po 1x 8.2 mV, high_po 1x 3.77 mV (> 3.76 target), xhigh_po 2x
           4.1 mV, high_po 2x 1.88 mV -> 2 x high_po 0.35 x 61.4 um per segment.
  TG       cmos_switch default instance (it IS the write-DAC tap role).
  logic    N at min_w, P = N * J_ON_n / J_ON_p at L (equal pull-up/down current).
           Speed is irrelevant here (100 ns slots), static power is not: 132 gates sit
           idle between writes. L = smallest k*Lmin whose worst-case leakage (every logic
           FET off at the worst corner, hottest temperature) stays under LEAK_RATIO of
           the ladder's own static power. Off currents are measured with the PDK's
           models on every corner (cached in netlist/char/<pdk>.json, like cmos_switch).
           sky130 ff/125 C: pfet 1.16/0.15 leaks 171 nA (AnalogIOC's 0.84/0.15: 452 nA),
           at L = 0.30 59 pA — Lmin logic burned 1.7 pJ per 200 ns slot at ff/125 C.
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "cmos_switch" / "netlist")]
import cmos_switch  # noqa: E402
import gmid  # noqa: E402
import specs  # noqa: E402
from devices import deck, fet, poly_res  # noqa: E402
from pdk_char import ngspice  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

import spicerack as ps  # noqa: E402

PORTS = ["b0", "b1", "b2", "b3", "out", "vref", "vdd", "vss"]
N_BITS = 4
N_TAPS = 1 << N_BITS
N_SEG = N_TAPS - 1
LEVEL_3SIGMA = 5e-3   # spec: 3-sigma tap-level error (docs/architecture.md)
RES_SHARE = 0.9       # of the level-error variance allotted to segment mismatch
MC_N = 30             # Monte Carlo samples that sign the level error off (tb_write_dac_mc)
MC_MARGIN = 1 + 2 / (2 * (MC_N - 1)) ** 0.5   # 2-sd error of a sigma from MC_N samples
KINDS = ("res_poly", "res_poly_lotc")   # poly_res kinds, densest first
LEAK_RATIO = 1.0      # worst-corner logic leakage power / ladder static power
N_LOGIC_FETS = 2 * N_BITS + 14 * N_TAPS   # bit inverters + per tap 2 nand2, nor2, inv
CHAR = Path(__file__).resolve().parent / "char"


def a_r(pdk, kind):
    """sigma(dR/R)*sqrt(W*L) [um] of a poly kind; 0 = undeclared by the PDK."""
    return getattr(pdk, kind + "_a_r")


def seg_area(pdk, kind, r_seg, n_par):
    """Poly area [um^2] of one segment: n_par parallel devices of n_par*r_seg."""
    w = getattr(pdk, kind + "_w")
    return n_par * n_par * r_seg / getattr(pdk, kind + "_ohm_sq") * w * w


def sigma_mid(pdk, kind, r_seg, n_par=1):
    """3-sigma worst-tap level error [V] of the ladder from segment mismatch."""
    area = seg_area(pdk, kind, r_seg, n_par)
    k_mid = max(k * (N_SEG - k) for k in range(N_TAPS))
    return 3 * specs.VCM_FRAC * pdk.vdd * a_r(pdk, kind) / area ** 0.5 * \
        (k_mid / N_SEG ** 3) ** 0.5


def j_on(dev, pdk, L):
    """On-current density [A/um] at |VGS| = VDD."""
    t = gmid.load_table(dev, L)
    return float(gmid.pchip(t["VGS"], t["ID_per_W"], pdk.vdd))


def _i_off(pdk, corner, L, wn, wp):
    """(I_off nfet, I_off pfet) [A] at |VDS| = VDD, hottest corner temperature."""
    lines = [f"* write_dac logic leakage {corner}", pdk.lib_line(corner),
             f".temp {max(cmos_switch.TEMPS)}", f"Vd vd 0 {pdk.vdd}", f"Vs vs 0 {pdk.vdd}",
             pdk.fet_card.format(name="n", d="vd", g="0", s="0", b="0", model=pdk.nfet,
                                 w=pdk.um(wn), l=pdk.um(L), extra=""),
             pdk.fet_card.format(name="p", d="0", g="vs", s="vs", b="vs", model=pdk.pfet,
                                 w=pdk.um(wp), l=pdk.um(L), extra=""),
             ".control", "op", "let in = abs(i(Vd))", "let ip = abs(i(Vs))",
             "print in", "print ip", ".endc"]
    r = ngspice(lines)
    return r["in"], r["ip"]


def i_off(pdk, L, wn, wp):
    """Worst (I_off n, I_off p) over the PDK's corners; measured once per PDK, cached."""
    path = CHAR / f"{pdk.name}.json"
    got = json.loads(path.read_text()) if path.exists() else {}
    key = f"{L}/{wn}/{wp}/{max(cmos_switch.TEMPS)}/{','.join(pdk.corners)}"
    if key not in got:
        with ThreadPoolExecutor(len(pdk.corners)) as ex:
            res = list(ex.map(lambda c: _i_off(pdk, c, L, wn, wp), pdk.corners))
        got[key] = [max(r[0] for r in res), max(r[1] for r in res)]
        CHAR.mkdir(exist_ok=True)
        path.write_text(json.dumps(got, indent=1) + "\n")
    return got[key]


def sizes(pdk=None):
    """{"r_seg": ohm, "r_kind": poly_res kind, "r_par": devices per
    segment, "logic": (Wn, Wp, L) um} — TG sizes come from cmos_switch.sizes()."""
    pdk = pdk or get_pdk()
    # worst tap Thevenin: k(15-k)/15 * R at k = 7/8 -> 56/15 R ~= 15R/4 (AnalogIOC doc)
    r_th_per_seg = max(k * (N_SEG - k) / N_SEG for k in range(N_TAPS))
    r_seg = round((1 - cmos_switch.R_GUARD) * cmos_switch.r_on_budget(pdk) / r_th_per_seg, -2)
    budget = RES_SHARE ** 0.5 * LEVEL_3SIGMA / MC_MARGIN
    fit = next(((n, k) for n in range(1, 5) for k in KINDS
                if sigma_mid(pdk, k, r_seg, n) <= budget), None)
    if fit is None:
        raise ValueError(f"no poly segment matches to {budget * 1e3:.2f} mV at {r_seg:.0f} ohm")
    n_par, kind = fit
    if not a_r(pdk, kind):
        print(f"write_dac: {pdk.name} declares no {kind}_a_r — segment mismatch unsized",
              file=sys.stderr)
    p_ladder = (specs.VCM_FRAC * pdk.vdd) ** 2 / (N_SEG * r_seg)
    for k in range(1, 11):
        L = round(k * pdk.min_l, 3)
        wn = pdk.min_w
        wp = round(wn * j_on("nfet", pdk, L) / j_on("pfet", pdk, L), 2)
        if N_LOGIC_FETS * max(i_off(pdk, L, wn, wp)) * pdk.vdd <= LEAK_RATIO * p_ladder:
            break
    else:
        raise ValueError("logic leakage over budget up to 10*Lmin")
    return {"r_seg": r_seg,     # AnalogIOC 10k ideal R (res_high_po 1.41 um in its doc)
            "r_kind": kind, "r_par": n_par,
            "logic": (wn, wp, L)}   # AnalogIOC inv_n/inv_p 0.42/0.84 at L 0.15


def children(name="write_dac", pdk=None):
    """The tap TG, `<name>_sw` like AnalogIOC's generate(); emit before build(name)."""
    return [cmos_switch.build(f"{name}_sw", **cmos_switch.sizes(pdk=pdk), pdk=pdk)]


def build(name="write_dac", pdk=None):
    pdk = pdk or get_pdk()
    sz = sizes(pdk)
    wn, wp, L = sz["logic"]
    s = ps.Subcircuit(name, PORTS)

    def inv(n, out, a):
        fet(s, f"{n}_n", out, a, "vss", "vss", "nfet", wn, L, pdk=pdk)
        fet(s, f"{n}_p", out, a, "vdd", "vdd", "pfet", wp, L, pdk=pdk)

    # ponytail: AnalogIOC's 1 fF ideal cap on the nand2 stack node was a convergence aid,
    # not a device — dropped (pwm_driver did the same).
    def nand2(n, out, a, b):
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
        return "vss" if k == 0 else "vref" if k == N_SEG else f"tap{k}"

    for k in range(1, N_TAPS):
        for j in range(sz["r_par"]):
            poly_res(s, f"seg{k}_{j}", tap(k), tap(k - 1), sz["r_par"] * sz["r_seg"], "vss",
                     pdk=pdk, kind=sz["r_kind"])
    for b in range(N_BITS):
        inv(f"invb{b}", f"b{b}_n", f"b{b}")
    for k in range(N_TAPS):
        lit = [f"b{b}" if (k >> b) & 1 else f"b{b}_n" for b in range(N_BITS)]
        nand2(f"dh{k}", f"nh{k}", lit[3], lit[2])
        nor2(f"dl{k}", f"sel{k}", f"nh{k}", f"nl{k}")
        nand2(f"dg{k}", f"nl{k}", lit[1], lit[0])
        inv(f"dinv{k}", f"seln{k}", f"sel{k}")
        s.X(f"tg{k}", f"{name}_sw", tap(k), "out", f"sel{k}", f"seln{k}", "vdd", "vss")
    return s


if __name__ == "__main__":
    print(deck(*children(), build()), end="")
