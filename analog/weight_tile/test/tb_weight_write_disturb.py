"""A11b, tile side: write disturb during the hold (INTERFACE §7.3 overlap, open Q10).

pass_05_typ_attn_q, the busiest column (max |mac_lo|, checksum included), LO window on
the real column integrator; then the tile clock gate parks the tile (phi1 = phi1e = 1,
phi2 = 0) and the integrator holds the residue, as during the converter's coarse + fine
conversion. Two runs: idle, and all 16 rows rewritten to the bitwise complement
(Cp -> 15 - Cp, Cn -> 15 - Cn: every one of the column's 128 bits toggles) starting
T_RW0 into the hold. The tile-level charge equivalent of A11b's "codes differ by <= 1
LSB" (the converter is not migrated yet):
  1. max |vout_rewrite - vout_idle| over the hold, from the first rewrite to the end,
     < 1 LSB (specs.u1())
  2. (sanity) the window excursion reads the column's mac within 3 LSB after k_cal and
     the busy-column multi-bank efficiency — reported, A11 gates the transfer
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tile import T_START, TQ, U1, WR_ROW, clocks, drive, testbench, writes  # noqa: E402
from bench import Report  # noqa: E402
import specs  # noqa: E402
import weight_tile as wt  # noqa: E402

sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from golden import model as G  # noqa: E402

PASS_DIR = HERE / "data" / "pass_05_typ_attn_q"
T_WIN = T_START + 16 * TQ          # window end = park
T_RW0 = 10e-9                      # first rewrite slot after the park
T_SETTLE = 30e-9                   # hold observed after the last rewrite


def column_codes():
    """(j, cp, cn, x_lo, mac_lo) of the busiest pass_05 column."""
    exp = json.loads((PASS_DIR / "expected.json").read_text())
    Cp, Cn, chk = wt.read_caps(PASS_DIR / "caps.spice")
    sign, _hi, lo = G.pwm_nibbles(np.array(exp["xq"], dtype=np.int64))
    x = (sign * lo).astype(np.int64)
    cps = [list(map(int, c)) for c in Cp] + [[max(int(c), 0) for c in chk]]
    cns = [list(map(int, c)) for c in Cn] + [[max(-int(c), 0) for c in chk]]
    macs = [int((np.array(p) - np.array(n)) @ x) for p, n in zip(cps, cns)]
    j = int(np.argmax(np.abs(macs)))
    return j, cps[j], cns[j], [int(v) for v in x], macs[j]


def run(cp, cn, x, rewrite):
    t_rw = T_WIN + T_RW0
    t_end = t_rw + len(cp) * WR_ROW + T_SETTLE
    sched = writes([15 - c for c in cp], [15 - c for c in cn], t0=t_rw) if rewrite else []
    tb = testbench(cp, cn, schedule=sched)
    clocks(tb, TQ, t_end, t_park=T_WIN)
    drive(tb, x)
    tb.save("V(vout)")
    d = tb.transient(step_time=0.1e-9, end_time=t_end)
    return np.array(d.time), np.array(d["vout"]), t_rw, t_end


def main():
    r = Report("weight_tile write disturb (A11b, tile side)")
    j, cp, cn, x, mac = column_codes()
    with ProcessPoolExecutor(2) as ex:
        idle, rw = ex.map(run, [cp] * 2, [cn] * 2, [x] * 2, (False, True))
    t_i, v_i, t_rw, t_end = idle
    t_w, v_w = rw[0], rw[1]
    grid = np.linspace(t_rw, t_end, 4000)
    dv = np.interp(grid, t_w, v_w) - np.interp(grid, t_i, v_i)
    k = int(np.argmax(np.abs(dv)))
    v0 = np.interp(T_START - 1e-9, t_i, v_i)
    exc = np.interp(T_WIN + T_RW0 - 1e-9, t_i, v_i) - v0
    nb = sum(1 for c in cp + cn if c)
    pred = mac * specs.k_cal() * specs.multibank_efficiency(nb)
    print(f"  column {j} (16 = checksum): mac_lo {mac}, {nb} nonzero banks; window "
          f"{exc / U1:+.1f} LSB vs k_cal*multibank {pred:+.1f}")
    r.check("rewrite of all 16 rows (128 bits toggle) during the hold: |dvout| < 1 LSB",
            abs(dv[k]) < U1,
            f"max {dv[k] * 1e6:+.1f} uV = {dv[k] / U1:+.3f} LSB at +{(grid[k] - t_rw) * 1e9:.1f} ns, "
            f"end {dv[-1] / U1:+.3f} LSB")
    print(f"  info  window excursion vs prediction {(exc / U1 - pred):+.1f} LSB")
    r.done()


if __name__ == "__main__":
    main()
