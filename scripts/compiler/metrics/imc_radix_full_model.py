"""Full-depth W8A8 radix/readout experiment; conditional behavioral circuit.

Two signed W4 magnitude slices, exact partial dot products, physical voltage
normalization, dynamic activation planes, quantization/clipping and independent
read noise. Thermal sharing is the explicit kT/(2C) per-stage hypothesis from
imc_radix_budget, not transistor transient-noise characterization. No chip PPA.
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

KT = 1.380649e-23 * 300.15


def radix_mvm(xq, wq, rows, cu_ff, bits, span, read_uV, thermal, rng, scales=None, weight_bits=8):
    """Integer output; default W8 uses two four-magnitude-bit banks.

    Optional symmetric W6/W7 proposals use one five/six-magnitude-bit bank.
    Its larger digit capacitance is charged explicitly; it is not a W4 macro.
    """
    assert xq.shape[1] == wq.shape[0]
    assert weight_bits in (4, 5, 6, 7, 8)
    # W5/W6/W7 use symmetric sign-plus-magnitude formats; their extra negative
    # two's-complement endpoint would need another physical magnitude bit.
    minimum = -(2**(weight_bits-1)-1) if weight_bits in (5, 6, 7) else -2**(weight_bits-1)
    assert np.all((wq >= minimum) & (wq < 2**(weight_bits-1)))
    out = np.zeros((len(xq), wq.shape[1]), dtype=np.float64)
    clips = events = planes = 0
    for start in range(0, xq.shape[1], rows):
        xb, wb = xq[:, start:start+rows], wq[start:start+rows]
        maximum = np.max(np.abs(xb.astype(np.int16)), axis=1)
        count = np.ceil(np.log2(maximum.astype(float)+1)).astype(int)
        scale = (2.0 ** count)[:, None]
        active = count > 0
        for shift in ((0,) if weight_bits < 8 else (0, 4)):
            mask = 2**(weight_bits-1)-1 if weight_bits in (6, 7) else 15
            digits = (np.sign(wb) * ((np.abs(wb.astype(np.int16)) >> shift) & mask)).astype(np.float32)
            carr = (120 + cu_ff*np.sum(np.abs(digits), axis=0, dtype=np.float64))*1e-15
            gain = cu_ff*1e-15*.45/carr
            partial = xb.astype(np.float32) @ digits
            held = partial*gain[None, :]/scale
            variance = np.full_like(held, (read_uV*1e-6)**2)
            if thermal:
                # Independent stage error, propagated through h'=(h+p)/2.
                # Initial/reset, correlated reference and comparator kickback
                # errors are omitted; a physical macro may have more noise.
                variance += (KT/(2*carr))[None, :]*(1-4.0**(-count[:, None]))/(1-.25)
            if read_uV or thermal:
                held += rng.standard_normal(held.shape)*np.sqrt(variance)
            if bits:
                code = np.floor(held/(span/2**bits)+.5)
                clips += int(np.count_nonzero(((code < -2**(bits-1)) | (code > 2**(bits-1)-1)) & active[:, None]))
                held = np.clip(code, -2**(bits-1), 2**(bits-1)-1)*(span/2**bits)
            recovered = held*scale/gain[None, :]
            recovered[~active] = 0
            factor = 1 if scales is None else scales[:, start//rows, None]
            out += recovered*(2**shift)*factor
            events += int(np.count_nonzero(active))*wq.shape[1]
            planes += int(count.sum())*wq.shape[1]
    return out, dict(clipped_conversions=clips, final_conversions=events,
                     separate_bit_conversions=planes)


def selfcheck():
    rng = np.random.default_rng(981)
    x = rng.integers(-128, 128, (31, 257), dtype=np.int16)
    w = rng.integers(-127, 128, (257, 9), dtype=np.int16)
    x[0] = 0
    for rows in (16, 64, 128):
        y, _ = radix_mvm(x, w, rows, 4, 0, .25, 0, False, rng)
        assert np.allclose(y, x.astype(np.int64) @ w.astype(np.int64), rtol=0, atol=1e-8)
    codes = np.arange(-128, 128, dtype=np.int16)[:, None]
    y, _ = radix_mvm(codes, np.array([[-127, 0, 127]]), 128, 4, 0, .25, 0, False, rng)
    assert np.allclose(y, codes @ np.array([[-127, 0, 127]]), rtol=0, atol=1e-8)
    # A deliberately tiny ADC range must produce saturation and output error.
    y, stats = radix_mvm(x, w, 128, 4, 8, .0001, 0, False, rng)
    assert stats["clipped_conversions"] > 0 and not np.array_equal(y, x @ w)
    y, stats = radix_mvm(np.zeros((2, 257), dtype=int), w, 128, 4, 9, .25, 200, True, rng)
    assert not np.any(y) and not stats["final_conversions"]


def main(quick=False, activation_mode="calibrated_tensor", adc_span=.25, adc_bits=10):
    selfcheck()
    start = time.perf_counter()
    net = Net()
    weights = {}
    for li, layer in enumerate(net.L):
        for name in TENSORS:
            w = layer[name]
            step = np.maximum(np.max(abs(w), axis=0)/127, 1e-30)
            code = np.clip(np.rint(w/step), -127, 127).astype(np.int8)
            layer[name] = np.ascontiguousarray(code*step)
            weights[li, name] = code, step
    nt = 64 if quick else 256
    sources = [next(NOTES.glob(p+" *.md")) for p in ("27l1", "27h1")]
    refs = [(p, tokenize_greedy(p.read_text(), net.vocab)[:nt]) for p in sources]
    refs = [(p, ids, Eval(net, ids)) for p, ids in refs]
    # Identity hook must preserve every logit, not just a summary metric.
    net.mvm = lambda li, name, a, w, y: y
    assert np.array_equal(net(refs[0][1]), refs[0][2].ref)
    # Independent text calibration; no held-out output ranges are fitted.
    cal_path = next(NOTES.glob("27h3 *.md"))
    assert cal_path not in sources
    xsteps = {}
    def calibrate(li, name, a, w, y):
        xsteps[li, name] = max(float(np.max(np.abs(a)))/127, 1e-30)
        return y
    net.mvm = calibrate
    net(tokenize_greedy(cal_path.read_text(), net.vocab)[:128])
    results = []
    configurations = [
        ("ideal_a8", 128, 4, 0, 0, False),
        ("ideal_a8_r64", 64, 4, 0, 0, False),
        ("quantization_only", 128, 4, adc_bits, 0, False),
        ("read50", 128, 4, adc_bits, 50, True),
        ("read100", 128, 4, adc_bits, 100, True),
        ("read200", 128, 4, adc_bits, 200, True),
        ("read100_c16", 128, 16, adc_bits, 100, True),
        ("read100_r64", 64, 4, adc_bits, 100, True),
    ]
    for label, rows, cu, bits, read, thermal in configurations:
        for seed in ((21,) if quick or not (read or thermal) else (21, 22)):
            for path, ids, ev in refs:
                rng = np.random.default_rng(seed)
                stats = dict(clipped_conversions=0, final_conversions=0, separate_bit_conversions=0,
                             clipped_activations=0, activation_values=0)
                def compute(li, name, a, w, y):
                    if activation_mode == "calibrated_tensor":
                        scales = np.full((len(a), (a.shape[1]+rows-1)//rows), xsteps[li, name])
                    elif activation_mode == "dynamic_tensor":
                        scales = np.broadcast_to(np.maximum(np.max(abs(a), axis=1, keepdims=True)/127, 1e-30),
                                                 (len(a), (a.shape[1]+rows-1)//rows))
                    else:
                        scales = np.stack([np.maximum(np.max(abs(a[:, i:i+rows]), axis=1)/127, 1e-30)
                                           for i in range(0, a.shape[1], rows)], axis=1)
                    expanded = np.repeat(scales, rows, axis=1)[:, :a.shape[1]]
                    raw = np.rint(a/expanded)
                    stats["clipped_activations"] += int(np.count_nonzero(abs(raw)>127))
                    stats["activation_values"] += a.size
                    xq = np.clip(raw, -127, 127).astype(np.int8)
                    wq, dw = weights[li, name]
                    if label.startswith("ideal_a8"):
                        return (xq.astype(np.float32)*expanded).astype(np.float32) @ w
                    got, counts = radix_mvm(xq, wq, rows, cu, bits, adc_span, read, thermal, rng, scales)
                    for k, value in counts.items():
                        stats[k] += value
                    return (got*dw).astype(np.float32)
                net.mvm = compute
                measured = ev.score(net(ids))
                result = dict(configuration=label, rows=rows, cu_ff=cu, ADC_bits=bits,
                              ADC_span_V=adc_span, read_noise_uV=read, sharing_thermal=thermal,
                              seed=seed, source=path.name, **measured, **stats)
                results.append(result)
                print(f"{label} seed={seed} {path.name[:4]} KL={measured['kl']:.5g} "
                      f"PPLratio={measured['ppl_ratio']:.5f} ADCclips={stats['clipped_conversions']}", flush=True)
    net.mvm = None
    assert np.array_equal(net(refs[0][1]), refs[0][2].ref)
    suffix = "_quick" if quick else ""
    out = ROOT/f"build/research/imc_radix_full_model_{activation_mode}_b{adc_bits}_s{adc_span}{suffix}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(results=results, runtime_s=time.perf_counter()-start, activation_mode=activation_mode,
        weight_mode="per-output RTN INT8, two signed W4 magnitude slices; reference is this W8 model with float activations",
        calibration=dict(source=cal_path.name, sha256=hashlib.sha256(cal_path.read_bytes()).hexdigest(), tokens=128,
                         method="fixed per-tensor max activation/127 from separate W8/float-input forward"),
        references=[dict(source=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), tokens=len(ids), ppl=ev.ppl) for p, ids, ev in refs],
        boundary="Conditional behavior of all seven MVMs in all30 layers; no physical ADC/energy/latency/yield",
        omissions="Weight mismatch, reset/reference correlations, ratio/gain calibration error, kickback, input conversion costs, SRAM/routing, KV/attention hardware",
        checks="Exact two-slice integer identity including -128/zero/partial blocks; clipping negative control; hook identity and restoration PASS"
        ), indent=2)+"\n")
    print(f"PASS: {len(results)} cases, {out.relative_to(ROOT)}, {time.perf_counter()-start:.2f}s", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quick", action="store_true")
    p.add_argument("--selfcheck", action="store_true")
    p.add_argument("--activation-mode", choices=("calibrated_tensor", "dynamic_tensor", "dynamic_block"), default="calibrated_tensor")
    p.add_argument("--adc-span", type=float, default=.25)
    p.add_argument("--adc-bits", type=int, choices=(8, 9, 10, 11, 12), default=10)
    args = p.parse_args()
    if args.selfcheck:
        selfcheck()
        print("PASS: signed radix arithmetic, zero gating, partial blocks, saturation")
    else:
        assert args.adc_span > 0
        main(args.quick, args.activation_mode, args.adc_span, args.adc_bits)
