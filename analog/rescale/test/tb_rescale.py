"""Rescale ratio pair: g = ilo/ihi vs exp(beta*dV), bias, settling, energy.

Spec rows (analog/rescale/docs/architecture.md):
  g(dV=0) = 1 +- G0_TOL                       (AnalogIOC measured 1.0000)
  g <= 1 and monotone over dV = -120..0 mV    (AnalogIOC: g <= 1 by construction)
  exponential law: max |g / e^(beta*dV) - 1| <= LAW_TOL, beta the fitted slope
                                              (AnalogIOC threshold 6 %, raw, no PTAT),
                                              at the score CM and at the window top
  beta_fit within BETA_TOL of the softmax bank's beta (rescale.beta_ref: the weak-
                                              inversion gm/ID ceiling, scaled 1/T;
                                              AnalogIOC measured 27.0 /V at 27 C)
  g(t) within 1 % (absolute, of the normalizer ihi) of its final value within T_WIN
    after a 0 -> -120 mV step                 (AnalogIOC read g at the end of T_WIN)
  energy per evaluation (T_WIN window) <= E_MARGIN x the ideal 2 I_B VDD T_WIN
                                              (AnalogIOC measured ~6.2 pJ = 1.15x)

Bias: the tail is current-referenced, as in the system (a bias generator mirrors I_B
onto vb_tail): vb_tail is swept at dV = 0 and set where ihi + ilo = I_B, so corners
see the design current, not a drifting fixed-voltage bias (AnalogIOC R2: 0.58 -> 2.2 uA
over 27 -> 85 C at a fixed 0.44 V).
Loads: ihi/ilo held at VOUT (the ~0.9 V column-side loads, A6); vhi at the score CM.

New testbench from AnalogIOC's use in tb_online_softmax_analog.py (part 2, rescale
accuracy) and tb_combine_tree.py (the B5 pair). tb_combine_tree's B5 == group-weight
cross-check needs softmax_combine and belongs to that block.
"""
import math
import os
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "rescale" / "netlist")]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
import specs  # noqa: E402
from rescale import I_B, PORTS, beta_ref, score_window, vb_tail  # noqa: E402

VDD = get_pdk().vdd
VOUT = specs.VCM_FRAC * VDD   # column-side load potential (A6 virtual ground)
SCORE_BOTTOM, SCORE_TOP = score_window()   # top: least branch Vds under the mirror
SCORE_CM = (SCORE_BOTTOM + SCORE_TOP) / 2  # AnalogIOC 0.75 V
DV_MIN = -0.120          # score spread (CHIP2_SPEC 2.4: <= 120 mV)
DV_STEP = 0.010
T_WIN = 3e-6             # evaluation window (AnalogIOC tb_online_softmax T_WIN)

G0_TOL = 0.01
LAW_TOL = 0.06
BETA_TOL = 0.10
SETTLE_TOL = 0.01
E_MAX = 1.3 * 2 * I_B * VDD * T_WIN


def temp_k():
    return float(os.environ.get("TEMP", 27)) + 273.15


def bench(vbt, vlo=SCORE_CM, vhi=SCORE_CM):
    tb = testbench("rescale", PORTS)
    tb.options(reltol=1e-4, method="gear")
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="bt", positive="vb_tail", negative="0", value=vbt)
    tb.V(name="hi", positive="vhi", negative="0", value=vhi)
    if vlo is not None:
        tb.V(name="lo", positive="vlo", negative="0", value=vlo)
    tb.V(name="ih", positive="ihi", negative="0", value=VOUT)
    tb.V(name="il", positive="ilo", negative="0", value=VOUT)
    return tb


def bias():
    """vb_tail where ihi + ilo = I_B at dV = 0 (log-interpolated DC sweep)."""
    v0 = vb_tail()
    r = bench(v0).dc(Vbt=slice(v0 - 0.25, v0 + 0.25, 0.005))
    vs, i = list(r.sweep), [a + b for a, b in zip(r["i(vih)"], r["i(vil)"])]
    for k in range(1, len(vs)):
        if i[k - 1] < I_B <= i[k]:
            f = math.log(I_B / i[k - 1]) / math.log(i[k] / i[k - 1])
            return vs[k - 1] + f * (vs[k] - vs[k - 1])
    raise RuntimeError(f"I_B {I_B:.2e} A not reached over vb_tail sweep ({i[0]:.2e}..{i[-1]:.2e})")


