"""WTA running-max: range, settle, replica offset, permutation, streamed max, shift invariance.

Spec rows (analog/wta/docs/architecture.md; CHIP2_SPEC 2.3 / T2 + R1). Softmax is
shift-invariant, so the WTA has a RANGE spec, not an accuracy spec:
  m_hat - max(vin) in [-5 mV, n*UT*ln8 + 18 mV] on every pattern, settle <= 1 us to +-5 mV
  replica-cancelled offset (one clear winner at vref) within budget(T)
  permutation-invariant within 5 mV; streamed running max tracks and holds
  +50 mV common mode on all inputs + vref moves (vin_i - m_hat) by <= 2 mV (R1)

m_hat (input domain) = mrail - rrail + vref: mrail = max(vin) - VGS, rrail = vref - VGS.

Two stimulus changes from AnalogIOC, both so corners measure the block and not the bench:
  vb_tail: AnalogIOC forced a fixed 0.44 V; in the system it comes from ptat_bias, a current
    reference. Here I_TAIL (netlist/wta.py) feeds a diode-connected copy of the tail. A
    fixed subthreshold VGS lets the tail current fall ~10x at ss/-40 C (settle 1.2 us).
  offset losers: AnalogIOC put them at vref - 150 mV. Their soft-max share, n*UT*ln(1 +
    7*exp(-150 mV/n*UT)), was most of its "replica residual" and grows with T (+3.5 mV at
    27 C, +13.8 at 125 C measured). They now sit at the window bottom (vref - 250 mV).
Temperature comes from $TEMP (AnalogIOC looped 27/55/85 C inside the tb; here each is a
TEMP= run, and corners.py sweeps the rest). Budgets scale with n*UT(T), n*UT(27 C) from
the PDK subthreshold swing (AnalogIOC used its measured softmax beta 27.31 /V -> 36.6 mV).
Adapted from AnalogIOC analog/testbenches/tb_wta.py (ngspice batch -> SpiceRack).
"""
import math
import os
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "wta" / "netlist")]
from types import SimpleNamespace  # noqa: E402

from bench import Report, testbench  # noqa: E402
from devices import fet  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from wta import I_TAIL, N, PORTS, VB_TAIL, sizes  # noqa: E402

PDK = get_pdk()
VDD = PDK.vdd
VREF = 0.85        # replica gate = TOP of the 0.6-0.85 V score window: keeps the replica
                   # Vds ~ the winner's so m_hat stays a SAFE overestimate (AnalogIOC:
                   # a bottom-of-window vref under-cancels VGS, measured -35 mV)
T_WIN = 2e-6       # per-pattern settle window
T0 = 300.15        # K, 27 C
V_WIN_LO = 0.60    # bottom of the score window
OFFSET_PAT = [VREF] + [V_WIN_LO] * (N - 1)   # one winner at vref, losers at the bottom

PATTERNS = {       # score window 0.6-0.85 V (CHIP2_SPEC 2.4)
    "one-winner": [0.85, 0.70, 0.68, 0.71, 0.69, 0.72, 0.67, 0.70],
    "all-equal":  [0.75] * 8,
    "tie-top2":   [0.82, 0.82, 0.70, 0.69, 0.71, 0.68, 0.70, 0.69],
    "1LSB-split": [0.800, 0.799, 0.70, 0.71, 0.69, 0.72, 0.70, 0.68],
    "winner-low": [0.62, 0.60, 0.61, 0.63, 0.60, 0.62, 0.61, 0.60],
    "permuted":   [0.67, 0.70, 0.85, 0.69, 0.72, 0.68, 0.70, 0.71],   # winner moved
}
BLOCKS = [         # streamed running max: rising then falling peaks
    ("block1 peak .78", [0.78, 0.70, 0.72, 0.69, 0.71, 0.68, 0.70, 0.69]),
    ("block2 peak .84", [0.72, 0.84, 0.70, 0.71, 0.69, 0.70, 0.68, 0.71]),
    ("block3 peak .75", [0.75, 0.70, 0.73, 0.69, 0.72, 0.68, 0.71, 0.70]),
]


def temp_c():
    return float(os.environ.get("TEMP", 27))


def nut_mv(t=None):
    """n*UT at temperature t [C]: PDK subthreshold swing / ln10, scaled with T."""
    t = temp_c() if t is None else t
    return PDK.ss_mv_dec / math.log(10) * (t + 273.15) / T0


def headroom_mv():
    """Safe-overestimate ceiling n*UT*lnN + 18 mV finite-tail/replica margin (AnalogIOC).
    Grows above 27 C only: the compiler reserves this headroom at design temperature, and
    the follower-slope part of the error, (1 - kappa)(vref - max), does not shrink when
    cold (fs -40 C: +81.8 mV, below the +91.5 mV at 27 C, over a cold-scaled 81.2 mV)."""
    return nut_mv(max(temp_c(), 27.0)) * math.log(N) + 18.0


