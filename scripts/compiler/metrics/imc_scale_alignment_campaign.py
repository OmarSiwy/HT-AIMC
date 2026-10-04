"""Frozen activation-scale/pooling development experiment; no transistor PPA.

Uses only the two predeclared development slices. Reserved slices have no CLI
entry point here. Local R256/A9 is compared with common R1024 scales and
power-of-two R256 scales, preserving every local holder capacitance on pooling.
"""
import argparse
from collections import Counter
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
from compiler.metrics.imc_smooth_radix import quantize_input, quantize_weight
from compiler.metrics.imc_radix_full_model import radix_mvm, KT

PROTOCOL = ROOT / "build/campaign/system_audit/scale_alignment_protocol.json"
LOCAL, POOL = 256, 1024
MENU = (("local", 9), ("common", 9), ("common", 10), ("common", 11),
        ("common", 12), ("power2", 9), ("power2", 10))


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantize(a, kind, bits):
    """Codes and scales per physical local holder, never an implicit gain."""
    assert kind in ("local", "common", "power2") and 9 <= bits <= 12
    rows = POOL if kind == "common" else LOCAL
    maximum = 2**(bits-1)-1
    scales = np.stack([np.maximum(np.max(abs(a[:, i:i+rows]), axis=1)/maximum, 1e-30)
                       for i in range(0, a.shape[1], rows)], axis=1)
    if kind == "power2":
        scales = np.exp2(np.ceil(np.log2(scales.astype(float)))).astype(np.float32)
    expanded = np.repeat(scales, rows, axis=1)[:, :a.shape[1]]
    raw = np.rint(a/expanded)
    assert np.all(np.isfinite(raw)) and np.max(abs(raw)) <= maximum
    local_scales = np.repeat(scales, rows//LOCAL, axis=1)[:, :(a.shape[1]+LOCAL-1)//LOCAL]
    return raw.astype(np.int16), local_scales, expanded


def histogram(x):
    values, counts = np.unique(x, return_counts=True)
    return {str(int(v)): int(c) for v, c in zip(values, counts)}


def reduction(xq, wq, scales, kind, pooled, adc_bits=0, read_uv=0, thermal=False,
              rng=None, cu_ff=4., bus_ff=0.):
    """Explicit charge sum, finite ADC, and stated independent-stage noise.

    Pooled common codes use the same B on every constituent local holder.
    Pooled power2 codes first compute B bits, then d=E-eg zero-input halving
    steps. Extra steps have the SAME assumed kT/(2*C) stage noise as computation.
    No reset/reference/join noise is added; those physical modes are unverified.
    ``bus_ff`` is an unnoisy held capacitive load, an optimistic model boundary.
    """
    assert xq.shape[1] == wq.shape[0]
    assert np.all(abs(wq.astype(np.int16)) <= 127)
    assert not (pooled and kind == "local"), "Unequal arbitrary scales need actual gain"
    ng = (xq.shape[1]+LOCAL-1)//LOCAL
    assert scales.shape == (len(xq), ng)
    group_size = POOL//LOCAL if pooled else 1
    out = np.zeros((len(xq), wq.shape[1]), dtype=float)
    counters = Counter(final_conversions=0, unpooled_conversions=0,
                       ADC_decisions=0, local_column_plane_events=0,
                       local_alignment_plane_events=0, group_column_plane_slots=0,
                       quantizer_clips=0, used_local_hold_states=0)
    plane_hist, extra_hist, exponent_hist, bits_hist = Counter(), Counter(), Counter(), Counter()
    requirements, read_ratios, cap_values, peaks = [], [], [], []
    for first in range(0, ng, group_size):
        last = min(first+group_size, ng)
        ids = list(range(first, last))
        local_max = np.stack([np.max(abs(xq[:, g*LOCAL:(g+1)*LOCAL]), axis=1) for g in ids], axis=1)
        local_b = np.ceil(np.log2(local_max.astype(float)+1)).astype(int)
        local_scale = scales[:, first:last].astype(float)
        active = np.any(local_max > 0, axis=1)
        if pooled:
            B = local_b.max(axis=1)
            output_scale = local_scale.max(axis=1)
            ratio = local_scale/output_scale[:, None]
            if kind == "common":
                assert np.array_equal(ratio, np.ones_like(ratio))
                delays = np.zeros_like(local_b)
            else:
                delays = np.rint(-np.log2(ratio)).astype(int)
                assert np.allclose(ratio, 2.**(-delays), rtol=0, atol=0)
                # A zero holder needs no extreme dummy exponent; still pay B
                # cycles if other holders in its pool compute.
                delays[local_max == 0] = 0
                ratio[local_max == 0] = 1.
            steps = B[:, None]+delays
            steps[~active] = 0
        else:
            B = local_b[:, 0]
            output_scale = local_scale[:, 0]
            ratio = np.ones_like(local_scale)
            delays = np.zeros_like(local_b)
            steps = local_b
        width = wq.shape[1]
        counters.update(final_conversions=2*int(active.sum())*width,
                        unpooled_conversions=2*int((local_max>0).sum())*width,
                        ADC_decisions=2*adc_bits*int(active.sum())*width,
                        local_column_plane_events=2*int(steps.sum())*width,
                        local_alignment_plane_events=2*int(delays[active].sum())*width,
                        group_column_plane_slots=2*int(steps.max(axis=1).sum())*width,
                        used_local_hold_states=2*int(active.sum())*len(ids)*width)
        plane_hist.update(histogram(B[active]))
        extra_hist.update(histogram(delays[active]))
        exponent_hist.update(histogram(delays[active].max(axis=1)))
        for shift in (0, 4):
            charge = np.zeros((len(xq), width), dtype=float)
            charge_var = np.zeros_like(charge)
            total_cap = np.full(width, bus_ff*1e-15)
            baseline_read_coefficient = np.zeros_like(charge)
            for j, g in enumerate(ids):
                xb = xq[:, g*LOCAL:(g+1)*LOCAL]
                wb = wq[g*LOCAL:(g+1)*LOCAL].astype(np.int16)
                digits = (np.sign(wb)*((abs(wb) >> shift)&15)).astype(np.float32)
                C = (120+cu_ff*np.sum(abs(digits), axis=0, dtype=float))*1e-15
                partial = (xb.astype(np.float32) @ digits).astype(float)
                # C*h = Cu*Vs*S / 2^B, followed by paid zero-input halvings.
                charge += cu_ff*1e-15*.45*partial/np.exp2(B[:, None])*ratio[:, j, None]
                if thermal:
                    v = KT/(2*C)[None, :]*(1-4.**(-steps[:, j, None]))/(1-.25)
                    charge_var += C[None, :]**2*v
                # Separate readout can use each local block's shorter B and
                # skip an exactly zero block. Its final error must include
                # that significance advantage in an equal-error comparison.
                separate_factor = ratio[:, j]*np.exp2(local_b[:, j]-B)*(local_max[:, j]>0)
                baseline_read_coefficient += (C[None, :]*separate_factor[:, None])**2
                total_cap += C
            held = charge/total_cap[None, :]
            required_ratio = np.sqrt(baseline_read_coefficient)/total_cap[None, :]
            required_ratio[~active] = 1.
            required_extra = np.maximum(0, np.ceil(-np.log2(required_ratio)-1e-12)).astype(int)
            if active.any():
                requirements.append((50*required_ratio[active]).ravel())
                read_ratios.append(required_ratio[active].ravel())
                bits_hist.update(histogram(required_extra[active]))
                cap_values.extend(total_cap*1e15)
                peaks.append(float(np.max(abs(held[active]))))
            if thermal or read_uv:
                assert rng is not None
                variance = charge_var/total_cap[None, :]**2+(read_uv*1e-6)**2
                held += rng.standard_normal(held.shape)*np.sqrt(variance)
            if adc_bits:
                step = .5/2**adc_bits
                code = np.floor(held/step+.5)
                counters['quantizer_clips'] += int(np.count_nonzero(
                    ((code < -2**(adc_bits-1)) | (code > 2**(adc_bits-1)-1)) & active[:, None]))
                held = np.clip(code, -2**(adc_bits-1), 2**(adc_bits-1)-1)*step
            got = held*total_cap[None, :]*np.exp2(B[:, None])/(cu_ff*1e-15*.45)
            got[~active] = 0
            out += got*output_scale[:, None]*2**shift
    def percentiles(values):
        if not values:
            return None
        data = np.concatenate(values) if isinstance(values[0], np.ndarray) else values
        return dict(zip(('min', 'p50', 'p95', 'max'), np.percentile(data, [0, 50, 95, 100]).tolist()))
    stats = dict(counters, magnitude_bits_histogram=dict(plane_hist),
                 extra_decay_histogram=dict(extra_hist), pool_exponent_spread_histogram=dict(exponent_hist),
                 extra_ADC_bits_equal_independent_quantization_variance=dict(bits_hist),
                 required_read_uV_to_match_separate_50uV=percentiles(requirements),
                 pooled_to_separate_read_noise_ratio=percentiles(read_ratios),
                 joined_capacitance_fF=percentiles(cap_values), max_ideal_held_magnitude_V=max(peaks, default=0.),
                 ADC_span_V=.5, ADC_LSB_V=.5/2**adc_bits if adc_bits else None,
                 ADC_signed_limits=[-2**(adc_bits-1), 2**(adc_bits-1)-1] if adc_bits else None,
                 padded_MACs=int(len(xq)*ng*LOCAL*wq.shape[1]), useful_MACs=int(len(xq)*wq.size))
    return out, stats


def selfcheck():
    rng = np.random.default_rng(90521)
    a = rng.normal(size=(8, 1283)).astype(np.float32)
    a[:, :256] *= 32
    a[:, 256:512] *= .03125
    a[0] = 0
    w = rng.integers(-127, 128, (1283, 5), dtype=np.int16)
    for kind, bits in MENU:
        q, scales, expanded = quantize(a, kind, bits)
        if kind == 'local':
            old_q, old_s, old_e = quantize_input(a, rows=LOCAL, bits=bits)
            assert np.array_equal(q, old_q) and np.array_equal(scales, old_s)
            assert np.array_equal(expanded, old_e)
        exact = (q.astype(float)*expanded) @ w.astype(float)
        for pooled in ((False,) if kind == 'local' else (False, True)):
            got, stats = reduction(q, w, scales, kind, pooled)
            assert np.allclose(got, exact, rtol=2e-12, atol=1e-7)
            assert np.all(got[0] == 0)
            assert stats['useful_MACs'] == a.shape[0]*w.size
            stride = POOL if pooled else LOCAL
            active_groups = sum(np.any(q[:,i:i+stride] != 0, axis=1).sum()
                                for i in range(0,q.shape[1],stride))
            assert stats['final_conversions'] == 2*int(active_groups)*5
        if kind == 'local':
            for noise in (False, True):
                old, old_stats = radix_mvm(q, w, LOCAL, 4, 11, .5, 50 if noise else 0,
                                           noise, np.random.default_rng(71), scales)
                got, stats = reduction(q, w, scales, kind, False, 11, 50 if noise else 0,
                                       noise, np.random.default_rng(71))
                assert np.allclose(old, got, rtol=1e-12, atol=1e-7)
                assert stats['final_conversions'] == old_stats['final_conversions']
                assert stats['quantizer_clips'] == old_stats['clipped_conversions']
        if kind == 'power2':
            # This deliberately ignores exponent significance.
            wrong, _ = reduction(q, w, np.ones_like(scales), 'common', True)
            assert np.linalg.norm(wrong-exact) > np.linalg.norm(exact)*.1
            assert stats['local_alignment_plane_events'] > 0
    # Independent sign, endpoint, cancellation and unequal-C conservation.
    q = np.array([[-2047, 2047, 0], [2047, -2047, 0], [0, 0, 0]], dtype=np.int16)
    w = np.array([[-127, 127, 127], [-127, 127, -127], [0, 0, 127]], dtype=np.int16)
    got, _ = reduction(q, w, np.ones((3, 1)), 'common', True)
    assert np.allclose(got, q.astype(np.int64)@w.astype(np.int64), atol=1e-8, rtol=0)
    q = np.full((1, 512), 255, dtype=np.int16)
    q[:,256:] = -255
    w = np.r_[np.ones((256, 1)), np.full((256, 1), 15)].astype(np.int16)
    got, stats = reduction(q, w, np.ones((1, 2)), 'common', True)
    C = np.array([120+4*256, 120+4*15*256])*1e-15
    S = np.array([255*256, -255*15*256])
    wrong_equal_voltage = np.mean(4e-15*.45*S/(256*C))*C.sum()*256/(4e-15*.45)
    assert abs(wrong_equal_voltage-got[0, 0]) > abs(got[0, 0])*.1
    assert np.isclose(stats['max_ideal_held_magnitude_V'], abs(4e-15*.45*S.sum()/256/C.sum()))
    print('PASS: local-baseline parity; signed/zero/ragged/unequal-scale charge identities; negative controls', flush=True)


def run(stage, outdir):
    selfcheck()
    outdir.mkdir(parents=True, exist_ok=True)
    output = outdir/f'{stage}.json'
    assert not output.exists(), f'Refusing to overwrite {output}'
    protocol = json.loads(PROTOCOL.read_text())
    scales_path = ROOT/protocol['frozen_scales']
    assert fingerprint(scales_path) == protocol['scales_sha256']
    source_paths = [Path(__file__), ROOT/'scripts/compiler/metrics/depth_budget.py',
                    ROOT/'scripts/compiler/metrics/imc_smooth_radix.py', ROOT/'scripts/compiler/metrics/imc_radix_full_model.py',
                    ROOT/'scripts/compiler/gguf_reader.py', PROTOCOL, scales_path,
                    ROOT/protocol['model']]
    sources = {str(p.relative_to(ROOT)): fingerprint(p) for p in source_paths}
    snapshot = outdir/f'source_{sources[str(Path(__file__).relative_to(ROOT))]}.py'
    if not snapshot.exists():
        snapshot.write_bytes(Path(__file__).read_bytes())
    net = Net()
    assert (net.NL, net.DM, net.NH, net.NKV, len(net.vocab)) == (30, 576, 9, 3, 49152)
    with np.load(scales_path) as saved:
        frozen = {k: saved[k].copy() for k in saved.files}
    weights = {}
    digest = hashlib.sha256()
    for li, layer in enumerate(net.L):
        for name in TENSORS:
            s = frozen[f'{li}_{name}']
            wq, dw = quantize_weight(layer[name], s)
            weights[li, name] = s, wq, dw
            digest.update(f'{li}/{name}/{wq.shape}\n'.encode())
            digest.update(wq.tobytes())
    anchor_path = ROOT/'build/research/imc_smooth_radix_r256_a9_b11_read50.json'
    anchor = json.loads(anchor_path.read_text())
    assert anchor['frozen_state']['scales_sha256'] == fingerprint(scales_path)
    # The historical artifact predates per-code hashing. Reproduce its exact
    # activity/capacitance summary, then record a code hash for this campaign.
    summaries, slices, totals, count = [], [[], []], [0,0], 0
    for _,wq,_ in weights.values():
        count += wq.size
        for j,shift in enumerate((0,4)):
            digits = (abs(wq.astype(np.int16)) >> shift)&15
            totals[j] += int(digits.sum())
            slices[j].extend(120+4*digits[start:start+128].sum(axis=0)
                             for start in range(0,len(wq),128))
    for shift,caps in zip((0,4),slices):
        summaries.append(dict(shift=shift, capacitance_fF=dict(zip(('min','p50','p95','max'),
            np.percentile(np.concatenate(caps),(0,50,95,100)).tolist()))))
    assert [dict(alpha='calibration_selected', mean_absolute_slice_digits=[v/count for v in totals],
                 slices=summaries)] == anchor['weight_summaries_at_4fF']
    sources[str(anchor_path.relative_to(ROOT))] = fingerprint(anchor_path)
    records, references = [], []
    started = time.perf_counter()
    result = dict(stage=stage, protocol=protocol, sources=sources, weight_code_sha256=digest.hexdigest(),
                  classification='Development behavioral experiment; no physical PPA; reserved corpus untouched',
                  precision_requirements='ADC extra bits/read-noise ratios are independent-error budgets, not actual adaptive converter measurements',
                  physical_assumptions='Each R256 local holder includes 120fF plus 4fF*sum(abs(slice)); original holders joined, zero bus capacitance; independent kT/(2C) stages; no reset/reference/join noise, mismatch, loading, clock energy or integration proof',
                  timing='Counts only; local groups assumed parallel while W8 slices serialized. Extra power2 significance steps paid; no transistor cycle or free ADC-energy saving assigned.',
                  limits='All seven projections perturbed; attention/KV/norm/nonlinear/LM head ideal. Greedy tokenizer; two technical notes. Every reported corpus uses first512 only.',
                  acceptance=protocol['quality_gates'], references=references, results=records)
    # Freeze complete stage policy before any quality evaluation.
    if stage == 'ideal':
        configs = [('weight_only', 0, False, 0, None)] + [(k, b, k!='local', 0, None) for k,b in MENU]
    else:
        configs = [(k, b, pool, 11, seed) for k,b in MENU
                   for pool in ((False,) if k=='local' else (False,True))
                   for seed in (None, *protocol['seeds'])]
    result['frozen_stage_configurations'] = configs
    output.write_text(json.dumps(result, indent=2)+'\n')
    for source in protocol['sources']:
        path = Path(source['path'])
        assert fingerprint(path) == source['sha256']
        # Tokenization alone is not evaluation; never construct a reserved Eval.
        ids = tokenize_greedy(path.read_text(), net.vocab)[:512]
        assert len(ids) == 512 and source['screen_token_slice'] == [0,512]
        net.mvm = None
        ev = Eval(net, ids)
        null = ev.score(ev.ref)
        assert abs(null['kl']) < 1e-12 and null['ppl_ratio'] == 1.
        references.append(dict(source=path.name, sha256=source['sha256'], tokens=512,
                               token_ids_sha256=hashlib.sha256(np.array(ids,dtype='<i4').tobytes()).hexdigest(),
                               original_Q8_0_PPL=ev.ppl))
        for kind,bits,pooled,adc_bits,seed in configs:
            tic = time.perf_counter()
            tensors = []
            rng = np.random.default_rng(60001 if seed is None else seed)
            def compute(li, name, a, w, clean):
                s, wq, dw = weights[li,name]
                scaled = a/s
                if kind == 'weight_only':
                    got = scaled @ (wq*dw)
                    stats = {}
                else:
                    xq, dx, expanded = quantize(scaled, kind, bits)
                    raw, stats = reduction(xq, wq, dx, kind, pooled, adc_bits,
                                           50 if seed is not None else 0, seed is not None, rng)
                    # Preserve the old ideal-control operation ordering.
                    got = (xq*expanded).astype(np.float32) @ (wq*dw) if not adc_bits else (raw*dw).astype(np.float32)
                err = got.astype(float)-clean
                stats.update(layer=li, tensor=name,
                             MVM_error_mse=float(np.mean(err**2)),
                             MVM_signal_mean_square=float(np.mean(clean.astype(float)**2)),
                             MVM_error_max=float(np.max(abs(err))))
                tensors.append(stats)
                return got
            net.mvm = compute
            metrics = ev.score(net(ids))
            assert len(tensors) == 210
            counts = {key: sum(t.get(key,0) for t in tensors) for key in
                      ('final_conversions','unpooled_conversions','ADC_decisions','local_column_plane_events',
                       'local_alignment_plane_events','group_column_plane_slots','quantizer_clips',
                       'used_local_hold_states','padded_MACs','useful_MACs')}
            rec = dict(source=path.name, kind=kind, activation_bits=bits, pooled=pooled,
                       ADC_bits=adc_bits, seed=seed, sharing_thermal=seed is not None,
                       read_noise_uV=50 if seed is not None else 0, **metrics, **counts,
                       joint_pass=metrics['kl']<=.01 and metrics['ppl_ratio']<=1.01,
                       runtime_s=time.perf_counter()-tic, tensors=tensors)
            records.append(rec)
            result['runtime_s'] = time.perf_counter()-started
            output.write_text(json.dumps(result, indent=2)+'\n')
            print(f"{stage} {path.stem[:20]} {kind} A{bits} pooled={pooled} seed={seed} "
                  f"KL={metrics['kl']:.6g} PPL={metrics['ppl_ratio']:.7f} PASS={rec['joint_pass']} "
                  f"ADCs={counts['final_conversions']} extraPlanes={counts['local_alignment_plane_events']} "
                  f"time={rec['runtime_s']:.2f}s", flush=True)
        net.mvm = None
        assert np.array_equal(net(ids), ev.ref), 'Original model changed'
    assert all(fingerprint(ROOT/p)==h for p,h in sources.items()), 'Source/artifact changed during run'
    result['complete'] = True
    result['arithmetic_checks'] = 'PASS; selfcheck plus unchanged original model and frozen sources'
    output.write_text(json.dumps(result, indent=2)+'\n')
    print(f'PASS: arithmetic/execution; quality {sum(r["joint_pass"] for r in records)}/{len(records)}; {output}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--selfcheck', action='store_true')
    parser.add_argument('--stage', choices=('ideal','physical'), default='ideal')
    parser.add_argument('--outdir', type=Path, default=ROOT/'build/campaign/scale_alignment')
    args = parser.parse_args()
    if args.selfcheck:
        selfcheck()
    else:
        run(args.stage, args.outdir)
