"""weight_tile write yield, Monte Carlo (ladder rung 5): MC_N mismatch samples (default
200) of one bitcell at the typical corner's mismatch section (sky130 `tt_mm`).

Per sample: tb_weight_write.write_margin() — the BL level that flips a stored 1 with
WL = BLB = VDD. Spec rows (analog/weight_tile/docs/architecture.md):
  1. every sample writes (margin > 0)
  2. projected tile write yield >= wt.YIELD: mean - z*sigma >= 0 with z the per-bit
     sigma that YIELD over all 8*N_ROWS*N_COLS bits needs (the same z as wt.wm_min())
Transistor-level only: DUT=va skips with PASS.
"""
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from pathlib import Path
from statistics import NormalDist

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tb_weight_write import N_BITS_TILE, write_margin  # noqa: E402
from bench import Report, dut_kind  # noqa: E402
from pdk_specs import get_pdk  # noqa: E402
import weight_tile as wt  # noqa: E402

N = int(os.environ.get("MC_N", 200))
JOBS = int(os.environ.get("JOBS", 8))


def main():
    pdk = get_pdk()
    section = pdk.typical + pdk.mismatch_suffix if pdk.mismatch_suffix else pdk.mc_section
    r = Report(f"weight_tile write yield MC ({N} samples, {section})")
    if dut_kind() == "va":
        print("  skip  transistor-level cell (DUT=va)")
        r.done()
    with ProcessPoolExecutor(JOBS) as ex:
        wm = list(ex.map(partial(write_margin, section, None), range(1, N + 1)))
    mu, sd = statistics.mean(wm), statistics.stdev(wm)
    z = NormalDist().inv_cdf(1 - (1 - wt.YIELD) / N_BITS_TILE)
    fails = sum(w <= 0 for w in wm)
    print(f"  write margin [mV]: mean {mu * 1e3:.0f}, sigma {sd * 1e3:.1f}, min "
          f"{min(wm) * 1e3:.0f}, max {max(wm) * 1e3:.0f}; mean/sigma {mu / sd:.1f}")
    r.check(f"every sample writes ({N - fails}/{N})", fails == 0)
    r.check(f"tile write yield >= {wt.YIELD} ({N_BITS_TILE} bits, z = {z:.2f})",
            mu - z * sd >= 0, f"mean - z*sigma = {(mu - z * sd) * 1e3:.0f} mV")
    r.done()


if __name__ == "__main__":
    main()
