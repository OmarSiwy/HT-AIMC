# Fixed MIM mismatch: coefficient-error audit

**VERIFIED arithmetic under the installed PDK variation model; not silicon yield
or complete IMC quality.** A fixed-per-weight error persists across inputs and
must not be redrawn independently every MVM.

The installed `sky130_fd_pr__cap_mim_m3_1.model.spice` defines independent Gaussian
relative capacitor mismatch as `0.028/sqrt(wc*lc*mf)`, enabled by `MC_MM_SWITCH`.
The [audit](../../../../../scripts/compiler/metrics/imc_fixed_cap_mismatch.py) fingerprints the exact
local PDK source. For square mf=1 TT devices, the used electrical relation is
`C[fF]=2u²+0.76u`, with `u=w−0.025µm`. This gives:

| Nominal C, fF | Drawn square side, µm | Relative one-sigma mismatch |
|---:|---:|---:|
| 4 | 1.26192 | 2.26369% |
| 8 | 1.84400 | 1.53930% |
| 16 | 2.66980 | 1.05868% |
| 32 | 3.83951 | .73404% |

These are model coefficients for the assumed geometry, not measured wafer
statistics. Common process shifts, spatial correlation, gradients, voltage and
temperature dependence require separate evidence.

For magnitude digit d formed from selected binary capacitors C_b, coefficient
variance in Cu units is

\[
V_d=\sum_b bit_b(d)(C_b\sigma_b/C_u)^2.
\]

For independent low/high banks and exact representation `q=L+RH`, weight-error
variance is `V_q=V_L+R²V_H`. The actual106,168,320-weight histogram produces:

| Representation | RMS weight error, integer weight units | White-activation error SNR |
|---|---:|---:|
| Original signed radix16 | .33723 | 38.57dB |
| Balanced radix9 | .29913 | 39.61dB |
| Signed radix8 | .26021 | 40.82dB |
| Saturated balanced radix8 | .28139 | 40.14dB |

SNR uses the measured weight-histogram RMS28.5924 and independent white input
statistics. It is not the model's actual activation-weight covariance or a
quality guarantee. The radix8 rows cover the observed symmetric−127…127 support;
full signed−128 requires an explicit extra code/representation.

The [saved numerical audit](../../../../../build/campaign/fixed_cap_mismatch/coefficient_sensitivity.json)
uses512 independent columns of256 fixed random weights drawn from that histogram.
Each physical binary capacitor gets one independent Gaussian error, reused for
every input. Repeated identical MVMs return identical errors. The heterogeneous
Gaussian variance check has predeclared `|z|<6`; all four cases have `|z|<1.92`.
An optimistic exact per-column multiplicative gain calibration removes little
of the random coefficient error: original RMS.33508→.33303 and signed8
.25903→.25765 in that realization. Exact weight-vector calibration is an upper
bound on correction, not an implemented calibration circuit.

This audit deliberately excludes holder/array ratio mismatch, ADC bit-cap
mismatch, reference and driver variation, bypass internal states, parasitic
mismatch, and finite settling. Holder mismatch changes the activation radix and
can make the error depend on bit position; it cannot generally be absorbed into
one fixed effective weight. The next full-depth model should retain one fixed
physical realization per die across both passages and all MVM calls, with
nominal calibration controls and separately priced calibration options.

## Preserved partial mechanism: exact carry choice using measured mismatch

For most weights in−127…127, two exact radix8 codes satisfy `q=L+8H`, `|L|≤7`,
`|H|≤15`. The alternative code changes which existing binary capacitors are
selected and may reverse one digit's sign. Given a measured fixed capacitor
realization, choose the legal code with smaller absolute physical coefficient
error. Both candidates must use the **same** capacitor errors.

The [same-cap oracle test](../../../../../scripts/compiler/metrics/imc_redundant_weight_calibration.py)
verifies exact reconstruction and that perfect-error knowledge never worsens an
individual coefficient relative to ordinary signed8. In131,072 sampled weights,
RMS error falls.26086→.21361, an18.1% reduction. Adding0.5% RMS relative measurement
error per physical capacitor still yields.22225 RMS, a14.8% reduction;2% measurement
error nearly removes the benefit. These errors are fixed measurements used for
both candidate codes, not independent favorable redraws.

