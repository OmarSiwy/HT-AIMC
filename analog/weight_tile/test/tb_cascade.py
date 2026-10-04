"""K* super-tile cascade, tile side (law:cascade, sec:supertile).

K back-to-back 16-cycle nibble windows accumulate IN CHARGE on the same column C_int,
then ONE conversion at a Kx coarser LSB. Tile: REAL pass_05_typ_attn_q caps (16x16 +
ABFT checksum column, D=1); windows drawn under AnalogIOC's headroom guard (every running
per-column |mac| <= 170 < MAC_MAX, prefix property so K = 1, 2, 4 share the draws).

Asserts (spec rows, analog/weight_tile/docs/architecture.md):
  1. charge accumulates linearly across windows: per column, the integrator excursion
     after K windows (x=0 baseline subtracted), read in code units and divided by ONE
     per-column gain fitted over K = 1..4, sits within 1 LSB (= K*D units) of
     sum_k Wq @ x_k, for K = 1, 2, 4. The gain is the converter's per-column
     calibration (A10); it is reported next to specs.multibank_efficiency().
  2. chain time matches specs.cascade_window_chain_time(K) (K windows + ONE conversion)
     within 40 ns and beats K x chain(1) for K > 1 — schedule arithmetic, AnalogIOC's.

Port of AnalogIOC analog/testbenches/tb_cascade.py. Not ported (needs integrator_conv,
not migrated): the converted codes vs golden eventrate_convert and the energy/pass
assert (E_chain(K)/K < E_chain(1)). Here the windows are separated by GAP (so each
K-prefix can be read settled from one run; C_int holds its charge across a gap exactly as
it does across the parked converter) and each column runs as a 1-column tile
(AnalogIOC diag_multibank: the deficit is per column, 1-col == 17-col).

    python3 tb_cascade.py [cols...]      # or $COLS="8 11 16"; default: all 17 columns
"""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from tile import T_START, TQ, U1, at, clocks, drive, testbench  # noqa: E402
from bench import Report  # noqa: E402
import specs  # noqa: E402
import weight_tile as wt  # noqa: E402

sys.path.insert(0, str(HERE.parents[2] / "scripts"))
from golden import model as G  # noqa: E402

KS = [1, 2, 4]
K_DRAW = max(KS)
MAC_GUARD = 170          # tb_tile_mvm's proven OTA headroom guard (< MAC_MAX 185)
PASS_DIR = HERE / "data" / "pass_05_typ_attn_q"
GAP = 6 * TQ             # settle gap after each window (tau_absorb ~ 26 ns)
PERIOD = 16 * TQ + GAP
JOBS = int(os.environ.get("JOBS", 4))


def pick_windows(Wq, chk, rng, k=K_DRAW, nib_max=15, tries=5000):
    """K_DRAW signed-nibble vectors whose per-column RUNNING mac sums all stay inside the
    headroom guard, with non-trivial traffic per window (AnalogIOC verbatim)."""
    W17 = np.vstack([Wq, chk[None, :]])
    for _ in range(tries):
        xs = rng.integers(-nib_max, nib_max + 1, size=(k, 16))
        macs = xs @ W17.T
        run = np.cumsum(macs, axis=0)
        if np.abs(run).max() > MAC_GUARD:
            continue
        if np.abs(macs).max(axis=1).min() < 32:
            continue
        if np.abs(run[-1]).max() < 96:
            continue
        return xs, macs
    raise RuntimeError(f"no legal window set at nib_max={nib_max}")


def chain_schedule(K, cmax):
    """AnalogIOC's chain instants (run_window's schedule): (t_win, t_end, n_coarse)
    relative to T_START."""
    cadence = specs.coarse_cadence()
    t_win = T_START + 16 * K * TQ
    t_c0 = t_win + 8 * TQ + 1e-9
    t_c0 = T_START + np.ceil((t_c0 - T_START) / TQ) * TQ
    n_coarse = min(cmax + 4, 17)
    t_sar = t_c0 + n_coarse * cadence + 10e-9
    t_end = t_sar + 45e-9 + 3 * 35e-9 + 55e-9
    return t_win - T_START, t_end - T_START, n_coarse


