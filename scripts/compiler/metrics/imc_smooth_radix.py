"""Frozen SmoothQuant scales with dynamic block A8 and conditional W8 readout.

This bounded experiment reuses the full-depth model and physical radix model.
It does not reproduce a paper's benchmark or price runtime scaling hardware.
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
from compiler.metrics.imc_radix_full_model import radix_mvm, selfcheck as radix_selfcheck

ROWS = 128


def smoothing_scale(xmax, w, alpha):
    # Alpha zero names the unsmoothed control, not equation (4) at alpha=0.
    if alpha == 0:
        return np.ones(w.shape[0], dtype=np.float32)
    return (np.maximum(xmax, 1e-8)**alpha /
            np.maximum(np.max(abs(w), axis=1), 1e-8)**(1-alpha)).astype(np.float32)


def quantize_input(a, rows=ROWS, bits=8):
    assert bits in (8, 9)
    maximum = 2**(bits-1)-1
    scales = np.stack([np.maximum(np.max(abs(a[:, i:i+rows]), axis=1)/maximum, 1e-30)
                       for i in range(0, a.shape[1], rows)], axis=1)
    expanded = np.repeat(scales, rows, axis=1)[:, :a.shape[1]]
    raw = np.rint(a/expanded)
    assert not np.any(abs(raw) > maximum)
    return raw.astype(np.int8 if bits == 8 else np.int16), scales, expanded


def quantize_weight(w, s):
    ws = w*s[:, None]
    dw = np.maximum(np.max(abs(ws), axis=0)/127, 1e-30)
    return np.clip(np.rint(ws/dw), -127, 127).astype(np.int8), dw


def select_alpha(a, w, layer, tensor_index):
    """Select from the fixed grid using only this original calibration MVM.

    Two common random draws per candidate include ADC threshold crossings.
    Streams are keyed by MVM, independent of held-out seeds or outputs.
    """
    xmax = np.max(abs(a), axis=0)
    target = a @ w
    signal_ms = max(float(np.mean(target.astype(float)**2)), 1e-30)
    scores = []
    for alpha in (.25, .5, .75):
        s = smoothing_scale(xmax, w, alpha)
        wq, dw = quantize_weight(w, s)
        xq, scales, _ = quantize_input(a/s)
        draw_mse, clips = [], []
        for seed in (1001, 1002):
            rng = np.random.default_rng([seed, layer, tensor_index])
            got, stats = radix_mvm(xq, wq, ROWS, 4, 10, .5, 100, True, rng, scales)
            error = (got*dw).astype(np.float32).astype(float)-target
            draw_mse.append(float(np.mean(error**2)))
            clips.append(stats["clipped_conversions"])
        scores.append(dict(alpha=alpha, mse=float(np.mean(draw_mse)),
                           normalized_mse=float(np.mean(draw_mse))/signal_ms,
                           draw_mse=draw_mse, clipped_conversions=clips))
    # Fixed ascending grid supplies deterministic tie breaking.
    best = min(scores, key=lambda r: r["mse"])
    return best["alpha"], dict(layer=layer, tensor=TENSORS[tensor_index],
                               selected_alpha=best["alpha"], signal_mean_square=signal_ms,
                               candidates=scores)


def selfcheck():
    radix_selfcheck()
    rng = np.random.default_rng(631)
    x = rng.normal(size=(8, 257))
    w = rng.normal(size=(257, 9))
    x[:, 0] = 0
    w[1] = 0
    for alpha in (0, .25, .5, .75):
        s = smoothing_scale(np.max(abs(x), axis=0), w, alpha).astype(float)
        assert np.all(np.isfinite(s)) and np.all(s > 0)
        assert np.allclose((x/s) @ (w*s[:, None]), x@w, rtol=1e-12, atol=1e-12)
    # Unequal block scales must be applied before partial sums are combined.
    x[0] = 0
    x[:, :128] *= 100
    wq = rng.integers(-127, 128, w.shape, dtype=np.int16)
    for rows in (128, 256):
        for bits in (8, 9):
            xq, scales, expanded = quantize_input(x, rows=rows, bits=bits)
            got, counts = radix_mvm(xq, wq, rows, 4, 0, .5, 0, False, rng, scales)
            assert np.allclose(got, (xq*expanded) @ wq, rtol=1e-12, atol=1e-8)
            assert not np.any(got[0])
            assert counts["final_conversions"] == 2*7*((257+rows-1)//rows)*9
            assert counts["separate_bit_conversions"] == (bits-1)*counts["final_conversions"]
            endpoints, _, _ = quantize_input(np.array([[-1., 1., 0.]]), bits=bits)
            assert endpoints.tolist() == [[-(2**(bits-1)-1), 2**(bits-1)-1, 0]]
    # Frozen calibration, rather than an evaluation input, sets this scale.
    frozen = smoothing_scale(np.max(abs(x), axis=0), w, .5)
    x_eval = x*1e4
    assert not np.array_equal(frozen, smoothing_scale(np.max(abs(x_eval), axis=0), w, .5))
    selected, record = select_alpha(x, w, 0, 0)
    repeated, again = select_alpha(x, w, 0, 0)
    assert selected == repeated and record == again
    assert selected == min(record["candidates"], key=lambda r: r["mse"])["alpha"]
    assert np.all(np.isfinite([r["mse"] for r in record["candidates"]]))


def main(validate=False, read_noise=100, optimize=False, fresh=False, activation_bits=8,
         architecture=False):
    if architecture:
        assert fresh and not optimize and activation_bits == 9 and read_noise == 50
    rows, adc_bits = (256, 11) if architecture else (ROWS, 10)
    assert activation_bits == 8 or (activation_bits == 9 and fresh and not optimize)
    selfcheck()
    started = time.perf_counter()
    net = Net()
    optimized_path = ROOT/"build/research/imc_smooth_radix_optimized.json"
    frozen_path = ROOT/"build/research/imc_smooth_radix_frozen.npz"
    if activation_bits != 8:
        assert frozen_path.is_file(), "A9 replay requires existing frozen A8-selected scales"
        anchor = json.loads((ROOT/'build/research/imc_smooth_radix_fresh_holdout.json').read_text())
        assert hashlib.sha256(frozen_path.read_bytes()).hexdigest() == anchor['frozen_state']['scales_sha256'], \
            "Frozen scales differ from the original A8 holdout artifact"
    saved = json.loads(optimized_path.read_text()) if fresh else None
    frozen_scales = {}
    if fresh and frozen_path.exists():
        with np.load(frozen_path) as archive:
            frozen_scales = {k: archive[k] for k in archive.files}
    selected_alphas = {(r["layer"], r["tensor"]): r["selected_alpha"]
                       for r in saved["alpha_selection"]["records"]} if fresh else {}
    if fresh:
        assert set(selected_alphas) == {(li, name) for li in range(net.NL) for name in TENSORS}
    sources = [next(NOTES.glob(p+" *.md")) for p in (("27g3", "27h5") if fresh else ("27l1", "27h1"))]
    ntokens = 512 if fresh else 256 if validate else 128
    refs = [(p, tokenize_greedy(p.read_text(), net.vocab)[:ntokens]) for p in sources]
    refs = [(p, ids, Eval(net, ids)) for p, ids in refs]
    cal_path = next(NOTES.glob("27h3 *.md"))
    assert cal_path not in sources
    if fresh:
        assert hashlib.sha256(cal_path.read_bytes()).hexdigest() == saved["calibration"]["sha256"]
    xmax, probes, calibration_inputs = {}, {}, {}

    def calibrate(li, name, a, w, y):
        xmax[li, name] = np.max(abs(a), axis=0)
        probes[li, name] = a[:2].copy()
        if optimize:
            calibration_inputs[li, name] = a.copy()
        return y

    net.mvm = calibrate
    if not (fresh and frozen_scales):
        net(tokenize_greedy(cal_path.read_text(), net.vocab)[:128])
        assert len(xmax) == net.NL*len(TENSORS)
    results, summaries, weight_code_hashes = [], [], {}
    selections = saved["alpha_selection"]["records"] if fresh else []
    identity_max_relative = saved["identity_max_relative"] if fresh else 0.
    for alpha in (("calibration_selected",) if optimize or fresh else (.5,) if validate else (0, .5, .75)):
        weights, cap_samples, architecture_caps = {}, [[], []], [[], []]
        weight_code_hash = hashlib.sha256()
        digit_sum = [0, 0]
        weight_values = 0
        for li, layer in enumerate(net.L):
            for name in TENSORS:
                w = layer[name]
                selected_alpha = alpha
                if optimize:
                    selected_alpha, selection = select_alpha(calibration_inputs[li, name], w,
                                                              li, TENSORS.index(name))
                    selections.append(selection)
                if fresh:
                    selected_alpha = selected_alphas[li, name]
                scale_key = f"{li}_{name}"
                s = (frozen_scales[scale_key] if fresh and scale_key in frozen_scales else
                     smoothing_scale(xmax[li, name], w, selected_alpha))
                assert s.shape == (w.shape[0],) and np.all(np.isfinite(s)) and np.all(s > 0)
                if optimize or fresh:
                    frozen_scales[scale_key] = s
                # Check the algebra before either quantizer, on actual inputs.
                if (li, name) in probes:
                    a64, w64, s64 = probes[li, name].astype(float), w.astype(float), s.astype(float)
                    exact = a64 @ w64
                    relative = float(np.max(abs((a64/s64) @ (w64*s64[:, None])-exact)) /
                                     max(float(np.max(abs(exact))), 1e-30))
                    assert relative < 1e-12
                    identity_max_relative = max(identity_max_relative, relative)
                wq, dw = quantize_weight(w, s)
                weight_code_hash.update(f'{li}/{name}/{wq.shape}\n'.encode())
                weight_code_hash.update(wq.tobytes())
                weights[li, name] = s, wq, dw
                weight_values += wq.size
                for j, shift in enumerate((0, 4)):
                    digits = (np.abs(wq.astype(np.int16)) >> shift) & 15
                    digit_sum[j] += int(digits.sum())
                    for start in range(0, len(wq), ROWS):
                        cap_samples[j].append(120 + 4*digits[start:start+ROWS].sum(axis=0))
                    if architecture:
                        for start in range(0, len(wq), rows):
                            architecture_caps[j].append(120 + 4*digits[start:start+rows].sum(axis=0))
            if optimize and (li+1) % 5 == 0:
                print(f"Calibration grid: {li+1}/{net.NL} layers frozen", flush=True)
        weight_code_hashes[str(alpha)] = weight_code_hash.hexdigest()
        summaries.append(dict(alpha=alpha, mean_absolute_slice_digits=[v/weight_values for v in digit_sum],
                              slices=[dict(shift=shift, capacitance_fF=dict(
                                  zip(("min", "p50", "p95", "max"),
                                      np.percentile(np.concatenate(caps), (0, 50, 95, 100)).tolist())))
                                      for shift, caps in zip((0, 4), cap_samples)]))
        if fresh:
            assert summaries == saved["weight_summaries_at_4fF"], "Frozen weight-code summary changed"
        architecture_summary = [dict(shift=shift, capacitance_fF=dict(
            zip(("min", "p50", "p95", "max"),
                np.percentile(np.concatenate(caps), (0, 50, 95, 100)).tolist())))
            for shift, caps in zip((0, 4), architecture_caps)] if architecture else None
        if optimize or fresh:
            assert len(frozen_scales) == net.NL*len(TENSORS)
            frozen_path.parent.mkdir(parents=True, exist_ok=True)
            if optimize or not frozen_path.exists():
                np.savez_compressed(frozen_path, **frozen_scales)
        configurations = [("weight_only", 4, None), ("ideal_a8", 4, None)]
        # Fixed before evaluation: alpha .5, no held-out winner selection.
        if alpha == .5:
            configurations += [("radix_quantization_only", 4, None), ("radix_read100", 4, 21)]
        if validate:
            configurations = [("ideal_a8", 4, None), ("radix_quantization_only", 4, None)]
            configurations += [("radix_read100", cu, seed) for cu in (4, 1.2) for seed in (21, 22)]
            if read_noise == 50:
                configurations = [("radix_read50", 4, seed) for seed in (21, 22)]
        if optimize or fresh:
            assert len(selections) == net.NL*len(TENSORS)
            control = "radix_quantization_only" if activation_bits == 9 and read_noise == 50 else f"ideal_a{activation_bits}"
            configurations = [(control, 4, None)] + [(f"radix_read{read_noise}", 4, seed) for seed in (21, 22)]
        if architecture:
            configurations = [("ideal_a9", 4, None), ("radix_quantization_only", 4, None),
                              ("radix_read50", 4, 21), ("radix_read50", 4, 22)]
        for configuration, cu, seed in configurations:
            for path, ids, ev in refs:
                rng = np.random.default_rng(seed if seed is not None else 21)
                counts = dict(clipped_conversions=0, final_conversions=0, separate_bit_conversions=0)

                def compute(li, name, a, w, y):
                    s, wq, dw = weights[li, name]
                    scaled = a/s
                    if configuration == "weight_only":
                        return scaled @ (wq*dw)
                    xq, scales, expanded = quantize_input(scaled, rows=rows, bits=activation_bits)
                    if configuration == f"ideal_a{activation_bits}":
                        return (xq*expanded).astype(np.float32) @ (wq*dw)
                    noisy = configuration.startswith("radix_read")
                    got, stats = radix_mvm(xq, wq, rows, cu, adc_bits, .5,
                                           read_noise if noisy else 0, noisy, rng, scales)
                    for key, value in stats.items():
                        counts[key] += value
                    return (got*dw).astype(np.float32)

                net.mvm = compute
                measured = ev.score(net(ids))
                results.append(dict(alpha=alpha, configuration=configuration, source=path.name,
                                    cu_ff=cu, seed=seed, activation_bits=activation_bits,
                                    rows=rows, ADC_bits=adc_bits,
                                    kl_pass=measured["kl"] <= .01, ppl_pass=measured["ppl_ratio"] <= 1.01,
                                    joint_pass=measured["kl"] <= .01 and measured["ppl_ratio"] <= 1.01,
                                    **measured, **counts))
                print(f"alpha={alpha} {configuration} Cu={cu} seed={seed} {path.name[:4]} KL={measured['kl']:.6g} "
                      f"PPLratio={measured['ppl_ratio']:.6f} ADCclips={counts['clipped_conversions']}", flush=True)
    net.mvm = None
    assert np.array_equal(net(refs[0][1]), refs[0][2].ref)
    out = ROOT/("build/research/imc_smooth_radix_fresh_holdout.json" if fresh else
                "build/research/imc_smooth_radix_optimized.json" if optimize else
                "build/research/imc_smooth_radix_validation_read50.json" if validate and read_noise == 50 else
                "build/research/imc_smooth_radix_validation.json" if validate else
                "build/research/imc_smooth_radix.json")
    if activation_bits != 8:
        suffix = "_read50" if read_noise == 50 else ""
        out = ROOT/f"build/research/imc_smooth_radix_a9_frozen_replay{suffix}.json"
    if architecture:
        out = ROOT/'build/research/imc_smooth_radix_r256_a9_b11_read50.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(results=results, weight_summaries_at_4fF=summaries,
        profile="Fixed R256/A9/ADC11/read50 development screen; frozen R128/A8-selected scales; exposed notes" if architecture else "512-token exposed-note A9 replay with frozen A8-selected scales" if activation_bits != 8 else "512-token fresh-note frozen-alpha test" if fresh else "256-token calibration-selected alpha" if optimize else "256-token fixed-alpha validation" if validate else "128-token bounded alpha comparison",
        architecture_capacitances_at_4fF=architecture_summary,
        weight_code_sha256_by_alpha=weight_code_hashes,
        frozen_state=dict(scales_file=str(frozen_path.relative_to(ROOT)), scales_sha256=hashlib.sha256(frozen_path.read_bytes()).hexdigest(),
                          choice_source=str(optimized_path.relative_to(ROOT)) if fresh else None,
                          choice_sha256=hashlib.sha256(optimized_path.read_bytes()).hexdigest() if fresh else None,
                          reconstruction="First use may replay the original hashed calibration solely to reconstruct scales; exact code/capacitance summary must match. No alpha search or fresh-note fitting.") if optimize or fresh else None,
        alpha_selection=dict(grid=[.25, .5, .75], draw_seeds=[1001, 1002], stream_key="[seed, layer, tensor_index]",
                             objective="mean of two explicit physical-output MSE draws against original calibration xW; no held-out selection",
                             records=selections, histogram_by_tensor={name: {str(a): sum(r["tensor"] == name and r["selected_alpha"] == a for r in selections)
                                                                           for a in (.25, .5, .75)} for name in TENSORS}) if optimize or fresh else None,
        acceptance=dict(maximum_KL=.01, maximum_PPL_ratio=1.01, require_both_each_case=True),
        runtime_s=time.perf_counter()-started, identity_max_relative=identity_max_relative,
        reference="Original GGUF Q8_0 weights, floating activations, all 30 layers and seven weight MVMs; not FP16 original model",
        calibration=dict(source=cal_path.name, sha256=hashlib.sha256(cal_path.read_bytes()).hexdigest(), tokens=128,
                         method="frozen input-channel maxima from separate original-Q8_0 forward; no held-out scale or alpha fitting"),
        references=[dict(source=p.name, sha256=hashlib.sha256(p.read_bytes()).hexdigest(), tokens=len(ids), ppl=ev.ppl)
                    for p, ids, ev in refs],
        scaling="alpha=0 means identity control; otherwise s_j=maxcalabs(x_j)^alpha/maxabs(W_inputrow_j)^(1-alpha), floors 1e-8",
        quantization=f"Per-output symmetric W8 RTN after scaling; dynamic per-token/per-{rows}-input-block A{activation_bits}; two signed magnitude weight slices",
        activation_bits=activation_bits,
        physical_followup=dict(alpha="calibration_selected" if optimize or fresh else .5, preselected=True, rows=rows, cu_ff=[4, 1.2] if validate and read_noise == 100 and not (optimize or fresh) else [4], ADC_bits=adc_bits, ADC_span_V=.5,
                               read_noise_uV=read_noise, sharing_thermal="independent kT/(2*C) per-stage hypothesis at 27 C"),
        limitations="Not a SmoothQuant benchmark replication. Runtime scaling/quantization/weight duplication/ADC hardware and energy unpriced. Float attention/KV/norm/LM head. No weight mismatch, ratio/gain error, reference/reset correlations, kickback or converter noise characterization. Two short technical passages, greedy tokenizer. Cu=1.2fF validation has no separate quantization-only control.",
        checks="Exact prequantization diagonal identity, zero channels, independent block-scale radix identity, full signed radix checks, original model restoration PASS"
        ), indent=2)+"\n")
    passed = sum(r["joint_pass"] for r in results)
    print(f"PASS: arithmetic checks; joint quality {passed}/{len(results)} cases; "
          f"{out.relative_to(ROOT)}, {time.perf_counter()-started:.2f}s", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selfcheck", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Fixed alpha .5, 256 tokens, two noise seeds, Cu=4/1.2fF")
    parser.add_argument("--optimize", action="store_true", help="One calibration-only per-MVM alpha grid, then fixed 256-token evaluation")
    parser.add_argument("--fresh-holdout", action="store_true", help="Frozen selected alphas, new notes27g3/27h5, 512 tokens; no search")
    parser.add_argument("--activation-bits", type=int, choices=(8, 9), default=8,
                        help="A9 requires --fresh-holdout and reuses its exposed notes/frozen A8-selected scales; extra plane is counted")
    parser.add_argument("--architecture-screen", action="store_true",
                        help="Fixed R256/A9/ADC11/read50 screen, frozen scales and exposed notes; requires --fresh-holdout --activation-bits 9 --read-noise 50")
    parser.add_argument("--read-noise", choices=(50, 100), type=int, default=100,
                        help="With --validate, 50 runs only four Cu=4fF noise follow-up cases")
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
        print("PASS: frozen rescaling algebra, partial blocks, zero channels, signed radix identity")
    else:
        if args.architecture_screen and not (args.fresh_holdout and args.activation_bits == 9 and args.read_noise == 50):
            parser.error("--architecture-screen requires --fresh-holdout --activation-bits 9 --read-noise 50")
        if args.activation_bits != 8 and not args.fresh_holdout:
            parser.error("A9 is a frozen replay only; requires --fresh-holdout")
        if args.optimize and args.fresh_holdout:
            parser.error("Choose either --optimize or --fresh-holdout")
        if (args.optimize or args.fresh_holdout) and (args.validate or (args.read_noise != 100 and args.activation_bits != 9)):
            parser.error("Optimization/fresh-holdout use their fixed profiles and read noise of 100 uV")
        if args.read_noise != 100 and not (args.validate or (args.fresh_holdout and args.activation_bits == 9)):
            parser.error("--read-noise 50 requires --validate")
        main(args.validate or args.optimize or args.fresh_holdout, args.read_noise, args.optimize, args.fresh_holdout, args.activation_bits, args.architecture_screen)
