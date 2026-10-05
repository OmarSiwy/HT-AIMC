"""lora_sidecar Monte Carlo (signoff ladder rung 5): golden agreement under mismatch.

Per sample (the PDK's mismatch section, sky130 `tt_mm`, fresh seed): the tb_lora_sidecar
program, the per-chip calibration (reference passes -> levels, rho) and one x = 0 pass —
the A3/A4 zero-point every column already gets: it removes the comparator / integrator
offset mismatch (a fixed window per chip) — then a LO verification pass with a fresh
random signed x. A sample passes when every column of (Delta mac - zero point) is within
max(TOL_ABS, TOL_REL) of the golden term. Spec: yield >= MC_YIELD over MC_N samples
(default 30, MC_JOBS run side by side).
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lora_bench as LB  # noqa: E402
from bench import Report  # noqa: E402

MC_N = int(os.environ.get("MC_N", 30))
MC_JOBS = int(os.environ.get("MC_JOBS", 4))
MC_YIELD = 0.9


def sample(seed, section):
    rng = np.random.default_rng(1000 + seed)
    guess = [0.0] + [((m + 1.5) / 8.5) ** 2 for m in range(1, 8)]
    a, _, x = LB.random_case(rng, guess, a_fixed={i: LB.WMAX for i in range(LB.CAL_ROWS)},
                             rows=range(LB.CAL_ROWS, LB.N))
    run = LB.Run()
    LB.cal_program(run, {i: int(a[i]) for i in range(LB.CAL_ROWS, LB.N)})
    pp, pn = LB.cal_passes(run)
    p0 = run.lora_pass(np.zeros(LB.N, int), "lo", "x=0")
    p = run.lora_pass(x, "lo", "lo")
    run.simulate(corner=section, seed=seed)
    cal = LB.calibrate(run, pp, pn)
    z = run.dmac(p0)
    gold = LB.golden_dmac(a, LB.CAL_B, x, cal)
    err = run.dmac(p, cal) - z - gold
    return {"seed": seed, "rho": cal["rho"], "z": float(np.max(np.abs(z))),
            "err": float(np.max(np.abs(err) / LB.tol(gold))),
            "abs": float(np.max(np.abs(err))), "km": cal["km"]}


def main():
    pdk = LB.PDK
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"lora_sidecar MC ({MC_N} samples, {section})")
    with ThreadPoolExecutor(MC_JOBS) as ex:
        res = list(ex.map(lambda s: sample(s, section), range(1, MC_N + 1)))
    for s in res:
        print(f"  seed {s['seed']:2d}: rho {s['rho']:.5f}  zero point max {s['z']:.2f}  "
              f"worst |err| {s['abs']:.2f} code ({s['err']:.2f} x tol)"
              + ("" if s["err"] <= 1 else "  FAIL"))
    rho = np.array([s["rho"] for s in res])
    km = np.array([s["km"] for s in res])
    print(f"  rho mean {rho.mean():.5f} sigma {rho.std(ddof=1) / rho.mean() * 100:.2f} %; "
          f"mirror gain sigma {km.std(ddof=1) * 100:.2f} %")
    y = np.mean([s["err"] <= 1 for s in res])
    r.check(f"yield >= {MC_YIELD * 100:.0f} % (every column within tolerance)", y >= MC_YIELD,
            f"{y * 100:.0f} % of {MC_N}")
    r.done()


if __name__ == "__main__":
    main()
