"""Gain-cell Monte Carlo: levels stay distinguishable cell-to-cell (signoff ladder rung 5).

The array's mismatch-sensitive metric is the read current of one stored level across
cells: write switch (injection) and read device (VGS) mismatch both move it. Per sample:
the PDK's mismatch section at the typical corner (sky130 `tt_mm`) with a fresh ngspice
seed; columns 0..3 of both arrays store levels 7, 8, 14, 15 in every row, then 8 row
reads (the tb_gain_cell read slots). Pooled over all cells and samples, per level pair
(k, k+1): 3 sigma(I_k) and 3 sigma(I_k+1) < half the mean step I_k+1 - I_k, i.e. the
3-sigma input-referred error stays under LSB/2. MC_N samples (default 30).
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_gain_cell import N, T_RD, T_WR, VCM, VDD, bench, lvl, pulse, run  # noqa: E402

MC_N = int(os.environ.get("MC_N", 30))
LEVELS = (7, 8, 14, 15)       # column c stores LEVELS[c]


def sample(seed, section):
    """{level: [read current of every cell storing it]} for one mismatch sample."""
    t_rd0 = len(LEVELS) * T_WR + 100e-9
    drive = {}
    for row in range(N):
        pts = []
        for c, k in enumerate(LEVELS):
            pts += [(c * T_WR, lvl(k)), ((c + 1) * T_WR - 1e-9, lvl(k))]
        drive[f"wdata{row}"] = pts + [(len(LEVELS) * T_WR, 0)]
        t0 = t_rd0 + row * T_RD
        drive[f"rd{row}"] = pulse(t0, t0 + 100e-9, VCM, 0)
    for c in range(N):
        drive[f"wsel{c}"] = pulse(c * T_WR + 10e-9, c * T_WR + 130e-9, 0, VDD) \
            if c < len(LEVELS) else 0.0
    tb = bench(drive, corner=section)
    tb.options(seed=seed)
    icols = [f"v{a}col{c}" for a in "kv" for c in range(len(LEVELS))]
    t, d = run(tb, 0.5e-9, t_rd0 + N * T_RD + 50e-9, *[f"I({s})" for s in icols])
    out = {k: [] for k in LEVELS}
    for row in range(N):
        w = (t > t_rd0 + row * T_RD + 40e-9) & (t < t_rd0 + row * T_RD + 90e-9)
        for s in icols:
            out[LEVELS[int(s[-1])]].append(-d[f"I({s})"][w].mean())
    return out


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"gain_cell_array MC ({MC_N} samples, {section})")
    cur = {k: [] for k in LEVELS}
    for seed in range(1, MC_N + 1):
        for k, v in sample(seed, section).items():
            cur[k] += v
    for lo, hi in zip(LEVELS[::2], LEVELS[1::2]):
        step = statistics.mean(cur[hi]) - statistics.mean(cur[lo])
        s3 = 3 * max(statistics.stdev(cur[lo]), statistics.stdev(cur[hi]))
        r.check(f"levels {lo}/{hi}: 3 sigma(I) < step/2", s3 < step / 2,
                f"mean {statistics.mean(cur[lo]) * 1e9:.4g} / {statistics.mean(cur[hi]) * 1e9:.4g}"
                f" nA, 3 sigma {s3 * 1e9:.4g} nA, step {step * 1e9:.4g} nA "
                f"(-> 3 sigma {s3 / step * 1e3 * lvl(1):.1f} mV of LSB {lvl(1) * 1e3:.0f} mV)")
    r.done()


if __name__ == "__main__":
    main()
