# Comparator decision noise versus final ADC noise

**VERIFIED mathematical model; physical SAR/noise integration unverified.**
The [frozen experiment](../../../../../scripts/compiler/metrics/imc_sar_noise_transfer.py) separates
noise drawn once at acquisition from fresh noise at each SAR decision. The
earlier full-model charge/noise studies use the first kind. Root's approximately
445-µV comparator estimate is a conditional physical input decision-noise
estimate and cannot automatically replace that parameter.

The [protocol](../../../../../build/campaign/sar_noise_mapping/protocol.json) has SHA-256
`f36bae65308049fdc3ad7408650a9fe21a70c739549fe5bb8cbf2f075bd33191`.
Its source snapshot, exact probability controls and all 90 scored cases are
in [results.json](../../../../../build/campaign/sar_noise_mapping/results.json).
No model corpus, calibration, or active guard experiment was changed.

## First-principles model and checks

A conventional N-bit SAR bisects an interval `[l,u]`. With unit output LSB,
the threshold is `t=(l+u)/2`; the decision retains the upper half when
`x+n_k >= t`, otherwise the lower half. After N decisions the reported value
is the final interval midpoint. This assumes exact DAC thresholds, settled
references, no redundancy, no metastability and no state disturbance.

For independent Gaussian noise of RMS sigma, the probability of a particular
code path is the product of its conditional branch probabilities. For a high
branch the factor is `Phi((x-t)/sigma)`, and for a low branch it is its
complement. Thresholds follow the candidate code's previous decisions. Summing
over codes gives normalized output probabilities and every desired moment.
Three independent 4-bit enumerations are compared with 300,000 Monte Carlo
samples each using a predeclared seven-standard-deviation bin tolerance;
maximum observed probability discrepancies are 0.00068–0.00085, all passing.

A useful deterministic bound follows without Gaussian assumptions. If every
decision error obeys `|n_k| <= delta`, then `x` remains inside the retained
interval expanded by delta. The next correct or incorrect branch preserves
that property directly from the decision inequality. Consequently,

```
|final midpoint - x| <= delta + 0.5 LSB.
```

The code asserts the interval invariant on bounded-noise draws and the final
bound using the maximum actually drawn decision noise in every Gaussian case.
Noise does not accumulate as an unconstrained sum of binary-weighted decision
errors: later thresholds depend on the earlier decisions. This does not bound
Gaussian tails by a finite fixed delta.

The correlation control draws `n_k = sigma*(sqrt(rho)*z_common +
sqrt(1-rho)*z_k)`. At rho=1 the result is exactly the ideal quantizer applied
to `x+sigma*z_common`, including saturation; the selfcheck requires bit-exact
agreement. Here the common draw changes between conversions. Fixed device
offset across all conversions is a different error process.

## Quantitative result

The main experiment uses N=14, 150,000 inputs per case, seed975312, and ten
noise levels from 0.1 to64 LSB. Uniform inputs occupy the central80% of the
range, avoiding meaningful overload. Additional constant inputs at the major
binary threshold and its adjacent code center expose input dependence.

Define equivalent excess noise by subtracting the noiseless quantizer's
measured MSE from the noisy total MSE, then taking the square root. This is
a moment comparison, not proof that the output error is additive Gaussian.

| Decision sigma / LSB | Independent excess RMS / decision sigma | Total output RMS / LSB | Absolute error99.9th percentile / LSB |
|---:|---:|---:|---:|
| 0.25 | 0.9974 | 0.3812 | 1.1093 |
| 0.5 | 0.9483 | 0.5549 | 1.8022 |
| 1 | 0.8553 | 0.9026 | 3.0646 |
| 2 | 0.7861 | 1.5985 | 5.6029 |
| 8 | 0.7206 | 5.7716 | 21.2163 |
| 64 | 0.6946 | 44.4529 | 163.2267 |

At64-LSB comparator noise, rho=0.5 gives an excess ratio0.8606, and rho=1
gives1.0009 within finite-sample variation. At a fixed input the mean error
can be nonzero: for the code center near the major transition, sigma1 gives
−0.0396-LSB observed mean with independent noise. A global attenuation factor
therefore does not preserve every input-conditioned error law or tail.

Comparator-noise attenuation in SARs is established prior art. Liu's primary
[2017 CMU dissertation, chapter4](https://s3-eu-west-1.amazonaws.com/pstorage-cmu-348901238291901/12255821/918_Liu_2017_2019.pdf)
derives code-path probabilities and explains why an additive-input model becomes
pessimistic at large comparator noise. Its discussion of redundant decisions
and unequal comparator precision also precedes this campaign. The present
script is an independent bounded verification and interface audit, not a new
noise-reduction architecture.

## Conditional implication for the campaign

Using the historical raw-comparator point445 µV, the tested independent-to-shared range suggests
effective signal gain of roughly15.5–22.3 to reach20-µV equivalent final
noise. This is only an arithmetic screen: correlation, decision-dependent
common mode/noise, comparator input load, colored noise and ADC transfer must
come from the connected circuit. A capacitor stack's deterministic gain does
not by itself establish these noise assumptions.

Root's crossed N16 fixture reports calibrated gain10.6313. Multiplying by an
ideal useful-half factor2 would give roughly14.5–20.9-µV equivalent noise,
but that factor is not uniform across actual weight loads. The separately
frozen capacity audit gives median ordinary-pool-to-matched-branch factors
1.805 low-slice and1.356 high-slice after guard-fit padding. Combined with
that fixture gain, the same arithmetic becomes approximately16.1–23.2 µV
low and21.5–30.9 µV high. These are **SPECULATIVE cross-fixture projections**,
not a model-quality result. Ground-segment CDAC fit, extra switch/reference
noise, matching and disconnected physical capacitor banks still require payment.

The next admissible system model should use measured or justified conditional
code probabilities, or simulate actual sequential decisions with their noise
correlation. Keep the held-charge thermal term separate. Do not claim a
breakthrough by inserting an ideal gain or universally shrinking the old
Gaussian read-noise parameter.

The examples above remain frozen arithmetic examples. Later matched full-diffusion
64-seed-per-input component screens give a default estimate455.260 µV
(95% interval387.51–538.79), versus328.851 µV (279.91–392.05) with4-fF
internal-node capacitors and315.815 µV (268.82–376.51) with16-fF capacitors.
See the [default](../../../../../build/campaign/decision_noise/tt_iw3p5_geom_n64/result.json),
[4-fF](../../../../../build/campaign/decision_noise/tt_iw3p5_geom_ci4_n64/result.json), and
[16-fF](../../../../../build/campaign/decision_noise/tt_iw3p5_geom_ci16_n64/result.json)
component artifacts. The earlier≈366-µV estimate used fewer trials and is
not an established superior default. Internal capacitance also changes energy,
loading and regeneration; the older crossed-stack gain cannot automatically
be combined with either new noise estimate. Actual loaded gain, retention,
coarse-decision behavior and interdecision noise statistics remain required.
