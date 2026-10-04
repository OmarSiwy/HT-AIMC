# Low-rank correction as a paid mismatch baseline

**FAILED full-depth quality acceptance for every tested rank1 candidate.** The
weighted-subspace error reduction is verified only within its analytical model. This combines the repo's existing LoRA-sidecar idea with fixed-cap
mismatch and the measured activation statistics. Low-rank analog-hardware
adaptation is already established prior art.

The [weighted-subspace screen](../../../../../scripts/compiler/metrics/imc_mismatch_subspace_screen.py)
uses only the old128 clean calibration tokens to choose directions. Let
`v_i=mean_j Var(deltaW_ij)` after the actual smoothing/dequantization scales, and
`D=diag(sqrt(v_i))`. Independent fixed capacitor errors give
`mean_j Cov(D^-1 deltaW_j)=I` on nonzero-variance rows. If U contains orthonormal
calibration input directions, an ideal linear correction leaves expected
aggregate fixed-error energy proportional to

\[
\|(X-\mu)D(I-UU^T)\|_F^2.
\]

The baseline is `||XD||_F²`. The offset is the rank0 case. U comes from the top
right singular vectors of the centered old calibration input `(Xcal-mu)D`.
Directions are held fixed for both previously exposed512-token passages. The
check verifies weighted orthonormality, nonnegative residuals and all source
fingerprints. It follows **clean input trajectories**, so it is an ensemble
linear-error oracle rather than full nonlinear inference under mismatch.

For signed8, expected fixed-error energy remaining on the two passages is:

| Rank | Passage1 | Passage2 | Extra MAC count | Float32 coefficient storage |
|---:|---:|---:|---:|---:|
| 0, offset only | .8903 | .8951 | 0 | .62208MB |
| 1 | .3866 | .3961 | .2875% | 1.84320MB |
| 4 | .3438 | .3574 | 1.1502% | 5.50656MB |
| 8 | .3183 | .3328 | 2.3003% | 10.39104MB |
| 16 | .2929 | .3090 | 4.6007% | 20.16000MB |

Full per-MVM results
and summary retain
both representations. Rank1 captures most of this oracle benefit. Aggregate
energy weighting is not task sensitivity; it does not predict KL or PPL by
itself. Storage and MAC counts exclude the tied output head, just as the current
physical error injector does.

A new [full-depth runner](../../../../../scripts/compiler/metrics/imc_mismatch_rank1_quality.py)
uses the **same fixed physical die realizations** as the uncalibrated and offset
controls. On the old128-token clean inputs, it computes finite-ADC plus fixed-cap
MVM error, regresses that error onto one predetermined weighted input direction,
and fits an offset. A relative ridge1e-6 is fixed before evaluation. Each MVM
then applies its frozen input projection, output vector and offset during both
exposed512-token passages. Inference does not access per-weight true errors or
fit coefficients from evaluation activations. The old calibration averages are
noiseless and factors float32; these are explicit optimistic limits.

The die1 protocol
and die2 protocol
were frozen before full-depth results. The hook self-check verifies correction
before downstream operations, clean-reference identity and restoration of the
original callback. Calibration verifies that rank1 regression does not increase
training residual energy relative to offset-only correction.

An extra.2875% MAC count is **not** an extra.2875% power or latency. Digital
correction MACs may cost much more than an analog MAC. A serial576-term digital
projection can exceed the analog stage latency unless enough lanes are provided.
An analog sidecar adds its own storage, readout, noise and calibration. The
projection can overlap the main MVM, but the output correction and addition must
finish before the next dependent stage. Fixed-point factor quantization, memory
access, physical sidecar sizing and end-to-end schedule remain open.

