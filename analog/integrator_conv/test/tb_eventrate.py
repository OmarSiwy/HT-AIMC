"""Event-rate coarse loop energy: E_conv vs |code| (contract acceptance A2).

The tb_integrator_conv points (cached by conv_bench) plus mac 32 (2 packets) and 80
(5 packets): >= 7 points.
  E_conv non-decreasing in |code| (5 % slack)
  E(code 0) / mean < 0.30 (early termination: energy stops with the events)
Adapted from AnalogIOC analog/testbenches/tb_eventrate.py.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tb_integrator_conv import POINTS, points  # noqa: E402
from bench import Report  # noqa: E402

EXTRA = [(4, 8, False), (8, 10, False)]


def main():
    r = Report("integrator_conv eventrate")
    res = sorted(points(POINTS + EXTRA), key=lambda p: abs(p["code"]))
    es = [p["e_coarse_pJ"] + p["e_fine_pJ"] for p in res]
    for p, e in zip(res, es):
        print(f"    |code| {abs(p['code']):3d} (mac {p['mac']:+4d}): E_conv {e:6.2f} pJ "
              f"(coarse {p['e_coarse_pJ']:.2f} + fine {p['e_fine_pJ']:.2f})")
    r.check(">= 7 points", len(res) >= 7, f"{len(res)}")
    r.check("E_conv non-decreasing in |code| (5 % slack)",
            all(b >= a * 0.95 for a, b in zip(es, es[1:])))
    mean = sum(es) / len(es)
    e0 = next(e for p, e in zip(res, es) if p["code"] == 0)
    r.check("E(code 0) / mean < 0.30", e0 < 0.3 * mean,
            f"{e0:.2f} / {mean:.2f} pJ = {e0 / mean:.2f}")
    r.done()


if __name__ == "__main__":
    main()
