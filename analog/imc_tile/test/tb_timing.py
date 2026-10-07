"""Timing (check c): pass time, streaming stalls, and whether each drive mode settles in its slot.

    python3 test/tb_timing.py

  t_pass      measured on the driver RTL (iverilog, ideal tiles): median sample-to-sample interval of
              a streaming GEMM, both drive modes, against ARCH's 6.30 ns
  no stall    weights in place before activations: zero stall ticks after the initial fill when the
              weight stream delivers a row word per tick (one tile load per pass)
  HBM-bound   the same GEMV with the ARCH per-tile HBM share (819 GB/s over 3,181 tiles): stall
              fraction measured vs the bandwidth law (decode is HBM-bound, as ARCH B9 says)
  settling    rail error at the share edge for n rows on one level (law validated against the
              Verilog-A drive network in tb_va_units), against the 0.1 % drive spec (B2)
"""
import importlib.util
import math
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "digital/imc_driver/test"))
import gen                         # noqa: E402
import jobs as J                   # noqa: E402
from golden import imc_tile as G   # noqa: E402

_spec = importlib.util.spec_from_file_location("imc_driver_tests", ROOT / "digital/imc_driver/test/run_tests.py")
DRV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DRV)
FAILS = []
T_PASS_ARCH = 6.30
HBM_B_PER_NS_TILE = 819.0 / 3181         # 819 GB/s shared by 3,181 tiles (ARCH B9, P)


def check(name, ok, msg):
    print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}", flush=True)
    if not ok:
        FAILS.append(name)


def main():
    rng = np.random.default_rng(3)
    base = gen.Cfg()
    tick = 2 * gen.HALF_PS / 1000
    job = J.SR.rand_job(rng, 32, 64, 16)
    nominal = {}
    for mode in ("ml2", "bitserial"):
        ok, r = DRV.run(f"timing_{mode}", replace(base, mode=mode), job)
        nominal[mode] = r["t_pass"]
        p = replace(base, mode=mode).params()
        tm = G.timing(p)
        check(f"t_pass {mode}", r["t_pass"] <= T_PASS_ARCH,
              f"RTL median {r['t_pass']:.3f} ns ({r['t_pass'] / tick:.0f} ticks of {tick * 1e3:.0f} ps) vs ARCH {T_PASS_ARCH} ns; "
              f"drive word {tm['t_word']:.2f} ns, conversion {tm['t_conv']:.2f} ns (4 rounds x 11 ticks)")
        check(f"no stall {mode}", ok and r["stall"] == 0,
              f"{r['stall']} stall ticks after the initial fill, M=32 tokens per weight group, bit-exact {ok}")
    # HBM-bound GEMV: a row word of Cols bytes arrives every Cols / (B/ns) ns
    gap = max(1, round(base.cols / HBM_B_PER_NS_TILE / tick))
    jv = J.SR.rand_job(rng, 1, 64, 16)
    ok, r = DRV.run("timing_gemv_hbm", replace(base, hbm_gap=gap), jv)
    ticks = int(r["log"].split("ticks=")[1].split()[0])
    rows = len(r["L"]["w"])
    law = rows * gap
    check("HBM-bound GEMV", ok and r["stall"] > 0 and abs(ticks - law) / law < 0.15,
          f"ARCH per-tile HBM share {HBM_B_PER_NS_TILE:.3f} B/ns -> one {base.cols}-B row word per {gap} ticks; "
          f"run {ticks} ticks vs weight-stream law {law} ticks ({rows} rows); {r['stall']} stall ticks after fill; "
          f"tile busy {100 * int(r['passes']) * nominal['ml2'] / (ticks * tick):.1f} % (decode is HBM-bound, B9)")
    # drive settling at the share edge (the slot's rail time), worst popcount
    for mode, rmid in (("ml2", 2.54), ("ml2", 5.3), ("bitserial", None)):
        p = G.P(mode=mode) if rmid is None else G.P(mode=mode, r_lvl_mid=rmid)
        e = {n: G.drive_settle_err(p, n) for n in (1, 4, 8)}
        worst = max(max(v.values()) for v in e.values())
        lv = "mid (V/3, 2V/3)" if mode == "ml2" else "V"
        r_used = rmid if rmid else p.r_lvl_top
        tau8 = p.tau_row + max(r_used, p.r_lvl_top) * 8 * p.c_row
        t_need = tau8 * math.log(1e3)
        tag = f"{mode}" + (f" r_lvl_mid={rmid} ohm" if rmid else "")
        check(f"settle {tag}", worst <= 1e-3,
              f"rails get {p.t_settle():.3f} ns of a {p.slot():.3f} ns slot; worst error at the share edge "
              f"(n = 8 rows on the {lv} level) {worst * 100:.3f} % of the level vs 0.1 %; "
              f"0.1 % needs {t_need * 1e9:.3f} ns at n = 8")
    print("ALL TIMING CHECKS PASS" if not FAILS else f"TIMING CHECKS FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
