"""tq_chain Monte Carlo: inner-stage t_q spread < 10% on every sample (ladder rung 5).

The t_q grid is the block's only matching-sensitive quantity: identical stages must
give identical PWM slots, and device mismatch is what separates them (the sequencer's
phases only need ordering and loose windows). Per sample: the PDK's mismatch section at
the typical corner (sky130 `tt_mm`) with a fresh ngspice seed. MC_N samples (default 30).
"""
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tb_async_ctrl import PDK, TQ_SPREAD, Report, spread, tq_stages, tq_testbench  # noqa: E402

N = int(os.environ.get("MC_N", 30))


def sample(seed, section):
    tb = tq_testbench(corner=section)
    tb.options(seed=seed)
    return tq_stages(tb)


def main():
    section = PDK.typical + PDK.mismatch_suffix if PDK.mismatch_suffix else PDK.mc_section
    r = Report(f"async_ctrl tq_chain MC ({N} samples, {section})")
    runs = [sample(seed, section) for seed in range(1, N + 1)]
    bad = runs.count(None)
    r.check("every sample toggles all taps", bad == 0, f"{bad} dead")
    runs = [s for s in runs if s is not None]
    sp = [spread(s) for s in runs]
    inner = [dt for s in runs for dt in s[1:]]
    mu, sd = statistics.mean(inner), statistics.stdev(inner)
    print(f"  info  inner t_q mean {mu * 1e9:.3f} ns, sigma {sd * 1e12:.1f} ps "
          f"({sd / mu * 100:.2f}%)")
    r.check("mismatch is sampled (spread varies)", len(set(round(x, 6) for x in sp)) > 1)
    r.check(f"inner-stage spread < {TQ_SPREAD * 100:.0f}% on every sample",
            max(sp) < TQ_SPREAD,
            f"worst {max(sp) * 100:.2f}%, mean {statistics.mean(sp) * 100:.2f}%")
    r.done()


if __name__ == "__main__":
    main()
