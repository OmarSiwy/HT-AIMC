"""Timing (check c): pass time, streaming stalls, and whether each drive mode settles in its slot.

    python3 test/tb_timing.py

  t_pass      measured on the driver RTL (iverilog, ideal tiles): median sample-to-sample interval of
              a streaming GEMM. BS6H + E-trim at AdcShare 3 against its 42-tick drive word (5.94 ns, D),
              AdcShare 4 (conversion-bound) and ml2 (replaced) reported
  no stall    weights in place before activations: zero stall ticks after the initial fill when the
              weight stream delivers a row word per tick (one tile load per pass)
  HBM-bound   the same GEMV with the ARCH per-tile HBM share (819 GB/s over 3,181 tiles): stall
              fraction measured vs the bandwidth law (decode is HBM-bound, as ARCH B9 says)
  settling    rail error at the share edge for n rows on one level: BS6H on the measured table (golden
              E_TAB, ASAP7 ESPice of the grid-driven rails at R_PDN 0.4 ohm, M), against the 0.1 % drive
              spec (B2). SS is reported (the open corner item: 7-tick slots close it)
"""
import importlib.util
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
    for mode, AS in (("bitserial", 3), ("bitserial", 4), ("ml2", 3)):
        cfg = replace(base, mode=mode, adc_share=AS)
        ok, r = DRV.run(f"timing_{mode}_as{AS}", cfg, job)
        nominal[(mode, AS)] = r["t_pass"]
        tm = G.timing(cfg.params())
        law = tm["t_pass"]
        check(f"t_pass {mode} AdcShare {AS}", abs(r["t_pass"] - law) < 0.5 * tick,
              f"RTL median {r['t_pass']:.3f} ns ({r['t_pass'] / tick:.0f} ticks of {tick * 1e3:.0f} ps) vs the "
              f"golden plan {law:.3f} ns: drive word {tm['t_word']:.3f} ns ({tm['t_word'] / tick:.0f} ticks, merge "
              f"hidden), conversion {tm['t_conv']:.3f} ns ({AS} rounds x {cfg.params().round_ticks} ticks)"
              + (" <- the pick" if (mode, AS) == ("bitserial", 3) else ""))
        check(f"no stall {mode} AdcShare {AS}", ok and r["stall"] == 0,
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
          f"tile busy {100 * int(r['passes']) * nominal[('bitserial', 3)] / (ticks * tick):.1f} % (decode is HBM-bound, B9)")
    # drive settling at the share edge (the slot's rail time), worst popcount: BS6H on the measured table
    for tag, p, gate in (("BS6H TT 0.4 ohm (M)", G.P(), True),
                         ("BS6H SS 0.4 ohm (M, open corner item)", G.P(corner="ss"), False),
                         ("BS6H SS 0.4 ohm, 7-tick slots (M)", G.P(corner="ss", slot_ticks_bs=7), True),
                         ("BS6H TT 1.3 ohm (M, the old tile PDN)", G.P(r_lvl_top=1.3), False)):
        e = {n: G.drive_settle_err(p, n)["top"] for n in (1, 4, 8)}
        ok = e[8] <= 1e-3
        line = (f"rails get {p.t_settle():.3f} ns of a {p.slot():.3f} ns slot; error at the share edge "
                f"(n = 1 / 4 / 8 rows on V) {e[1] * 100:.4f} / {e[4] * 100:.4f} / {e[8] * 100:.4f} % vs 0.1 %")
        if gate:
            check(f"settle {tag}", ok, line)
        else:
            print(f"{'PASS' if ok else 'OPEN'} settle {tag}: {line} (reported, not gating)", flush=True)
    print("ALL TIMING CHECKS PASS" if not FAILS else f"TIMING CHECKS FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
