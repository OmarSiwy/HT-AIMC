"""integrator_conv: single-column conversion vs golden, through the conv_seq handshakes.

Contract acceptance A1 (analog/analogioc/docs/INTERFACE.md §10), D = 1:
  mac in {0, 15, 16, -50, 165}: |code - golden.eventrate_convert| <= 1
  coarse decisions (cb_req count) = crossings + 1 per conversion (n_eval)
  E(0) < 0.3 * E(165) (early termination)
Fixture: test/conv_bench.py (real 1x1 weight_tile, ladders, transistor-level conv_seq,
XSPICE rail stand-in). Away from tt/27 C the reference rails stay at their nominal
(ideal, uncalibrated) values, so the code tolerance there is the tile gate CODE_TOL
(§10) and the +-1 count is reported.
Adapted from AnalogIOC analog/testbenches/tb_integrator_conv.py.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conv_bench import PDK, run_point  # noqa: E402
from bench import Report  # noqa: E402

# (w, nibble, negative): 0, fine-only max, exactly one packet, negative mid, near-full
POINTS = [(0, 0, False), (1, 15, False), (2, 8, False), (5, 10, True), (15, 11, False)]
CODE_TOL = 8          # §10 gate; +-1 is the tt/27 C acceptance
JOBS = int(os.environ.get("JOBS", 8))


def nominal():
    return os.environ.get("CORNER", PDK.typical) == PDK.typical and \
        float(os.environ.get("SIM_TEMP", 27)) == 27


def points(pts):
    with ThreadPoolExecutor(min(JOBS, len(pts))) as ex:
        return list(ex.map(lambda p: run_point(*p), pts))


def show(p):
    print(f"    mac {p['mac']:+4d}: code {p['code']:+4d} (exp {p['exp_code']:+4d}) "
          f"coarse {p['count']}/{p['exp_count']} fine {p['fine']:2d}/{p['exp_fine']:2d} "
          f"decisions {p['n_dec']} E_coarse {p['e_coarse_pJ']:5.2f} pJ "
          f"E_fine {p['e_fine_pJ']:5.2f} pJ  T_conv {p['t_conv_ns']:.0f} ns")


def main():
    r = Report("integrator_conv")
    res = points(POINTS)
    for p in res:
        show(p)
    tol = 1 if nominal() else CODE_TOL
    err = [abs(p["code"] - p["exp_code"]) for p in res]
    r.check(f"all codes within +-{tol} LSB", max(err) <= tol,
            f"worst {max(err)}, {sum(e > 1 for e in err)} outside +-1")
    r.check("SAR completed (4 trials) on every point", all(p["fine_done"] for p in res))
    r.check("decisions = crossings + 1 (n_eval)",
            all(p["n_dec"] == p["count"] + 1 for p in res),
            " ".join(f"{p['n_dec']}/{p['exp_n_eval']}" for p in res) + " (measured/golden)")
    e = {abs(p["mac"]): p["e_coarse_pJ"] + p["e_fine_pJ"] for p in res}
    r.check("E(0) < 0.3 E(165) (early termination)", e[0] < 0.3 * e[165],
            f"{e[0]:.2f} / {e[165]:.2f} pJ = {e[0] / e[165]:.2f}")
    r.done()


if __name__ == "__main__":
    main()
