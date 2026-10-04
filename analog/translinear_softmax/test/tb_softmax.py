"""8-input translinear softmax: KCL checksum, softmax shape, subthreshold beta, settle, energy.

Spec rows (analog/translinear_softmax/docs/architecture.md), AnalogIOC's contract:
  1. KCL checksum: sum of mirrored output currents = tail current within 1 %, every pattern
  2. shares vs softmax(beta*V): per-branch rel err < 10 % over 3 patterns (equal, ramp,
     mixed); beta self-calibrated from the ramp (ln I vs V least squares) — the compiler
     applies the same calibration when mapping scores, so this checks the exponential
     COMPETITION (shape). The equal pattern checks uniformity (beta-independent).
  3. subthreshold operating point: beta in 20..30 /V at 27 C (the gm/ID band), scaled
     T0/T at other temperatures (beta = 1/(n*UT))
  4. settle (P0 -> P1 step, slowest output into its 2 % band) and energy per window

Changes from AnalogIOC (analog/testbenches/tb_softmax.py, ngspice batch -> SpiceRack):
  * vb_tail: AnalogIOC forced 0.44 V. Here I_B feeds a diode-connected copy of the tail
    (what ptat_bias's replica does in the system), so corners measure the block at its
    design current, not a fixed subthreshold VGS (I_b 0.58 -> 2.2 uA over 27 -> 85 C
    in AnalogIOC). The fixed-bias case lives on in tb_softmax_drift (config A).
  * tail current: AnalogIOC probed the tail device's @m[id]; here it is the current out of
    the vss port (all branch current returns through the tail), so va/pex DUTs measure
    the same thing.
  * patterns: AnalogIOC's, re-centred from 0.75 V onto the derived score-window centre
    (netlist score_window()); outputs held at VDD/2 (AnalogIOC 0.9 V).
  * temperature: $TEMP (AnalogIOC looped 27/55/85 C inside the tb; corners.py sweeps it).
    The PTAT ratio-drift study is tb_softmax_drift.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "translinear_softmax" / "netlist"),
                str(A / "ptat_bias" / "netlist"), str(A / "rescale" / "netlist")]
import numpy as np  # noqa: E402

import specs  # noqa: E402
from bench import Report, testbench  # noqa: E402
from devices import fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from rescale import _fingered  # noqa: E402
from translinear_softmax import I_B, N, PORTS, score_window, sizes, vb_tail  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VOUT = specs.VCM_FRAC * VDD          # column-side loads (AnalogIOC 0.9 V)
V_CM = sum(score_window()) / 2       # AnalogIOC 0.75 V
T0 = 300.15
T_WIN = 3e-6                         # per-pattern settling window (AnalogIOC)
PATTERNS = [[V_CM + v - 0.75 for v in p] for p in (
    [0.75] * 8,                                               # equal
    [0.80, 0.783, 0.766, 0.749, 0.732, 0.715, 0.698, 0.681],  # ramp (beta fit)
    [0.79, 0.71, 0.75, 0.68, 0.77, 0.69, 0.73, 0.71],         # mixed
)]
KCL_TOL = 0.01
REL_TOL = 0.10
BETA_BAND = (20.0, 30.0)             # /V at 27 C
SETTLE_MAX = 1.5e-6                  # 2 % band, half the read window (AnalogIOC 0.99 us)
SETTLE_BAND = 0.02
E_MARGIN = 1.3                       # energy <= 1.3 x ideal 2*I_b*VDD per window


def temp_c():
    return float(os.environ.get("TEMP", 27))


def bench(bias="replica", **kw):
    """Testbench with supplies, VDD/2 output loads and the tail bias:
    replica  I_B into a diode copy of the tail (ptat_bias stand-in)
    fixed    vb_tail at the gm/ID design VGS (AnalogIOC's 0.44 V)
    ptat     ptat_bias (its build()) with this block's tail as the replica"""
    tb = testbench("translinear_softmax", PORTS, **kw)
    tb.options(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")   # AnalogIOC TIGHT
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    if bias == "replica":
        tb.I(name="bt", positive="0", negative="vb_tail", value=I_B)
        fet(SimpleNamespace(raw_spice=tb.extra_line), "rep", "vb_tail", "vb_tail", "0", "0",
            "nfet", *_fingered(*sizes()["tail"]))
    elif bias == "fixed":
        tb.V(name="bt", positive="vb_tail", negative="0", value=vb_tail())
    else:
        import ptat_bias
        sz = ptat_bias.sizes(PDK)
        sz["tail"] = _fingered(*sizes()["tail"])[:2]   # replica = this tail (docs: ptat_bias change)
        tb.add_subcircuit(ptat_bias.build(PDK, sz=sz))
        tb.extra_line("Xpt vb_tail vdd 0 ptat_bias")
    for i in range(N):
        tb.V(name=f"o{i}", positive=f"iout{i}", negative="0", value=VOUT)
    return tb


def outputs(r, k=-1):
    """(branch output currents [A] as array, tail current [A]) at sample k."""
    return np.array([r[f"i(vo{i})"][k] for i in range(N)]), abs(r["i(vss)"][k])


def run():
    """Transient over the three patterns, T_WIN each."""
    tb = bench()
    for i in range(N):
        pts = [(0, PATTERNS[0][i])]
        for p in range(1, len(PATTERNS)):
            pts += [(p * T_WIN, PATTERNS[p - 1][i]), (p * T_WIN + 10e-9, PATTERNS[p][i])]
        pts.append((len(PATTERNS) * T_WIN, PATTERNS[-1][i]))
        tb.PieceWiseLinearVoltageSource(name=f"in{i}", positive=f"vin{i}", negative="0",
                                        values=pts)
    return tb.transient(step_time=2e-9, end_time=len(PATTERNS) * T_WIN, max_time=10e-9)


def settled_idx(t, p):
    """Sample index at the end of pattern window p (20 ns before the switch)."""
    return int(np.argmin(np.abs(np.asarray(t) - ((p + 1) * T_WIN - 20e-9))))


def beta_fit(i_out, v):
    """Least-squares slope of ln I vs V."""
    return float(np.polyfit(np.asarray(v), np.log(i_out), 1)[0])


def main():
    temp = temp_c()
    r = Report("translinear_softmax")
    d = run()
    t = np.asarray(d.time)
    idx = [settled_idx(t, p) for p in range(len(PATTERNS))]
    beta = beta_fit(outputs(d, idx[1])[0], PATTERNS[1])
    print(f"  score window {score_window()} V, CM {V_CM:.3f} V, beta = {beta:.2f} /V")

    for p, (pat, k) in enumerate(zip(PATTERNS, idx)):
        i_m, itail = outputs(d, k)
        ksum = abs(i_m.sum() - itail) / itail
        r.check(f"P{p}: KCL checksum < 1 %", ksum < KCL_TOL,
                f"sum {i_m.sum() * 1e9:.2f} nA, tail {itail * 1e9:.2f} nA, err {ksum * 100:.3f} %")
        v = np.array(pat)
        gold = np.exp(beta * (v - v.max()))
        gold /= gold.sum()
        rel = np.abs(i_m / i_m.sum() - gold) / gold
        r.check(f"P{p}: per-branch rel err vs softmax(beta*V) < 10 %", rel.max() < REL_TOL,
                f"worst {rel.max() * 100:.2f} % (branch {int(rel.argmax())})")

    lo, hi = (b * T0 / (temp + 273.15) for b in BETA_BAND)
    r.check(f"subthreshold OP: beta in {lo:.1f}..{hi:.1f} /V (20..30 at 27 C, x T0/T)",
            lo < beta < hi, f"{beta:.2f} /V")

    w = (t >= T_WIN) & (t < 2 * T_WIN)
    worst = 0.0
    for i in range(N):
        y = np.asarray(d[f"i(vo{i})"])[w]
        out = np.abs(y - y[-1]) > SETTLE_BAND * abs(y[-1])
        worst = max(worst, t[w][np.where(out)[0][-1]] - T_WIN if out.any() else 0.0)
    r.check(f"settle P0->P1, all outputs to 2 % < {SETTLE_MAX * 1e6:.1f} us",
            worst < SETTLE_MAX, f"{worst * 1e6:.2f} us")

    ivdd = -np.asarray(d["i(vsup)"])
    e = float(np.sum(np.diff(t) * (ivdd[1:] + ivdd[:-1]) / 2)) * VDD / len(PATTERNS)
    itail = outputs(d, idx[0])[1]
    e_max = E_MARGIN * 2 * itail * VDD * T_WIN
    r.check(f"energy per {T_WIN * 1e6:.0f} us window <= {E_MARGIN} x 2 I_b VDD T",
            e <= e_max, f"{e * 1e12:.2f} pJ ({e / T_WIN * 1e6:.2f} uW), I_b "
            f"{itail * 1e9:.1f} nA, limit {e_max * 1e12:.2f} pJ")
    r.done()


if __name__ == "__main__":
    main()
