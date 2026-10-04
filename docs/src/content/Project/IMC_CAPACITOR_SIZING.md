# Capacitor sizing, calibration and full-model error

2026-09-07. **Statistical experiments on real weights, not foundry mismatch simulation or chip measurements.** The result favors sufficient physical capacitor size and a quality-preserving weight format over extensive redundant calibration. The [circuit sizing experiment](IMC_SIZING_RESEARCH.md) separately tests transistor settling and interface energy.

## Decision supported by this experiment

- Carry **4–8 fF effective unit-capacitor candidates** into the passive-column study, subject to actual MOM/MIM geometry, extraction and noise. Do not enlarge every bank in the old ballast-heavy topology.
- Keep a **two-slice INT8 weight mode** for the quality reference. Naive INT4 roughly doubles perplexity on these passages before analog errors; capacitor sizing cannot repair it. W4 remains a candidate after better quantization/adaptation passes the quality budget.
- Use **uncertainty-aware, limited calibration** only where it pays. A perfect-characterization optimizer can look excellent while a noisy version worsens both error and switched capacitance.
- Keep selective precision available, but choose its placement using the relevant error distribution. The earlier 5–8× KL improvement for output noise becomes only approximately **1.04×** for fixed capacitor-weight mismatch here.

These are conditional design choices. They do not establish an optimum for arbitrary models or a win over Mythic.

## 1. Fixed physical errors versus capacitor area

The user's [27i1 capacitor-ratio note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27i1 Charge-Domain Compute Wins on Linearity Because a Capacitor Ratio Is a Lithographic Quantity.md>) and the existing [tb_csnr](../../../../analog/testbenches/tb_csnr.py) motivate an area-dependent mismatch study. This experiment uses their *hypothesis*:

`sigma_unit = (Ac/100) * sqrt(2/Cu_fF)`.

`Ac` is swept over 0.3, 1 and 3 percent-micrometers. The 2 fF/µm² coefficient is a nominal MIM area density, **not a measured MOM matching coefficient**. Sky130's published MIM specifications give that area density and a separate peripheral capacitance; they do not supply the local matching coefficient assumed here. Its minimum MIM dimension is 2 µm, so the area term alone is 8 fF for a square minimum feature. Smaller values need a different physical structure, such as a designed and extracted MOM capacitor. [Sky130 device specifications](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html#mim-capacitors), [minimum dimensions](https://skywater-pdk.readthedocs.io/en/main/rules/assumptions.html#minimum-critical-dimensions).

For a binary capacitor group of nominal weight `b ∈ {1,2,4,8}`, the normalized absolute error is `N(0, b*sigma_unit²)`. Different groups and the two banks are independent. Each device error is drawn once, then stays fixed as inputs change. Gradients, correlated routing parasitics, switch injection, temperature dependence and drift are absent. The capacitance sweep therefore answers an allocation question under a declared statistical model; it cannot certify manufacturing yield.

## 2. Redundant differential codes: benefit and cost

For each integer weight `w`, the ordinary codes are `Cp=max(w,0)` and `Cn=max(-w,0)`. Adding the same integer `k` to both preserves the exact nominal weight:

`(Cp+k) - (Cn+k) = w`.

Because the two physical banks have different errors, some equivalent pairs implement the target weight more accurately. The experiment permits `k≤0/1/4/15`, keeping both codes ≤15 and zero weights at 0/0. This is an independently derived programming experiment, not a claimed reproduction of a published calibration algorithm.

The raw experiment samples eight distinct 16×16 tiles from each of seven real compiler matrices: **56 tiles, 14,336 weights per device seed**. Four seeds, five capacitor sizes, three matching coefficients, three characterization-noise levels, four redundancy limits and two selection methods produce **1,440 cases**. Input files and selected tiles are fingerprinted in the artifact. Existing INT4/INT8 quantization is frozen. The first six saved activations fit the optional column gain; the last three score it. Upstream quantization previously saw the entire nine-token stream, so this is a holdout for the new gain fit only.

`closest` picks the pair whose measured weight is closest to the target. `uncertainty_aware` uses the known simulated prior and calibration-noise variances. For one group, with prior variance `v` and characterization variance `r`:

`posterior_mean = b + v/(v+r)*(measurement-b)`

`posterior_variance = v*r/(v+r)`.

The second method minimizes the posterior expected squared weight error, including the variances of selected groups. It avoids selecting a large common-mode code merely because its noisy measurement looks favorable. Hardware deployment must estimate these distributions; the experiment gives the optimizer the correct simulated variances.

Illustrative results pooled over four seeds, `Ac=1% µm`, before column gain correction:

| Unit cap | Characterization RMS, code units | Selection | Max k | Mismatch CSNR | Switched signal-capacitance ratio |
|---|---:|---|---:|---:|---:|
| 0.15 fF | 0 | Baseline | 0 | 33.93 dB | 1.000 |
| 0.15 fF | 0 | Exact characterization | 4 | 40.77 dB | 2.369 |
| 0.15 fF | 0 | Exact characterization | 15 | 43.28 dB | 5.040 |
| 0.15 fF | 0.02 | Closest measurement | 15 | 36.97 dB | 5.201 |
| 0.15 fF | 0.02 | Uncertainty aware | 15 | 38.08 dB | 2.448 |
| 0.15 fF | 0.10 | Closest measurement | 15 | 27.95 dB | 5.778 |
| 0.15 fF | 0.10 | Uncertainty aware | 15 | 34.26 dB | 1.056 |
| 1.2 fF | 0.02 | Baseline | 0 | 42.96 dB | 1.000 |
| 1.2 fF | 0.02 | Uncertainty aware | 15 | 43.71 dB | 1.249 |
| 4 fF | 0.02 | Baseline | 0 | 48.19 dB | 1.000 |
| 4 fF | 0.02 | Uncertainty aware | 15 | 48.51 dB | 1.051 |