def transfer(vbt, vhi=SCORE_CM):
    """(dV list, g list, supply current at dV=0) from a DC sweep of vlo below vhi."""
    r = bench(vbt, vhi=vhi).dc(Vlo=slice(vhi + DV_MIN, vhi + 1e-6, DV_STEP))
    dv = [v - vhi for v in r.sweep]
    g = [lo / hi for lo, hi in zip(r["i(vil)"], r["i(vih)"])]
    return dv, g, abs(r["i(vsup)"][-1])


def beta_fit(dv, g):
    """Least-squares slope of ln g vs dV through the origin."""
    return sum(x * math.log(y) for x, y in zip(dv, g)) / sum(x * x for x in dv)


def law_error(dv, g):
    """(beta_fit, worst |g / e^(beta*dV) - 1|)."""
    b = beta_fit(dv, g)
    return b, max(abs(y / math.exp(b * x) - 1) for x, y in zip(dv, g))


def settle_time(vbt):
    """Time for g = ilo/ihi to enter +-SETTLE_TOL of its final value after a vlo
    step to DV_MIN (error on the normalizer's scale: g multiplies a partial that is
    summed with the new block's, whose weight is 1)."""
    t0, end = 0.5e-6, 6e-6
    tb = bench(vbt, vlo=None)
    tb.PieceWiseLinearVoltageSource(name="lo", positive="vlo", negative="0", values=[
        (0, SCORE_CM), (t0, SCORE_CM), (t0 + 1e-9, SCORE_CM + DV_MIN), (end, SCORE_CM + DV_MIN)])
    r = tb.transient(step_time=5e-9, end_time=end, max_time=10e-9)
    t = r.time
    g = [lo / hi for lo, hi in zip(r["i(vil)"], r["i(vih)"])]
    last_out = max((k for k in range(len(t)) if abs(g[k] - g[-1]) > SETTLE_TOL), default=0)
    return t[min(last_out + 1, len(t) - 1)] - t0


def main():
    r = Report("rescale")
    vbt = bias()
    print(f"  vb_tail for I_B = {I_B * 1e9:.0f} nA: {vbt:.3f} V (gm/ID design {vb_tail():.3f} V)")
    dv, g, i_sup = transfer(vbt)
    beta, law = law_error(dv, g)
    b_ref = beta_ref(temp_k() - 273.15)
    for x, y in zip(dv, g):
        print(f"    vhi={SCORE_CM:.3f} V  dV={x * 1e3:+6.0f} mV  g={y:.4f}  e^(beta*dV)={math.exp(beta * x):.4f}")
    r.check("g(0) = 1", abs(g[-1] - 1) <= G0_TOL, f"g(0) = {g[-1]:.4f}")
    r.check("g <= 1 and monotone over -120..0 mV",
            all(y <= 1 + G0_TOL for y in g) and all(b > a for a, b in zip(g, g[1:])))
    r.check(f"exponential law within {LAW_TOL:.0%}", law <= LAW_TOL,
            f"worst {law * 100:.2f} % at beta = {beta:.2f} /V")
    b_top, law_top = law_error(*transfer(vbt, SCORE_TOP)[:2])
    r.check(f"exponential law within {LAW_TOL:.0%} at vhi = {SCORE_TOP} V", law_top <= LAW_TOL,
            f"worst {law_top * 100:.2f} % at beta = {b_top:.2f} /V")
    r.check(f"beta within {BETA_TOL:.0%} of the bank's", abs(beta / b_ref - 1) <= BETA_TOL,
            f"{beta:.2f} vs {b_ref:.2f} /V")
    ts = settle_time(vbt)
    r.check(f"g within {SETTLE_TOL:.0%} of final < {T_WIN * 1e6:.0f} us", ts < T_WIN, f"{ts * 1e9:.0f} ns")
    e = VDD * i_sup * T_WIN
    r.check(f"energy per evaluation < {E_MAX * 1e12:.1f} pJ", e < E_MAX, f"{e * 1e12:.2f} pJ")
    r.done()


if __name__ == "__main__":
    main()
