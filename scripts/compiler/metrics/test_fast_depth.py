"""Numerical parity and timing for faster full-depth research iterations."""
import os
import sys
from pathlib import Path
from statistics import median
from time import perf_counter

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np
from compiler.metrics.depth_budget import Net, Eval, tokenize_greedy, top5_indices


def main():
    rng = np.random.default_rng(3)
    # Include ties at the selection boundary and duplicate vocabulary logits.
    for z in (rng.normal(size=(20, 200)), np.zeros((3, 10)),
              rng.integers(-3, 4, (20, 200)).astype(float)):
        want = np.sort(np.argsort(z, axis=-1)[:, -5:], axis=-1)
        assert np.array_equal(np.sort(top5_indices(z), axis=-1), want)
    net = Net(fast_attention=False)
    notes = Path.home() / "Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute"
    ids = tokenize_greedy(next(notes.glob("27l1 *.md")).read_text(), net.vocab)[:256]
    ev = Eval(net, ids)
    elapsed = {False: [], True: []}
    for _ in range(3):
        for fast in (False, True):
            net.fast_attention = fast
            start = perf_counter()
            z = net(ids)
            elapsed[fast].append(perf_counter() - start)
            assert np.allclose(z, ev.ref, rtol=2e-4, atol=2e-3)
            score = ev.score(z)
            assert abs(score["kl"]) < 1e-7 and score["argmax"] == 100.0 and score["top5"] == 5.0
    old_s, new_s = median(elapsed[False]), median(elapsed[True])
    z = ev.ref
    select_times = []
    for fn in (lambda a: np.argsort(a, axis=-1)[:, -5:], top5_indices):
        times = []
        for _ in range(5):
            start = perf_counter(); fn(z); times.append(perf_counter() - start)
        select_times.append(median(times))
    print("PASS: random/tied top-5 sets exactly match; full-model logits, KL, argmax and top-5 match")
    print(f"attention forward median: {old_s:.3f}s -> {new_s:.3f}s ({old_s/new_s:.2f}x)")
    print(f"top-5 selection median: {select_times[0]:.3f}s -> {select_times[1]:.3f}s ({select_times[0]/select_times[1]:.2f}x)")


if __name__ == "__main__":
    main()