CSNR here is `10log10(sum(y²)/sum(error²))`, not the centered-variance SNR used by the older depth study. It scores mismatch-only tile partials, without ADC clipping or rounding. Absolute values should not be compared directly to an earlier 36–43 dB output-noise gate. Minimizing every weight's error also does not guarantee minimizing every activation's dot-product error: error signs can cancel differently.

The switched-capacitance ratio is an activation-weighted charge proxy for an unchanged repeated-transfer schedule. It excludes clock gates, ballast, reference losses, ADCs, SRAM and routing. It is neither total power nor total area. An encoded four-bit weight plus `k≤1` can use five configuration bits; `k≤4` needs seven; unrestricted independent Cp/Cn can use eight. Physical reserve capacitors and switches still need two programmable banks. A generated netlist containing only selected capacitors does not implement that programmability.

Characterization precision also costs work. At the old nominal 1.35-mV/code conversion slope, 0.02 code is 27 µV. An illustrative 0.5-V-span eight-bit ADC plus 0.2-mV independent read noise has approximately 0.598-mV RMS combined noise, requiring about **490 independent measurements** to average down to 27 µV. That calculation requires suitable dither or another mechanism making quantization errors independent; repeatedly observing the same ADC code cannot provide this resolution. Fixed offsets and correlated errors do not average away. This is an ideal repeated-read requirement, not an implemented calibration schedule or energy estimate.

## 3. Full-depth sizing test: INT4 and two-slice INT8

The [same script](../../../../scripts/compiler/metrics/imc_cap_calibration.py) separately runs **48 full-depth cases**: 30-layer SmolLM2, all seven weight projections, all attention heads, two 256-token note passages, two fixed-device seeds, three capacitor sizes and two protection choices. These tests use ordinary nonredundant codes; **they do not validate redundant calibration end to end**.

For signed INT4 magnitude `a`, weight-error variance is `a*sigma_unit²`. For INT8 stored as low/high four-bit magnitude slices, it is:

`[a%16 + 256*floor(a/16)] * sigma_unit²`.

The high slice's error is multiplied by 16 along with its signal. The same fixed weight errors apply to every token. All other arithmetic is floating point; input DAC/ADC errors, analog attention, KV corruption and transient noise are absent. Increasing Cu assumes the digital scaling/reference range is adjusted consistently. That adjustment's circuit costs are not modeled here.

Mean KL and actual perplexity change relative to each precision's own error-free reference, with all weight projections analog:

| Weight format | Cu | Mean KL | Perplexity change across four cases |
|---|---:|---:|---:|
| Naive INT4 | 0.15 fF | 0.020438 | +2.190% to +5.929% |
| Naive INT4 | 1.2 fF | 0.002558 | +0.364% to +1.852% |
| Naive INT4 | 4 fF | 0.000768 | +0.146% to +0.981% |
| Two-slice INT8 | 0.15 fF | 0.006884 | −0.683% to +1.166% |
| Two-slice INT8 | 1.2 fF | 0.000851 | −0.368% to +0.248% |
| Two-slice INT8 | 4 fF | 0.000255 | −0.219% to +0.114% |

Negative perplexity changes can occur on a finite passage when perturbations improve the observed next-token likelihood. They are not a general quality improvement. KL and observed-token perplexity are different metrics; neither determines the other.

The naive INT4 references have perplexities **90.04/124.88**, versus **43.77/60.53** for the original dequantized Q8_0 model. The per-output INT8 references are **43.58/60.62**; requantization alone changes observed PPL by −0.421%/+0.140% and has nonzero KL. Thus two-slice INT8 is a more credible immediate quality reference. It requires **twice the physical four-bit weight-slice work**, and potentially twice the storage/conversions unless a real charge-domain combination circuit replaces them. Its numerical accuracy is not a free energy advantage.

Protecting layer-11 FFN-down, the earlier output-noise hotspot, reduces mean mismatch KL only approximately **4%**. Some seed-13 perplexities worsen slightly. This falsifies transferring the earlier 5–8× output-noise benefit unchanged to fixed coefficient mismatch. Keep separate characterization and allocation policies for weight, input and readout errors.

## 4. Reproduce and interpret the checks

```sh
python3 scripts/compiler/metrics/imc_cap_calibration.py
python3 scripts/compiler/metrics/imc_cap_calibration.py --full-model
python3 scripts/compiler/metrics/imc_cap_calibration.py --full-model --weight-bits 8
```

Use the existing Nix NumPy environment. Results are `build/research/imc_cap_calibration.json`, `imc_cap_full_model.json` and `imc_cap_full_model_w8.json`. Recorded runtimes were approximately **10 s, 64 s and 83 s**. The speed improvements from the previous round remain active.

Checks assert exact nominal weights, zero-weight preservation, ideal-device identity, monotone per-weight error under exact characterization, unchanged zero-noise references and restoration of original weights. An independent exhaustive enumeration checked code selection against all legal pairs. These verify the implementation and statistical hypothesis; they do not establish device noise, end-to-end deployed quality or a chip benchmark.
