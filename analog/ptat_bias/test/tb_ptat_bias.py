"""PTAT bias: tail current, PTAT slope, line regulation, supply current, startup.

Spec rows (analog/ptat_bias/docs/architecture.md). I_b is the drain current of a copy of
the softmax tail device (same W/L as the replica, gate on vb_tail, drain held at the
softmax shared-source voltage) — what translinear_softmax actually draws.
  I_b(27 C) in 0.50..0.66 uA at tt; I_b * T0/T in the corner band elsewhere
  PTAT exponent alpha = dln(I_b)/dln(T) from AnalogIOC's 27->85 C slope band 12..28 %
  line: I_b within +-LINE_TOL over VDD +-10 %
  supply current at VDD, scaled T/T0 (every leg carries a multiple of I_b)
  startup from a VDD ramp: vb_tail settles to its DC value, not the I = 0 state. Judged
  on vb_tail (dI/I = gm/ID * dV at the tail coordinate), not on the load's drain current:
  after vb_tail overshoots, ngspice's transient i(Vdt) sits ~15 % above the device's own
  channel current @m[id] for > 30 us at constant terminal voltages (reproduced with a
  second, never-disturbed copy of the device in the same deck) — a simulator artefact.

$TEMP is the measurement temperature; the slope partner is TEMP+58 C (TEMP-58 above
67 C), so at 27 C the slope check is AnalogIOC's 27->85 C self-check unchanged.
New testbench (AnalogIOC had only ptat_bias.py --check and its use in tb_softmax.py).
"""
import math
import os
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "ptat_bias" / "netlist")]
import gmid  # noqa: E402
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from ptat_bias import GMID_TAIL, PORTS, sizes  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
T0 = 27.0
DT = 58.0                       # AnalogIOC self-check span, 27 -> 85 C
V_CM_IN = 0.75                  # softmax input common mode (AnalogIOC tb_softmax STUDY_CM)
W_TAIL, L_TAIL = sizes(PDK)["tail"]
V_DS_TAIL = V_CM_IN - float(gmid.VGS(GMID_TAIL, L_TAIL))   # softmax shared-source node
LINE = 0.10                     # VDD +-10 %

# spec (docs/architecture.md)
IB_NOM = (0.50e-6, 0.66e-6)     # AnalogIOC self-check band, tt 27 C
IB_CORNER = (0.40e-6, 0.80e-6)  # I_b * T0/T, any corner: within the R-trim reach
SLOPE = (0.12, 0.28)            # AnalogIOC: 27 -> 85 C slope band
ALPHA = tuple(math.log(1 + s) / math.log((T0 + DT + 273.15) / (T0 + 273.15)) for s in SLOPE)
LINE_TOL = 0.05
IDD_MAX = 1.25 * 6 * IB_NOM[1]  # (K + 2) PTAT legs at I_b max, +25 % startup pull-up/margin
T_START = 6e-6                  # AnalogIOC self-check transient window
START_TOL = 0.01


def bench(temp):
    tb = testbench("ptat_bias", PORTS, temp=temp)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="dt", positive="dtail", negative="0", value=V_DS_TAIL)
    tb.extra_line(f"Xmtail dtail vb_tail vss vss {PDK.nfet} W={W_TAIL} L={L_TAIL}")
    return tb


def line_sweep(temp):
    """VDD swept over +-LINE -> (vdd, I_b, I_dd) lists; each point a fresh DC solve."""
    step = VDD * LINE / 4
    r = bench(temp).dc(Vsup=slice(VDD * (1 - LINE), VDD * (1 + LINE) + step / 2, step))
    return (list(r.sweep), [abs(i) for i in r["i(vdt)"]], [abs(i) for i in r["i(vsup)"]],
            list(r["vb_tail"]))


def startup(temp):
    """VDD ramps 0 -> VDD in 1 us from the all-zero state -> (t, I_b)."""
    tb = testbench("ptat_bias", PORTS, temp=temp)
    tb.PieceWiseLinearVoltageSource(name="sup", positive="vdd", negative="0",
                                    values=[(0, 0), (1e-6, VDD), (T_START, VDD)])
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="dt", positive="dtail", negative="0", value=V_DS_TAIL)
    tb.extra_line(f"Xmtail dtail vb_tail vss vss {PDK.nfet} W={W_TAIL} L={L_TAIL}")
    tb.save("V(vb_tail)")
    # ss/125 C: "timestep too small" as VDD leaves 0 unless abstol is relaxed to 0.1 nA
    # (0.02 % of I_b); gear as in AnalogIOC's decks
    tb.options(method="gear", abstol=1e-10, chgtol=1e-14)
    r = tb.transient(step_time=10e-9, end_time=T_START)
    return list(r.time), list(r["vb_tail"])


def main():
    temp = float(os.environ.get("TEMP", T0))
    t2 = temp + DT if temp <= 67 else temp - DT
    r = Report("ptat_bias")
    corner = os.environ.get("CORNER", PDK.typical)

    v, ib, idd, vb = line_sweep(temp)
    mid = len(v) // 2
    i_b = ib[mid]
    norm = i_b * (T0 + 273.15) / (temp + 273.15)
    print(f"  V_DS(tail) = {V_DS_TAIL:.3f} V, tail {W_TAIL}/{L_TAIL} um")
    if corner == PDK.typical and temp == T0:
        r.check("I_b(27 C) in 0.50..0.66 uA", IB_NOM[0] <= i_b <= IB_NOM[1],
                f"{i_b * 1e9:.1f} nA")
    r.check("I_b*T0/T in 0.40..0.80 uA", IB_CORNER[0] <= norm <= IB_CORNER[1],
            f"I_b {i_b * 1e9:.1f} nA at {temp:g} C -> {norm * 1e9:.1f} nA")

    _, ib2, _, _ = line_sweep(t2)
    lo, hi = sorted([(temp, i_b), (t2, ib2[mid])])
    alpha = math.log(hi[1] / lo[1]) / math.log((hi[0] + 273.15) / (lo[0] + 273.15))
    r.check(f"PTAT exponent in {ALPHA[0]:.2f}..{ALPHA[1]:.2f} (27->85 C slope 12..28 %)",
            ALPHA[0] <= alpha <= ALPHA[1],
            f"{lo[0]:g}->{hi[0]:g} C: {(hi[1] / lo[1] - 1) * 100:+.1f} %, alpha {alpha:.2f}")

    dev = max(abs(i / i_b - 1) for i in ib)
    r.check("I_b within +-5 % over VDD +-10 %", dev <= LINE_TOL, f"worst {dev * 100:.2f} %")
    idd_max = IDD_MAX * (temp + 273.15) / (T0 + 273.15)        # the legs are PTAT
    r.check("supply current <= 4.95 uA * T/T0", idd[mid] <= idd_max,
            f"{idd[mid] * 1e6:.2f} uA (limit {idd_max * 1e6:.2f} uA)")

    t, vst = startup(temp)
    tol = START_TOL / GMID_TAIL                                # 1 % of I_b in vb_tail
    late = [tt for tt, x in zip(t, vst) if abs(x - vb[mid]) > tol]
    r.check("startup from VDD ramp settles to DC I_b (1 %) within 6 us",
            abs(vst[-1] - vb[mid]) <= tol,
            f"vb_tail end {vst[-1] * 1e3:.2f} vs DC {vb[mid] * 1e3:.2f} mV, "
            f"settled at {(late[-1] if late else 0) * 1e6:.2f} us")
    r.done()


if __name__ == "__main__":
    main()
