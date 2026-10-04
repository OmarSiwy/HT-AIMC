# Grouped low-bit weights: quality gate remains open

2026-09-09. **None of the tested W4–W7 formats closes the A8 quality target.** Group-128 second-order weight compensation reduces local calibration error and logit KL, but every scored W4/W5/W6 case and every W7 ideal-A8 case fails the unchanged joint gates, **KL ≤ 0.01 and perplexity ratio ≤ 1.01**. Their potentially cheaper single-bank readout is therefore not an accepted replacement for the two-slice W8 reference.

These are bounded experiments on the available SmolLM2-135M Q8_0 checkpoint. They do not establish that low-bit quantization cannot work on larger models, or reproduce GPTQ's published benchmarks. No chip energy or token rate is measured here.

## Fixed method and independent checks

[Source](../../../../scripts/compiler/metrics/imc_grouped_w4.py) implements the second-order update of [GPTQ, Algorithm 1 and equations (2)–(3)](https://arxiv.org/abs/2210.17323), transposed for the repository's `x @ W` convention. Each output channel has a static symmetric grid per 128 input channels. A natural input order, 128-row update block and diagonal damping of 1% of mean Hessian diagonal are fixed before evaluation. There is no activation-order search, clipping search, learned rounding or held-out hyperparameter selection. Matched round-to-nearest (RTN) uses the same static grids.

Calibration is one 512-token forward on note **27h3**, propagating the already quantized upstream projections. The original weights and current calibration inputs define each local reconstruction target. Q/K/V share their input Hessian; FFN gate/up share theirs. Inputs remain floating point during this weight calibration. All seven projections in all 30 layers are quantized; attention, KV, nonlinearities, norms and the tied embedding/LM head remain floating point.

Evaluation uses separate notes **27a3 / 27d6**, 256 tokens each, against original Q8_0 logits. Those excerpts were new to the preceding smoothing experiment. Subsequent weight formats reuse these W4 evaluation passages as explicit format screens; they are not independent validation. The tokenizer is the existing greedy vocabulary matcher, so these are technical-note stress tests, not a standard language benchmark. Source hashes and frozen codes/scales are recorded in `build/research`.

The upper Cholesky factor of the inverse damped Hessian drives blocked error compensation. A separate direct inverse-elimination oracle agrees exactly, including partial blocks. Independent review checked input widths 1/17/129/257, input and weight group scales spanning six orders of magnitude, zero channels, signed endpoints, and restoration of original-model logits. A diagonal Hessian reduces to RTN. All checks pass; successful experiment execution is distinct from the failed quality gates.

## W4 results

The symmetric code range is **−7…7**, using four stored bits per coefficient. Dynamic block A8 uses one scale per token/input block. Weight group scales multiply their own recovered partials **before** summation; treating them as one output scale would be incorrect.

The artifact is `build/research/imc_grouped_w4.json`: **20 scored cases in 122.00 seconds**, including calibration. Columns below are 27a3 / 27d6.

| Method and path | Mean logit KL | Perplexity ratio |
|---|---:|---:|
| RTN, weights only | 0.48849 / 0.42651 | 1.30522 / 1.41609 |
| GPTQ update, weights only | 0.34020 / 0.32542 | 1.38224 / 1.38903 |
| RTN, ideal A8 | 0.48318 / 0.42786 | 1.30116 / 1.42419 |
| GPTQ update, ideal A8 | 0.34881 / 0.33744 | 1.37858 / 1.40030 |
| GPTQ update, ADC quantization only | 0.36082 / 0.38032 | 1.39054 / 1.48555 |
| GPTQ update, physical hypothesis, seed 21 | 0.37771 / 0.37142 | 1.48214 / 1.41434 |
| GPTQ update, physical hypothesis, seed 22 | 0.39607 / 0.36190 | 1.40935 / 1.41943 |

Mean unweighted local calibration NMSE improves **0.0146154 → 0.00152811**, an **89.5%** reduction. That is fitting error on current quantized-upstream calibration inputs, not a guarantee of independent full-model accuracy. The poorer first-passage perplexity despite improved KL illustrates why the two metrics must remain separate.

Physical cases explicitly use one signed capacitor bank, R128, Cu4 fF, 120-fF fixed column load, seven dynamic activation planes, a 10-bit ADC over 0.5 V, and two independent seeds for 100-µV read noise plus the earlier independent sharing-noise hypothesis. There are **230,031,360 conversions per 256-token passage**, or **898,560 per token**, before checksum and all system omissions. This is half the earlier two-slice W8 service count, but it is not a valid equal-quality saving. All ADC clipping counts are zero.

The GPTQ codes have mean absolute magnitude **1.9272** and median modeled column capacitance **1.068 pF**, versus **0.6631** mean magnitude in the earlier 128×8 W4 circuit fixture. Its measured 4.50-fJ/MAC interface energy cannot be assigned to these more heavily loaded codes. Grouped scale storage also remains: **106,168,320 coefficients and 898,560 scales** across these projections. Storing scales as FP16 would add 0.1354 bits/weight (3.39% above four-bit coefficients), but the experiment uses floating scales and does not validate FP16 scale accuracy or processing energy.

## Symmetric W5 screen

The next fixed format uses **−15…15**, requiring five logical coefficient bits: a sign plus four magnitude bits. One four-capacitor binary magnitude bank can represent it with one conversion. It must not be labeled native W4. The unused two's-complement endpoint −16 is explicitly rejected by the single-bank model because it needs another magnitude bit.

The artifact `build/research/imc_grouped_w5_screen.json` contains **eight scored controls in 48.49 seconds**. It repeats the same calibration algorithm and evaluates weight-only and ideal A8 before spending time on a physical-noise sweep.

| Method and path | Mean logit KL, 27a3 / 27d6 | Perplexity ratio |
|---|---:|---:|
| RTN, weights only | 0.12082 / 0.11709 | 1.09564 / 1.10331 |
| GPTQ update, weights only | 0.08937 / 0.06635 | 1.12852 / 1.07821 |
| RTN, ideal A8 | 0.13200 / 0.12777 | 1.10920 / 1.10823 |
| GPTQ update, ideal A8 | 0.09598 / 0.07587 | 1.12669 / 1.08579 |

All controls fail. No ADC/noise energy point is assigned to this format, and no scale is retuned to these outputs. Keep W8 as the quality reference while pursuing more representative calibration/quantization research; converter improvements cannot repair these failed weight-only baselines.

## Symmetric W6 screen: fewer conversions requires a larger bank

The next fixed precision step uses **−31…31** in one proposed bank with five
magnitude bits plus sign. This changes the capacitor architecture: it cannot
be mapped into the existing four-magnitude-bit bank without splitting it.
The arithmetic model includes its full absolute digit in the column
capacitance and explicitly rejects −32. It does not inherit W4 circuit energy.

The artifact `build/research/imc_grouped_w6_screen.json` contains eight
weight-only/ideal-A8 controls in **46.2 seconds**. All fail the joint gate:

| Method and path | Mean logit KL, 27a3 / 27d6 | Perplexity ratio |
|---|---:|---:|
| RTN, weights only | 0.03195 / 0.02575 | 1.04234 / 1.03643 |
| GPTQ update, weights only | 0.02041 / 0.01618 | 1.03620 / 1.00949 |
| RTN, ideal A8 | 0.04021 / 0.03068 | 1.03763 / 1.03968 |
| GPTQ update, ideal A8 | 0.02687 / 0.02269 | 1.03325 / 0.98994 |

The GPTQ codes' mean absolute magnitude is **8.506**, with median/max modeled
column capacitance **4.312/11.244 pF** at Cu4 fF and R128. Those loads already
exceed the small circuit fixture substantially. The lower second-passage
perplexity does not compensate for its failed logit-KL gate. No ADC/noise
sweep or energy saving is assigned after these failed baseline controls.

## Symmetric W7 screen: input quantization still matters

One further fixed precision step uses **−63…63**, with six magnitude bits in
one proposed capacitor bank. It also requires new hardware. The artifact
`build/research/imc_grouped_w7_screen.json` contains eight controls in
**46.5 seconds**:

| Method and path | Mean logit KL, 27a3 / 27d6 | Perplexity ratio |
|---|---:|---:|
| RTN, weights only | 0.00789 / 0.00681 | 0.99939 / 1.01032 |
| GPTQ update, weights only | 0.00575 / 0.00410 | 1.01128 / 0.99673 |
| RTN, ideal A8 | 0.01627 / 0.01391 | 1.00674 / 1.01387 |
| GPTQ update, ideal A8 | 0.01330 / 0.01091 | 1.01854 / 0.98885 |

Two of four weight-only controls pass, but neither method passes both
passages and all four ideal-A8 controls fail. No ADC noise was injected into
these controls. Weight precision alone does not close input quantization;
there is no accepted one-bank replacement from this format ladder.

The GPTQ mean absolute magnitude is **17.281**, with median/max modeled
column capacitance **8.640/22.676 pF**. Fewer conversions trade against much
heavier switching and settling loads. Their energy requires a new loaded
circuit measurement. Independent arithmetic checks verify exact signed
endpoints, unequal input scales, partial blocks, ADC clipping and conversion
counts for W6/W7, while the default two-bank W8 remains unchanged, including
its −128 endpoint. Subsequent artifacts explicitly identify these reused
evaluation passages as development screens; a selected format would still
need fresh validation.

## Reproduction

Use the repository's Nix Python with NumPy; these runs used the cached Nix Python 3.12.13 environment and one BLAS thread.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_grouped_w4.py --selfcheck
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_grouped_w4.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_grouped_w4.py --weight-bits 5 --screen-only
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_grouped_w4.py --weight-bits 6 --screen-only
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_grouped_w4.py --weight-bits 7 --screen-only
```

The shared [radix kernel](../../../../scripts/compiler/metrics/imc_radix_full_model.py) now has an explicit logical weight-format argument. Its default remains the original two-slice W8 behavior. New checks verify one-bank counts and signed arithmetic; no operational compiler or golden-model numerical behavior changes.
