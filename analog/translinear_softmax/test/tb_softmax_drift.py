"""Translinear softmax: PTAT ratio-drift study (AnalogIOC tb_softmax.py ratio_drift_study).

A fixed reference score pattern (CM + spread, +-70 mV) is driven at three temperatures;
the winning branch's share must stay put. beta = 1/(n*UT) ~ 1/T moves it, so:
  (A) fixed bias,  fixed input   baseline (vb_tail at the gm/ID design VGS)
  (B) PTAT bias,   fixed input   ptat_bias drives vb_tail: I_b tracks T, ratios still move
  (C) PTAT bias,   PTAT input    spread co-scaled T/T0 (the compiler's ptat_score_gain),
                                 so beta*dV is invariant
Spec rows (docs/architecture.md): KCL checksum < 1 % in every config and temperature;
win-share drift of (C) < 5 % and smaller than (A)'s.

Temperatures: $TEMP, $TEMP + 28, $TEMP + 58 C (minus above 67 C), so at 27 C this is
AnalogIOC's 27/55/85 C study unchanged. DC operating points (AnalogIOC ran a 2 us transient
per point and read its end). ptat_bias is built with this block's tail as its replica.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import numpy as np  # noqa: E402

from bench import Report  # noqa: E402
from tb_softmax import N, T0, V_CM, VDD, bench, outputs  # noqa: E402

STUDY_DV = np.array([0.070, 0.035, 0.010, -0.010, -0.020, -0.035, -0.050, -0.070])
DRIFT_MAX = 5.0        # % win-share drift, config C
KCL_TOL = 0.01


def shares(temp, spread, bias):
    """(shares, KCL error, I_b) at the DC operating point."""
    tb = bench(bias, temp=temp)
    for i in range(N):
        tb.V(name=f"in{i}", positive=f"vin{i}", negative="0", value=V_CM + spread[i])
    r = tb.dc(Vsup=slice(VDD, VDD + 1e-3, 1e-2))
    i_m, itail = outputs(r, 0)
    return i_m / i_m.sum(), abs(i_m.sum() - itail) / itail, itail


def main():
    t1 = float(os.environ.get("TEMP", 27))
    sgn = 1 if t1 <= 67 else -1
    temps = [t1, t1 + sgn * 28, t1 + sgn * 58]
    r = Report("translinear_softmax drift")
    win = int(np.argmax(STUDY_DV))
    kcl_worst, drift = 0.0, {}
    for label, bias, ptat_in in (("A fixed-bias/fixed-in", "fixed", False),
                                 ("B PTAT-bias /fixed-in", "ptat", False),
                                 ("C PTAT-bias /PTAT-in", "ptat", True)):
        w, ib = [], []
        for t in temps:
            g = (t + 273.15) / T0 if ptat_in else 1.0
            sh, kcl, itail = shares(t, STUDY_DV * g, bias)
            w.append(sh[win])
            ib.append(itail)
            kcl_worst = max(kcl_worst, kcl)
        drift[label] = (w[2] - w[0]) / w[0] * 100
        print(f"  {label}: win-share " + " / ".join(f"{x * 100:5.1f}" for x in w)
              + " %  I_b " + " / ".join(f"{x * 1e9:.0f}" for x in ib)
              + f" nA  ->  drift {temps[0]:g}->{temps[2]:g} C = {drift[label]:+6.1f} %")
    dA, dC = drift["A fixed-bias/fixed-in"], drift["C PTAT-bias /PTAT-in"]
    r.check("KCL checksum < 1 % (all configs/temps)", kcl_worst < KCL_TOL,
            f"worst {kcl_worst * 100:.3f} %")
    r.check("ratio drift < 5 % with PTAT bias + PTAT input, and below baseline",
            abs(dC) < DRIFT_MAX and abs(dC) < abs(dA), f"C {dC:+.2f} % vs A {dA:+.2f} %")
    r.done()


if __name__ == "__main__":
    main()
