"""PWM driver Monte Carlo: sign symmetry of the transferred width (signoff rung 5).

The block's mismatch-sensitive quantity is the outa-vs-outb path skew: the P-style
line of a positive activation is outa (inp&phi1e), of a negative one outb
(inn&phi1e). Mismatch between the two paths shifts their gated widths apart, i.e. a
sign-dependent charge fraction (LAYOUT_REQUIREMENTS "outa/outb slew matching").
Per sample: code CODE on each sign under the PDK's mismatch section at the typical
corner (sky130 `tt_mm`) with a fresh ngspice seed. MC_N samples (default 30).

  every sample: transfer count == code on both signs
  3-sigma |width_a - width_b| / mean < 2 %  (the width-linearity limit)
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_pwm_driver import TQ, sweep  # noqa: E402

N = int(os.environ.get("MC_N", 30))
CODE = 4


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"pwm_driver MC ({N} samples, {section})")
    cases = [(CODE, neg, TQ, {"seed": s, "corner": section})
             for s in range(1, N + 1) for neg in (False, True)]
    res = sweep(cases)
    pairs = list(zip(res[0::2], res[1::2]))
    bad = sum(a[0] != CODE or b[0] != CODE for a, b in pairs)
    r.check("transfer count == code on both signs, every sample", bad == 0, f"{bad} bad")
    skew = [(a[1] - b[1]) / ((a[1] + b[1]) / 2) for a, b in pairs]
    mu, sd = statistics.mean(skew), statistics.stdev(skew)
    r.check("3-sigma sign width skew < 2 %", abs(mu) + 3 * sd < 0.02,
            f"mean {mu * 100:.3f} %, sigma {sd * 100:.3f} %")
    gaps = [min(a[3], b[3]) for a, b in pairs]
    print(f"  INFO  gap margin: mean {statistics.mean(gaps) * 1e12:.0f} ps, "
          f"sigma {statistics.stdev(gaps) * 1e12:.1f} ps")
    r.done()


if __name__ == "__main__":
    main()
