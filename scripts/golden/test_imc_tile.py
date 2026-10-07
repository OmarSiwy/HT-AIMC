"""Checks of the IMC tile golden (scripts/golden/imc_tile.py). Prints PASS/FAIL, exits non-zero on failure.

    python3 scripts/golden/test_imc_tile.py
"""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden import imc_tile as G      # noqa: E402
from golden.model import requant_int8  # noqa: E402


def main():
    G._selfcheck()
    rng = np.random.default_rng(9)
    p = G.P(noise=False, terms=())
    # formats: slicing and digits reconstruct the operands exactly
    W = rng.integers(-128, 128, 1000)
    s, hi, lo, n_clip = G.slice_w(W)
    assert np.all((1 - 2 * s) * (16 * hi + lo) == np.clip(W, -127, 127)) and n_clip == np.sum(W == -128)
    X = rng.integers(-128, 128, 1000)
    for mode, base, sc in (("ml2", 4, 2), ("bitserial", 2, 1)):
        sx, d = G.digits(X, mode)
        mag = np.sum(d * base ** np.arange(d.shape[1]), -1)
        assert np.all((1 - 2 * sx) * mag == sc * np.clip(X, -127, 127)), mode
    # calibration arithmetic is the RTL's: (g*c + o + 2^13) >> 14, arithmetic shift
    c = rng.integers(-2048, 2048, 500)
    g = rng.integers(0, 65536, 500)
    o = rng.integers(-(1 << 19), 1 << 19, 500)
    ref = np.array([(int(a) * int(b) + int(z) + (1 << 13)) >> 14 for a, b, z in zip(c, g, o)])
    assert np.all(G.cal_apply(c, g, o) == ref)
    # requant on the code domain equals requant on 64 x acc in the systolic reference's function
    acc = rng.integers(-(1 << 20), 1 << 20, 64)
    sc_, sh_, of_ = rng.integers(0, 256, 64), rng.integers(0, 25, 64), rng.integers(-128, 128, 64)
    assert np.all(G.requant(acc, p, sc_, sh_, of_) == requant_int8(acc * 64, sc_, sh_, of_))
    # noise on: the error model is unbiased and its kT/C term shrinks with C (sanity of the laws)
    Wt = rng.integers(-127, 128, (8, 64))
    Xt = np.clip(np.rint(rng.standard_normal((300, 8)) * 40), -127, 127).astype(int)
    s1, _, e1 = G.pass_snr(replace(G.P(cols=64), terms=("ktc",)), Wt, Xt, seed=1)
    s2, _, e2 = G.pass_snr(replace(G.P(cols=64, cu_msb=4e-15, cu_lsb=1e-15), terms=("ktc",)), Wt, Xt, seed=1)
    assert s2 > s1 + 3, (s1, s2)
    assert abs(np.mean(e1)) < 0.2 * np.std(e1)
    # reference model: an ideal reference (ref term off) gives ideal codes; the droop at the decisions
    # grows with the number of converters on the node and is gone when the decap is huge
    v = rng.uniform(-0.6, 0.6, (50, 16))
    dw = np.tile(2.0 ** np.arange(12), (16, 1))
    ci = np.clip(np.floor(v / p.lsb() + 0.5), -2048, 2047)
    c0, _ = G.sar_convert(v, replace(p, terms=()), dw)
    assert np.all((c0 == ci) | (np.abs(v / p.lsb() % 1 - 0.5) < 1e-9))
    pr = replace(p, terms=("ref",))
    tr1, tr4 = [], []
    G.sar_convert(v, pr, dw, mult=1, trace=tr1)
    G.sar_convert(v, pr, dw, mult=4, trace=tr4)
    assert 3.5 < np.max(tr4) / np.max(tr1) < 4.5
    cbig, _ = G.sar_convert(v, replace(pr, c_ref=1e-3, r_ref=1e-6), dw, mult=4)
    assert np.all(cbig == c0)
    # timing law
    t = G.timing(G.P())
    assert abs(t["t_word"] - 5 * 1.132) < 0.01 and abs(t["t_conv"] - 4 * 11 * 1.132 / 8) < 1e-9
    print("PASS test_imc_tile: formats, cal arithmetic, requant equivalence, kT/C law, reference law, timing law")
    return 0


if __name__ == "__main__":
    sys.exit(main())
