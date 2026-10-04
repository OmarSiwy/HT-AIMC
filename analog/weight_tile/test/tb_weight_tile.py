"""weight_tile: crosspoint linearity, differential null, sign mirror, cancelling column.

Spec rows (analog/weight_tile/docs/architecture.md), measured on the real column
integrator (test/tile.py, AnalogIOC's instrument):
  1. single crosspoint, nibble 10, Cp = 0..15: R^2 > 0.999 of the excursion vs code;
     slope within 10 % of the design u = nibble*C_u*VDD/C_int
  2. differential null Cp = Cn = 8: |excursion| < 1.5 LSB (LSB = u1)
  3. sign mirror, -x vs +x on Cp = 8: within 2 %
  4. cancelling column at the real worst traffic (4 rows +8 / 4 rows -8 = 32:32 units per
     cycle): |excursion| < 1.5 LSB; 64:64 (2x beyond real) reported only
Adapted from AnalogIOC analog/testbenches/tb_weight_tile.py (ngspice batch -> SpiceRack).
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile import U1, VCM, excursion  # noqa: E402  (tile.py sets the analog/ paths)
from bench import Report  # noqa: E402

NIB = 10
JOBS = int(os.environ.get("JOBS", 4))


def cancel(half):
    return excursion([8] * half + [0] * half, [0] * half + [8] * half, [NIB] * (2 * half))[0]


def main():
    r = Report("weight_tile")
    with ThreadPoolExecutor(JOBS) as ex:
        lin = [ex.submit(excursion, [w], [0], [NIB]) for w in range(16)]
        null = ex.submit(excursion, [8], [8], [NIB])
        sp, sn = ex.submit(excursion, [8], [0], [NIB]), ex.submit(excursion, [8], [0], [-NIB])
        c4, c8 = ex.submit(cancel, 4), ex.submit(cancel, 8)
        exc = np.array([f.result()[0] for f in lin])

    codes = np.arange(16)
    for w, (dv, vg) in zip(codes, [f.result() for f in lin]):
        print(f"    Cp={w:2d}: dVout {dv * 1e3:+8.3f} mV (ideal {w * NIB * U1 * 1e3:+8.3f}), "
              f"vg err {abs(vg - VCM) * 1e3:.2f} mV")
    slope, icept = np.polyfit(codes, exc, 1)
    r2 = 1 - np.sum((exc - (slope * codes + icept)) ** 2) / np.sum((exc - exc.mean()) ** 2)
    r.check("linearity R^2 > 0.999", r2 > 0.999, f"R^2 {r2:.6f}")
    r.check("slope within 10 % of design u", abs(slope / (NIB * U1) - 1) < 0.10,
            f"{slope * 1e3:.4f} mV/code = {slope / (NIB * U1) * 100:.1f} % of design, "
            f"intercept {icept * 1e3:+.3f} mV (TG injection)")

    dv = null.result()[0]
    r.check("differential null < 1.5 LSB", abs(dv) < 1.5 * U1, f"{dv * 1e3:+.3f} mV = {dv / U1:+.2f} LSB")

    dvp, dvn = sp.result()[0], sn.result()[0]
    mism = abs(dvp + dvn) / abs(dvp)
    r.check("sign mirror within 2 %", mism < 0.02,
            f"+x {dvp * 1e3:+.3f} mV, -x {dvn * 1e3:+.3f} mV, {mism * 100:.2f} %")

    dv = c4.result()
    r.check("32:32 cancelling column < 1.5 LSB", abs(dv) < 1.5 * U1,
            f"{dv * 1e3:+.3f} mV = {dv / U1:+.2f} LSB")
    dv = c8.result()
    print(f"  info  64:64 cancelling column {dv * 1e3:+.3f} mV = {dv / U1:+.2f} LSB")
    r.done()


if __name__ == "__main__":
    main()
