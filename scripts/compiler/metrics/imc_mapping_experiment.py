"""Bounded SAGE-inspired input permutation study; no compiler mutation.

Run with the repository's NumPy environment. Fits mapping and ADC scale on
the first six saved tokens, scores the last three, and reuses golden ADCs.
Stored INT4/INT8 values are frozen: this isolates placement, not quantization.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from golden import model as G

NAMES = ("attn_q", "attn_k", "attn_v", "attn_o", "ffn_gate", "ffn_up", "ffn_down")
TILE = 16
CAL = 6


def permutations(w, x):
    """Fixed saliency choices and five random controls, calibration only."""
    n = w.shape[1]
    saliency = np.max(np.abs(x), axis=0) * np.sqrt(np.mean(w.astype(float) ** 2, axis=0))
    order = np.argsort(-saliency, kind="stable")
    yield "identity", np.arange(n)
    yield "cluster", order
    # Consecutive high-saliency channels land in different row tiles.
    yield "interleave", order.reshape(TILE, n // TILE).T.ravel()
    for seed in range(5):
        yield f"random_{seed}", np.random.default_rng(seed).permutation(n)


def partials(w, x, p):
    wp, xp = w[:, p], x[:, p]
    wt = wp.reshape(w.shape[0], -1, TILE)
    sign, hi, lo = G.pwm_nibbles(xp)
    def product(a):
        return np.einsum("ori,tri->tor", wt, a.reshape(len(x), -1, TILE))
    mh, ml = product(sign * hi), product(sign * lo)
    full = 16 * mh + ml
    assert np.array_equal(full.sum(axis=2), x @ w.T), "permutation changed exact integer MAC"
    assert np.allclose(xp.astype(float) @ wp.T, x.astype(float) @ w.T,
                       rtol=1e-12, atol=1e-10), "permutation changed exact float MAC"
    return mh, ml, full


def measure(mh, ml, full, mode, ranges, weight_units):
    samples = np.concatenate([mh[:CAL], ml[:CAL]], axis=0) if mode == "nibble" else full[:CAL]
    if ranges == "tensor":
        d = np.full(full.shape[2], G.conv_scale_D(samples), dtype=np.int64)
    else:
        d = np.array([G.conv_scale_D(samples[:, :, r]) for r in range(full.shape[2])])
    assert np.all(d >= 1)
    if mode == "nibble":
        ch, cl = G.eventrate_convert(mh[CAL:], d), G.eventrate_convert(ml[CAL:], d)
        partial_codes = G.nibble_combine(ch["code"], cl["code"])
        raw_codes = 16 * ch["code"] + cl["code"]
        y = (partial_codes * d).sum(axis=2)
        conversions = [ch, cl]
        analog = [mh[CAL:], ml[CAL:]]
        combine_saturations = int(np.count_nonzero(raw_codes != partial_codes))
    else:
        c = G.eventrate_convert(full[CAL:], d)
        y = (c["code"] * d).sum(axis=2)
        conversions, analog = [c], [full[CAL:]]
        combine_saturations = 0
    exact = full[CAL:].sum(axis=2)
    ref = exact * weight_units[None, :]
    err = (y - exact) * weight_units[None, :]
    mse, signal = float(np.mean(err ** 2)), float(np.mean(ref ** 2))
    count = sum(c["code"].size for c in conversions)
    clipped = sum(int(np.count_nonzero(np.floor((2*np.abs(a)+d)/(2*d)) > 127)) for a in analog)
    z = samples.astype(float).ravel()
    z -= z.mean()
    kurtosis = float(np.mean(z**4) / max(np.mean(z**2)**2, 1e-30))
    return {
        "nmse": mse / max(signal, 1e-30),
        "sqnr_db": 10 * np.log10(max(signal, 1e-30) / max(mse, 1e-30)),
        "error_sq_sum": float(np.sum(err**2)), "signal_sq_sum": float(np.sum(ref**2)),
        "adc_events": count, "mean_n_eval": float(sum(c["n_eval"].sum() for c in conversions)/count),
        "clipped_fraction": clipped/count, "combine_saturations": combine_saturations,
        "D_min": int(d.min()), "D_max": int(d.max()), "D_mean": float(d.mean()),
        "D_unique": int(len(np.unique(d))), "D": d.tolist(), "cal_partial_kurtosis": kurtosis,
    }


def main():
    rows = []
    fingerprints = {}
    source = ROOT / "scripts/compiler/out"
    for name in NAMES:
        wfile, xfile = source / "programming" / f"{name}.npz", source / "acts" / f"{name}.npz"
        for path in (wfile, xfile):
            fingerprints[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        with np.load(wfile) as z:
            w = z["Wq"].copy()
            units = z["dw"].copy() * float(z["dx_in"])
        with np.load(xfile) as z:
            x = z["xq"].copy()
        assert len(x) > CAL and w.shape[1] % TILE == 0
        for strategy, p in permutations(w, x[:CAL]):
            assert np.array_equal(np.sort(p), np.arange(w.shape[1]))
            mh, ml, full = partials(w, x, p)
            for mode in ("nibble", "merged"):
                for ranges in ("tensor", "row_tile"):
                    row = {"tensor": name, "strategy": strategy, "mode": mode,
                           "ranges": ranges, "cal_tokens": CAL, "test_tokens": len(x)-CAL,
                           "outputs": w.shape[0], "inputs": w.shape[1],
                           "tile_passes_per_token": w.size//(TILE*TILE),
                           "permutation": p.tolist()}
                    row.update(measure(mh, ml, full, mode, ranges, units))
                    rows.append(row)
    for name in NAMES:
        for mode in ("nibble", "merged"):
            sub = [r for r in rows if r["tensor"] == name and r["mode"] == mode]
            assert len({r["adc_events"] for r in sub}) == 1, "unmatched conversion count"
            assert len({r["tile_passes_per_token"] for r in sub}) == 1, "unmatched pass count"
    out = ROOT / "build/research/imc_mapping"
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(rows, indent=2)+"\n")
    (out / "inputs.json").write_text(json.dumps({"sha256": fingerprints,
        "calibration_indices": list(range(CAL)), "evaluation_indices": list(range(CAL, len(x))),
        "adc_event_boundary": "data columns only; checksum excluded",
        "numpy_version": np.__version__}, indent=2)+"\n")
    report = [
        "# SAGE-inspired AnalogIOC tile mapping experiment", "",
        "Date: 2026-09-07. **Golden-model placement experiment, not SPICE or end-to-end LLM inference.**",
        "No implementation/compiler behavior was changed. Existing `scripts/compiler/out/programming` INT4 weights "
        "and `scripts/compiler/out/acts` INT8 inputs are frozen; the first six saved token positions choose the "
        "permutation and converter scales, and the last three score it. The original compiler fitted "
        "upstream quantization scales on its full nine-token stream, so this is held out only for the "
        "new mapping/range decision, not an independently calibrated deployment-quality test.", "",
        "The experiment is inspired by the SAGE author abstract, which describes input-channel grouping "
        "to improve analog robustness. It does not claim to reproduce the unavailable full algorithm. "
        "[Primary author description](https://zhenyu001225.github.io/), "
        "[paper DOI](https://doi.org/10.1109/ICCAD66269.2025.11240907).", "",
        "## Exact operation and controls", "",
        "For a fixed permutation P, `x'=Px`, `W'=WP^T` leaves the complete MVM unchanged. "
        "It changes which products enter each 16-row tile before rounding/clipping. Saliency is "
        "`max_cal(abs(x_i))*rms_j(Wq_ji)`. `cluster` places descending saliency together; "
        "`interleave` spreads adjacent ranks across different row tiles. Five seeded random "
        "permutations provide controls. All permutations are fixed before examining test outputs.", "",
        "`tensor` uses the existing one-D-per-tensor policy refitted on calibration partials. "
        "`row_tile` fits one D per 16-input group across all output columns. Every D uses the "
        "golden `max(1,ceil(4*std/120))` law. The latter needs independently configurable analog "
        "scales and multiplication/alignment before accumulation; it is proposed hardware support, "
        "not a capability of the shipped fixed-D rail. Each comparison holds weight bits, activation "
        "bits, output ADC bits, physical tile passes and scalar ADC event counts constant.", "",
        "Both the baseline two-nibble path (golden event converter plus saturating nibble combine) "
        "and the merged-window path are shown. Compare strategies **within** one path: merged has "
        "half the scalar ADC events and is not a matched-conversion comparison against nibble. "
        "Outputs are scored before final requantization against exact integer MAC, dequantized with "
        "the stored per-output `dw*dx`. No analog mismatch/read noise is invented. Metrics measure "
        "the marginal ideal-converter error, not the full FP32 model error.", "",
        "All ADC counts are **data-column** events. Checksum columns and ABFT checking are excluded. "
        "A deployed permutation must regenerate/reorder the checksum programming consistently, and "
        "its static activation wiring/permutation network costs area, delay and energy even when "
        "tile and ADC event counts are unchanged.", "",
        "## Held-out results", "",
        "Higher SQNR is better. Random is median SQNR over five fixed seeds, not a selected winner. "
        "All values are dB. A changed kurtosis alone is not an accuracy or energy win.", "",
    ]
    for mode in ("nibble", "merged"):
        for ranges in ("tensor", "row_tile"):
            report += [f"### {mode}, {ranges} D", "", "| Tensor | Identity | Cluster | Interleave | Random median | Cluster Δ |", "|---|---:|---:|---:|---:|---:|"]
            for name in NAMES:
                subset = {r["strategy"]:r for r in rows if r["tensor"]==name and r["mode"]==mode and r["ranges"]==ranges}
                v = [subset[k]["sqnr_db"] for k in ("identity", "cluster", "interleave")]
                rand = float(np.median([subset[f"random_{s}"]["sqnr_db"] for s in range(5)]))
                report.append(f"| {name} | {v[0]:.2f} | {v[1]:.2f} | {v[2]:.2f} | {rand:.2f} | {v[1]-v[0]:+.2f} |")
            report.append("")
    report += ["## Event-count, scale and clipping detail", "",
               "Shown for FFN-down, a predeclared tensor of interest (this saved file is layer 0, "
               "not the sensitive layer 11 from DEPTH_BUDGET). Comparator evaluation averages are "
               "golden counts; they are not measured energy or variable-duration hardware completion.", "",
               "| Path | D policy | Mapping | D range | Clip % | Mean coarse evaluations | Data ADC events/test token |", "|---|---|---|---|---:|---:|---:|"]
    for r in rows:
        if r["tensor"] == "ffn_down" and r["strategy"] in ("identity", "cluster", "interleave"):
            report.append(f"| {r['mode']} | {r['ranges']} | {r['strategy']} | {r['D_min']}–{r['D_max']} | {100*r['clipped_fraction']:.4f} | {r['mean_n_eval']:.3f} | {r['adc_events']//r['test_tokens']} |")
    def score(mode, ranges, strategy):
        return next(r["sqnr_db"] for r in rows if r["tensor"] == "ffn_down"
                    and r["mode"] == mode and r["ranges"] == ranges and r["strategy"] == strategy)
    ni, nc, ns = [score("nibble", "tensor", s) for s in ("identity", "cluster", "interleave")]
    mi, mc = [score("merged", "row_tile", s) for s in ("identity", "cluster")]
    report += ["", "## Interpretation and next gate", "",
        "Two predeclared mappings have opposite behavior depending on the physical range policy. "
        "For layer-0 FFN-down in the nibble/tensor-D path, interleaving raises held-out ideal-converter "
        f"SQNR from {ni:.2f} to {ns:.2f} dB ({ns-ni:+.2f} dB), while clustering yields {nc:.2f} dB. "
        "The data ADC counts are unchanged. For the merged/row-tile-D path, clustering "
        f"changes FFN-down from {mi:.2f} to {mc:.2f} dB ({mc-mi:+.2f} dB), with the same data ADC count but "
        "additional range support and more coarse evaluations. The useful candidate is grouping "
        "co-designed with range granularity; a universal clustering rule is falsified here.", "",
        "This experiment can falsify a simple training-free grouping recipe or identify a placement "
        "candidate worth testing. It cannot establish a token/J or token/s gain: no physical ADC, "
        "range-switching energy, activation permutation fabric, mismatch redistribution, or full-model "
        "quality is measured. It does not select a per-tensor winner from held-out results. A follow-up "
        "needs independent raw calibration/evaluation corpora, full-model activations, actual calibrated "
        "physical residuals and independently programmable tile ranges.", "",
        "Checks: permutation bijections; exact integer MVM invariant; float MVM invariant; matched "
        "ADC and tile-pass counts within each path; positive integer scales. **PASS**.", "",
        "Reproduce: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_mapping_experiment.py` "
        "inside the repository NumPy environment. Full scales, permutations, errors and event counts: "
        "`build/research/imc_mapping/results.json`; source fingerprints and split: "
        "`build/research/imc_mapping/inputs.json` (generated artifacts).", "",
    ]
    (ROOT / "docs/src/content/Project/IMC_MAPPING_EXPERIMENT.md").write_text("\n".join(report))
    print(f"PASS: {len(rows)} conditions; exact-MAC and matched-service checks; {out}")
    for mode in ("nibble", "merged"):
        for ranges in ("tensor", "row_tile"):
            r = {x["strategy"]: x for x in rows if x["tensor"]=="ffn_down" and x["mode"]==mode and x["ranges"]==ranges}
            print(mode, ranges, {k:round(r[k]["sqnr_db"],2) for k in ("identity","cluster","interleave")})


if __name__ == "__main__":
    main()
