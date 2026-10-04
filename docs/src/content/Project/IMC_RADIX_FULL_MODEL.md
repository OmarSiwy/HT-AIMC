# Full-model test of the physical radix/readout model

2026-09-07. **The 128-row circuit's high deterministic accuracy does not by itself preserve model quality.** A full-depth experiment maps integer partial sums to actual modeled held voltages, adds readout/sharing errors, quantizes and clips each physical slice, and reconstructs every projection. At 100-µV read noise, the unsmoothed 128-row case increases observed perplexity by 1.35–3.68% over its W8 reference. The follow-up [channel-scaling experiment](IMC_SMOOTH_RADIX.md) addresses this limitation without presuming that higher ADC resolution alone solves it.

## What executes

The [self-checking experiment](../../../../scripts/compiler/metrics/imc_radix_full_model.py) uses all seven weight projections in all 30 layers of SmolLM2-135M. Its reference is per-output RTN INT8 reconstructed from the supplied Q8_0 checkpoint, with floating activations. It is not the original unquantized pretrained model. The reference perplexities on the two 256-token passages are 43.58345 and 60.61687; the earlier [capacitor study](IMC_CAPACITOR_SIZING.md) separately measures this W8 requantization against the original Q8_0 file.

For each input block and output channel:

1. Quantize activations and encode signed magnitude planes. Dynamic bit count is `B=bit_length(max(abs(xq)))`; zero blocks skip conversion.
2. Split W8 magnitude into low/high four-bit digits, retaining the sign on each digit. The low digit can reach ±15. These are **four-bit magnitude slices**, not two copies of the earlier signed-INT4 ±7 fixture.
3. Compute each exact integer partial. Model `Carray=120 fF + Cu*sum(abs(weight_digit))`, `g=Cu*0.45 V/Carray`, and held voltage `h=g*partial/2^B`.
4. Add independent read noise. The optional sharing-noise hypothesis is independent `kT/(2*Carray)` per stage, giving final variance `(kT/(2*Carray))*(1−4^−B)/(1−1/4)`.
5. Apply the actual finite-range uniform quantizer, including saturation, to each held slice. Reconstruct its partial with `2^B/g`, apply the block input scale and output weight scale, and combine the high slice with significance 16.

The model therefore preserves the effects of row count, coefficient population, input range, slice significance and clipping. It does not substitute one arbitrary global output SNR for these operations. Integer matrix products fit exactly within float32's integer range; gain/voltage reconstruction uses float64.

A minimal optional `Net.mvm` hook supplies the experiment without duplicating the transformer implementation. Its default is `None`. Identity-hook execution and restoration reproduce every reference logit exactly. Attention products, KV, normalization, nonlinearities and the final LM head remain floating/digital and unperturbed.

## Input scaling was itself a major error source

The first 64-token screen used a fixed activation scale per tensor, calibrated from a **different** note, `27h3`, for 128 tokens. Tests used `27l1` and `27h1`; no evaluation ranges were fitted. This simple policy failed before adding readout errors: ideal-A8 KL was 1.045/0.623 and perplexity ratios were 1.636/1.285.

Dynamic per-token, per-input-block scaling dramatically improved the same short test: ideal-A8 KL 0.01236/0.01294 and perplexity ratios 1.0277/1.0264. The shorter screen has different statistics from the subsequent 256-token run; a longer run must be reported separately.

This scaling is real architecture work to implement. It needs block maxima, scale metadata, quantization and scale-aware partial combination. Every nonzero block peaks at integer magnitude 127, so it uses **seven magnitude planes**. The earlier physical fixture's average six-plane schedule cannot be reused as its energy measurement. Independent per-block scales must be applied before summing blocks.

## Full 256-token results

The final sweep uses dynamic block A8, two passages, two noise seeds where noise is present, and a **0.5-V, 12-bit modeled ADC**. The ADC specification is hypothetical, not a fabricated converter or a measured 12-ENOB circuit. W8 weight errors are held at zero in this study. All noisier cases include the sharing hypothesis above.

