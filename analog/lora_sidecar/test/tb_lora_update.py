"""lora_sidecar: one SGD outer-product step, written through the DACs (the analog half of
CONTRACT acceptance 4 / INTERFACE A5; the full step on the analog top is phase 2).

One transient (analog/lora_sidecar/docs/architecture.md spec rows):
  1. program the calibration reference (A rows 0..3 = +7) plus a random signed A on rows
     4..15 and a random signed B; reference passes -> levels, rho
  2. pass y0 (LO, random signed x on rows 4..15)
  3. digital step: golden lora_sgd_step on the effective weights (B scaled by rho so
     y = B (A.x) in code units) toward a target one B level away on four columns (two
     up, two down; planned with the typical-corner specs.lora_cal()), lr sized so the
     largest B move is one level; the new values are quantized onto the level table,
     and the predicted Delta y is the golden LoRA term after minus before (this run's
     calibration). Only the cells whose code changed are rewritten. The target is
     y0 + 0.8 x that prediction on the four columns (origin: 0.8 x the 1-level dy).
  4. pass y1 (same x).
Asserts: loss L1 < L0; every column whose predicted |Delta y| >= 1.5 has the golden sign
and |Delta y - pred| <= max(TOL_ABS, TOL_REL |y|); the others move <= TOL_ABS (no write
disturb). AnalogIOC origin (tb_training_step, full chip): down-only targets, ±40 % / 3 LSB.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lora_bench as LB  # noqa: E402
from bench import Report  # noqa: E402
from golden import model as G  # noqa: E402

SEED = 11
UPD_COLS = (1, 6, 9, 12)


def quantize(v, levels):
    """Nearest signed level value in -7..7 of effective weights v."""
    grid = np.array([LB.eff(k, levels) for k in range(-LB.WMAX, LB.WMAX + 1)])
    return np.array([int(np.argmin(np.abs(grid - u))) - LB.WMAX for u in np.atleast_1d(v)])


def step(a, b, x, y0, cal):
    """Golden SGD step -> (a2, b2) signed codes and the target offsets (code units)."""
    lv, rho = cal["levels"], cal["rho"]
    ae, be = LB.eff(a, lv), LB.eff(b, lv)
    sign, _, lo = G.pwm_nibbles(x)
    xe = (sign * lo).astype(float)                 # this LO window's signed nibble
    ax = float(ae @ xe)
    off = np.zeros(LB.N)
    for k, j in enumerate(UPD_COLS):               # 0.8 of one B level, alternating sign
        m = min(abs(int(b[j])), LB.WMAX - 1)
        off[j] = (1 if k % 2 == 0 else -1) * 0.8 * rho * abs(ax) * \
            (LB.eff(m + 1, lv) - LB.eff(m, lv))
    target = y0 + off
    # y = (rho B)(A.x): the golden rank-1 step on (A, rho B); lr moves the largest B by
    # one top level spacing
    _, b1 = G.lora_sgd_step(ae, be * rho, xe, y0, target, 1.0)
    lr = (LB.eff(LB.WMAX, lv) - LB.eff(LB.WMAX - 1, lv)) / np.max(np.abs(b1 / rho - be))
    a2, b2 = G.lora_sgd_step(ae, be * rho, xe, y0, target, lr)
    return quantize(a2, lv), quantize(b2 / rho, lv), off


def main():
    r = Report("lora_sidecar: one SGD outer-product step")
    rng = np.random.default_rng(SEED)
    try:
        cal0 = LB.specs.lora_cal()          # typical-corner record, for the step plan only
    except FileNotFoundError:
        cal0 = {"levels": [0.0] + [((m + 1.5) / 8.5) ** 2 for m in range(1, 8)],
                "rho": LB.specs.lora_rho_design()}
    # a strong A.x (near the LORA_AX_MAX budget) so one B level moves a column by codes:
    # large signed A on rows 4..15, x = sign(A) * 15 row by row while the budget holds
    a = np.zeros(LB.N, int)
    a[:LB.CAL_ROWS] = LB.WMAX
    a[LB.CAL_ROWS:] = rng.choice([-1, 1], LB.N - LB.CAL_ROWS) * \
        rng.integers(LB.WMAX - 2, LB.WMAX + 1, LB.N - LB.CAL_ROWS)
    x = np.zeros(LB.N, int)
    for i in range(LB.CAL_ROWS, LB.N):
        x[i] = 15 * np.sign(a[i])
        if not LB.ax_budget_ok(a, x, cal0["levels"]):
            x[i] = 0
    b = np.array(LB.CAL_B)
    a2, b2, off = step(a, b, x, LB.golden_dmac(a, b, x, cal0), cal0)
    a2[:LB.CAL_ROWS] = LB.WMAX                     # the reference rows stay put
    print(f"  x {[int(v) for v in x]}\n  A {[int(v) for v in a]} -> {[int(v) for v in a2]}"
          f"\n  B {[int(v) for v in b]} -> {[int(v) for v in b2]}")

    run = LB.Run()
    LB.cal_program(run, {i: int(a[i]) for i in range(LB.CAL_ROWS, LB.N)})
    pp, pn = LB.cal_passes(run)
    p0 = run.lora_pass(x, "lo", "y0")
    run.program({i: int(a2[i]) for i in range(LB.N) if a2[i] != a[i]},
                {j: int(b2[j]) for j in range(LB.N) if b2[j] != b[j]})
    p1 = run.lora_pass(x, "lo", "y1")
    run.simulate()

    cal = LB.calibrate(run, pp, pn)
    y0, y1 = run.dmac(p0, cal), run.dmac(p1, cal)
    pred = LB.golden_dmac(a2, b2, x, cal) - LB.golden_dmac(a, b, x, cal)
    # the target sits 0.8 of the step this chip's code grid can make (its calibration):
    # the plan above only fixed the direction and the codes
    target = y0 + 0.8 * np.where(off != 0, pred, 0.0)
    l0, l1 = np.sum((y0 - target) ** 2), np.sum((y1 - target) ** 2)
    print(f"  rho {cal['rho']:.5f}; y0 {np.round(y0, 1)}\n  y1 {np.round(y1, 1)}")
    r.check("loss decreased", l1 < l0, f"L0 {l0:.2f} -> L1 {l1:.2f}")
    dy = y1 - y0
    t = LB.tol(LB.golden_dmac(a2, b2, x, cal))
    upd = np.abs(pred) >= 1.5
    for j in range(LB.N):
        print(f"    col {j:2d}: dy {dy[j]:+7.2f}  pred {pred[j]:+7.2f}  tol {t[j]:.2f}"
              + ("  (updated)" if upd[j] else ""))
    ok_sign = np.all(np.sign(dy[upd]) == np.sign(pred[upd]))
    r.check("updated columns move with the golden sign", ok_sign and upd.any(),
            f"{int(upd.sum())} columns")
    r.check("updated columns |dy - pred| within tolerance",
            np.all(np.abs(dy - pred)[upd] <= t[upd]),
            f"worst {np.max(np.abs(dy - pred)[upd]):.2f} code" if upd.any() else "none")
    r.check("other columns move <= TOL_ABS",
            np.all(np.abs(dy - pred)[~upd] <= LB.TOL_ABS),
            f"worst {np.max(np.abs(dy - pred)[~upd]):.2f} code")
    r.done()


if __name__ == "__main__":
    main()
