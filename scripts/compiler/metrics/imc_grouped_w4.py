"""Bounded group-128 W4--W7 study: RTN vs second-order error compensation.

GPTQ Algorithm 1 (https://arxiv.org/abs/2210.17323), transposed for x @ W.
Static symmetric grids, natural input order, 1% Hessian damping; no grid search.
Seven projections in all layers; original Q8_0 reference. No energy claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from compiler.metrics.depth_budget import Net, Eval, TENSORS, tokenize_greedy
from compiler.metrics.imc_precision_experiment import NOTES
from compiler.metrics.imc_radix_full_model import radix_mvm
from compiler.metrics.imc_smooth_radix import quantize_input

ROWS = 128


def group_steps(w, rows=ROWS, maximum=7):
    return np.array([np.maximum(np.max(abs(w[i:i+rows]), axis=0)/maximum, 1e-30)
                     for i in range(0, len(w), rows)], dtype=np.float64)


def quantize(w, steps, hessian=None, rows=ROWS, maximum=7):
    """Natural-order blocked GPTQ with static scales; None is matched RTN."""
    working = w.astype(np.float64).copy()
    code = np.zeros(w.shape, dtype=np.int8)
    if hessian is not None:
        # U.T @ U = inverse Hessian; the upper-triangular orientation matters.
        inv = np.linalg.inv(hessian)
        upper = np.linalg.cholesky((inv+inv.T)/2).T
    for start in range(0, len(w), rows):
        end = min(start+rows, len(w))
        step = steps[start//rows]
        if hessian is None:
            code[start:end] = np.clip(np.rint(working[start:end]/step), -maximum, maximum)
            continue
        block = working[start:end].copy()
        errors = np.zeros_like(block)
        for j in range(end-start):
            i = start+j
            q = np.clip(np.rint(block[j]/step), -maximum, maximum)
            code[i] = q
            errors[j] = (block[j]-q*step)/upper[i, i]
            block[j:] -= upper[i, i:end, None]*errors[j]
        working[end:] -= upper[start:end, end:].T @ errors
    reconstructed = code*np.repeat(steps, rows, axis=0)[:len(w)]
    return code, np.ascontiguousarray(reconstructed, dtype=np.float32)


def hessian(a):
    a = a.astype(np.float64)
    h = a.T @ a/len(a)
    # Damping retains finite curvature even for unobserved input channels.
    h.flat[::len(h)+1] += max(.01*float(np.mean(np.diag(h))), 1e-12)
    return h


def selfcheck():
    rng = np.random.default_rng(942)
    x = rng.normal(size=(40, 17))
    w = rng.normal(size=(17, 4))
    w[:, 0] = 0
    steps = group_steps(w, 6)
    h = hessian(x)
    code, reconstructed = quantize(w, steps, h, 6)
    # Independent, expensive inverse-elimination reference from equation (2).
    work, expected = w.copy(), np.zeros_like(code)
    for i in range(len(w)):
        inv = np.linalg.inv(h[i:, i:])
        q = np.clip(np.rint(work[i]/steps[i//6]), -7, 7)
        expected[i] = q
        work[i:] -= (inv[:, 0]/inv[0, 0])[:, None]*(work[i]-q*steps[i//6])
    assert np.array_equal(code, expected), "Blocked compensation differs from inverse elimination"
    rtn, _ = quantize(w, steps, None, 6)
    diagonal, _ = quantize(w, steps, np.eye(len(w)), 6)
    assert np.array_equal(rtn, diagonal) and not np.any(code[:, 0])
    assert np.array_equal(reconstructed, (code*np.repeat(steps, 6, axis=0)[:len(w)]).astype(np.float32))
    # One W4 slice including -8, signed A8, zero and unequal group scales.
    xq = rng.integers(-128, 128, (5, 17), dtype=np.int16)
    xq[0] = 0
    wq = rng.integers(-8, 8, (17, 4), dtype=np.int16)
    got, count = radix_mvm(xq, wq, 6, 4, 0, .5, 0, False, rng, weight_bits=4)
    assert np.allclose(got, xq @ wq, rtol=0, atol=1e-10)
    assert count["final_conversions"] == 4*4*3
    double, counts = radix_mvm(xq, wq, 6, 4, 0, .5, 0, False, rng)
    assert np.array_equal(got, double) and counts["final_conversions"] == 2*count["final_conversions"]
    for bits in (5, 6, 7):
        maximum = 2**(bits-1)-1
        single = rng.integers(-maximum, maximum+1, (17, 4), dtype=np.int16)
        single[0, :2] = [-maximum, maximum]
        got, counts = radix_mvm(xq, single, 6, 4, 0, .5, 0, False, rng, weight_bits=bits)
        assert np.allclose(got, xq @ single, rtol=0, atol=1e-10) and counts == count
        try:
            radix_mvm(np.array([[1]]), np.array([[-maximum-1]]), 6, 4, 0, .5, 0, False, rng, weight_bits=bits)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"Single-bank symmetric W{bits} accepted an extra magnitude bit")
    print("PASS: GPTQ inverse-elimination oracle, diagonal RTN, zero, partial blocks, one-slice arithmetic/counts", flush=True)


def main(quick=False, weight_bits=4, screen_only=False):
    selfcheck()
    started = time.perf_counter()
    maximum = 2**(weight_bits-1)-1
    net = Net()
    # These two notes were not used by the preceding smoothing evaluation.
    paths = [next(NOTES.glob(p+" *.md")) for p in ("27a3", "27d6")]
    cal = next(NOTES.glob("27h3 *.md"))
    assert cal not in paths
    nt = 64 if quick else 256
    refs = [(p, tokenize_greedy(p.read_text(), net.vocab)[:nt]) for p in paths]
    refs = [(p, ids, Eval(net, ids)) for p, ids in refs]
    weights, records = {}, []
    # The one calibration forward propagates quantized upstream projections.
    # Q/K/V share one input; reuse its Hessian. Gate/up likewise share theirs.
    last_key, last_h = None, None
    def calibrate(li, name, a, w, y):
        nonlocal last_key, last_h
        family = "qkv" if name in ("attn_q", "attn_k", "attn_v") else "gateup" if name in ("ffn_gate", "ffn_up") else name
        if last_key != (li, family):
            last_key, last_h = (li, family), hessian(a)
        steps = group_steps(w, maximum=maximum)
        code, restored = quantize(w, steps, last_h, maximum=maximum)
        rtn, rtn_w = quantize(w, steps, maximum=maximum)
        weights[li, name] = {"gptq": (code, restored), "rtn": (rtn, rtn_w), "steps": steps}
        signal = max(float(np.mean(y.astype(float)**2)), 1e-30)
        records.append(dict(layer=li, tensor=name,
            gptq_calibration_nmse=float(np.mean(((a@restored).astype(float)-y)**2))/signal,
            rtn_calibration_nmse=float(np.mean(((a@rtn_w).astype(float)-y)**2))/signal))
        if name == "ffn_down":
            print(f"Calibrated layer {li+1}/{net.NL}: {time.perf_counter()-started:.1f}s", flush=True)
        return a @ restored
    net.mvm = calibrate
    cal_ids = tokenize_greedy(cal.read_text(), net.vocab)[:512]
    net(cal_ids)
    assert len(weights) == net.NL*len(TENSORS)
    net.mvm = None
    assert np.array_equal(net(refs[0][1]), refs[0][2].ref)
    outdir = ROOT/"build/research"
    outdir.mkdir(parents=True, exist_ok=True)
    frozen = outdir/f"imc_grouped_w{weight_bits}_frozen.npz"
    np.savez(frozen, **{f"{li}_{name}_{kind}": value for (li, name), entry in weights.items()
              for kind, value in (("codes", entry["gptq"][0]), ("steps", entry["steps"]))})
    results = []
    for method in ("rtn", "gptq"):
        # Physical noise is evaluated only after preserving the weight-only
        # and ideal-A8 controls; failing controls stay in the record.
        for mode, bits, read, thermal in (("weight_only",0,0,False), ("ideal_a8",0,0,False),
                                         ("adc_only",10,0,False), ("physical",10,100,True)):
            if screen_only and mode not in ("weight_only", "ideal_a8"):
                continue
            for seed in ((21,22) if mode == "physical" and not quick else (21,)):
                for path, ids, ev in refs:
                    rng = np.random.default_rng(seed)
                    stats = dict(clipped_conversions=0, final_conversions=0, separate_bit_conversions=0)
                    def compute(li, name, a, w, y):
                        entry = weights[li, name]
                        code, reconstructed = entry[method]
                        if mode == "weight_only":
                            return a @ reconstructed
                        xq, scales, expanded = quantize_input(a)
                        if mode == "ideal_a8":
                            return (xq*expanded).astype(np.float32) @ reconstructed
                        out = np.zeros((len(a), w.shape[1]), dtype=np.float64)
                        for b, start in enumerate(range(0, len(w), ROWS)):
                            val, counts = radix_mvm(xq[:,start:start+ROWS], code[start:start+ROWS],
                                ROWS, 4, bits, .5, read, thermal, rng, scales[:,b:b+1], weight_bits=weight_bits)
                            out += val*entry["steps"][b]
                            for key, value in counts.items():
                                stats[key] += value
                        return out.astype(np.float32)
                    net.mvm = compute
                    measured = ev.score(net(ids))
                    result = dict(method=method, mode=mode, seed=seed, source=path.name,
                                  **measured, **stats, joint_pass=measured["kl"]<=.01 and measured["ppl_ratio"]<=1.01)
                    results.append(result)
                    print(f"{method}/{mode} {path.name[:4]} seed{seed}: KL={measured['kl']:.6f} "
                          f"PPLratio={measured['ppl_ratio']:.6f} pass={result['joint_pass']}", flush=True)
    net.mvm = None
    assert np.array_equal(net(refs[0][1]), refs[0][2].ref)
    summaries = []
    for method in ("rtn", "gptq"):
        caps, digit_sum, values, groups = [], 0, 0, 0
        for entry in weights.values():
            code = entry[method][0]
            digit_sum += int(np.abs(code.astype(np.int16)).sum())
            values += code.size
            groups += entry["steps"].size
            caps.extend(120+4*np.sum(abs(code[i:i+ROWS].astype(np.int16)), axis=0)
                        for i in range(0,len(code),ROWS))
        summaries.append(dict(method=method, mean_absolute_digit=digit_sum/values,
            column_capacitance_fF_percentiles=np.percentile(np.concatenate(caps),[5,50,95,100]).tolist(),
            coefficient_count=values, scale_count=groups, coefficient_bits=weight_bits*values,
            conditional_fp16_scale_bits=16*groups, scale_precision="float64 modeled, FP16 storage not validated"))
    suffix = ("_quick" if quick else "")+("_screen" if screen_only else "")
    target = outdir/f"imc_grouped_w{weight_bits}{suffix}.json"
    target.write_text(json.dumps(dict(results=results, calibration_records=records, summaries=summaries,
        logical_weight_bits=weight_bits, symmetric_weight_range=[-maximum, maximum], screen_only=screen_only,
        calibration=dict(source=cal.name, sha256=hashlib.sha256(cal.read_bytes()).hexdigest(), tokens=len(cal_ids),
                         method="sequential quantized upstream; natural order; static symmetric group128; 1% mean diagonal damping"),
        references=[dict(source=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), tokens=len(ids), ppl=ev.ppl) for p,ids,ev in refs],
        frozen_sha256=hashlib.sha256(frozen.read_bytes()).hexdigest(), runtime_s=time.perf_counter()-started,
        boundary="Q8_0 original reference, seven projections x30 layers; ideal float scales/attention/KV/norm/head; no PPA",
        physical_model=f"one sign-plus-magnitude W{weight_bits} bank, dynamic block A8, Cu4fF, 120fF load, 10bit ADC/0.5V span, read100uV plus independent sharing hypothesis",
        omissions="fixed mismatch, comparator physical errors, reset/reference correlation, scale quantization/processing cost, SRAM, wiring, clocks, actual ADC",
        protocol="Fixed calibration recipe; reused development passages screen weight formats; no scale/damping retuning to evaluation outputs; RTN uses same static grids; greedy tokenizer/technical notes, not standard benchmark"
        ), indent=2)+"\n")
    print(f"PASS: experiment execution; quality gates recorded independently; {target}; {time.perf_counter()-started:.1f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--weight-bits", type=int, choices=(4, 5, 6, 7), default=4)
    parser.add_argument("--screen-only", action="store_true")
    args = parser.parse_args()
    selfcheck() if args.selfcheck else main(args.quick, args.weight_bits, args.screen_only)
