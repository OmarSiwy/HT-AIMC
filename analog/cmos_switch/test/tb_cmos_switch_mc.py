"""cmos_switch Monte Carlo: peak R_on over [0, V_W], mean + 3 sigma <= r_on_budget()
(ladder rung 5).

Peak R_on sits at the top of the write range, where both channels are barely on, so
a Vth shift moves it more than any other metric — the pedestal and I_off move with the
full-rail overdrive or the rails. Per sample: the PDK's mismatch section at the typical
corner (sky130 `tt_mm`) with a fresh ngspice seed. MC_N samples (default 30).
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_cmos_switch import DV, PORTS, R_ON_MAX, V_W, supplies  # noqa: E402

N = int(os.environ.get("MC_N", 30))


def peak_r_on(seed, section):
    tb = testbench("cmos_switch", PORTS, corner=section)
    tb.options(seed=seed)
    supplies(tb)
    tb.V(name="in", positive="in_", negative="0", value=0.0)
    tb.V(name="dv", positive="in_", negative="out", value=DV)
    res = tb.dc(Vin=slice(0.0, V_W, V_W / 18))
    return max(DV / abs(i) for i in res["i(vdv)"])


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"cmos_switch MC ({N} samples, {section})")
    peaks = [peak_r_on(seed, section) for seed in range(1, N + 1)]
    mu, sd = statistics.mean(peaks), statistics.stdev(peaks)
    r.check("samples differ (mismatch section live)", sd > 0, f"sigma {sd:.1f} ohm")
    r.check("peak R_on mean + 3 sigma <= budget", mu + 3 * sd <= R_ON_MAX,
            f"mean {mu / 1e3:.1f} kohm, sigma {sd / 1e3:.2f} kohm "
            f"({100 * sd / mu:.1f}%), budget {R_ON_MAX / 1e3:.0f} kohm")
    r.done()


if __name__ == "__main__":
    main()
