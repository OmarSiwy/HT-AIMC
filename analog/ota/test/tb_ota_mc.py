"""OTA Monte Carlo input offset: |mean| + 3 sigma of Vos < V_OS_MAX (signoff rung 5).

Offset is the OTA's most mismatch-sensitive metric: the integrator resets out to
vcm + Vos, so the offset spends output range the signal needs. Budget: the usable range
(tb_ota_swing, A0 >= 200) must hold V_SWING plus the offset; with the +-350 mV measured
range that leaves 100 mV -> V_OS_MAX = 0.4 * specs.V_SWING.

Per sample: the PDK's mismatch section at the typical corner (sky130 `tt_mm`) with a
fresh ngspice seed; Vos = V(out) - vcm of the unity-gain buffer at the operating point.
MC_N samples (default 100).
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
import specs  # noqa: E402
from bench import Report  # noqa: E402
from ota_bench import ota_testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402

N = int(os.environ.get("MC_N", 100))
VDD = get_pdk().vdd
VCM = specs.VCM_FRAC * VDD
V_OS_MAX = 0.4 * specs.V_SWING


def offset(seed, section):
    tb = ota_testbench(corner=section)
    tb.options(seed=seed)
    tb.V(name="in", positive="inp", negative="0", value=VCM)
    tb.V(name="fb", positive="out", negative="inn", value=0.0)
    return tb.operating_point()["out"] - VCM


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"ota MC offset ({N} samples, {section})")
    offs = [offset(seed, section) for seed in range(1, N + 1)]
    mu, sd = statistics.mean(offs), statistics.stdev(offs)
    r.check("mismatch spread is non-zero (section re-samples per seed)", sd > 1e-5,
            f"sigma {sd * 1e3:.2f} mV")
    r.check(f"|mean| + 3 sigma Vos < {V_OS_MAX * 1e3:.0f} mV", abs(mu) + 3 * sd < V_OS_MAX,
            f"mean {mu * 1e3:.2f} mV, sigma {sd * 1e3:.2f} mV, "
            f"worst {max(offs, key=abs) * 1e3:+.1f} mV")
    r.done()


if __name__ == "__main__":
    main()