The benefit is not free. About30.1% of codes change; mean active magnitude units
rise5.5823→5.9363. Applying the measured programming C(code) increases mean
loading37.034→38.288fF/weight and the equal-scale thermal coefficient1085.0→1153.7,
about6.33%. Per-weight choice information must be retained, potentially an extra
bit beyond the8-bit logical weight, or encoded in a correspondingly larger
physical state space. Independently controllable digit signs and the calibration
read/scheduling/energy must be paid. No full-model or physical net advantage has
been demonstrated. Evidence is saved in
[result](../../../../../build/campaign/redundant_weight_calibration/result.json) and
[loading budget](../../../../../build/campaign/redundant_weight_calibration/oracle_loading_budget.json).

For scale, a4-fF selected capacitor driven through0.45V onto2.4pF produces only
0.75mV. Resolving0.5% of that signal requires about3.75µV standard error. Even
an independent20µV read-noise floor requires roughly29 averages before reset,
reference and drift terms; this is an illustrative measurement budget, not an
implemented calibration. Shared row/column parallelism may amortize wall time,
but cannot erase those measurements or their energy.

Prior-art search already finds related mechanisms. The Duke ISCAS2025 study
compares mismatch-induced inference degradation in C2C, binary-weighted and split
capacitive CIM structures; its abstract warns that simple-task robustness does
not predict harder-model robustness. [Primary institutional record](https://scholars.duke.edu/publication/1682294).
A separate ISCAS2025 work uses intentional CDAC mismatch and redundancy to gain
resolution without additional DAC capacitors, evaluated in TSMC130nm simulation.
[Primary institutional abstract](https://researchonline.jcu.edu.au/88540/).
Redundant code calibration is therefore established in general. The specific
per-weight same-cap carry selection has not had an exhaustive novelty search and
must not be labeled novel on this evidence.

## Stronger baseline: frozen per-output offset calibration

The uncalibrated full-depth mismatch runs must not be treated as a fundamental
mismatch limit. For actual nonzero-mean activations, fixed coefficient error
induces a persistent output bias `mean(x)·deltaW`. A single per-output constant
can remove its calibrated mean while leaving input-dependent residual error.
The white-input coefficient audit above does not capture this opportunity.

A new [runner](../../../../../scripts/compiler/metrics/imc_mismatch_offset_quality.py) and frozen
[die1](../../../../../build/campaign/mismatch_offset_quality/die1/protocol.json)/
[die2](../../../../../build/campaign/mismatch_offset_quality/die2/protocol.json) protocols
use exactly the same capacitor realizations as the uncalibrated mismatch runs.
Calibration captures only the old128 clean tokens, runs the actual finite ADC
model with fixed capacitor mismatch, and records the mean error against each
clean MVM output. Each constant remains fixed during both exposed512-token
passages and is subtracted after physical bank combination, before the next
network operation. No evaluation activations are used for calibration.

The modeled implementation uses float32 constants and noiseless calibration
averages. Finite calibration-read noise, constant quantization, PVT drift and
physical measurement cost remain unverified. There are155,520 block-MVM output
channels per implemented architecture, requiring0.62208MB at32bits/constant;
this is much less state than one calibration bit per106M weights. The existing
per-channel affine requantization path is a possible place to combine the
subtraction, but its exact fixed-point range and implementation must be checked.
No quality result is presumed before the frozen campaigns complete.

## Completed uncalibrated full-depth fixed-mismatch runs

Both36-case die runs completed and their source hashes were rechecked. Die1 has
11/36 individual passes and die2 has10/36; no architecture passes all six cases.
The [summary](../../../../../build/campaign/fixed_mismatch_quality/summary.json) preserves
both passages, mismatch-only diagnostics, and the two fixed-mismatch+thermal+
20µV read-noise cases per passage. This is two modeled realizations, not a yield
estimate. Every architecture also fails some physically noisy cases; the
conclusion does not depend solely on the mismatch-only diagnostic.

| Die | Format / architecture | Passing cases | Worst KL | Worst PPL ratio |
|---:|---|---:|---:|---:|
| 1 | Balanced9 / A10 separate | 2/6 | .0128368 | 1.0067507 |
| 1 | Balanced9 / A11 separate | 2/6 | .0125826 | 1.0031411 |
| 1 | Balanced9 / A10 pooled | 2/6 | .0190513 | 1.0153787 |
| 1 | Signed8 / A10 separate | 2/6 | .0110432 | 1.0167039 |
| 1 | Signed8 / A11 separate | 2/6 | .0109800 | 1.0144365 |
| 1 | Signed8 / A10 pooled | 1/6 | .0159704 | 1.0170319 |
| 2 | Balanced9 / A10 separate | 1/6 | .0128114 | 1.0105436 |
| 2 | Balanced9 / A11 separate | 2/6 | .0126066 | 1.0098765 |
| 2 | Balanced9 / A10 pooled | 2/6 | .0188239 | 1.0195446 |
| 2 | Signed8 / A10 separate | 2/6 | .0111576 | 1.0102165 |
| 2 | Signed8 / A11 separate | 2/6 | .0107547 | 1.0137057 |
| 2 | Signed8 / A10 pooled | 1/6 | .0153319 | 1.0176973 |

Lower fixed-error white-input RMS does not guarantee a better passage PPL.
The full model retains actual activation correlations and fixed errors across
layers; replacing them with newly drawn per-MVM Gaussian output noise would
change this experiment. The offset-calibrated controls remain separate and must
complete before interpreting the uncalibrated failures as a calibration limit.

The repository also already contains
[imc_cap_calibration.py](../../../../../scripts/compiler/metrics/imc_cap_calibration.py), which
keeps physical capacitor errors fixed, tests redundant differential programming
by adding the same code to both banks, and includes independent calibration error
and held-out activations. The present radix8 carry test uses a different exact
code freedom within22 magnitude units, but it is not the first redundant-cap
calibration experiment in this repo. The older full-model branch uses a1%
area-law coefficient; that coefficient must not silently substitute for the
current installed-PDK2.8% effective-area law.

## Completed offset-calibrated fixed-mismatch controls

All source hashes were rechecked. Die1 has10/36 passes and die2 has17/36. Signed8 separate passes all six cases in die2, but fails three cases in die1. No candidate survives both modeled dies. Offset correction can reduce KL while worsening PPL on a different passage distribution.

| Die | Format | Architecture | Passes | Worst KL | Worst PPL ratio |
|---:|---|---|---:|---:|---:|
| 1 | balanced9 | common_A10_separate | 1/6 | 0.0117380 | 1.0206394 |
| 1 | balanced9 | common_A11_separate | 1/6 | 0.0113303 | 1.0177104 |
| 1 | balanced9 | common_A10_pooled | 1/6 | 0.0181205 | 1.0300219 |
| 1 | signed8 | common_A10_separate | 3/6 | 0.0097144 | 1.0188665 |
| 1 | signed8 | common_A11_separate | 3/6 | 0.0094274 | 1.0173278 |
| 1 | signed8 | common_A10_pooled | 1/6 | 0.0149014 | 1.0230392 |
| 2 | balanced9 | common_A10_separate | 1/6 | 0.0122015 | 1.0143341 |
| 2 | balanced9 | common_A11_separate | 1/6 | 0.0116614 | 1.0144100 |
| 2 | balanced9 | common_A10_pooled | 1/6 | 0.0176354 | 1.0236844 |
| 2 | signed8 | common_A10_separate | 6/6 | 0.0097035 | 1.0097063 |
| 2 | signed8 | common_A11_separate | 6/6 | 0.0095712 | 1.0097696 |
| 2 | signed8 | common_A10_pooled | 2/6 | 0.0139396 | 1.0186520 |

[Complete summary](../../../../../build/campaign/mismatch_offset_quality/summary.json). Two realizations do not estimate yield. The constants were frozen using the old128-token calibration input; no held-out fitting was used.
