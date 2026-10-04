"""WTA Monte Carlo replica-cancelled offset (signoff ladder rung 5).

The replica offset is the block's mismatch-sensitive metric: m_hat = mrail - rrail + vref
cancels VGS only as far as the winning follower + main tail match the replica follower +
replica tail. Per sample: the PDK's mismatch section at the typical corner (sky130
`tt_mm`) with a fresh ngspice seed, one clear winner at vref (tb_wta's offset setup).
MC_N samples (default 30).

  3-sigma of the random part <= 5 mV (CHIP2_SPEC 2.3, the sizing target of netlist/wta.py)
  no sample below -5 mV (an underestimate is the unsafe direction)
"""
import os
import statistics
import sys
from pathlib import Path

A = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(A / "docs"), str(A / "common"), str(Path(__file__).parent)]
from bench import Report  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
from tb_wta import OFFSET_PAT, VREF, mhat, run  # noqa: E402

N_MC = int(os.environ.get("MC_N", 30))
T_END = 0.5e-6     # settle is < 0.1 us (tb_wta); the full 2 us window buys nothing here


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"wta MC ({N_MC} samples, {section})")
    offs = [mhat(run(OFFSET_PAT, seed=s, t_end=T_END, corner=section)) - VREF
            for s in range(1, N_MC + 1)]
    mu, sd = statistics.mean(offs), statistics.stdev(offs)
    r.check("mismatch actually sampled (sigma > 0)", sd > 0, f"sigma {sd * 1e3:.3f} mV")
    r.check("3-sigma random offset <= 5 mV", 3 * sd <= 5e-3,
            f"mean {mu * 1e3:+.2f} mV, sigma {sd * 1e3:.2f} mV")
    r.check("no sample underestimates by > 5 mV", min(offs) >= -5e-3,
            f"min {min(offs) * 1e3:+.2f} mV, max {max(offs) * 1e3:+.2f} mV")
    r.done()


if __name__ == "__main__":
    main()
