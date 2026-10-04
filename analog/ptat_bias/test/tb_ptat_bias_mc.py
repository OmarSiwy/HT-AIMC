"""PTAT bias Monte Carlo: 3-sigma spread of I_b (signoff ladder rung 5).

I_b is the block's most mismatch-sensitive metric: it carries the mirror (mpr/mpo,
mpl vs mpr), the core pair's delta-VGS (~50 mV against ~1 mV sigma VT) and the
replica-vs-tail mismatch. Spec: 3-sigma/mean <= 20 % — the reach of the R trim
(AnalogIOC: "R is the TRIM knob, real poly R varies +-20 %").

Per sample: the PDK's mismatch section at the typical corner (sky130 `tt_mm`) with a
fresh ngspice seed, DC operating point at VDD, 27 C. MC_N samples (default 30).
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_ptat_bias import L_TAIL, PDK, PORTS, V_DS_TAIL, VDD, W_TAIL  # noqa: E402

N = int(os.environ.get("MC_N", 30))
SIGMA3_MAX = 0.20


def i_b(seed, section):
    tb = testbench("ptat_bias", PORTS, corner=section)
    tb.options(seed=seed)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="dt", positive="dtail", negative="0", value=V_DS_TAIL)
    tb.extra_line(f"Xmtail dtail vb_tail vss vss {PDK.nfet} W={W_TAIL} L={L_TAIL}")
    return abs(tb.dc(Vsup=slice(VDD, VDD + 1e-3, 1e-2))["i(vdt)"][0])


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"ptat_bias MC ({N} samples, {section})")
    ib = [i_b(seed, section) for seed in range(1, N + 1)]
    mu, sd = statistics.mean(ib), statistics.stdev(ib)
    print(f"  I_b min {min(ib) * 1e9:.1f} / max {max(ib) * 1e9:.1f} nA")
    r.check("samples differ (mismatch section live)", sd > 0)
    r.check("3-sigma/mean of I_b <= 20 %", 3 * sd / mu <= SIGMA3_MAX,
            f"mean {mu * 1e9:.1f} nA, sigma {sd * 1e9:.2f} nA, 3s/mu {3 * sd / mu * 100:.1f} %")
    r.done()


if __name__ == "__main__":
    main()
