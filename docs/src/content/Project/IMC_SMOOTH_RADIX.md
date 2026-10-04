# Frozen channel smoothing with physical radix readout

**Calibration-only noise-aware smoothing improved joint acceptance on reused validation passages, but failed the fresh-note check.** Frozen per-MVM alpha choices at **4-fF units / 100-µV read noise** pass **3/4 physical cases** on two new 512-token passages; the ideal A8 controls pass **1/2**. Every KL passes, but two cases exceed the unchanged **PPL ratio ≤ 1.01** gate. This grid is stopped without changing its choices. It supplies a useful candidate, not a converged chip or a validated readout-noise requirement.

The initial uniform-alpha tests and failed smaller-capacitor/noise variants remain below. A subsequent A9 replay makes both ideal input-quantization controls pass, but the ten-bit ADC and noisy paths still fail the joint gate; its extra bit plane is counted. All physical evaluations have zero ADC clipping. Every energy implication is conditional: these results are behavioral, with no measured TOPS/W or token performance.

Source: [imc_smooth_radix.py](../../../../scripts/compiler/metrics/imc_smooth_radix.py). Artifact: `build/research/imc_smooth_radix.json` (16 scored cases, 20 full-model forwards, **33.85 seconds** on one CPU thread). The script imports [radix_mvm](../../../../scripts/compiler/metrics/imc_radix_full_model.py), preserving its actual column-capacitance normalization.

