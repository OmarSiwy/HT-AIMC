"""lora_sidecar: signed A.x integrate, V->T, B drive onto the columns vs golden, both windows.

Spec rows (analog/lora_sidecar/docs/architecture.md), one transient:
  PROGRAM  16 write slots: A rows 0..3 = +7 (calibration reference) and random signed
           A on rows 4..15; B = every level of both signs (lora_bench.CAL_B).
  CAL      reference passes x = +-15 on rows 0..3 -> level table, mirror gain, rho
           (the per-chip knob; tb_lora_rho records the typical-corner values).
  VERIFY   fresh random signed INT8 x on rows 4..15 (rows 0..3 at 0), and a coherent x
           (sign(x) = sign(A): A.x near the LORA_AX_MAX budget, large signal): a LO pass
           and a HI pass each (xen pulses one t_q per 16 t_q chop cycle), every column vs
           scripts/golden/model.py tile_mvm(lora=(A_eff, B_eff, rho)) within
           max(TOL_ABS, TOL_REL x reading); x -> -x flips every column (sign symmetry);
           x = 0 reads ~0 without any baseline (comparator delays cancel).
  STORAGE  the + reference pass repeated after all of that: within 0.5 %.
  ENERGY   per write slot and per LO op (vdd + vcm), reported.
AnalogIOC origin (tb_lora_sidecar): unsigned |x|, LO only, golden = I_cal at measured
store voltages, 1.36 % / 0.93 %.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lora_bench as LB  # noqa: E402
from bench import Report  # noqa: E402

SEED = 7


def check_cols(r, label, meas, gold):
    err = meas - gold
    t = LB.tol(gold)
    worst = int(np.argmax(np.abs(err) / t))
    print(f"  {label}: meas / golden [code units]")
    for j in range(0, LB.N, 8):
        print("    " + "  ".join(f"{meas[k]:+7.2f}/{gold[k]:+7.2f}" for k in range(j, j + 8)))
    r.check(f"{label}: all {LB.N} columns within max({LB.TOL_ABS:g}, "
            f"{LB.TOL_REL * 100:g} %)", np.all(np.abs(err) <= t),
            f"worst col {worst}: {err[worst]:+.2f} vs tol {t[worst]:.2f}; "
            f"|err| max {np.max(np.abs(err)):.2f}, rms {np.sqrt(np.mean(err ** 2)):.2f}; "
            f"outside +-1: {int(np.sum(np.abs(err) > 1))}")


def main():
    r = Report("lora_sidecar: signed outer product vs golden, LO + HI")
    rng = np.random.default_rng(SEED)
    nominal = [0.0] + [((m + 1.5) / 8.5) ** 2 for m in range(1, 8)]   # budget guess only
    a, b, x = LB.random_case(rng, nominal, a_fixed={i: LB.WMAX for i in range(LB.CAL_ROWS)},
                             rows=range(LB.CAL_ROWS, LB.N), hi=True)
    run = LB.Run()
    LB.cal_program(run, {i: int(a[i]) for i in range(LB.CAL_ROWS, LB.N)})
    pp, pn = LB.cal_passes(run)
    x2 = LB.coherent_x(rng, a, nominal, rows=range(LB.CAL_ROWS, LB.N))
    p_lo2 = run.lora_pass(x2, "lo", "lo coherent")
    p_hi2 = run.lora_pass(x2, "hi", "hi coherent")
    p_lo = run.lora_pass(x, "lo", "lo")
    p_neg = run.lora_pass(-x, "lo", "lo -x")
    p_hi = run.lora_pass(x, "hi", "hi")
    p_0 = run.lora_pass(np.zeros(LB.N, int), "lo", "x=0")
    p_re = run.lora_pass(pp["xq"], "lo", "cal+ again")
    run.simulate()

    cal = LB.calibrate(run, pp, pn)
    print(f"  levels (I_m / I_7): {' '.join(f'{v:.3f}' for v in cal['levels'])}, "
          f"I_7 {cal['i_b7'] * 1e9:.0f} nA")
    print(f"  mirror gain per level: {' '.join(f'{k:.3f}' for k in cal['km'])}")
    print(f"  rho {cal['rho']:.5f} (physical {cal['rho_phys']:.5f}, design "
          f"{LB.specs.lora_rho_design():.5f}); window pedestal c0 {cal['c0']:+.3f} code; "
          f"fit residual {cal['resid']:.2f} code")
    r.check("level table strictly monotone", np.all(np.diff(cal["levels"]) > 0))
    r.check("reference passes fit rho within TOL_ABS", cal["resid"] <= LB.TOL_ABS,
            f"{cal['resid']:.2f} code")

    bvals = np.array(LB.CAL_B)
    for p in (p_lo, p_hi, p_lo2, p_hi2):
        gold = LB.golden_dmac(a, bvals, p["xq"], cal, p["window"])
        check_cols(r, f"{p['tag'].upper()} window", run.dmac(p, cal), gold)
    d_lo, d_neg = run.dmac(p_lo, cal), run.dmac(p_neg, cal)
    sym = np.max(np.abs(d_lo + d_neg))
    r.check("x -> -x negates every column", sym <= LB.TOL_ABS, f"max |sum| {sym:.2f} code")
    z = np.max(np.abs(run.dmac(p_0)))
    r.check("x = 0 reads 0 (no baseline pass)", z <= 0.5, f"max |dmac| {z:.3f} code")
    d0, d1 = run.dmac(pp), run.dmac(p_re)
    big = np.abs(d0) > 5
    drift = np.max(np.abs(d1[big] - d0[big]) / np.abs(d0[big]))
    r.check("storage non-destructive (reference pass repeated) < 0.5 %", drift < 0.005,
            f"{drift * 100:.3f} %")
    swing = max(max(abs(v) for v in run.ax_swing(p)) for p in run.passes)
    r.check("A integrators inside SWING_MAX", swing <= LB.SWING_MAX,
            f"max |vax - vcm| {swing * 1e3:.0f} mV")

    n_slot = LB.N
    e_slot = run.energy(50e-9, 50e-9 + n_slot * LB.T_SLOT) / n_slot
    e_op = run.energy(p_lo["tw"] - LB.T_RST - LB.T_RG, p_lo["t1"])
    print(f"  E per write slot (one A row + one B column) {e_slot * 1e12:.2f} pJ; E per LO op "
          f"(rst + window + ramp, vdd + vcm) {e_op * 1e12:.1f} pJ")
    r.done()


if __name__ == "__main__":
    main()
