"""write_dac Monte Carlo level accuracy: every tap |mean| + 3 sigma < 5 mV (ladder rung 5).

Per sample: the 16-code sweep of tb_write_dac on the PDK's mismatch section (sky130
`tt_mm`) with a fresh ngspice seed — FET mismatch in the tap TGs, decoder and the load.
Segment mismatch is added in Python: neither PDK varies poly resistors per instance in
ngspice (sky130 fixes res_high_po__slope_spectre = 0), so each sample draws
dR/R ~ N(0, a_r / sqrt(area)) per segment (pdk_specs `<kind>_a_r`, the model files'
body_pelgrom; area = all parallel devices of a segment) and adds the resulting tap
shift, superposed on the simulated error (both are small linear perturbations of v_k).
MC_N samples (default write_dac.MC_N, the count its sizing margin assumes), MC_JOBS
runs in parallel (default 6).
"""
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "write_dac" / "netlist"),
                str(Path(__file__).parent)]
import write_dac  # noqa: E402
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_write_dac import LEVEL_ERR, LSB, VREF, finals, run  # noqa: E402

N = int(os.environ.get("MC_N", write_dac.MC_N))
JOBS = int(os.environ.get("MC_JOBS", 6))
CODES = list(range(16))


def sigma_r(pdk):
    """Per-segment sigma(dR/R) of the netlist's ladder."""
    sz = write_dac.sizes(pdk)
    area = write_dac.seg_area(pdk, sz["r_kind"], sz["r_seg"], sz["r_par"])
    return getattr(pdk, sz["r_kind"] + "_a_r") / area ** 0.5


def sample(seed, section, s_r):
    t, v, _, _ = run(CODES, seed=seed, corner=section)
    sim = finals(t, v, 16) - np.arange(16) * LSB
    r = 1 + np.random.default_rng(seed).normal(0, s_r, 15)
    ladder = VREF * np.concatenate(([0.0], np.cumsum(r) / r.sum())) - np.arange(16) * LSB
    return sim, ladder


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    s_r = sigma_r(pdk)
    r = Report(f"write_dac MC ({N} samples, {section}, sigma_R {s_r * 100:.2f} %)")
    with ThreadPoolExecutor(JOBS) as ex:
        sim, ladder = np.array(list(ex.map(lambda s: sample(s, section, s_r),
                                           range(1, N + 1)))).transpose(1, 0, 2)
    err = sim + ladder
    print(f"  worst-tap sigma: simulated (FET) {sim.std(0, ddof=1).max() * 1e3:.3f} mV, "
          f"segments {ladder.std(0, ddof=1).max() * 1e3:.3f} mV")
    lv = err + np.arange(16) * LSB
    r.check("every sample strictly monotone", np.all(np.diff(lv, axis=1) > 0))
    worst = [abs(statistics.mean(err[:, k])) + 3 * statistics.stdev(err[:, k])
             for k in range(16)]
    k = int(np.argmax(worst))
    r.check(f"every tap |mean| + 3 sigma < {LEVEL_ERR * 1e3:.0f} mV", worst[k] < LEVEL_ERR,
            f"worst tap {k}: mean {err[:, k].mean() * 1e3:+.2f} mV, "
            f"sigma {err[:, k].std(ddof=1) * 1e3:.2f} mV")
    r.done()


if __name__ == "__main__":
    main()
