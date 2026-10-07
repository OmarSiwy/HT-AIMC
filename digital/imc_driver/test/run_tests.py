"""imc_driver regression: the systolic reference's jobs -> imc_driver RTL + ideal tiles in iverilog.

    python3 test/run_tests.py            # all cases (needs iverilog + numpy)
    python3 test/run_tests.py quick      # random jobs only, no SmolLM2

Each case checks (1) every output row's 24-b chain sum and INT8 requant are bit-exact against the
bit-true golden (scripts/golden/imc_tile.py, ideal analog), inside the tb; (2) zero stall ticks when
the HBM model keeps up (one row word per tick), and stalls > 0 with exactly the expected weights
when it does not; (3) reports the error of the analog path's ideal quantization against the
systolic array's exact INT8 result (sysreference golden), which is a property of the format, not a
defect: one code = 64 MAC units.
"""
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BLK = HERE.parent
ROOT = BLK.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "analog/imc_tile/test"))
import gen  # noqa: E402
import jobs as J  # noqa: E402


NCASES = [0]


def run(name, cfg, job, cal=None, replay=None, trace=False):
    NCASES[0] += 0 if replay else 1
    out = BLK / "build" / "test" / name
    out.mkdir(parents=True, exist_ok=True)
    L = gen.layout(cfg, job)
    tb = out / "tb.v"
    tb.write_text(gen.tb_verilog(cfg, L, out / "out.txt", cal, replay=replay,
                                 trace_txt=(out / "pins.txt") if trace else None))
    vvp = out / "tb.vvp"
    subprocess.run(["iverilog", "-g2005", "-o", str(vvp), str(tb), str(HERE / "imc_tile_beh.v"),
                    str(HERE / "imc_tile_replay.v"), *gen.SRC], check=True)
    log = subprocess.run(["vvp", "-n", str(vvp)], capture_output=True, text=True).stdout
    ok = "PASS" in log and "FAIL" not in log
    outs, samp = gen.parse_trace(out / "out.txt", cfg)
    stats = dict(l.split("=") for l in log.split() if "=" in l)
    # systolic exact result (INT32) and its requant, vs the IMC path
    X, W = np.asarray(job["X"]), np.asarray(job["W"])
    Nout = W.shape[1]
    acc_imc = np.zeros((X.shape[0], L["Np"]), np.int64)
    y_imc = np.zeros_like(acc_imc)
    for m, nb, a, y in outs:
        acc_imc[m, nb * cfg.cols:(nb + 1) * cfg.cols] = a
        y_imc[m, nb * cfg.cols:(nb + 1) * cfg.cols] = y
    exact = X @ W
    e = acc_imc[:, :Nout] * 64 - exact
    y_sys = J.SS.golden(X, W, job["scale"], job["shift"], job["offset"])[1]
    dy = y_imc[:, :Nout] - y_sys
    dt = np.diff(samp)
    tp = float(np.median(dt)) * 2 * gen.HALF_PS / 1000 if len(dt) else float("nan")
    tag = "REPLAY" if replay else ("PASS" if ok else "FAIL")       # a replay is judged by its caller
    print(f"{tag} {name}: {cfg.mode} R{cfg.rows}xC{cfg.cols}x{cfg.ntiles} tiles "
          f"M{X.shape[0]} K{X.shape[1]} N{Nout} passes={stats.get('passes')} stall_ticks={stats.get('stall_ticks')} (after fill {stats.get('stall_after_fill')}) "
          f"t_pass(median)={tp:.3f} ns | vs systolic INT32: rms err {np.sqrt(np.mean(e**2)):.1f} MAC "
          f"(max {np.max(np.abs(e))}), rms(exact) {np.sqrt(np.mean(exact.astype(float)**2)):.0f}; "
          f"INT8 out: {100*np.mean(dy == 0):.1f} % equal, max |dy| {np.max(np.abs(dy))}")
    if not ok and not replay:
        print(log[-1500:])
    return ok, dict(stall=int(stats.get("stall_after_fill", -1)), t_pass=tp, e=e, dy=dy, passes=stats.get("passes"),
                    outs=outs, samp=samp, dir=out, L=L, log=log)


def main(argv):
    rng = np.random.default_rng(1)
    which = argv[1] if len(argv) > 1 else "all"
    ok = True
    base = gen.Cfg()
    for mode in ("ml2", "bitserial"):
        cfg = replace(base, mode=mode)
        for name, job in J.systolic_jobs(rng):
            r, _ = run(f"{mode}_{name}", cfg, job)
            ok &= r
    # a 4-tile chain and an 8x16 tile
    r, _ = run("ml2_4tiles", replace(base, ntiles=4), J.SR.rand_job(rng, 6, 96, 16)); ok &= r
    r, _ = run("ml2_c16", replace(base, cols=16), J.SR.rand_job(rng, 5, 48, 40)); ok &= r
    # starved HBM: a row word every 12 ticks -> the driver must stall, still bit-exact
    r, res = run("ml2_slow_hbm", replace(base, hbm_gap=12), J.SR.rand_job(rng, 3, 64, 16)); ok &= r
    if res["stall"] <= 0:
        print("FAIL ml2_slow_hbm: expected stall ticks with a starved HBM"); ok = False
    # weights in place before activations: no stall after the initial fill at one row per tick
    for mode in ("ml2", "bitserial"):
        r, res = run(f"{mode}_stream_m16", replace(base, mode=mode), J.SR.rand_job(rng, 16, 64, 16)); ok &= r
        if res["stall"] != 0:
            print(f"FAIL {mode}_stream_m16: {res['stall']} stall ticks after the initial fill"); ok = False
    # gain-cell refresh: a group held for 16 tokens is rewritten every 4 passes from its stage bank
    for mode in ("ml2", "bitserial"):
        r, res = run(f"{mode}_refresh4", replace(base, mode=mode, refresh=4), J.SR.rand_job(rng, 16, 16, 8)); ok &= r
        nref = int(dict(l.split("=") for l in res["log"].split() if "=" in l).get("refreshes", 0))
        if nref <= 0:
            print(f"FAIL {mode}_refresh4: no refresh rewrites"); ok = False
        else:
            print(f"PASS {mode}_refresh4: {nref} refresh rewrites (tile-groups), outputs bit-exact")
    if which == "all":
        job = J.real_rot_job(n_out=32)
        for mode in ("ml2", "bitserial"):
            r, _ = run(f"{mode}_smollm2_attn_q", replace(base, mode=mode), job); ok &= r
    print(f"{NCASES[0]} cases: " + ("ALL IMC_DRIVER TESTS PASS" if ok else "IMC_DRIVER TESTS FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
