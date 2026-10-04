"""Translinear softmax Monte Carlo: per-branch input-referred offset, KCL, I_b spread
(signoff ladder rung 5).

The most mismatch-sensitive metric is the per-branch share at equal inputs: every branch
device and mirror pair lands on it, and it refers to the input as
V_os,i = ln(N * share_i) / beta (beta = the branch's weak-inversion gm/ID ceiling, the
bank's beta at 27 C). Spec: 3 sigma + |mean| of V_os (pooled over the N branches and all
samples) <= specs.VOS_SOFTMAX. Also per sample: KCL checksum < 1 % (mirror errors
average over N), and the I_b spread with ptat_bias as the bias, built with this block's
tail as its replica: 3 sigma/mean <= 20 % (ptat_bias's MC spec, now carrying the
tail-vs-replica share this block owns).

Per sample: the PDK's mismatch section at the typical corner (sky130 `tt_mm`), a fresh
ngspice seed, DC operating point at 27 C. MC_N samples (default 30).
"""
import math
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import specs  # noqa: E402
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_softmax import KCL_TOL, N, V_CM, VDD, bench, outputs  # noqa: E402
from translinear_softmax import sizes  # noqa: E402

MC_N = int(os.environ.get("MC_N", 30))
IB_3SIG = 0.20


def sample(seed, section):
    """(per-branch shares, KCL error, I_b) at equal inputs."""
    tb = bench("ptat", corner=section)
    tb.options(seed=seed)
    for i in range(N):
        tb.V(name=f"in{i}", positive=f"vin{i}", negative="0", value=V_CM)
    i_m, itail = outputs(tb.dc(Vsup=slice(VDD, VDD + 1e-3, 1e-2)), 0)
    return i_m / i_m.sum(), abs(i_m.sum() - itail) / itail, itail


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    beta = sizes(pdk)["gmid"]["beta"]
    r = Report(f"translinear_softmax MC ({MC_N} samples, {section})")
    runs = [sample(seed, section) for seed in range(1, MC_N + 1)]
    vos = [math.log(N * s) / beta for sh, _, _ in runs for s in sh]
    mu, sd = statistics.mean(vos), statistics.stdev(vos)
    r.check("samples differ (mismatch section live)", sd > 0)
    r.check(f"3-sigma + |mean| branch offset <= {specs.VOS_SOFTMAX * 1e3:.0f} mV",
            abs(mu) + 3 * sd <= specs.VOS_SOFTMAX,
            f"mean {mu * 1e3:.3f} mV, sigma {sd * 1e3:.3f} mV (beta {beta:.2f} /V), "
            f"worst share err {max(abs(N * s - 1) for sh, _, _ in runs for s in sh) * 100:.2f} %")
    kcl = max(k for _, k, _ in runs)
    r.check("KCL checksum < 1 % every sample", kcl < KCL_TOL, f"worst {kcl * 100:.3f} %")
    ib = [i for _, _, i in runs]
    m, s = statistics.mean(ib), statistics.stdev(ib)
    r.check("I_b 3-sigma/mean <= 20 % (ptat_bias + this tail)", 3 * s / m <= IB_3SIG,
            f"mean {m * 1e9:.1f} nA, sigma {s * 1e9:.2f} nA, 3s/mu {3 * s / m * 100:.1f} %")
    r.done()


if __name__ == "__main__":
    main()
