#!/usr/bin/env python3
"""Self-check for quality.py. Prints PASS/FAIL per check, exits nonzero on FAIL.
Uses 1 eval window (511 tokens) to stay fast; reference cached under out/."""
import sys

import numpy as np

from quality import Err, digits, evaluate, make_lin, quantize, resolve

fails = 0


def check(name, ok, info=""):
    global fails
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}", flush=True)


# unit: slicing recombines exactly; int quantizer round-trips integer grids
C = np.arange(-127, 128, dtype=np.float32)[None]
check("digits recombine", all(np.array_equal(sum(s * D.astype(np.float32) for s, D, _ in digits(C, b, 127)), C)
                              for b in (1, 2, 3, 4, 8)))
c, s, _ = quantize(C, "int8", "channel", 0, False, 1.0)
check("int8 quantize exact on grid", np.allclose(c * s, C))

W1 = 1                                                   # windows
r0 = evaluate(None, W1)
check("zero-error == reference", abs(r0["delta_pct"]) < 1e-9 and r0["top1_agree"] == 1.0, r0)
re = evaluate(Err(), W1)
check("Err() (all fields exact) == reference", abs(re["delta_pct"]) < 1e-9 and re["top1_agree"] == 1.0, re)

# ideal analog path (slices, row tiles, no ADC/noise) == digital quant path, per linear.
# Compared per layer, not by PPL: fp32 summation-order differences flip a few
# round-half activation codes downstream, which moves PPL by ~1 se (chaotic, not a bug).
la = make_lin(resolve(Err(w_fmt="int8", a_fmt="int8", rows=128, w_slice_bits=4, x_slice_bits=4)), {}, None, None)
ld = make_lin(resolve(Err(w_fmt="int8", a_fmt="int8")), {}, None, None)
x = np.random.default_rng(0).standard_normal((32, 1536)).astype(np.float32)
x[:, 7] *= 40                                            # an outlier channel
err = max(float(np.abs(la(li, k, x[:, :K]) - ld(li, k, x[:, :K])).max() / np.abs(ld(li, k, x[:, :K])).max())
          for li, k, K in ((0, "q", 576), (0, "k", 576), (3, "down", 1536), (-1, "head", 576)))
check("ideal analog path == digital quant path (per linear)", err < 1e-5, f"max rel err {err:.1e}")

rh = evaluate(Err(hadamard=True, smooth=0.5), W1)
check("FP Hadamard+smooth is output-invariant", abs(rh["delta_pct"]) < 0.5 and rh["top1_agree"] > 0.97, rh)

rn = evaluate(Err(w_fmt="int8", a_fmt="int8", rows=128, w_slice_bits=4, x_slice_bits=4, noise=0.05, adc_bits=8), W1)
check("heavy noise (5% FS) degrades", rn["delta_pct"] > 20 and rn["top1_agree"] < 0.8, rn)
r2 = evaluate(Err(w_fmt="int2", a_fmt="int8"), W1)
check("INT2 weights degrade", r2["delta_pct"] > 100, r2)

print("ALL PASS" if not fails else f"{fails} FAIL")
sys.exit(bool(fails))
