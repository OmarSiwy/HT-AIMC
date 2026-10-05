"""integrator_conv Monte Carlo: converter offset and offset-corrected code (ladder rung 5).

Per sample (the PDK's mismatch section at the typical corner, sky130 `tt_mm`, fresh
ngspice seed): convert mac 0 (the offset: the code an empty column reads) and mac 50.
The system removes the offset with its x = 0 zero-point (tb_tile_mvm, AnalogIOC's
shipping convention), so the yield criterion is the offset-corrected code
code(50) - code(0) within the tile gate CODE_TOL of golden on every sample; the raw
offset distribution and the +-1 count are reported. Device mismatch in both StrongARMs,
the OTA and the switches moves every threshold; the reference rails are ideal (§2).
MC_N samples (default 16), JOBS parallel simulations.
"""
import os
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conv_bench import PDK, run_point  # noqa: E402
from tb_integrator_conv import CODE_TOL, JOBS  # noqa: E402
from bench import Report  # noqa: E402

N = int(os.environ.get("MC_N", 16))
MID = (5, 10, False)       # mac +50


def sample(seed, section):
    z = run_point(0, 0, False, seed=seed, corner=section)
    m = run_point(*MID, seed=seed, corner=section)
    return z, m


def main():
    section = PDK.typical + PDK.mismatch_suffix if PDK.mismatch_suffix else PDK.mc_section
    r = Report(f"integrator_conv MC ({N} samples, {section})")
    with ThreadPoolExecutor(max(1, JOBS // 2)) as ex:
        res = list(ex.map(lambda s: sample(s, section), range(1, N + 1)))
    off = [z["code"] for z, _ in res]
    corr = [m["code"] - z["code"] - m["exp_code"] for z, m in res]
    print(f"  info  offset code(0): {off}")
    print(f"  info  corrected error code(50)-code(0)-50: {corr}")
    mu, sd = statistics.mean(off), statistics.pstdev(off)
    print(f"  info  offset mean {mu:+.2f} LSB, sigma {sd:.2f} LSB; "
          f"{sum(abs(o) <= 1 for o in off)}/{N} within +-1")
    r.check("every sample converts (SAR completes)", all(z["fine_done"] and m["fine_done"]
                                                         for z, m in res))
    r.check("mismatch is sampled (offset varies)", len(set(off + corr)) > 1)
    r.check(f"offset-corrected code within +-{CODE_TOL} LSB on every sample",
            max(abs(c) for c in corr) <= CODE_TOL,
            f"worst {max(corr, key=abs):+d}, {sum(abs(c) <= 1 for c in corr)}/{N} within +-1")
    r.done()


if __name__ == "__main__":
    main()