The novelty search already found directly relevant baselines. IBM's2026
AHWA-LoRA work keeps analog base weights fixed and trains external low-rank
adapters, including a practical hybrid pipeline study. Its reported overhead is
specific to that implementation and is not imported here.
[Official IBM paper record](https://research.ibm.com/publications/efficient-transformer-adaptation-for-analog-in-memory-computing-using-low-rank-adapters).
The2026 GPTQ-intrinsic LoRA paper studies calibration-weighted reconstruction and
uses top input singular vectors to bound low-rank correction error.
[Author manuscript](https://arxiv.org/abs/2606.01412).
These establish related principles; the current experiment is a matched
fixed-capacitor-error calibration test, not a claim of a new low-rank method.

## Completed paired read-noise budget controls

The signed8 A11 separate candidate was frozen with the same rank1 factors, fixed capacitor errors and ADC calibration. Both12-case runs completed with unchanged source hashes. Every case includes stationary kT/C; read0 is an ideal-readout control, not a noiseless core. The two exposed512-token passages and two thermal/read seeds are reused consistently.

| Die | Read noise (µV RMS) | Passing cases | Worst KL | Worst PPL ratio |
|---:|---:|---:|---:|---:|
| 1 | 0 | 3/4 | 0.0085143 | 1.0144363 |
| 1 | 10 | 3/4 | 0.0088028 | 1.0140389 |
| 1 | 20 | 2/4 | 0.0094776 | 1.0145739 |
| 2 | 0 | 4/4 | 0.0084401 | 1.0087431 |
| 2 | 10 | 4/4 | 0.0086233 | 1.0087732 |
| 2 | 20 | 3/4 | 0.0092355 | 1.0108021 |

**FAILED as a two-die robust quality candidate:** reducing read noise to zero does not remove the die1 PPL failure. This rules out assuming that a better comparator alone will rescue this modeled core. It does not prove a fundamental impossibility or silicon yield. Die2 passes all four cases at0 and10µV but only three at20µV. The matching20µV cases reproduce parent rank1 cases exactly wherever those parent cases have completed; all eight matching cases now reproduce the completed parent campaign exactly. Frozen protocol and detailed results, summary.

## Completed full-depth rank1 correction campaign

Both36-case campaigns completed and all source fingerprints pass. Each row includes two mismatch-only diagnostics and four fixed-mismatch + kT/C +20µV read-noise cases. No architecture passes all six cases on either modeled die. These negative full-depth results supersede any inference-quality expectation from the clean-trajectory subspace screen.

| Die | Format | Architecture | Passes | Worst KL | Worst PPL ratio |
|---:|---|---|---:|---:|---:|
| 1 | balanced9 | common_A10_separate | 2/6 | 0.0112543 | 1.0184370 |
| 1 | balanced9 | common_A11_separate | 1/6 | 0.0112163 | 1.0142669 |
| 1 | balanced9 | common_A10_pooled | 1/6 | 0.0183984 | 1.0274117 |
| 1 | signed8 | common_A10_separate | 3/6 | 0.0096512 | 1.0163033 |
| 1 | signed8 | common_A11_separate | 3/6 | 0.0094776 | 1.0159507 |
| 1 | signed8 | common_A10_pooled | 1/6 | 0.0146936 | 1.0215370 |
| 2 | balanced9 | common_A10_separate | 1/6 | 0.0117500 | 1.0113019 |
| 2 | balanced9 | common_A11_separate | 2/6 | 0.0111082 | 1.0095661 |
| 2 | balanced9 | common_A10_pooled | 2/6 | 0.0174345 | 1.0217140 |
| 2 | signed8 | common_A10_separate | 5/6 | 0.0092901 | 1.0106507 |
| 2 | signed8 | common_A11_separate | 5/6 | 0.0092355 | 1.0108021 |
| 2 | signed8 | common_A10_pooled | 2/6 | 0.0140302 | 1.0194156 |

Complete summary. Exact eight-case read20 reproduction audit. A low-dimensional correction can reduce a linear error norm yet fail PPL because layer sensitivity, nonlinear propagation and calibration-distribution shift remain. The current tests do not isolate their relative contributions. Increasing correction rank, retraining, enlarging capacitors or changing arithmetic sharing would require a separately frozen experiment and paid hardware costs; none is credited here.
