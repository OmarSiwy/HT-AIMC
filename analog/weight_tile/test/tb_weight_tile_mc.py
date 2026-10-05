"""weight_tile Monte Carlo: differential null |mean| + 3 sigma < 1.5 LSB (ladder rung 5).

The null (Cp = Cn = 8, nibble 10) is the tile's most mismatch-sensitive metric: the two
banks' TG injection and dummy cancellation no longer match, and the residue lands on the
column as an offset in code units. Per sample: the PDK's mismatch section at the typical
corner (sky130 `tt_mm`) with a fresh ngspice seed. MC_N samples (default 30).
"""
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile import T_START, TQ, U1, at, clocks, drive, testbench  # noqa: E402
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

N = int(os.environ.get("MC_N", 30))
JOBS = int(os.environ.get("JOBS", 4))
NIB = 10


def null(seed, section):
    t_end = T_START + 16 * TQ + 60e-9
    tb = testbench([8], [8], corner=section)
    tb.options(seed=seed)
    clocks(tb, TQ, t_end)
    drive(tb, [NIB])
    tb.save("V(vout)")
    d = tb.transient(step_time=0.1e-9, end_time=t_end)
    return at(d, "vout", t_end - 5e-9) - at(d, "vout", T_START - 1e-9)


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"weight_tile MC ({N} samples, {section})")
    with ProcessPoolExecutor(JOBS) as ex:
        v = [x / U1 for x in ex.map(partial(null, section=section), range(1, N + 1))]
    mu, sd = statistics.mean(v), statistics.stdev(v)
    print(f"  null [LSB]: {' '.join(f'{x:+.2f}' for x in v)}")
    r.check("|mean| + 3 sigma null < 1.5 LSB", abs(mu) + 3 * sd < 1.5,
            f"mean {mu:+.3f} LSB, sigma {sd:.3f} LSB")
    r.done()


if __name__ == "__main__":
    main()
