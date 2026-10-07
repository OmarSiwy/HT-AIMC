"""SNR of Verilog-A-generated codes against the golden's error model, pooled (review finding 7).

    python3 test/tb_va_snr.py [bitserial|ml2] [n_runs] [full|dyn]   (default bitserial, 4 runs, full)

The full co-simulation path (driver RTL -> Verilog-A tiles in ESPice -> RTL chain, tb_cosim) on
block8 SmolLM2 attn_q data, every error term on, 2 tiles x 8 rows x 16 columns, 18 tokens per run;
each run has its own static draw (seed offset) and its own 16 output columns. The SNR of the chain
outputs against the exact INT8 dot products, pooled over all runs, is compared with the golden's on
the same jobs (8 seed sets). Gate: |SNR_VA - SNR_golden| <= 0.5 dB, the size of the margins in
question, widened to 2 sigma of the golden's seed-to-seed spread when that is larger: the frozen
static draws (C-DAC weights of only 2 x 4 x n_runs converters, unit caps) scatter the error power
from draw to draw, and the Verilog-A run is one draw. kind "dyn" switches the static terms off, so
the fresh per-event terms (kT/C, comparator, drive, share, reference) are compared at 0.5 dB with
small sampling error. The chain outputs are uncalibrated in both (identity cal), so static gain terms count in
full here; the per-pass calibrated SNR is tb_accuracy's.
"""
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tb_cosim as T        # noqa: E402
import jobs as J            # noqa: E402
from golden import imc_tile as G   # noqa: E402
from dataclasses import replace


def va_jobs(n_runs):
    rot = J.real_rot_job()
    X, W = G.block_scale(rot["X"], rot["W"], 8)
    M, C = X.shape[0], 16
    out = []
    for i in range(n_runs):
        a, b = 4 * i, 4 * i + 2                       # two token sets from different K-chunk pairs
        Xi = np.vstack([X[:, 8 * a:8 * a + 16], X[:, 8 * b:8 * b + 16]])
        Wi = W[8 * a:8 * a + 16, C * i:C * (i + 1)]
        out.append((f"va_snr_r{i}", dict(X=Xi, W=Wi, scale=np.ones(C, np.int64), shift=np.zeros(C, np.int64),
                                         offset=np.zeros(C, np.int64))))
    return out


def main(argv):
    mode = argv[1] if len(argv) > 1 else "bitserial"
    n_runs = int(argv[2]) if len(argv) > 2 else 4
    kind = argv[3] if len(argv) > 3 else "full"
    cfg = replace(T.gen.Cfg(), mode=mode, cols=16)
    p = cfg.params()
    if kind == "dyn":
        p = replace(p, terms=T.DYN)
    errs, ex = [], []
    for i, (name, job) in enumerate(va_jobs(n_runs)):
        r = T.evaluate(cfg, name, job, kind, *T.run_job(cfg, name, job, kind, seed0=100000 * (i + 1)))
        errs.append(r["err"].ravel()); ex.append(r["exact"].ravel())
    e, s = np.concatenate(errs).astype(float), np.concatenate(ex).astype(float)
    snr_va = 10 * math.log10(np.var(s) / np.mean(e ** 2))
    # golden on the same jobs, 8 seed sets
    gs = []
    for k in range(8):
        ge = []
        for i, (_, job) in enumerate(va_jobs(n_runs)):
            X, W = np.asarray(job["X"]), np.asarray(job["W"])
            tiles = [G.Tile(p, seed=1000 * k + 10 * i + t) for t in range(cfg.ntiles)]
            acc, _ = G.gemm(X, W, p, tiles=tiles)
            ge.append((acc * 64 - np.clip(X, -127, 127) @ np.clip(W, -127, 127)).ravel())
        gs.append(10 * math.log10(np.var(s) / np.mean(np.concatenate(ge).astype(float) ** 2)))
    g, gsd = float(np.mean(gs)), float(np.std(gs))
    d = snr_va - g
    gate = max(0.5, 2 * gsd)
    ok = abs(d) <= gate
    print(f"{'PASS' if ok else 'FAIL'} VA-vs-golden SNR {mode} {kind}: Verilog-A {snr_va:.2f} dB over {e.size} chain outputs "
          f"({n_runs} runs, own static draws), golden {g:.2f} +- {gsd:.2f} dB (8 seed sets); "
          f"difference {d:+.2f} dB vs gate {gate:.2f} dB (rms ratio {10 ** (-d / 20):.3f})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
