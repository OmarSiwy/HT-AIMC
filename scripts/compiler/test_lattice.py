#!/usr/bin/env python3
"""Task C tests: CSNR mid-lattice converter thresholds
(python3 scripts/compiler/test_lattice.py). Prints PASS/FAIL.

(a) golden lattice primitives: achievable-value lattice + pitch, mid-lattice
    thresholds delete noise below half the local pitch EXACTLY;
(b) the paper's law:csnr regime -- when lattice pitch >> sigma_a the
    mid-lattice converter beats the uniform converter by many dB; the gain
    DIES when the lattice densifies / sigma collapses the pitch (measured
    crossover), reproducing 'up to +6 dB when Delta >> sigma, dies otherwise';
(c) real SmolLM2 head-0 + FFN matrices: positive CSNR gain in the low-noise
    regime, decaying with sigma_a; schedule emits valid 4b ladder tap codes.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compiler import lattice as L      # noqa: E402
from compiler import compile as CC     # noqa: E402
from golden import model as G          # noqa: E402

rng = np.random.default_rng(5)


def test_lattice_primitives():
    # sparse column -> coarse pitch (shared factor); dense -> pitch 1
    w = np.array([2, 0, 0, -2, 0, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    X = rng.integers(0, 16, (300, 16))
    macs, pitch = G.output_lattice(w, X)
    assert pitch == 2, pitch                       # gcd of {2,2,4} weights
    assert np.all(np.diff(macs) > 0)               # sorted unique
    thr = G.lattice_thresholds(macs, D=1)
    assert thr.size == macs.size - 1
    # noise strictly below half the pitch is DELETED (snaps back exactly)
    ideal = X @ w
    noisy = ideal + rng.uniform(-0.49 * pitch, 0.49 * pitch, ideal.shape)
    y = G.convert_lattice(noisy, macs, thr)
    assert np.array_equal(y, ideal), "sub-half-pitch noise not deleted"


def test_law_csnr_regime():
    """Paper L6: big gain when pitch >> sigma; gain dies as sigma grows /
    lattice densifies. One sparse (coarse-pitch) column shows both ends."""
    w = np.zeros(16, dtype=np.int64)
    w[[1, 9]] = [3, 3]                              # pitch = 3
    X = rng.integers(0, 16, (800, 16))
    macs, pitch = G.output_lattice(w, X)
    assert pitch == 3
    thr = G.lattice_thresholds(macs, 1)
    ideal = X @ w

    def gain(sig):
        noisy = ideal + rng.normal(0, sig, ideal.shape)
        return (G.csnr_db(ideal, G.convert_lattice(noisy, macs, thr))
                - G.csnr_db(ideal, G.convert_uniform(noisy, 1)))

    g_win = gain(0.4)          # pitch/sigma = 7.5 -> deep in the win regime
    g_die = gain(6.0)          # pitch/sigma = 0.5 -> pitch collapsed
    print(f"\n    law:csnr sparse col (pitch=3): gain {g_win:+.2f} dB at "
          f"sigma 0.4 (pitch/sig 7.5), {g_die:+.2f} dB at sigma 6 (0.5)")
    assert g_win > 3.0, "expected large gain when pitch >> sigma"
    assert g_die < 0.5, "gain should die once pitch collapses"

    # dense lattice (every integer achievable) -> mid-lattice == uniform:
    wd = rng.integers(1, 8, 16)                     # all nonzero, pitch 1
    Xd = rng.integers(0, 16, (800, 16))
    md, pd = G.output_lattice(wd, Xd)
    thrd = G.lattice_thresholds(md, 1)
    idd = Xd @ wd
    noisy = idd + rng.normal(0, 4.0, idd.shape)     # sigma >> pitch 1
    gd = (G.csnr_db(idd, G.convert_lattice(noisy, md, thrd))
          - G.csnr_db(idd, G.convert_uniform(noisy, 1)))
    assert abs(gd) < 0.5, f"dense-lattice gain should vanish, got {gd:+.2f}"


def _res():
    if not hasattr(_res, "r"):
        with tempfile.TemporaryDirectory() as td:
            _res.r = CC.run(out=Path(td), quiet=True)
    return _res.r


def test_real_model_gain_and_schedule():
    res = _res()
    sigmas = (0.5, 1.0, 2.0, 4.0, 8.0)
    peaks = {}
    for n in ("attn_q", "attn_k", "attn_v", "attn_o",
              "ffn_gate", "ffn_up", "ffn_down"):
        C = res["mats"][n]
        cur = L.csnr_gain_curve(C["Wq"], res["stream"][n], C["D"], sigmas)
        # peak over finite entries (inf = total deletion at some sigma)
        finite = [v["gain_db"] for v in cur.values() if np.isfinite(v["gain_db"])]
        peaks[n] = max(finite)
        # low-noise gain must be strictly positive (lattice is a real subset)
        assert cur[0.5]["gain_db"] > 0 or not np.isfinite(cur[0.5]["gain_db"]), n
        # monotone decay of the win with rising analog noise (finite tail)
        assert cur[8.0]["gain_db"] <= cur[2.0]["gain_db"] + 0.5, (n, cur)
    print("    real gains (peak dB): " + ", ".join(
        f"{n} {peaks[n]:+.1f}" for n in peaks))
    assert min(peaks.values()) > 0, peaks

    # schedule emission: valid 4b ladder tap codes, monotone rails
    C = res["mats"]["attn_q"]
    sched = L.lattice_schedule(C["Wq"], res["stream"]["attn_q"], C["D"])
    assert len(sched) == C["Wq"].shape[0] // 16
    for b in sched:
        assert b["vrn_code"] <= b["vrp_code"]
        t = np.array(b["tap_codes"])
        assert np.all((t >= 0) & (t <= 15)), "tap codes must be 4b"
        assert len(b["boundaries"]) == b["n_lattice"] - 1
        assert np.all(np.diff(b["lattice"]) > 0)


def test_run_emission():
    with tempfile.TemporaryDirectory() as td:
        r = L.run_lattice(out=Path(td) / "o", quiet=True,
                          sigmas=(0.5, 1.0, 2.0, 4.0))
        o = Path(td) / "o"
        assert (o / "threshold_schedule.json").exists()
        assert (o / "csnr_gain.json").exists()
        import json
        ts = json.loads((o / "threshold_schedule.json").read_text())
        assert ts["ladder_taps"] == 16
        for n, mm in ts["matrices"].items():
            for b in mm["blocks"]:
                assert all(0 <= t <= 15 for t in b["tap_codes"])
        gv = json.loads((o / "csnr_gain.json").read_text())
        # every matrix wins in the low-noise regime
        for n, c in gv["matrices"].items():
            g = c["0.5"]["gain_db"]
            assert g > 0 or not np.isfinite(g), (n, g)
        print("    lattice e2e: schedule + gain curve for "
              f"{len(ts['matrices'])} matrices, all valid tap codes")


def main():
    for t in (test_lattice_primitives, test_law_csnr_regime,
              test_real_model_gain_and_schedule, test_run_emission):
        t()
        print(f"  ok {t.__name__}")
    print("PASS test_lattice")


if __name__ == "__main__":
    try:
        main()
    except AssertionError:
        import traceback
        traceback.print_exc()
        print("FAIL test_lattice")
        sys.exit(1)
