# SAGE-inspired AnalogIOC tile mapping experiment

Date: 2026-09-07. **Golden-model placement experiment, not SPICE or end-to-end LLM inference.**
No implementation/compiler behavior was changed. Existing `scripts/compiler/out/programming` INT4 weights and `scripts/compiler/out/acts` INT8 inputs are frozen; the first six saved token positions choose the permutation and converter scales, and the last three score it. The original compiler fitted upstream quantization scales on its full nine-token stream, so this is held out only for the new mapping/range decision, not an independently calibrated deployment-quality test.

The experiment is inspired by the SAGE author abstract, which describes input-channel grouping to improve analog robustness. It does not claim to reproduce the unavailable full algorithm. [Primary author description](https://zhenyu001225.github.io/), [paper DOI](https://doi.org/10.1109/ICCAD66269.2025.11240907).

## Exact operation and controls

For a fixed permutation P, `x'=Px`, `W'=WP^T` leaves the complete MVM unchanged. It changes which products enter each 16-row tile before rounding/clipping. Saliency is `max_cal(abs(x_i))*rms_j(Wq_ji)`. `cluster` places descending saliency together; `interleave` spreads adjacent ranks across different row tiles. Five seeded random permutations provide controls. All permutations are fixed before examining test outputs.

`tensor` uses the existing one-D-per-tensor policy refitted on calibration partials. `row_tile` fits one D per 16-input group across all output columns. Every D uses the golden `max(1,ceil(4*std/120))` law. The latter needs independently configurable analog scales and multiplication/alignment before accumulation; it is proposed hardware support, not a capability of the shipped fixed-D rail. Each comparison holds weight bits, activation bits, output ADC bits, physical tile passes and scalar ADC event counts constant.

Both the baseline two-nibble path (golden event converter plus saturating nibble combine) and the merged-window path are shown. Compare strategies **within** one path: merged has half the scalar ADC events and is not a matched-conversion comparison against nibble. Outputs are scored before final requantization against exact integer MAC, dequantized with the stored per-output `dw*dx`. No analog mismatch/read noise is invented. Metrics measure the marginal ideal-converter error, not the full FP32 model error.

All ADC counts are **data-column** events. Checksum columns and ABFT checking are excluded. A deployed permutation must regenerate/reorder the checksum programming consistently, and its static activation wiring/permutation network costs area, delay and energy even when tile and ADC event counts are unchanged.

## Held-out results

Higher SQNR is better. Random is median SQNR over five fixed seeds, not a selected winner. All values are dB. A changed kurtosis alone is not an accuracy or energy win.

### nibble, tensor D

| Tensor | Identity | Cluster | Interleave | Random median | Cluster Δ |
|---|---:|---:|---:|---:|---:|
| attn_q | 35.60 | 27.47 | 36.46 | 35.62 | -8.12 |
| attn_k | 45.65 | 31.60 | 50.32 | 43.16 | -14.06 |
| attn_v | 19.46 | 22.52 | 19.40 | 20.04 | +3.06 |
| attn_o | 28.98 | 29.30 | 28.87 | 28.80 | +0.32 |
| ffn_gate | 20.33 | 20.60 | 21.12 | 20.64 | +0.27 |
| ffn_up | 19.66 | 19.79 | 19.65 | 19.73 | +0.12 |
| ffn_down | 44.28 | 33.16 | 51.13 | 46.38 | -11.12 |

### nibble, row_tile D

| Tensor | Identity | Cluster | Interleave | Random median | Cluster Δ |
|---|---:|---:|---:|---:|---:|
| attn_q | 29.25 | 26.45 | 29.31 | 29.95 | -2.80 |
| attn_k | 32.10 | 30.32 | 33.46 | 30.44 | -1.78 |
| attn_v | 20.96 | 23.24 | 20.47 | 21.01 | +2.28 |
| attn_o | 28.73 | 31.40 | 28.87 | 28.89 | +2.67 |
| ffn_gate | 20.33 | 20.60 | 21.12 | 20.64 | +0.27 |
| ffn_up | 19.66 | 19.79 | 19.65 | 19.73 | +0.12 |
| ffn_down | 44.28 | 35.67 | 51.13 | 46.38 | -8.61 |

### merged, tensor D

| Tensor | Identity | Cluster | Interleave | Random median | Cluster Δ |
|---|---:|---:|---:|---:|---:|
| attn_q | 15.75 | 9.07 | 15.41 | 15.36 | -6.68 |
| attn_k | 16.86 | 9.55 | 16.99 | 16.76 | -7.31 |
| attn_v | 26.91 | 17.06 | 23.48 | 33.67 | -9.86 |
| attn_o | 40.52 | 34.51 | 40.80 | 40.93 | -6.01 |
| ffn_gate | 29.30 | 18.08 | 31.05 | 30.41 | -11.22 |
| ffn_up | 26.36 | 16.61 | 27.61 | 26.65 | -9.75 |
| ffn_down | 15.79 | 14.15 | 15.38 | 16.22 | -1.64 |

### merged, row_tile D

| Tensor | Identity | Cluster | Interleave | Random median | Cluster Δ |
|---|---:|---:|---:|---:|---:|
| attn_q | 37.71 | 42.53 | 36.63 | 38.82 | +4.83 |
| attn_k | 39.04 | 42.09 | 39.88 | 40.39 | +3.05 |
| attn_v | 40.62 | 41.57 | 24.38 | 39.80 | +0.95 |
| attn_o | 40.60 | 41.22 | 40.07 | 40.80 | +0.62 |
| ffn_gate | 36.54 | 36.88 | 36.83 | 36.43 | +0.34 |
| ffn_up | 34.22 | 35.29 | 34.76 | 34.90 | +1.07 |
| ffn_down | 16.51 | 24.31 | 15.42 | 17.44 | +7.80 |

## Event-count, scale and clipping detail

Shown for FFN-down, a predeclared tensor of interest (this saved file is layer 0, not the sensitive layer 11 from DEPTH_BUDGET). Comparator evaluation averages are golden counts; they are not measured energy or variable-duration hardware completion.

| Path | D policy | Mapping | D range | Clip % | Mean coarse evaluations | Data ADC events/test token |
|---|---|---|---|---:|---:|---:|
| nibble | tensor | identity | 1–1 | 0.0274 | 1.349 | 110592 |
| nibble | row_tile | identity | 1–1 | 0.0274 | 1.349 | 110592 |
| merged | tensor | identity | 3–3 | 0.3056 | 1.314 | 55296 |
| merged | row_tile | identity | 1–7 | 0.3587 | 1.519 | 55296 |
| nibble | tensor | cluster | 1–1 | 0.0889 | 1.339 | 110592 |
| nibble | row_tile | cluster | 1–2 | 0.0344 | 1.329 | 110592 |
| merged | tensor | cluster | 3–3 | 0.3231 | 1.307 | 55296 |
| merged | row_tile | cluster | 1–14 | 0.5178 | 1.773 | 55296 |
| nibble | tensor | interleave | 1–1 | 0.0169 | 1.353 | 110592 |
| nibble | row_tile | interleave | 1–1 | 0.0169 | 1.353 | 110592 |
| merged | tensor | interleave | 3–3 | 0.2948 | 1.319 | 55296 |
| merged | row_tile | interleave | 2–7 | 0.5076 | 1.515 | 55296 |

## Interpretation and next gate

Two predeclared mappings have opposite behavior depending on the physical range policy. For layer-0 FFN-down in the nibble/tensor-D path, interleaving raises held-out ideal-converter SQNR from 44.28 to 51.13 dB (+6.85 dB), while clustering yields 33.16 dB. The data ADC counts are unchanged. For the merged/row-tile-D path, clustering changes FFN-down from 16.51 to 24.31 dB (+7.80 dB), with the same data ADC count but additional range support and more coarse evaluations. The useful candidate is grouping co-designed with range granularity; a universal clustering rule is falsified here.

This experiment can falsify a simple training-free grouping recipe or identify a placement candidate worth testing. It cannot establish a token/J or token/s gain: no physical ADC, range-switching energy, activation permutation fabric, mismatch redistribution, or full-model quality is measured. It does not select a per-tensor winner from held-out results. A follow-up needs independent raw calibration/evaluation corpora, full-model activations, actual calibrated physical residuals and independently programmable tile ranges.

Checks: permutation bijections; exact integer MVM invariant; float MVM invariant; matched ADC and tile-pass counts within each path; positive integer scales. **PASS**.

Reproduce: `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_mapping_experiment.py` inside the repository NumPy environment. Full scales, permutations, errors and event counts: `build/research/imc_mapping/results.json`; source fingerprints and split: `build/research/imc_mapping/inputs.json` (generated artifacts).
