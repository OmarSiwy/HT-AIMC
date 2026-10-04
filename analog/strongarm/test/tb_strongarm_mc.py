"""StrongARM Monte Carlo offset: 3-sigma |Vos| < 10 mV (signoff ladder rung 5).

Per sample: the PDK's mismatch section at the typical corner (sky130 `tt_mm`) with a
fresh ngspice seed; offset found by bisecting vdiff for the decision flip (0.3 mV
resolution over +-20 mV). MC_N samples (default 30).
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
from bench import Report, testbench  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_strongarm import CLK_EDGE, CLK_RISE, C_LOAD, PORTS, VCM, VDD  # noqa: E402

N = int(os.environ.get("MC_N", 30))
END = CLK_RISE + CLK_EDGE + 6e-9


def outp_high(vdiff, seed, section):
    tb = testbench("strongarm", PORTS, corner=section)
    tb.options(seed=seed)
    tb.V(name="sup", positive="vdd", negative="0", value=VDD)
    tb.V(name="ss", positive="vss", negative="0", value=0.0)
    tb.V(name="inp", positive="vinp", negative="0", value=VCM + vdiff / 2)
    tb.V(name="inn", positive="vinn", negative="0", value=VCM - vdiff / 2)
    tb.PieceWiseLinearVoltageSource(
        name="clk", positive="clk", negative="0",
        values=[(0, 0), (CLK_RISE, 0), (CLK_RISE + CLK_EDGE, VDD), (END, VDD)])
    tb.C(name="lp", positive="outp", negative="0", value=C_LOAD)
    tb.C(name="ln", positive="outn", negative="0", value=C_LOAD)
    return tb.transient(step_time=0.05e-9, end_time=END)["outp"][-1] > VDD / 2


def offset(seed, section):
    lo, hi = -20e-3, 20e-3          # outp high at lo (vinn wins), low at hi
    if not outp_high(lo, seed, section) or outp_high(hi, seed, section):
        return None
    for _ in range(7):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if outp_high(mid, seed, section) else (lo, mid)
    return (lo + hi) / 2


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"strongarm MC ({N} samples, {section})")
    offs = [offset(seed, section) for seed in range(1, N + 1)]
    bad = offs.count(None)
    r.check("every sample resolves within +-20 mV", bad == 0, f"{bad} unresolved")
    offs = [o for o in offs if o is not None]
    mu, sd = statistics.mean(offs), statistics.stdev(offs)
    r.check("3-sigma |Vos| < 10 mV", abs(mu) + 3 * sd < 10e-3,
            f"mean {mu * 1e3:.2f} mV, sigma {sd * 1e3:.2f} mV")
    r.done()


if __name__ == "__main__":
    main()
