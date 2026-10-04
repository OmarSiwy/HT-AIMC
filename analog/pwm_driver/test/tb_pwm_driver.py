"""PWM row driver: chop-count fidelity, width linearity, edges, gap timing.

Spec rows (analog/pwm_driver/docs/architecture.md):
  transfer count on the P-style line == code EXACTLY, codes 0..15, both signs
  accumulated gated width per cycle constant within 2 % over codes 1..15
  worst 10-90 % edge < t_q/3 into the 100 fF row load
  (reported, not asserted) gap margin: phi2 50 % minus the latest bottom-edge 50 %
  hi window (chop = 16 t_q), code 7 -> 7 transfers, both signs

The charge-defining event is the phi2 rise of a cycle whose bottom edge landed in the
gap: the P-style line (inp&phi1e / inn&phi1e) is high 1 ns before that rise, the
N-style line rises in the gap and is high 1 ns after it. Counted on the P-style line
exactly as AnalogIOC did.

Adapted from AnalogIOC analog/testbenches/tb_pwm_driver.py + _conv_common.py
(ngspice batch -> SpiceRack; PULSE clocks -> PWL, SpiceRack's pulse has no delay).
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common")]
import specs  # noqa: E402
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

PORTS = ["inp", "inn", "phi1", "phi1e", "outa", "outb", "vdd", "vss"]
VDD = get_pdk().vdd
TQ = specs.TQ_SIM
C_ROW = 100e-15
# Chop grid, cycle k at t0 = T_START + k*t_chop (AnalogIOC _conv_common, single source
# for the tile path): phi1 high [t0+0.3n, +1.6n], phi1e 0.2 ns longer, phi2 high
# [t0+2.5n, t0+t_chop-0.6n]. Envelope edges land in the all-off gap.
T_START = 5e-9
T_EDGE = 0.1e-9
T_CLK = 0.1e-9
PHI1_D, PHI1_W = 0.3e-9, 1.6e-9
PHI2_D = 2.5e-9


def pulse_train(delay, width, t_chop, end):
    """PULSE(0 VDD delay T_CLK T_CLK width t_chop) as PWL points up to `end`."""
    pts, t0 = [(0, 0.0)], T_START
    while t0 + delay < end:
        a = t0 + delay
        pts += [(a, 0.0), (a + T_CLK, VDD), (a + T_CLK + width, VDD),
                (a + 2 * T_CLK + width, 0.0)]
        t0 += t_chop
    return pts


def envelope(code, t_chop):
    """A5-format PWM envelope for one nibble code."""
    if code == 0:
        return [(0, 0.0)]
    t_off = T_START + code * t_chop
    return [(0, 0.0), (T_START, 0.0), (T_START + T_EDGE, VDD), (t_off, VDD),
            (t_off + T_EDGE, 0.0)]


def run(code, neg, t_chop, seed=None, **kw):
    """One transient: envelope on inp (neg: inn), both lines into C_ROW. `seed` sets
    the ngspice seed (Monte Carlo); kw goes to bench.testbench (corner, temp)."""
    end = T_START + (code + 1.5) * t_chop
    tb = testbench("pwm_driver", PORTS, **kw)
    if seed is not None:
        tb.options(seed=seed)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    env = envelope(code, t_chop)
    tb.PieceWiseLinearVoltageSource(name="inp", positive="inp", negative="0",
                                    values=[(0, 0.0)] if neg else env)
    tb.PieceWiseLinearVoltageSource(name="inn", positive="inn", negative="0",
                                    values=env if neg else [(0, 0.0)])
    for n, d, w in (("phi1", PHI1_D, PHI1_W), ("phi1e", PHI1_D, PHI1_W + 0.2e-9),
                    ("phi2", PHI2_D, t_chop - PHI2_D - 0.6e-9)):
        tb.PieceWiseLinearVoltageSource(name=n, positive=n, negative="0",
                                        values=pulse_train(d, w, t_chop, end))
    tb.C(name="la", positive="outa", negative="0", value=C_ROW)
    tb.C(name="lb", positive="outb", negative="0", value=C_ROW)
    tb.save("V(outa)", "V(outb)", "V(phi2)")
    r = tb.transient(step_time=0.05e-9, end_time=end)
    return (np.array(r.time), np.array(r["outa"]), np.array(r["outb"]),
            np.array(r["phi2"]))


def edge_time(t, v, lo, hi):
    """Worst 10-90 % transition time over all edges."""
    worst, i = 0.0, 1
    while i < len(v):
        if (v[i - 1] < lo <= v[i]) or (v[i - 1] > hi >= v[i]):
            rising = v[i] > v[i - 1]
            j = i
            while j < len(v) and ((rising and v[j] < hi) or (not rising and v[j] > lo)):
                j += 1
            if j < len(v):
                worst = max(worst, t[j] - t[i - 1])
            i = j + 1
        else:
            i += 1
    return worst


def first_cross(t, v, level, t0, t1, rising):
    """First crossing of `level` in [t0, t1] in the given direction, else None."""
    k = np.where((t >= t0) & (t <= t1))[0]
    for a, b in zip(k[:-1], k[1:]):
        if (v[a] < level <= v[b]) if rising else (v[a] > level >= v[b]):
            return t[b]
    return None


def measure(code, neg, t_chop, **kw):
    """(transfers, gated width, worst edge, worst gap margin) for one run."""
    t, oa, ob, p2 = run(code, neg, t_chop, **kw)
    pline, nline = (ob, oa) if neg else (oa, ob)
    rises = [t[i] for i in range(1, len(t)) if p2[i - 1] < VDD / 2 <= p2[i]]
    n_xfer = 0
    for tr in rises:
        jm = np.argmin(np.abs(t - (tr - 1e-9)))
        jp = np.argmin(np.abs(t - (tr + 1e-9)))
        n_xfer += bool(pline[jm] > VDD / 2 or pline[jp] > VDD / 2)
    # time above VDD/2, crossings linearly interpolated (AnalogIOC summed whole
    # timesteps: up to one step of error per edge, too coarse for the MC skew)
    x = pline - VDD / 2
    x0, x1, dt = x[:-1], x[1:], np.diff(t)
    frac = np.where((x0 > 0) == (x1 > 0), (x0 > 0) * 1.0,
                    np.maximum(x0, x1) / np.where(x0 == x1, 1, np.abs(x1 - x0)))
    width = float(np.sum(dt * frac))
    edge = edge_time(t, pline, 0.1 * VDD, 0.9 * VDD)
    # gap margin: the P-line fall and the N-line rise should land (50 %) before the
    # phi2 connect (50 %) — later, the remainder transfers as a driven edge during phi2
    margin = np.inf
    for k in range(code):
        t0 = T_START + k * t_chop
        t_p2 = t0 + PHI2_D + T_CLK / 2
        tp = first_cross(t, pline, VDD / 2, t0 + PHI1_D, t_p2 + 1e-9, rising=False)
        tn = first_cross(t, nline, VDD / 2, t0 + PHI1_D, t_p2 + 1e-9, rising=True)
        for te in (tp, tn):
            margin = min(margin, (t_p2 - te) if te is not None else -np.inf)
    return n_xfer, width, edge, margin


def sweep(cases, **kw):
    """measure() over [(code, neg, t_chop[, kwargs])], 8 ngspice runs at a time."""
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(lambda c: measure(*c[:3], **{**kw, **(c[3] if len(c) > 3 else {})}),
                           cases))


def main():
    r = Report("pwm_driver")
    ok_cnt, widths, worst_edge, worst_gap = True, {}, 0.0, np.inf
    cases = [(c, neg, TQ) for c in range(16) for neg in ([False] if c == 0 else [False, True])]
    cases += [(7, neg, 16 * TQ) for neg in (False, True)]
    res = sweep(cases)
    for (code, neg, _), (n, w, e, g) in zip(cases[:-2], res[:-2]):
        ok_cnt &= n == code
        worst_edge = max(worst_edge, e)
        worst_gap = min(worst_gap, g)
        if not neg:
            widths[code] = w
        print(f"    code {code:2d} ({'n' if neg else 'p'}): transfers {n:2d} "
              f"width {w * 1e9:6.2f} ns edge {e * 1e12:5.0f} ps gap margin "
              f"{g * 1e12:6.0f} ps" + ("" if n == code else "  <-- COUNT MISMATCH"))
    r.check("transfer count == code (codes 0..15, both signs)", ok_cnt)

    per = np.array([widths[c] / c for c in range(1, 16)])
    dev = float(np.max(np.abs(per / per.mean() - 1)))
    r.check("accumulated width tracks code within 2 %", dev < 0.02,
            f"{per.mean() * 1e9:.3f} ns/cycle, max dev {dev * 100:.2f} %")
    r.check("10-90 % edge < t_q/3 into 100 fF", worst_edge < TQ / 3,
            f"worst {worst_edge * 1e12:.0f} ps, spec {TQ / 3 * 1e9:.2f} ns")
    print(f"  INFO  gap margin (phi2 50 % - bottom edge 50 %): worst {worst_gap * 1e12:.0f} ps")

    hi = [n for n, *_ in res[-2:]]
    r.check("hi window (16 t_q chop) code 7 -> 7 transfers", hi == [7, 7], f"{hi}")
    r.done()


if __name__ == "__main__":
    main()
