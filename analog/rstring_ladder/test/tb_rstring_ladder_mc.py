"""R-string ladder Monte Carlo: worst tap error at the SAR span, mean + 3 sigma <= V_TAP_TOL
(signoff ladder rung 5).

Tap accuracy is set by segment-resistor mismatch (the mux carries no DC current), so it
is the block's mismatch-sensitive metric. Rails at the SAR CDAC span the ladder serves,
vcm +- 16*u_cal (AnalogIOC rstring_ladder docstring); the error budget there is the tap
tolerance specs.V_TAP_TOL (~u_cal/3). Per sample: tb_rstring's 16-code sweep on the PDK's
mismatch section at the typical corner (sky130 `tt_mm`) with a fresh ngspice seed.
MC_N samples (default 30), MC_JOBS in parallel (default 8).

sky130's ngspice mismatch sections carry no poly-resistor mismatch: the model's
`*_slope_spectre` / `*_con_slope_spectre` are fixed .params (0) and their per-instance
`vary ... std=1.0` lives only in a commented Spectre statistics block. So the SPICE samples
cover FET mismatch (mux leakage / injection) only, and the resistor term is a Monte Carlo
over the model file's own declared statistics, per segment
    R = rsheet*l*(1 + body_pelgrom/sqrt(w*l) * N(0,1)) + rcon*(1 + rend_mm * N(0,1)).
"""
import math
import os
import re
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
import specs  # noqa: E402
from bench import Report  # noqa: E402
from pdk_specs import get_pdk, pdk_root  # noqa: E402
from tb_rstring import VCM, sweep  # noqa: E402

N = int(os.environ.get("MC_N", 30))
JOBS = int(os.environ.get("MC_JOBS", 8))
SPAN = 32 * specs.u_cal()
VRN, VRP = VCM - SPAN / 2, VCM + SPAN / 2


def sample(seed, section):
    """-> (monotone, worst |tap error| [V]) for one mismatch sample."""
    taps, _ = sweep(VRN, VRP, corner=section, seed=seed)
    err = [v - (VRN + k * SPAN / 15) for k, v in enumerate(taps)]
    return all(b > a for a, b in zip(taps, taps[1:])), max(abs(e) for e in err)


def res_model(pdk):
    """The segment device's declared parameters (sky130 model file) + drawn w, l [um]."""
    f = (pdk_root() / pdk.variant / "libs.ref" / "sky130_fd_pr" / "spice" /
         f"{pdk.res_poly_lotc}.model.spice")
    num = r"([-+]?\d*\.?\d+(?:e[-+]?\d+)?)"
    p = {k: float(v) for k, v in re.findall(rf"\b(\w+)\s*=\s*{num}(?![\w*/(])", f.read_text())}
    w = pdk.res_poly_lotc_w
    return p, w, round(specs.r_seg(pdk) / pdk.res_poly_lotc_ohm_sq * w, 2)  # as poly_res


def resistor_mc(pdk, n=100_000, seed=1):
    """Worst |tap error| [V] per sample from segment-resistor mismatch alone."""
    p, w, l = res_model(pdk)
    rng = np.random.default_rng(seed)
    body = p["rsheet"] * l * (1 + p["body_pelgrom"] / math.sqrt(w * l)
                              * rng.standard_normal((n, 15)))
    end = p["rcon"] * (1 + p["rend_mm"] * rng.standard_normal((n, 15)))
    cum = np.cumsum(body + end, axis=1)
    taps = cum[:, :-1] / cum[:, -1:]                      # tap1..tap14 / span
    return np.abs(taps - np.arange(1, 15) / 15).max(axis=1) * SPAN


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"rstring_ladder MC ({N} samples, {section}, span {SPAN * 1e3:.1f} mV)")
    with ThreadPoolExecutor(JOBS) as ex:
        res = list(ex.map(lambda s: sample(s, section), range(1, N + 1)))
    worst = [w for _, w in res]
    mu, sd = statistics.mean(worst), statistics.stdev(worst)
    r.check("samples differ (FET mismatch live)", sd > 0, f"sigma {sd * 1e6:.1f} uV")
    r.check("every sample monotone", all(m for m, _ in res),
            f"{sum(not m for m, _ in res)} non-monotone")
    r.check("SPICE worst tap error mean + 3 sigma <= V_TAP_TOL", mu + 3 * sd <= specs.V_TAP_TOL,
            f"mean {mu * 1e6:.0f} uV, sigma {sd * 1e6:.1f} uV, tol {specs.V_TAP_TOL * 1e6:.0f} uV")
    rw = resistor_mc(pdk)
    r.check("+ resistor mismatch: mean + 3 sigma <= V_TAP_TOL",
            mu + rw.mean() + 3 * math.hypot(sd, rw.std()) <= specs.V_TAP_TOL,
            f"resistor-only {len(rw)} samples: mean {rw.mean() * 1e6:.0f} uV, "
            f"sigma {rw.std() * 1e6:.0f} uV; total {(mu + rw.mean() + 3 * math.hypot(sd, rw.std())) * 1e6:.0f} uV")
    r.done()


if __name__ == "__main__":
    main()