The 256-token extension is `build/research/imc_smooth_radix_validation.json`: **12 scored cases, 16 forwards, 116.97 seconds**. Run the script from the repository root with a Nix Python containing NumPy:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --selfcheck
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --validate
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --validate --read-noise 50
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --optimize
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --fresh-holdout
```

## Method and controls

The starting identity is `xW = (x/s)(diag(s)W)`. Frozen input-channel scales use `s_j = max_cal|x_j|^alpha / max|W_j,:|^(1-alpha)`, with positive floors for zero channels. This is the transformation in [SmoothQuant, equations (3)–(4)](https://arxiv.org/html/2211.10438v5). The existing compiler already uses alpha 0.5 smoothing; this experiment tests its interaction with the new full-depth radix model rather than claiming a new method or reproduction of the paper's benchmark. Here **alpha 0 denotes the unsmoothed identity control**, not the paper's formula evaluated at zero.

Calibration is the first 128 greedily tokenized tokens of note **27h3**, run through the original Q8_0 model with floating activations. Each of all seven weight MVMs in all 30 layers records a channel maximum. The scales then remain frozen. Evaluation uses separate notes **27l1 / 27h1**, 128 tokens each; no evaluation values fit the scales or choose the physical follow-up's alpha. Source hashes are recorded in the artifact. Alpha **0.5** was selected for that follow-up before evaluation; alpha **0.75** is a diagnostic control.

Each scaled matrix is requantized to symmetric INT8 using one scale per output channel. The weight-only control applies exact floating input rescaling with these quantized weights. The ideal A8 control additionally quantizes each token's groups of 128 input channels to `[-127,127]`, using that group's current maximum. Runtime block scales multiply partial outputs **before** summing input blocks. This runtime quantizer is a capability that hardware must implement, not a frozen calibration table.

Every result is measured against **the original GGUF Q8_0 model with floating activations**, before the additional weight requantization. This differs from the earlier radix experiment's requantized-W8 reference. Neither reference is the original unquantized pretrained model. Attention matmuls, KV, nonlinearities, norms and the LM head remain floating point. The greedy tokenizer and technical-note excerpts do not constitute a standard language-model benchmark.

## Results

Columns are passage 27l1 / passage 27h1. Perplexity ratios use observed next tokens; they are not `exp(KL)` and can improve by chance on a short passage.

| Alpha | Path | Mean logit KL | PPL ratio |
|---|---|---:|---:|
| 0, identity | Weight only | 0.003503 / 0.003316 | 0.99209 / 0.99751 |
| 0, identity | Ideal A8 | 0.012882 / 0.014487 | 1.00581 / 1.00990 |
| 0.5 | Weight only | 0.002942 / 0.002801 | 0.98688 / 1.00434 |
| 0.5 | Ideal A8 | 0.004752 / 0.004649 | 0.97936 / 1.00539 |
| 0.5 | Radix + ADC quantization only | 0.007299 / 0.006760 | 0.98330 / 1.02037 |
| 0.5 | Radix + ADC + read/sharing noise | 0.009488 / 0.009122 | 0.99813 / 1.00583 |
| 0.75 | Weight only | 0.012662 / 0.016116 | 0.99728 / 1.01064 |
| 0.75 | Ideal A8 | 0.014694 / 0.017184 | 1.00624 / 1.01317 |

Alpha 0.5 reduces the ideal A8 KL by **2.71× / 3.12×** relative to identity scaling. Alpha 0.75 already loses quality in the weight-only control: moving more input range into weights is not monotonically beneficial. The 100-µV case passes the provisional **0.01 KL** screening threshold on both passages, but it has only one noise seed. Its lower second-passage PPL than the quantization-only case is a stochastic/sample effect, not evidence that noise helps inference. The quantization-only second passage exceeds a +1% PPL gate. This experiment therefore does not establish reliable simultaneous KL and PPL acceptance across data and seeds.

### Fixed-alpha extension: 256 tokens, two noise seeds

Alpha remains **0.5**, with the same separate 128-token calibration, and the original Q8_0 reference. The evaluation passages extend the same excerpts to 256 tokens; their first halves overlap the initial test, so this is a length/seed check rather than a fresh independent dataset. The gates **KL ≤ 0.01 and PPL ratio ≤ 1.01** were declared before this extension. No scale or alpha was fitted to its outputs.

| Path | Unit C | Seed | KL, 27l1 / 27h1 | PPL ratio, 27l1 / 27h1 | Joint pass, 27l1 / 27h1 |
|---|---:|---:|---:|---:|---|
| Ideal A8 | — | — | 0.003937 / 0.003865 | 0.99210 / 0.99940 | Yes / Yes |
| ADC quantization only | 4 fF | — | 0.005538 / 0.005917 | 0.99518 / 1.00822 | Yes / Yes |
| ADC + read100 + sharing | 4 fF | 21 | 0.008029 / 0.007606 | 1.00424 / **1.010016** | Yes / **No** |
| ADC + read100 + sharing | 4 fF | 22 | 0.007294 / 0.007671 | 1.00588 / **1.02291** | Yes / **No** |
| ADC + read100 + sharing | 1.2 fF | 21 | **0.015847 / 0.015134** | 1.01606 / 1.00459 | No / No |
| ADC + read100 + sharing | 1.2 fF | 22 | **0.014108 / 0.016817** | 1.01171 / 1.04034 | No / No |

The 1.010016 PPL ratio is a strict failure even though it is very close to the threshold. Cu=4 fF passes all four KL gates but fails two PPL gates. Cu=1.2 fF fails all four KL gates; its smaller capacitors do not preserve quality at this readout point. There is no separate Cu=1.2-fF quantization-only control in this bounded extension, so that comparison includes changed quantization gain and sharing noise together. No fixed capacitor mismatch was added: this does not establish its tolerance.

The requested **Cu=4 fF / 50-µV** follow-up holds all other settings fixed. Its artifact is `build/research/imc_smooth_radix_validation_read50.json`, **four scored cases in 53.44 seconds**, including recomputed calibration/references. The same gates remain in force:

| Seed | KL, 27l1 / 27h1 | PPL ratio, 27l1 / 27h1 | Joint pass, 27l1 / 27h1 |
|---|---:|---:|---|
| 21 | 0.007191 / 0.006420 | 1.00864 / 1.00589 | Yes / Yes |
| 22 | 0.006914 / 0.006526 | 1.00981 / **1.01688** | Yes / **No** |

All four KL values pass and ADC clipping remains zero, but **one PPL case fails**. Reducing read noise alone has not yet established the joint requirement. This model still includes independent sharing noise and deterministic ADC quantization; there is no basis for assigning the remaining failure exclusively to the comparator or extrapolating a universal sufficient µV limit from these few seeds.

## Physical readout and cost implications

The physical cases use **128 rows, 4-fF units, two signed weight-magnitude slices, and separate 10-bit conversions over a 0.5-V total span**. The ADC covers approximately −0.25 to +0.2495 V with a **488.3-µV step**. Quantization is explicit, including clipping; it is not replaced by white noise. The noisy case adds independent **100-µV RMS final read noise** plus the radix model's independent `kT/(2*C)` sharing error at each stage, propagated through successive halvings at **27 °C**. Reset/reference correlation, fixed weight mismatch, gain/ratio calibration error, kickback and actual converter thermal noise are omitted.

For each weight slice, the model recomputes `C_array = 120 fF + 4 fF*sum|digit|` and `gain = 4 fF*0.45 V/C_array` from the **rescaled, requantized physical codes**. Smoothing is not assumed to improve voltage for free. Across all matrices and layers, the resulting distributions are:

| Alpha | Mean absolute low / high digit | Median low / high column C | 95th-percentile low / high C |
|---|---:|---:|---:|
| 0, identity | 7.077 / 1.316 | 3.696 / 0.772 pF | 4.076 / 1.016 pF |
| 0.5 | 6.935 / 1.053 | 3.628 / 0.612 pF | 4.032 / 0.948 pF |
| 0.75 | 6.610 / 0.785 | 3.496 / 0.456 pF | 3.980 / 0.880 pF |

Digit means weight every stored weight equally; capacitance percentiles weight each physical input-block/output column equally, including partial blocks. They are analytical circuit parameters, not extracted parasitics. The low W8 slice's roughly 3.6-pF median is substantially larger than the earlier W4 fixture and the illustrative 0.5–1-pF readout load. Its row/reference switching and settling must be simulated before assigning energy. The [100/250-TOPS/W budget](IMC_CIRCUIT_TARGETS.md#7-readout-under-100250-topsw-targets) remains an optimistic **W4A8** allocation; this experiment cannot transfer it to W8A8.

At Cu=1.2 fF the same fixed codes instead have median low/high C of **1.1724 / 0.2676 pF**. Because the model keeps 120 fF of fixed capacitance, their gains are approximately **7.2% / 31.4% lower** than at Cu=4 fF; smaller C also raises sharing noise. The actual code-specific capacitance and gain enter every readout, so the extension does not assume a free 3.33× energy improvement from shrinking units. Driver, clock, reference, readout and scaling energy remain unmeasured.

There are **230,031,360 final conversions per passage**, or **1,797,120 per token**, representing both weight slices. The equivalent separate-bit count is exactly seven times larger because dynamic block scaling puts a nonzero peak at magnitude code 127. Thus this quantizer largely removes leading-zero-plane savings while retaining final-only radix conversion. None of those counts supplies ADC energy, input quantizer energy, or a chip service rate.

The independent per-matrix channel scales also need a concrete implementation. Q/K/V and gate/up share original inputs but may receive different scales here; folding every scale into one preceding normalization is not automatic. Existing compiler wrappers can represent separate scales, but their arithmetic, storage and fanout costs still require accounting. Shared-scale constraints or explicit branch scaling are implementation choices to compare after establishing quality.

## Verification and next decision

Self-checks cover the exact diagonal identity before quantization, zero input/weight channels, unequal block scales, partial blocks, full signed radix arithmetic including −128, and unchanged original-model logits after removing the hook. On real calibration samples, maximum relative prequantization identity error was **7.08e−16**. Checks print PASS; no SPICE or simulator settings changed.

Retain alpha 0.5 as a candidate, but keep the failed 50/100-µV joint gates visible. Validate with independent text and more noise seeds before adopting any readout allowance. Then replay the actual two-slice W8 codes and dynamic A8 blocks through the circuit, including the larger low-slice capacitance and all input/readout supplies. This quality improvement supplies a workload for that test; it does not yet demonstrate faster or more efficient silicon. The script's PASS message verifies arithmetic and successful execution; per-case `joint_pass` fields determine quality acceptance.

### Implemented calibration-only alpha selection

The fixed refinement grid is **0.25 / 0.5 / 0.75**, chosen before its evaluation. `--optimize` captures all 128 calibration inputs for every MVM from the original Q8_0 forward on **27h3**. For each candidate it applies weight quantization, dynamic block A8, actual two-slice capacitor normalization, explicit ADC rounding/clipping, **100-µV read noise and sharing noise**, at R128/Cu4 fF/0.5 V/10 bits. It selects the lowest mean output MSE against the original calibration `xW` across two common random draws, **1001 / 1002**, keyed by layer and tensor. Thus candidates see paired noise realizations without reusing evaluation seeds. ADC threshold crossings are simulated directly; no additive quantization-noise approximation enters the objective. All **210 choices freeze before evaluation**, and only one grid is run.

The artifact `build/research/imc_smooth_radix_optimized.json` contains every candidate's two draw MSEs, normalized MSE, clipping count, chosen alpha and class histogram. The complete selection and six scored evaluations take **95.46 seconds**. Mean per-MVM normalized calibration MSE falls from **2.4040e−4** for uniform 0.5 to **1.9921e−4**, a **17.1%** reduction. This is an unweighted mean across MVMs, normalized by each original calibration output's mean square; raw errors in different tensor units are not pooled. It measures fitting on those two calibration draws, not independent expected error.

| MVM class | Alpha 0.25 | Alpha 0.5 | Alpha 0.75 |
|---|---:|---:|---:|
| Attention Q | 0 | 2 | 28 |
| Attention K | 0 | 1 | 29 |
| Attention V | 0 | 3 | 27 |
| Attention output | 0 | 7 | 23 |
| FFN gate | 0 | 5 | 25 |
| FFN up | 0 | 1 | 29 |
| FFN down | 0 | 28 | 2 |
| Total | 0 | 47 | 163 |

Three MVMs have different winners if each noise draw is scored individually; four have less than 1% separation between the two best mean scores. Two draws limit confidence in near-tied choices. The strong FFN-down preference for 0.5 also explains why a universal move toward 0.75 is inappropriate. No second grid or post-evaluation choice adjustment is performed.

The first evaluation uses the **previously reused** 256-token passages 27l1/27h1, original Q8_0 references, and unchanged gates:

| Path | Seed | KL, 27l1 / 27h1 | PPL ratio, 27l1 / 27h1 | Joint pass |
|---|---:|---:|---:|---|
| Ideal A8 | — | 0.005094 / 0.005107 | 0.99898 / 0.98980 | 2/2 |
| ADC + read100 + sharing | 21 | 0.008054 / 0.008322 | 0.99565 / 1.00506 | 2/2 |
| ADC + read100 + sharing | 22 | 0.008316 / 0.009100 | 1.00812 / 1.00698 | 2/2 |

All four physical cases pass jointly, compared with **2/4** for uniform 0.5 at the identical hardware settings. However, their KL values are slightly worse than uniform 0.5. This is improved joint acceptance on reused validation passages, not uniformly better logits or proof of a sufficient readout budget. Every candidate/evaluation conversion has zero clipping. Median modeled low/high slice C becomes **3.580 / 0.524 pF**, with mean absolute digits **6.816 / 0.893**; circuit energy remains unmeasured.

Local calibration MSE is not a guarantee of full-model KL/PPL. Calibration inputs come from the original model and can shift under upstream quantization. These reused passages have also informed the broader research sequence even though the selector itself never fits their outputs. Shared-input branches still need common-scale constraints or separately priced scaling. Noise-aware rescaling is already the subject of [NORA's first-party research description](https://research.ibm.com/publications/nora-noise-optimized-rescaling-of-llms-on-analog-compute-in-memory-accelerators). This is an independently specified experiment, not a reproduction of NORA's optimizer or a claim to improve upon its published results.

### Fresh-note test of the frozen choices: failure retained

The final check uses notes **27g3 / 27h5**, **512 tokens each**, which were not used in calibration or the earlier evaluations. The 210 alpha choices remain those already recorded in `imc_smooth_radix_optimized.json`; no grid is rerun. Because that first artifact did not store the scale vectors, their first freeze replays the same hash-verified original calibration solely to reconstruct them. The complete code/capacitance summary must exactly match the previous selected run before any physical evaluation. All 210 vectors are then stored in `build/research/imc_smooth_radix_frozen.npz`; subsequent `--fresh-holdout` runs load them directly. The output records hashes for both the frozen scale file and the original choice artifact.

The artifact is `build/research/imc_smooth_radix_fresh_holdout.json`, **six scored cases in 121.60 seconds**, with original Q8_0 references, unchanged Cu4 fF/R128/10-bit/0.5-V/read100/sharing settings and evaluation seeds 21/22:

| Path | Seed | KL, 27g3 / 27h5 | PPL ratio, 27g3 / 27h5 | Joint pass, 27g3 / 27h5 |
|---|---:|---:|---:|---|
| Ideal A8 | — | 0.005279 / 0.005437 | 1.00070 / **1.010741** | Yes / **No** |
| ADC + read100 + sharing | 21 | 0.009222 / 0.008585 | 0.99549 / 1.00716 | Yes / Yes |
| ADC + read100 + sharing | 22 | 0.009005 / 0.008348 | 1.00518 / **1.020095** | Yes / **No** |

The fresh physical pass rate is **3/4**, and the ideal A8 control already fails once. A noisy result passing where the control fails is not evidence that hardware noise is helpful. In particular, the control failure means improving ADC noise alone cannot establish the required baseline quantization quality. These failures remain in the artifact and report; no alpha choice is changed, no lucky seed is selected, and this grid stops here. More diverse data would still be necessary even if all six cases had passed.


### A9 replay: input precision improves, full conversion still fails

The next bounded change keeps the same W8 codes and the 210 previously
frozen A8-selected channel scales, and adds one activation magnitude plane.
The stored scale/choice hashes and complete weight-capacitance summaries
match the earlier run exactly. Notes 27g3/27h5 are now **exposed development
passages**, not new holdouts. No scale, alpha, weight or acceptance threshold
was fitted to these replay outputs.

| Path | Seed | KL, 27g3 / 27h5 | PPL ratio | Joint pass |
|---|---:|---:|---:|---|
| Ideal A9, no ADC | — | 0.004413 / 0.004541 | 1.001831 / 1.007059 | yes / yes |
| Ten-bit ADC, no read/sharing noise | — | 0.006136 / 0.005839 | 1.001900 / 1.013562 | yes / no |
| ADC + read100 + sharing | 21 | 0.007474 / 0.007827 | 1.003798 / 1.008273 | yes / yes |
| ADC + read100 + sharing | 22 | 0.007634 / 0.007874 | 1.011390 / 1.012928 | no / no |
| ADC + read50 + sharing | 21 | 0.006856 / 0.007095 | 1.001406 / 1.007341 | yes / yes |
| ADC + read50 + sharing | 22 | 0.007056 / 0.007043 | 1.004259 / 1.015800 | yes / no |

A9 closes these two ideal input-quantization controls. The separately run
ADC-only control exposes a remaining deterministic conversion error; reducing
read noise alone cannot guarantee the quality target. Physical pass counts
are **2/4 at 100 µV and 3/4 at 50 µV**. Noise sometimes moving a failing
quantized output across a threshold is not a benefit to assume in hardware.
These exact threshold and full-depth effects are why the simulation uses
explicit quantization rather than replacing it with additive white noise.

Every physical 512-token case still counts **920,125,440 final ADC services**
(two weight slices). The corresponding separate-plane count increases from
**6,440,878,080 to 7,361,003,520**, exactly **seven to eight planes per
service**, or **14.29% more plane operations**. This is a count, not a measured
14.29% change in whole-chip power: reset, acquisition and readout costs differ
from per-plane work. The existing A8 circuit timing/energy cannot be assigned
to A9. Input storage, transport and the digital interface also need nine bits.

Artifacts are `imc_smooth_radix_a9_frozen_replay.json` (120.54 s) and
`imc_smooth_radix_a9_frozen_replay_read50.json` (140.40 s), under
`build/research`. They preserve all failed cases. The second run adds ADC-only
controls and four 50-µV cases; it does not repeat the ideal A9 controls. Cached
Nix Python/NumPy and one BLAS thread were used alongside functional circuit
work, so these runtimes are not controlled speed benchmarks.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --fresh-holdout --activation-bits 9
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --fresh-holdout --activation-bits 9 --read-noise 50
```