def column_run(cp, cn, xs):
    """vout minus its pre-window value at the end of every window's settle gap."""
    t_end = T_START + K_DRAW * PERIOD
    tb = testbench(cp, cn)
    clocks(tb, TQ, t_end)
    drive(tb, xs, period=PERIOD)
    tb.save("V(vout)")
    d = tb.transient(step_time=0.1e-9, end_time=t_end)
    v0 = at(d, "vout", T_START - 1e-9)
    return [at(d, "vout", T_START + (k + 1) * PERIOD - 2e-9) - v0 for k in range(K_DRAW)]


def column(j, Cp, Cn, chk, xs):
    """(measured units after windows 1..K_DRAW, n_banks) for data column j (16 = chk)."""
    if j < 16:
        cp, cn = [int(v) for v in Cp[j]], [int(v) for v in Cn[j]]
    else:
        cp, cn = [max(int(c), 0) for c in chk], [max(-int(c), 0) for c in chk]
    x = column_run(cp, cn, [[int(xs[k][i]) for k in range(K_DRAW)] for i in range(16)])
    z = column_run(cp, cn, [[0] * K_DRAW for _ in range(16)])
    return [(a - b) / U1 for a, b in zip(x, z)], sum(cp) + sum(cn)


def main():
    cols = [int(a) for a in (sys.argv[1:] or os.environ.get("COLS", "").split())] \
        or list(range(17))
    r = Report("weight_tile cascade (K-window charge accumulation)")
    exp = json.loads((PASS_DIR / "expected.json").read_text())
    Cp, Cn, chk = wt.read_caps(PASS_DIR / "caps.spice")
    D = int(exp["D"])
    Wq = Cp.astype(np.int64) - Cn.astype(np.int64)
    xs, macs = pick_windows(Wq, chk.astype(np.int64), np.random.default_rng(11))
    run = np.cumsum(macs, axis=0)                     # (K_DRAW, 17) exact running mac
    print(f"  window macs (17-col max |.|): {[int(np.abs(m).max()) for m in macs]}, "
          f"running max {int(np.abs(run).max())} <= {MAC_GUARD}")

    with ThreadPoolExecutor(JOBS) as ex:
        res = dict(zip(cols, ex.map(lambda j: column(j, Cp, Cn, chk, xs), cols)))

    worst = {K: 0.0 for K in KS}
    print(f"  {'col':>4}{'units':>7}{'gain':>8}{'eff(A9)':>9}  " +
          "".join(f"{'K=' + str(K) + ' mac/meas':>20}" for K in KS))
    for j in cols:
        meas, nb = res[j]
        m, e = np.array(meas), run[:, j].astype(float)
        g = float(m @ e / (e @ e)) if e @ e else 1.0   # one gain per column
        line = f"  {j:>4}{nb:>7}{g:>8.3f}{specs.multibank_efficiency(nb):>9.3f}  "
        for K in KS:
            err = m[K - 1] / g - e[K - 1]
            worst[K] = max(worst[K], abs(err) / (K * D))
            line += f"{int(e[K - 1]):>9d}/{m[K - 1] / g:>+8.1f}{'*' if abs(err) > K * D else ' '}  "
        print(line)
    for K in KS:
        r.check(f"K={K}: every column within 1 LSB ({K * D} units) after per-column gain",
                worst[K] <= 1, f"worst {worst[K]:.2f} LSB")

    chains = {}
    for K in KS:
        cmax = int(G.eventrate_convert(run[K - 1], K * D)["coarse"].max())
        _, chain, n_coarse = chain_schedule(K, cmax)
        law = specs.cascade_window_chain_time(K, window="lo", n_coarse=n_coarse)
        chains[K] = chain
        r.check(f"K={K}: chain matches the law", abs(chain - law) <= 40e-9,
                f"chain {chain * 1e9:.0f} ns vs law {law * 1e9:.0f} ns")
    for K in KS[1:]:
        r.check(f"K={K}: chain < K x chain(1)", chains[K] < K * chains[1],
                f"{chains[K] * 1e9:.0f} vs {K * chains[1] * 1e9:.0f} ns")
    r.done()


if __name__ == "__main__":
    main()
