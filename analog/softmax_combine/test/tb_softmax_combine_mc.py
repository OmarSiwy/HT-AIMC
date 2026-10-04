"""softmax_combine Monte Carlo: 3-sigma input-referred offset < specs.VOS_SOFTMAX
(signoff ladder rung 5).

The offset is the most mismatch-sensitive metric: every mismatch in the tail-shared
branch pair and both mirrors lands on the group weight ratio igrp0/igrp1, a g_b error
that refers to the gates as V_os = the vls0 - vls1 where igrp0 = igrp1 (read from a DC
sweep of vls0 around vls1 = score CM). Per sample: the PDK's mismatch section at the
typical corner (sky130 `tt_mm`), a fresh ngspice seed, the nominal current-referenced
vb_tail. MC_N samples (default 30).
"""
import math
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(A / "softmax_combine" / "netlist"),
                str(Path(__file__).parent)]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
import specs  # noqa: E402
from softmax_combine import PORTS  # noqa: E402
from tb_combine_tree import SCORE_CM, VDD, VOUT, bias  # noqa: E402

N = int(os.environ.get("MC_N", 30))
SPAN = 20e-3


def offset(seed, section, vbt):
    """vls0 - vls1 where igrp0 = igrp1, or None if outside +-SPAN."""
    tb = testbench("softmax_combine", PORTS, corner=section)
    tb.options(seed=seed, reltol=1e-4)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="bt", positive="vb_tail", negative="0", value=vbt)
    for b in range(2):
        tb.V(name=f"ls{b}", positive=f"vls{b}", negative="0", value=SCORE_CM)
        tb.V(name=f"ig{b}", positive=f"igrp{b}", negative="0", value=VOUT)
    r = tb.dc(Vls0=slice(SCORE_CM - SPAN, SCORE_CM + SPAN + 1e-6, 2e-3))
    dv = [v - SCORE_CM for v in r.sweep]
    lg = [math.log(a / b) for a, b in zip(r["i(vig0)"], r["i(vig1)"])]
    for k in range(1, len(dv)):
        if lg[k - 1] < 0 <= lg[k]:
            return dv[k - 1] - lg[k - 1] * (dv[k] - dv[k - 1]) / (lg[k] - lg[k - 1])
    return None


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    vbt = bias()
    r = Report(f"softmax_combine MC ({N} samples, {section})")
    offs = [offset(seed, section, vbt) for seed in range(1, N + 1)]
    bad = offs.count(None)
    r.check(f"every sample resolves within +-{SPAN * 1e3:.0f} mV", bad == 0, f"{bad} unresolved")
    offs = [o for o in offs if o is not None]
    mu, sd = statistics.mean(offs), statistics.stdev(offs)
    r.check(f"3-sigma |Vos| < {specs.VOS_SOFTMAX * 1e3:.0f} mV",
            abs(mu) + 3 * sd < specs.VOS_SOFTMAX,
            f"mean {mu * 1e3:.2f} mV, sigma {sd * 1e3:.2f} mV")
    r.done()


if __name__ == "__main__":
    main()
