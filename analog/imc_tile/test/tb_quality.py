"""V9-style quality check of the operand formats (review finding 10): SmolLM2-135M perplexity in the
model-quality harness (scripts/golden/quality), every linear layer, Hadamard on.

    python3 test/tb_quality.py [tokact] [block8]   # ~25 min; run under the shared lock with a 4 GB cap

Rows: tokact (INT8 per-channel w, per-token x: ARCH as specified) and block8 (INT8 scales per 8-row
block of w and of x: the variant whose per-pass SNR passes), each digital quantization alone and
then with the analog path (tokact only: the harness analog path takes one x scale per token): 8 rows per conversion, 12-b converter at the hard range (one code = 64
MAC), plus Gaussian error per conversion at the class-weighted-equivalent error power tb_accuracy
measured for bit-serial (read from output/accuracy.json; static terms treated as fresh noise, D).
Gate (ARCH V9): analog increment over the same format's digital quantization <= +1.0 % PPL.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts/golden/quality"))
import quality as Q          # noqa: E402

FS = 8 * 127 * 127           # harness adc_fs="max" for INT8 x INT8 over 8 rows


def noise_frac(fmt):
    rows = json.loads((HERE.parent / "output" / "accuracy.json").read_text())
    r = next(r for r in rows if r["fmt"] == fmt and r["mode"] == "bitserial" and r["cfg"] == "default")
    return r["rms_S"] * 10 ** (-r["total_db"] / 20) / FS


def main():
    fmts = {"tokact": dict(w_fmt="int8", a_fmt="int8"),
            "block8": dict(w_fmt="int8", w_gran="group", w_group=8, a_fmt="int8", a_gran="group", a_group=8)}
    res, ok = {}, True
    only = sys.argv[1:] or list(fmts)
    for name, f in fmts.items():
        if name not in only:
            continue
        dq = Q.evaluate(Q.Err(hadamard=True, **f))
        if name == "block8":
            # the harness's analog path takes one x scale per token (its assert); a per-8-row x scale
            # per conversion is not supported there, so block8 gets the digital-quantization row only
            res[name] = dict(digital=dq)
            print(f"INFO V9 {name}: digital quant dPPL {dq['delta_pct']:+.2f} +- {dq['delta_pct_se']:.2f} %, "
                  f"top-1 {100 * dq['top1_agree']:.1f} %; analog path NOT RUN (harness: per-token x scale only)", flush=True)
            continue
        nz = noise_frac(name)
        an = Q.evaluate(Q.Err(hadamard=True, rows=8, adc_bits=12, adc_fs="max", noise=nz, **f))
        inc = an["delta_pct"] - dq["delta_pct"]
        res[name] = dict(digital=dq, analog=an, noise=nz, increment=inc)
        good = inc <= 1.0
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} V9 {name}: digital quant dPPL {dq['delta_pct']:+.2f} +- {dq['delta_pct_se']:.2f} %, "
              f"analog path (8 rows, 12 b, noise {nz:.2e} FS) {an['delta_pct']:+.2f} +- {an['delta_pct_se']:.2f} %, "
              f"increment {inc:+.2f} % vs <= +1.0 %; top-1 {100 * an['top1_agree']:.1f} %", flush=True)
    out = HERE.parent / "output" / "quality.json"
    old = json.loads(out.read_text()) if out.exists() else {}
    old.update(res)
    out.write_text(json.dumps(old, indent=1, default=float))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
