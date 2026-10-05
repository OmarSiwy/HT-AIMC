"""sa_top regression: numpy golden -> cycle-exact schedule -> iverilog -> bit-exact check.

    python3 test/run_tests.py            # all cases (needs iverilog + numpy on PATH)
    python3 test/run_tests.py real       # only the SmolLM2 transformer GEMM
    python3 test/run_tests.py vcd        # write build/power/sa.vcd (16x16, prefill GEMM)

Every case checks (1) each INT8 output row == golden requant, (2) each column's INT32
accumulator result == X @ W, (3) the RTL's last-output cycle == the scheduler's
prediction (so the utilization model used for PPA is the RTL's real throughput).
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BLK = HERE.parent
sys.path.insert(0, str(HERE))
import sched as S  # noqa: E402

SRC = sorted(str(p) for p in (BLK / "src").glob("*.sv"))
TB = str(HERE / "tb_sa_top.sv")


def run_case(name, cfg, jobs, vcd_dir=None):
    out = Path(vcd_dir) if vcd_dir else BLK / "build" / "test" / name
    out.mkdir(parents=True, exist_ok=True)
    ev, n_cyc, outs, sums, macs, _ = S.schedule(cfg, jobs)
    words = S.pack(cfg, ev, n_cyc)
    (out / "stim.hex").write_text("\n".join(f"{w:x}" for w in words) + "\n")
    shift = cfg.C * 8
    (out / "exp.hex").write_text("\n".join(
        f"{(idx << shift) | sum((int(v) & 0xFF) << (8 * i) for i, v in enumerate(y)):x}"
        for idx, y in outs) + "\n")
    params = dict(Rows=cfg.R, Cols=cfg.C, WW=cfg.WW, AccDepth=cfg.D, PipeMul=cfg.P,
                  NCyc=n_cyc, NExp=len(outs))
    pargs = [f"-Ptb_sa_top.{k}={v}" for k, v in params.items()]
    pargs.append(f'-Ptb_sa_top.Dir="{out}"')
    vvp = out / "tb.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(vvp), *pargs, TB, *SRC], check=True)
    res = subprocess.run(["vvp", "-n", str(vvp)] + (["+vcd"] if vcd_dir else []),
                         capture_output=True, text=True)
    log = res.stdout
    ok = "PASS" in log and "FAIL" not in log
    # INT32 sums, per column in emission order
    got = {}
    for line in (out / "sums.txt").read_text().split("\n"):
        if line:
            c, v = line.split()
            got.setdefault(int(c), []).append(int(v))
    for c in range(cfg.C):
        exp = [int(s[c]) for s in sums]
        if got.get(c, []) != exp:
            ok = False
            print(f"  INT32 sums mismatch in column {c}")
            break
    # cycle check: last output = last-issue + pipeline latency (tb cycle numbering)
    last = int(log.split("last_out_cycle=")[1].split()[0]) if "last_out_cycle=" in log else -1
    pred = max(t for t, e in ev.items() if "a" in e) + cfg.lat
    if last != pred:
        ok = False
        print(f"  last output at cycle {last}, scheduler predicts {pred}")
    util = macs / (n_cyc * cfg.R * cfg.C)
    print(f"{'PASS' if ok else 'FAIL'} {name}: R{cfg.R}xC{cfg.C} WW{cfg.WW} D{cfg.D} "
          f"pipe{cfg.P} outputs={len(outs)} cycles={n_cyc} util={util:.3f}")
    if not ok:
        print(log[-2000:])
    return ok


def rand_job(rng, M, K, N, ww=8, xlo=-128, xhi=127):
    wmax = (1 << (ww - 1))
    X = rng.integers(xlo, xhi + 1, (M, K))
    W = rng.integers(-wmax, wmax, (K, N))
    # scale/shift chosen so outputs land mostly in range with some saturation
    return dict(X=X, W=W, scale=rng.integers(1, 256, N), shift=rng.integers(8, 25, N),
                offset=rng.integers(-128, 128, N))


def sparse(rng, job, p):
    job["X"] = np.where(rng.random(job["X"].shape) < p, 0, job["X"])
    return job


def real_job():
    """SmolLM2-135M blk.0 attn_q (576x576) on the rmsnormed prompt embeddings."""
    sys.path.insert(0, str(S.ROOT / "scripts"))
    from compiler import compile as CC
    from compiler.gguf_reader import tokenize_greedy
    from golden import model as G
    model = CC.MODEL
    if not model.exists():                          # worktree: fall back to main checkout
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=HERE,
                                capture_output=True, text=True).stdout.strip()
        model = Path(common).resolve().parent / "scripts/models/smollm2-135m-q8_0.gguf"
    if not model.exists():
        return None
    m = CC.load_model(model)
    ids = tokenize_greedy(CC.PROMPT, m["vocab"])
    A = CC.rms_rows(m["embd"][ids].astype(np.float64), m["attn_norm"], m["rms_eps"])
    Wf = m["gguf"].array("blk.0.attn_q.weight").astype(np.float64)     # (out, in)
    # INT8 per-output-channel symmetric weights, INT8 per-tensor activations
    dw = np.max(np.abs(Wf), axis=1) / 127.0
    Wq = np.clip(np.rint(Wf / dw[:, None]), -127, 127).astype(np.int64)
    Xq, dx = G.quant_x_int8(A)
    yf = A @ Wf.T
    dy = np.max(np.abs(yf)) / 127.0
    scale, shift = G.make_requant(dx * dw / dy)
    job = dict(X=Xq, W=Wq.T, scale=scale, shift=shift, offset=np.zeros(Wq.shape[0], np.int64))
    acc, y8 = S.golden(Xq, Wq.T, scale, shift, job["offset"])
    cos = float(np.dot((y8 * dy).ravel(), yf.ravel()) /
                (np.linalg.norm(y8 * dy) * np.linalg.norm(yf)))
    print(f"  real GEMM: {Xq.shape[0]} tokens x {Wq.shape[1]} -> {Wq.shape[0]}, "
          f"INT8 path vs float cosine {cos:.4f}")
    assert cos > 0.99, "INT8 reference path itself is broken"
    return job


def main(argv):
    rng = np.random.default_rng(1)
    which = argv[1] if len(argv) > 1 else "all"
    if which == "vcd":
        d = BLK / "build" / "power"
        job = sparse(rng, rand_job(rng, 16, 256, 64), 0.1)
        return 0 if run_case("vcd", S.Cfg(), [job], vcd_dir=d) else 1
    cases = []
    if which in ("all",):
        c16 = S.Cfg()
        cases += [
            ("rand_m1", c16, [rand_job(rng, 1, 64, 32)]),
            ("rand_m5_pad", c16, [rand_job(rng, 5, 40, 37)]),
            ("rand_m16", c16, [rand_job(rng, 16, 48, 48)]),
            ("rand_m40_chunks", c16, [rand_job(rng, 40, 32, 16)]),
            ("single_ktile", c16, [rand_job(rng, 3, 16, 64)]),
            ("sparse_x", c16, [sparse(rng, rand_job(rng, 16, 64, 32), 0.5)]),
            ("edge_min_saturate", c16, [dict(
                X=np.full((16, 1024), -128), W=np.full((1024, 32), -128),
                scale=np.full(32, 255), shift=np.full(32, 0), offset=np.full(32, 0))]),
            ("edge_mixed_rounding", c16, [dict(
                X=rng.choice([-128, -1, 0, 1, 127], (8, 64)),
                W=rng.choice([-128, -1, 0, 1, 127], (64, 16)),
                scale=np.full(16, 1), shift=rng.integers(0, 25, 16),
                offset=rng.integers(-128, 128, 16))]),
            ("back_to_back_jobs", c16, [rand_job(rng, 1, 96, 32), rand_job(rng, 16, 64, 48),
                                        rand_job(rng, 7, 16, 16), rand_job(rng, 2, 128, 64)]),
            ("cfg8x8_comb", S.Cfg(8, 8, pipe=0, acc_depth=8), [rand_job(rng, 9, 40, 20)]),
            ("cfg4x8_nonsquare", S.Cfg(4, 8, acc_depth=4), [rand_job(rng, 6, 20, 24)]),
            # Cols > Rows makes the bank-reload drain rule the binding constraint; the
            # schedule here is exact (reloading 2 cycles earlier fails this case).
            ("cfg4x16_reload_bound", S.Cfg(4, 16, acc_depth=4), [rand_job(rng, 4, 64, 32)]),
            ("cfg16_int4w", S.Cfg(ww=4), [rand_job(rng, 16, 64, 32, ww=4)]),
            ("cfg32x32_d32", S.Cfg(32, 32, acc_depth=32), [rand_job(rng, 33, 96, 64)]),
        ]
    if which in ("all", "real"):
        job = real_job()
        if job is None:
            print("SKIP real GEMM: scripts/models/smollm2-135m-q8_0.gguf not found")
        else:
            cases.append(("smollm2_blk0_attn_q", S.Cfg(), [job]))
    ok = all([run_case(n, c, j) for n, c, j in cases])
    print("ALL SYSREFERENCE TESTS PASS" if ok else "SYSREFERENCE TESTS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