The legacy `--fresh-holdout` flag selects the stored state and passage pair;
the A9 artifact explicitly labels the replay as exposed-data development.
Default A8 arithmetic is unchanged. Self-checks independently verify ±255
endpoints without int8 overflow, zero rows, unequal group scales, partial
blocks, exact recovered products and the extra plane count. This refinement
narrows the input/converter precision question; it supplies neither a
validated ADC-noise allowance nor a cheaper accepted chip configuration.

### Fixed R256/A9/ADC11 architecture screen

The next preselected configuration doubles physical reduction rows to 256,
retains A9, and uses an eleven-bit ADC with 50-µV read noise. It reuses the
exact frozen W8 codes and R128/A8-selected channel scales; block activation
scales now cover 256 inputs. The same exposed notes and both fixed seeds are
replayed. No scale or acceptance threshold is fitted to these results.

| Path | Seed | KL, 27g3 / 27h5 | PPL ratio | Joint pass |
|---|---:|---:|---:|---|
| Ideal A9, no ADC | — | 0.004647 / 0.004685 | 1.001630 / 1.009449 | yes / yes |
| Eleven-bit ADC, no read/sharing noise | — | 0.005923 / 0.005640 | 1.001382 / 1.007413 | yes / yes |
| ADC + read50 + sharing | 21 | 0.006842 / 0.006729 | 1.009221 / 1.007144 | yes / yes |
| ADC + read50 + sharing | 22 | 0.007511 / 0.007103 | 1.002987 / **1.017448** | yes / **no** |

