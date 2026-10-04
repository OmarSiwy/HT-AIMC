"""Capacitor sizing versus redundant differential programming, statistical only.

Frozen real INT4 tiles; same device errors across activations, independent
calibration error, and activation holdout. Does not modify compiled weights.
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
sys.path.insert(0, str(ROOT / "scripts/compiler/metrics"))
from imc_mapping_experiment import NAMES

BITS = np.array([1, 2, 4, 8])
CODE_BITS = ((np.arange(16)[:, None] & BITS) != 0).astype(float)
CAL = 6


def sample_tiles():
    weights, inputs, units, labels, fingerprints = [], [], [], [], {}
    rng = np.random.default_rng(1984)
    for name in NAMES:
        wp = ROOT / "scripts/compiler/out/programming" / f"{name}.npz"
        xp = ROOT / "scripts/compiler/out/acts" / f"{name}.npz"
        for p in (wp, xp):
            fingerprints[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
        with np.load(wp) as z:
            w, u = z["Wq"].copy(), z["dw"] * float(z["dx_in"])
        with np.load(xp) as z:
            x = z["xq"].copy()
        assert w.shape[0] % 16 == w.shape[1] % 16 == 0 and len(x) > CAL
        nr = w.shape[1] // 16
        for idx in rng.choice(w.size // 256, 8, replace=False):
            j, i = divmod(int(idx), nr)
            weights.append(w[j*16:(j+1)*16, i*16:(i+1)*16])
            inputs.append(x[:, i*16:(i+1)*16])
            units.append(u[j*16:(j+1)*16])
            labels.append({"tensor": name, "output_tile": j, "input_tile": i})
    return np.array(weights), np.array(inputs), np.array(units), labels, fingerprints


def select_codes(w, observed, max_extra, variance=None):
    """Add k to both banks; nominal Cp-Cn stays exactly W. Zeros stay off.

    observed has per-cell measured physical capacitances for the two banks'
    four binary groups, normalized by nominal unit capacitance.
    """
    cp0, cn0 = np.maximum(w, 0), np.maximum(-w, 0)
    best_cp, best_cn = cp0.copy(), cn0.copy()
    best = np.full(w.shape, np.inf)
    for k in range(max_extra + 1):
        cp, cn = cp0 + k, cn0 + k
        valid = (cp <= 15) & (cn <= 15) & ((w != 0) | (k == 0))
        cp, cn = np.minimum(cp, 15), np.minimum(cn, 15)
        measured = (CODE_BITS[cp]*observed[..., 0, :]
                    - CODE_BITS[cn]*observed[..., 1, :]).sum(axis=-1)
        err = (measured - w)**2
        if variance is not None:
            err += ((CODE_BITS[cp]+CODE_BITS[cn])*variance).sum(axis=-1)
        take = valid & (err < best)
        best_cp, best_cn = np.where(take, cp, best_cp), np.where(take, cn, best_cn)
        best = np.where(take, err, best)
    assert np.array_equal(best_cp-best_cn, w), "nominal MAC changed"
    assert np.all((best_cp[w == 0] == 0) & (best_cn[w == 0] == 0))
    return best_cp, best_cn


def evaluate(w, x, units, actual, cp, cn):
    physical = (CODE_BITS[cp]*actual[..., 0, :]
                - CODE_BITS[cn]*actual[..., 1, :]).sum(axis=-1)
    ideal_y = x @ w.swapaxes(-1, -2)
    analog_y = x @ physical.swapaxes(-1, -2)
    # Optional one scalar per output column, fit six activations, test three.
    numerator = np.sum(analog_y[:, :CAL]*ideal_y[:, :CAL], axis=1)
    denominator = np.sum(analog_y[:, :CAL]**2, axis=1)
    gain = np.divide(numerator, denominator, out=np.ones_like(numerator), where=denominator > 0)
    scale = units[:, None, :]
    ref = ideal_y[:, CAL:]*scale
    signal = float(np.sum(ref**2))
    raw_error = float(np.sum(((analog_y[:, CAL:]-ideal_y[:, CAL:])*scale)**2))
    gain_error = float(np.sum(((analog_y[:, CAL:]*gain[:, None, :]-ideal_y[:, CAL:])*scale)**2))
    # Same repeated-activation schedule in each comparison; charge activity
    # proxy only. Clock, ballast, reference, OTA and memory are excluded.
    activity = np.mean(np.abs(x[:, CAL:]), axis=1)[:, None, :]
    switched = float(np.sum((cp+cn)*activity))
    base = float(np.sum(np.abs(w)*activity))
    return {"signal_sq": signal, "error_sq": raw_error, "gain_error_sq": gain_error,
            "csnr_db": 10*np.log10(signal/max(raw_error, 1e-300)),
            "gain_csnr_db": 10*np.log10(signal/max(gain_error, 1e-300)),
            "switched_cap_ratio": switched/base,
            "active_banks_ratio": float(np.count_nonzero(cp)+np.count_nonzero(cn))/np.count_nonzero(w),
            "max_abs_weight_error": float(np.max(np.abs(physical-w)))}


def main():
    start = time.perf_counter()
    w, x, units, labels, fingerprints = sample_tiles()
    assert np.max(np.abs(w)) <= 7
    rows = []
    for seed in range(4):
        rng = np.random.default_rng(901+seed)
        shape = w.shape+(2, 4)
        device_z, calibration_z = rng.normal(size=shape), rng.normal(size=shape)
        for cap_ff in (0.15, 0.6, 1.2, 4.0, 8.0):
            for ac_pct_um in (0.3, 1.0, 3.0):
                # Existing tb_csnr hypothesis, NOT a foundry matching model:
                # 2 fF/um2, sigma_rel=Ac/sqrt(area); binary-group variance
                # equals the sum of independent unit-cap variances.
                sigma_unit = ac_pct_um/100*np.sqrt(2/cap_ff)
                actual = BITS + device_z*np.sqrt(BITS)*sigma_unit
                assert np.all(actual > 0)
                for calibration_sigma_units in (0.0, 0.02, 0.1):
                    observed = actual + calibration_z*calibration_sigma_units
                    # Normal-prior posterior, known simulated variances.
                    # Avoid selecting a large common-mode code just because
                    # a noisy characterization happened to look favorable.
                    vdev, vcal = BITS*sigma_unit**2, calibration_sigma_units**2
                    posterior = BITS + vdev/(vdev+vcal)*(observed-BITS)
                    uncertainty = vdev*vcal/(vdev+vcal)
                    for policy, estimate, var in (("closest", observed, None),
                                                  ("uncertainty_aware", posterior, uncertainty)):
                        for max_extra in (0, 1, 4, 15):
                            cp, cn = select_codes(w, estimate, max_extra, var)
                            result = evaluate(w, x, units, actual, cp, cn)
                            if max_extra == 0:
                                assert result["switched_cap_ratio"] == 1
                            rows.append({"seed": seed, "cap_ff": cap_ff,
                                         "ac_pct_um": ac_pct_um, "policy": policy,
                                         "calibration_sigma_units": calibration_sigma_units,
                                         "max_extra": max_extra, **result})
    # Exact-characterization search must never worsen individual weights.
    actual = BITS + np.random.default_rng(13).normal(size=w.shape+(2, 4))*0.01
    baseline = np.maximum(w, 0), np.maximum(-w, 0)
    cp, cn = select_codes(w, actual, 15)
    def errors(pair):
        p, n = pair
        return np.abs((CODE_BITS[p]*actual[..., 0, :]-CODE_BITS[n]*actual[..., 1, :]).sum(-1)-w)
    assert np.all(errors((cp, cn)) <= errors(baseline)+1e-14)
    ideal = np.broadcast_to(BITS, w.shape+(2, 4))
    cp, cn = select_codes(w, ideal, 15)
    assert np.array_equal(cp, baseline[0]) and np.array_equal(cn, baseline[1])
    cp, cn = select_codes(w, ideal, 15, np.array([1., 2., 4., 8.]))
    assert np.array_equal(cp, baseline[0]) and np.array_equal(cn, baseline[1])
    out = ROOT / "build/research/imc_cap_calibration.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    report = {"boundary": "fixed statistical capacitor error only, no SPICE/ADC/thermal/full-model quality",
              "matching_coefficient_status": "hypothetical sensitivity sweep, not sky130 yield prediction",
              "input_sha256": fingerprints, "tiles": labels, "cal_tokens": CAL,
              "test_tokens": x.shape[1]-CAL, "samples_per_seed": int(w.size), "results": rows,
              "runtime_s": time.perf_counter()-start}
    out.write_text(json.dumps(report, indent=2)+"\n")
    print(f"PASS: {len(rows)} cases, {w.size} physical weights/seed; {out.relative_to(ROOT)}")
    print("C[fF] cal_sigma extra CSNR[dB] gain[dB] switchedC/base (pooled four devices)")
    for c in (0.15, 1.2, 4.0, 8.0):
        for sigma in (0.0, 0.02, 0.1):
            for extra in (0, 1, 4, 15):
                sub = [r for r in rows if r["cap_ff"] == c and r["ac_pct_um"] == 1.0
                       and r["policy"] == "uncertainty_aware"
                       and r["calibration_sigma_units"] == sigma and r["max_extra"] == extra]
                signal = sum(r["signal_sq"] for r in sub)
                csnr = 10*np.log10(signal/sum(r["error_sq"] for r in sub))
                gain = 10*np.log10(signal/sum(r["gain_error_sq"] for r in sub))
                print(f"{c:5.2f} {sigma:5.2f} {extra:2d} {csnr:7.2f} {gain:7.2f} "
                      f"{np.mean([r['switched_cap_ratio'] for r in sub]):7.3f}")
    print(f"Runtime: {report['runtime_s']:.2f}s")


def full_model(weight_bits):
    """Fixed physical weight errors; no redraw when token/activation changes."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from compiler.metrics.depth_budget import Net, Eval, TENSORS, tokenize_greedy
    from compiler.metrics.imc_precision_experiment import NOTES
    started = time.perf_counter()
    net = Net(w_int4=(weight_bits == 4))
    quantization = []
    if weight_bits == 8:
        q8_refs = []
        for prefix in ("27l1", "27h1"):
            p = next(NOTES.glob(prefix+" *.md"))
            ids = tokenize_greedy(p.read_text(), net.vocab)[:256]
            q8_refs.append((p, ids, Eval(net, ids)))
        for layer in net.L:
            for name in TENSORS:
                w = layer[name]
                step = np.maximum(np.max(np.abs(w), axis=0, keepdims=True)/127, 1e-30)
                layer[name] = np.ascontiguousarray(np.clip(np.rint(w/step), -127, 127)*step)
        for p, ids, ev in q8_refs:
            quantization.append({"source": p.name, "Q8_0_reference_ppl": ev.ppl,
                                 **ev.score(net(ids))})
        del q8_refs
    base = [dict(layer) for layer in net.L]
    refs = []
    for prefix in ("27l1", "27h1"):
        path = next(NOTES.glob(prefix+" *.md"))
        ids = tokenize_greedy(path.read_text(), net.vocab)[:256]
        assert len(ids) == 256
        ev = Eval(net, ids)
        assert abs(ev.score(net(ids))["kl"]) < 1e-12
        refs.append((path, ids, ev))
        print(f"INT{weight_bits} reference {prefix}: PPL={ev.ppl:.5f}", flush=True)
    rows = []
    for seed in (12, 13):
        for cap_ff in (0.15, 1.2, 4.0):
            rng = np.random.default_rng(seed)
            # Aggregate of binary-group errors for a chosen nonredundant
            # code: var(error/code_unit)=abs(code)*sigma_unit^2.
            sigma_unit = 0.01*np.sqrt(2/cap_ff)
            for li, layer in enumerate(base):
                for name in TENSORS:
                    w = layer[name]
                    limit = (1 << (weight_bits-1))-1
                    step = np.maximum(np.max(np.abs(w), axis=0, keepdims=True)/limit, 1e-30)
                    code = np.rint(w/step)
                    assert np.max(np.abs(code)) <= limit
                    magnitude = np.abs(code)
                    variance = magnitude if weight_bits == 4 else magnitude % 16+256*(magnitude//16)
                    error = rng.standard_normal(w.shape, dtype=np.float32)*np.sqrt(variance)*sigma_unit*step
                    assert np.all(error[code == 0] == 0)
                    net.L[li][name] = np.ascontiguousarray(w+error)
            hot = net.L[11]["ffn_down"]
            for protect in (False, True):
                net.L[11]["ffn_down"] = base[11]["ffn_down"] if protect else hot
                for path, ids, ev in refs:
                    metrics = ev.score(net(ids))
                    rows.append({"seed": seed, "cap_ff": cap_ff, "source": path.name,
                                 "protect_layer11_down": protect, **metrics})
                    print(f"C={cap_ff:g}fF seed={seed} protected={protect} {path.name[:4]} "
                          f"KL={metrics['kl']:.6f} PPLratio={metrics['ppl_ratio']:.6f}", flush=True)
    # Restore exact reference weights and check that the experiment is reversible.
    net.L = base
    assert abs(refs[0][2].score(net(refs[0][1]))["kl"]) < 1e-12
    suffix = "_w8" if weight_bits == 8 else ""
    path = ROOT / f"build/research/imc_cap_full_model{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows, "runtime_s": time.perf_counter()-started,
        "references": [{"source": p.name, "PPL": ev.ppl,
                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p, ids, ev in refs],
        "scope": "30 layers, all seven weight-MVM tensors, 256-token teacher-forced notes, greedy tokenizer",
        "weights": f"per-output RTN INT{weight_bits} from dequantized Q8_0; marginal analog error vs this reference",
        "weight_slices": weight_bits//4,
        "quantization_vs_Q8_0": quantization,
        "error_model": "fixed independent capacitor mismatch, Ac=1%um and2fF/um2 assumed; no temporal output noise",
        "limitations": "No physical ADC, switch errors, correlated layout gradients, KV errors, energy, or timing; not foundry yield",
        "protection": f"ideal base INT{weight_bits} weight MVM for layer11 down, not restored Q8_0 weights",
        "checks": "zero reference KL, zero code means zero weight error, final exact restoration PASS"}, indent=2)+"\n")
    print(f"PASS: fixed-weight experiment complete: {path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-model", action="store_true", help="24 full-depth fixed-mismatch quality cases")
    parser.add_argument("--weight-bits", choices=(4, 8), type=int, default=4,
                        help="full model only: INT8 uses two physical 4-bit magnitude slices")
    args = parser.parse_args()
    if args.full_model:
        full_model(args.weight_bits)
    else:
        main()