def offset_budget_mv():
    """Random 5 mV (CHIP2_SPEC 2.3) + AnalogIOC's systematic single-signed Vds-match term,
    3.5 x 5 mV per unit n*UT growth above 27 C (none below: the term only grows)."""
    return 5.0 + 5.0 * max(nut_mv() / nut_mv(27.0) - 1.0, 0.0) * 3.5


def run(pat, cm_shift=0.0, vin_hold=0.0, seed=None, t_end=T_WIN, **kw):
    """One settle run on a static pattern. cm_shift rides all inputs and vref;
    vin_hold 0 V parks the accumulate follower (fresh single-block max);
    seed selects the ngspice mismatch sample (Monte Carlo)."""
    tb = testbench("wta", PORTS, **kw)
    if seed is not None:
        tb.options(seed=seed)
    tb.options(reltol=1e-4, abstol=1e-12, vntol=1e-6, method="gear")  # sub-mV tracking
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.I(name="bt", positive="0", negative="vb_tail", value=I_TAIL)   # ptat_bias stand-in
    fet(SimpleNamespace(raw_spice=tb.extra_line), "bias", "vb_tail", "vb_tail", "0", "0",
        "nfet", *sizes()["tail"])
    tb.initial_condition(vb_tail=VB_TAIL)   # bias is always on in the system; start it there
    tb.V(name="ref", positive="vref", negative="0", value=VREF + cm_shift)
    tb.V(name="hold", positive="vin_hold", negative="0", value=vin_hold)
    for i in range(N):
        tb.V(name=f"in{i}", positive=f"vin{i}", negative="0", value=pat[i] + cm_shift)
    tb.save("V(mrail)", "V(rrail)", "I(Vsup)")
    return tb.transient(step_time=2e-9, end_time=t_end, use_initial_condition=True)


def mhat(d, cm_shift=0.0):
    """Settled input-domain m_hat [V]: mrail - rrail + vref."""
    return d["mrail"][-1] - d["rrail"][-1] + VREF + cm_shift


def settle_s(d, band=5e-3):
    """Time m_hat last leaves +-band of its final value."""
    final = mhat(d)
    out = [t for t, m, r in zip(d.time, d["mrail"], d["rrail"])
           if abs(m - r + VREF - final) > band]
    return out[-1] if out else 0.0


def energy_j(d):
    t, i = d.time, d["i(vsup)"]
    return -sum((t[k] - t[k - 1]) * (i[k] + i[k - 1]) / 2 for k in range(1, len(t))) * VDD


def main():
    r = Report("wta")
    hr = headroom_mv()
    print(f"  n*UT = {nut_mv():.1f} mV, range [-5, {hr:.1f}] mV, I_tail {I_TAIL * 1e6:.2f} uA")

    for label, pat in PATTERNS.items():
        d = run(pat)
        err = (mhat(d) - max(pat)) * 1e3
        st = settle_s(d)
        e = energy_j(d)
        r.check(f"{label}: range [-5, {hr:.0f}] mV & settle <= 1 us",
                -5.0 <= err <= hr and st <= 1e-6,
                f"err {err:+.1f} mV, settle {st * 1e9:.0f} ns, "
                f"P {e / T_WIN * 1e6:.2f} uW, E/upd {e * 1e12:.2f} pJ")

    # one clear winner at vref, losers at the window bottom: one device carries the tail,
    # the replica's operating point -> mrail - rrail is the replica residual
    off = (mhat(run(OFFSET_PAT)) - VREF) * 1e3
    bud = offset_budget_mv()
    r.check(f"replica-cancelled |offset| <= {bud:.1f} mV", abs(off) <= bud, f"{off:+.2f} mV")

    da, db = mhat(run(PATTERNS["one-winner"])), mhat(run(PATTERNS["permuted"]))
    r.check("permutation-invariant within 5 mV", abs(da - db) <= 5e-3,
            f"|diff| {abs(da - db) * 1e3:.2f} mV")

    held, true_run = 0.0, 0.0     # input-domain m_hat register, sampled per block
    for label, blk in BLOCKS:
        held = mhat(run(blk, vin_hold=held))
        true_run = max(true_run, max(blk))
        err = (held - true_run) * 1e3
        r.check(f"{label}: running max tracks, in range", -5.0 <= err <= hr,
                f"m_hat {held * 1e3:.1f} mV, true {true_run * 1e3:.1f} mV, err {err:+.1f} mV")
    r.check("running max held across falling block", held >= max(BLOCKS[1][1]) - 5e-3,
            f"{held * 1e3:.1f} mV")

    # R1: one mrail/rrail pair feeds exp + rescale; +50 mV CM must leave vin_i - m_hat
    pat = PATTERNS["one-winner"]
    m0, m1 = mhat(run(pat)), mhat(run(pat, cm_shift=0.05), 0.05)
    drift = max(abs((v + 0.05 - m1) - (v - m0)) for v in pat) * 1e3
    r.check("shift-invariant: (vin - m_hat) drift <= 2 mV @ +50 mV CM", drift <= 2.0,
            f"{drift:.3f} mV")
    r.done()


if __name__ == "__main__":
    main()