Both deterministic controls improve to passing the joint gate, but the
noisy set still passes only **3/4**. This configuration is not accepted as a
complete quality solution. It changes row grouping and ADC precision
together, so the control improvement is not attributed solely to one knob.

Final services per 512 tokens fall from **920,125,440 to 530,841,600**, a
**42.31% reduction** after counting actual partial blocks, rather than
assuming a factor of two. A9 separate-plane counts fall from 7,361,003,520 to
**4,246,732,800**. These are service counts, not measured energy or latency
savings: each new ADC has eleven bits and the larger reduction changes
loading and signal normalization. Median modeled low/high weight-slice
capacitance grows from **3.580/0.524 pF to 6.980/0.828 pF** at Cu4 fF;
maximums become **8.740/2.872 pF**. Neither the current 128-row array nor the
768-fF ten-bit converter measures this proposed interface.

The artifact `build/research/imc_smooth_radix_r256_a9_b11_read50.json` records
all eight results, larger capacitance distributions and the unchanged frozen
state hashes. Runtime was **211.39 s** with one BLAS thread alongside
functional circuit work. Subsequent A9 replays additionally enforce the
original A8 holdout's frozen-scale file hash before loading, and record an
exact ordered weight-code hash for each alpha profile. The completed result predates that extra
metadata check; its scale/choice hashes and full R128 weight-code summaries
were independently checked unchanged after execution.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_smooth_radix.py --fresh-holdout --activation-bits 9 --read-noise 50 --architecture-screen
```

This fixed profile preserves the R128/A8 defaults. Partial-block arithmetic,
unequal input scales, signed nine-bit endpoints and exact service/plane
counts pass the expanded self-check. Broader data and combined physical
error families remain necessary even for a configuration that passes all
these short development cases.