| Configuration | Cases | Mean KL versus W8/float-input reference | Observed perplexity change range | ADC saturation events per forward |
|---|---:|---:|---:|---:|
| R128, ideal A8, no ADC errors | 2 | 0.007602 | +0.549 to +0.760% | — |
| R64, ideal A8, no ADC errors | 2 | 0.003691 | +0.213 to +1.548% | — |
| R128, 4 fF, quantization only | 2 | 0.007712 | +0.433 to +0.959% | 0 |
| R128, 4 fF, 50-µV read noise | 4 | 0.012359 | −0.145 to +2.903% | 0 |
| R128, 4 fF, 100-µV read noise | 4 | 0.016826 | +1.354 to +3.682% | 0 |
| R128, 4 fF, 200-µV read noise | 4 | 0.038473 | +3.543 to +10.766% | 0 |
| R128, 16 fF, 100-µV read noise | 4 | 0.013614 | +1.264 to +4.085% | 2–6 |
| R64, 4 fF, 100-µV read noise | 4 | 0.008359 | +0.294 to +3.263% | 0 |

**None of the noisy configurations passes both KL≤0.01 and observed perplexity increase≤1% in every tested case.** A lower KL can coexist with a larger observed perplexity on a particular passage. KL is not equal to the measured change in log perplexity on those token targets, and a lucky noise draw is not an accuracy improvement to exploit.

The R64 controls matter: reducing row count also improves activation quantization granularity, so its change cannot all be attributed to reduced readout error. Enlarging Cu reduces the assumed thermal noise but approaches a larger passive signal gain as the fixed 120-fF load becomes less significant. That can create clipping; four times the capacitance is not a universal quality improvement.

The preceding 0.25-V/10-bit short screen did saturate, with 445/471 events for the dynamic-block quantization-only case. The later 0.5-V/12-bit run removed those events for the 4-fF cases; substantial read-noise error remained. This is evidence for joint range, normalization and noise optimization.

## Accounting and limitations

The 128-row, two-slice path services 460,062,720 ADC results per 256-token forward across these projections, excluding checksum and other overhead. With dynamic block scaling the equivalent separate-bit count is seven times larger. These are counted logical services, not measured conversions, energy or latency.

The sharing-noise formula is an explicit incomplete hypothesis. It omits initial/reset noise, correlated reference errors, capacitor mismatch and gradients, inaccurate radix ratios, switch nonlinearity and kickback, ADC offset/drift, and extracted interconnect. A normal transient's deterministic PASS does not validate that hypothesis. Hardware costs for resident weights, scaling, ADC/reference generation, digital combine and checksum remain unpriced. The experiment cannot establish 100 or 250 TOPS/W or a token benchmark.

The source includes exact signed-code tests through −128, all-zero skipping, partial final blocks, a saturation negative control and default-path identity/restoration. Independent review also checked conversion counts and the sharing recurrence against 60,000 random draws at each B=1…8. A further independent-block-scale identity is checked by the smoothing experiment.

## Reproduce

Use the existing cached Nix Python/NumPy environment and local GGUF. No dependency or flow changes are required.

```sh
python3 scripts/compiler/metrics/imc_radix_full_model.py --selfcheck
python3 scripts/compiler/metrics/imc_radix_full_model.py --quick
python3 scripts/compiler/metrics/imc_radix_full_model.py --quick --activation-mode dynamic_block
python3 scripts/compiler/metrics/imc_radix_full_model.py --activation-mode dynamic_block --adc-span 0.5 --adc-bits 12
```

The final 26 cases completed in 302.6 seconds. Outputs are separate JSON artifacts under `build/research/imc_radix_full_model_*`; each records source hashes, exact settings, reference perplexities, clipping counts and quality metrics. Earlier exploratory artifact names predate the added span/bit suffix. Quick screens remain screening data rather than deployment benchmarks.
