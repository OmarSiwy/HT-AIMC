"""A11, tile side: write through the port, read back by MAC (INTERFACE §11 A11 SPICE subset).

A 16-row programmable column on the real column integrator (COLS columns, default 1:
a 16 x 17 run costs ~17x a column — the full-width MAC readback is the analog top's A11;
the wd -> (column, bit) mapping of all 17 columns is checked bit by bit on the storage
nodes by tb_weight_write). Rows 0 and 15 are written through wwl/wd, every other row 0.
Per column j the pattern type is (v,0) / (0,v) / (v,v) by (j + rot) mod 3, v random
0..15 per cell; each rotation runs with v and again with 15 - v, so every bit of rows 0
and 15 is written both 0 and 1 (6 runs). Read back with two LO windows per run: nibble 7
on row 0 only, then on row 15 only (D = 1). The tile-level charge equivalent of the code
(the converter is not migrated yet): excursion / u1 / k_cal per window.
  1. every column, both rows, every run: |read - 7*(Cp - Cn)| <= 3 LSB, which
     identifies W uniquely (adjacent W are 7 LSB apart)
  2. (info) how many reads fall outside +-1 LSB (CONTRACT acceptance 1's original bar)

    python3 tb_weight_readback.py [runs...]     # subset of 0..5, default all
"""
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tile import T_START, TQ, U1, at, clocks, drive, testbench, vout  # noqa: E402
from bench import Report  # noqa: E402
import specs  # noqa: E402

ROWS = (0, specs.N_ROWS - 1)
NIB = 7
TOL = 3
GAP = 4 * TQ                       # settle after each window
PERIOD = 8 * TQ + GAP              # nibble 7 needs 7 chop cycles
SEED = 11
JOBS = int(os.environ.get("JOBS", 6))
N_COLS = int(os.environ.get("COLS", 1))


def pattern(run):
    """(Cp, Cn) [col][row] of one run: rotation run//2, v (even run) or 15 - v (odd)."""
    rng = np.random.default_rng(SEED + run // 2)
    v = rng.integers(0, 16, (N_COLS, len(ROWS)))
    v = v if run % 2 == 0 else 15 - v
    cp = np.zeros((N_COLS, specs.N_ROWS), dtype=int)
    cn = np.zeros_like(cp)
    for j in range(N_COLS):
        kind = (j + run // 2) % 3
        for r, i in enumerate(ROWS):
            cp[j, i] = v[j, r] if kind in (0, 2) else 0
            cn[j, i] = v[j, r] if kind in (1, 2) else 0
    return cp, cn


def readback(run):
    """Measured LSB per (window = row, column), shape (len(ROWS), N_COLS)."""
    cp, cn = pattern(run)
    t_end = T_START + len(ROWS) * PERIOD
    tb = testbench(cp.tolist(), cn.tolist())
    clocks(tb, TQ, t_end)
    drive(tb, [[NIB if i == r else 0 for r in ROWS] for i in range(specs.N_ROWS)],
          period=PERIOD)
    outs = [vout(j) for j in range(N_COLS)]
    tb.save(*(f"V({o})" for o in outs))
    d = tb.transient(step_time=0.1e-9, end_time=t_end)
    marks = [T_START - 1e-9] + [T_START + (k + 1) * PERIOD - 2e-9 for k in range(len(ROWS))]
    v = np.array([[at(d, o, t) for o in outs] for t in marks])
    return np.diff(v, axis=0) / U1 / specs.k_cal(), cp, cn


def main():
    runs = [int(a) for a in sys.argv[1:]] or list(range(6))
    r = Report("weight_tile write -> MAC readback (A11, tile side)")
    with ProcessPoolExecutor(min(JOBS, len(runs))) as ex:
        res = dict(zip(runs, ex.map(readback, runs)))
    worst, n_out1, n = 0.0, 0, 0
    for run in runs:
        meas, cp, cn = res[run]
        for k, i in enumerate(ROWS):
            want = NIB * (cp[:, i] - cn[:, i])
            err = meas[k] - want
            worst = max(worst, float(np.abs(err).max()))
            n_out1 += int(np.sum(np.abs(err) > 1))
            n += len(err)
            bad = [f"c{j}:{want[j]:+d}/{meas[k][j]:+.1f}" for j in np.where(np.abs(err) > TOL)[0]]
            print(f"  run {run} row {i:2d}: max |err| {np.abs(err).max():.2f} LSB, mean "
                  f"{err.mean():+.2f}" + (f"  FAIL {' '.join(bad)}" if bad else ""))
    print(f"  info  {n_out1}/{n} reads outside +-1 LSB")
    r.check(f"every read within {TOL} LSB of 7*W (rows {ROWS}, {N_COLS} columns, "
            f"{len(runs)} runs)", worst <= TOL, f"worst {worst:.2f} LSB")
    r.done()


if __name__ == "__main__":
    main()
