# Reset-noise correction and activation-radix limits

Status: **STRONGLY SUPPORTED analytical model; physical and full-quality qualification pending.**

The completed balanced16 grids used sharing-only thermal variance. The radix9
grids stopped after 34/72 Cu4 cases and 33/72 Cu8 cases; those partial files are
preserved. Neither incomplete grid proves a two-passage survivor.

A new frozen control
uses the original/radix9 calibration choices, both Cu4 and Cu8, all three matched
architectures, the minimum-error policy, and the same two exposed 512-token
passages and seeds 60001/60002. Quantization-only cases remain controls. The
only physical-model change is complete ideal reset/share noise. ADC selections
are deliberately unchanged to isolate this correction; they are not claimed
optimal under the corrected model. The
[runner](../../../../../scripts/compiler/metrics/imc_reset_noise_campaign.py) reuses the frozen
radix9 engine and preserves the original calibration/source fingerprints.

For an equal array and holder capacitor C, an independently reset array starts
with variance kT/C. Complete charge sharing retains half its voltage plus half
the previous holder voltage and thermalizes the differential mode:

\[
V_{n+1}=V_n/4+kT/(4C)+kT/(2C).
\]

Here V denotes **variance**, not the signal voltage. A reset-equilibrated holder
starts at kT/C and remains at kT/C after every plane. A perfectly noiseless initial
holder instead approaches `(kT/C)(1-4^-B)`, which is still larger than the old
sharing-only `(2kT/3C)(1-4^-B)`. Independent pooled holder charges have variance
`kT*sum(C_i)`; sharing them does not erase this conserved charge noise. Reference,
row, supply, programming-switch, finite-settling and mismatch terms remain extra
unverified contributions. Active capacitance is still not installed storage area.

## General radix and banking bound

Assume a fresh array capacitance A, holder H, fully settled sharing, independent
thermal reset of A each plane, and initial equilibrium of H. Let `R=1+A/H`, so
`H=A/(R-1)` and holder retention is `r=1/R`. A row DAC encoding digit d as
`0.45*d/(R-1)` gives the familiar normalized radix recurrence:

\[
h_{n+1}=h_n/R+0.45\sum_i C_i d_i/(R A),
\]

where C_i is the signed capacitance contribution of row i. This
reduces the number of planes, but requires R-level row generation (or a signed
equivalent), with its actual error, energy and settling included.

The reset contribution is `(1-r)^2*kT/A`; sharing adds
`kT*A/[H(A+H)]`. Together the variance recursion is

\[
\sigma_{n+1}^2=r^2\sigma_n^2+(1-r^2)kT/H.
\]

Thus `sigma_h^2=kT/H=(R-1)kT/A`. A smaller holder buys radix at a noise cost.
For K independently usable native holders sharing one compute array, capacitor
area proxy is `A+KH`, and

\[
(A+KH)\sigma_h^2=kT(R-1+K).
\]

At matched output noise to a binary single-holder array of capacitance C0, this
requires `A=(R-1)C0`, `H=C0`, and total capacitance `(R-1+K)C0`. Consequently:

| Radix R | Holders K | Nominal 9-bit planes | Capacitance relative to binary serial |
|---|---:|---:|---:|
| 2 | 1 | 9 | 1 |
| 2 | 2 | 9 | 1.5 |
| 3 | 1 | 6 unsigned, 7 balanced ternary for ±511 | 1.5 |
| 3 | 2 | same | 2 |
| 8 | 1 | 3 | 4 |
| 8 | 2 | 3 | 4.5 |

The unsigned radix3 count represents codes 0…511; balanced ternary needs seven
planes because six balanced digits cover only ±364. Signed binary has a separate
sign convention, also requiring actual row-sign hardware. No table entry asserts
equal hardware or equal useful throughput.

Even nominal stage time is not constant at matched noise: the sharing time
constant is `Ron*A*H/(A+H)=Ron*C0*(R-1)/R`, versus `Ron*C0/2` for binary. R8 is
1.75× larger at fixed switch resistance, before extra DAC settling, clock load,
and final accuracy requirements. Larger gm/ID-sized switch conductance can
recover speed while adding gate energy, parasitic load and area. Switch sizing
must use triode conductance at the real common mode, not saturation gm/ID alone.

These bounds assume one shared array and K native holders. Duplicating arrays,
noise correlations, correlated double sampling, incremental conversion, or a
changed signal normalization require a new derivation. They do not establish a
universal impossibility theorem. Pipelining can improve initiation interval but
cannot make a slower ADC service rate disappear or automatically reduce the
latency of one completed result.

The runner self-check verifies the general covariance recurrence for R=2,3,8,
including cold-start finite-plane behavior, and retains the old exact arithmetic
and seeded quantizer checks before installing the corrected noise term.

The radix area table matches **output-voltage noise**, under its stated row
normalization. Matching product error also requires matching signal gain:
`0.45*Cu/R^B`. For example, three radix8 planes have `R^B=512`, exactly matching
nine binary planes, whereas seven radix3 planes have `R^B=2187`. Driving balanced
ternary digits at ±0.45 rather than ±0.225 doubles its signal gain but still does
not equal the nine-bit binary gain. Therefore the table is not by itself an
apples-to-apples balanced-ternary accuracy comparison.

## Physical precision targets from the frozen calibration

The hardware budget extract
retains all 420 MVM/bank settings per architecture. Cu4 radix9 separate uses
12 bits in 372 settings, 13 in 34, 11 in 11, and 10 in 3. Its common spans are
0.25 V (224 settings) and 0.5 V (165), giving charge quanta 0.05859375 and
0.1171875 fC. A 2.4-pF holder sees these as 24.414 and 48.828 µV. The system's
20-µV final read-noise term remains an assumption requiring a physical converter.
The separate12-bit distributed coarse-cap requirement is 960 fF at Cu4, versus
3840 fF for14-bit; small native columns still require paid matched padding.

Cu4 active connected C is 4.3244 µF for radix9 separate and 4.1337 µF pooled,
only 4.41% lower for pooling. The comparable original separate value is
6.9948 µF. These are conditional active array+holder+fine-cap totals, not chip
area. Conventional installed digit banks remain 22 Cu units for both original
and radix9 over the observed −127…127 weights. Pooling changes converter service
counts and resources; average ADC depth alone is not a throughput result.

## Measured unsigned programming-bank sensitivity

A separate frozen experiment
uses the measured 1-kHz code-dependent port capacitance from the full-geometry
Cu4 bypass bank. The [runner](../../../../../scripts/compiler/metrics/imc_programmable_loading_campaign.py)
replaces each digit's ideal active capacitance by C(code), retains the exact ideal
signal charge, and sizes an ideal holder to match the resulting array loading.
It does not add a constant 9.66-fF correction: the measured residual changes with
code. A zero-code256-row column nevertheless has about2.473pF programming loading
before the unchanged120-fF column floor.

Classification: **SPECULATIVE system sensitivity using measured AC inputs**.
The unsigned4-bit fixture is applied equally to both banks; sign mux and SRAM
are absent. Its installed bank is60fF+16MOS even at zero code. A minimal3-bit bank
requires a separate physical measurement. Neither full-array transient charge
error nor native radix matching is validated. The effective-lumped kT/C noise
assumption does not prove the bypass network's internal-mode noise covariance;
fast internal-mode noise can survive even when low-frequency port C is small.
Reference, row and state-driver noise remain unpriced. A passing quality result
would support only this bounded loading sensitivity, not a programmable IMC.

The earlier activation-radix numerical audit already verifies these ideal identities with 200,000 Gaussian trials per stage and 128 independent slice-sizing inequalities. Its fixed±511 balanced-ternary comparison requires `1.5*(2187/1024)^2 = 6.8421` times the binary single-holder capacitance at matched product noise, under full±0.45 row drive. This recovered evidence is preserved; the present derivation is a cross-check, not a new discovery.

## Completed corrected-reset control, 2026-09-11 12:50 UTC

Both36-case Cu grids completed and all recorded source fingerprints were
independently rechecked. The immutable
summary records result
hashes. Each row below requires both passages and both noise seeds, plus both
quantization-only controls. Noise is20µV additive read plus the corrected ideal
kT/C reset/share variance.

| Cu | Format / architecture | Cases passing | Worst KL | Worst PPL ratio | Active connected C, µF |
|---|---|---:|---:|---:|---:|
| 4 | Original / A10 separate | 5/6 | .0074664 | **1.0105648** | 6.9948 |
| 4 | Original / A11 separate | 6/6 | .0072892 | 1.0087384 | 6.9967 |
| 4 | Original / A10 pooled | 6/6 | .0084307 | 1.0084720 | 6.8219 |
| 4 | Balanced9 / A10 separate | 6/6 | .0070949 | 1.0085851 | 4.3244 |
| 4 | Balanced9 / A11 separate | 6/6 | .0068767 | 1.0077357 | 4.3245 |
| 4 | Balanced9 / A10 pooled | 6/6 | .0083795 | 1.0078610 | 4.1337 |
| 8 | Original / A10 separate | 6/6 | .0066314 | 1.0088942 | 13.9627 |
| 8 | Original / A11 separate | 6/6 | .0064014 | 1.0085273 | 13.9652 |
| 8 | Original / A10 pooled | 6/6 | .0071946 | 1.0068076 | 13.4090 |
| 8 | Balanced9 / A10 separate | 6/6 | .0062658 | 1.0094620 | 8.5439 |
| 8 | Balanced9 / A11 separate | 6/6 | .0060380 | 1.0079699 | 8.5477 |
| 8 | Balanced9 / A10 pooled | 6/6 | .0070714 | 1.0087479 | 8.0221 |

Classification: **VERIFIED within the explicitly bounded full-depth model**.
This verifies neither installed-memory area nor a physical20µV ADC, and the
clean tied output head remains outside physical error injection. Larger Cu is
not monotonically better on a finite corpus with changed frozen ADC choices.
Reserved corpus slices have not been evaluated. The measured-programming-load
sensitivity is a separate campaign and already contains failures; these passes
must not be transferred to it.

## Completed programming-load sensitivity: no complete survivor

The separate36-case Cu4 programming-load control completed, with18/36 individual
passes and all source hashes rechecked. **No architecture passes all six cases.**
The immutable summary
retains the result hash and complete negative evidence.

| Format / architecture | Cases passing | Worst KL | Worst PPL ratio | Connected C, µF |
|---|---:|---:|---:|---:|
| Original / A10 separate | 2/6 | .0179878 | 1.0091738 | 9.9986 |
| Original / A11 separate | 2/6 | .0175474 | 1.0108818 | 9.9988 |
| Original / A10 pooled | 2/6 | .0310422 | 1.0306804 | 9.9393 |
| Balanced9 / A10 separate | 5/6 | **.0102039** | 1.0085851 | 7.4025 |
| Balanced9 / A11 separate | 5/6 | **.0103014** | 1.0077357 | 7.4025 |
| Balanced9 / A10 pooled | 2/6 | .0164348 | 1.0153487 | 7.3515 |

These failures use unchanged ADC calibration choices. The new
programmable-digit protocol
recalibrates depth/span on the same old128-token calibration segment with the
measured loading and corrected thermal model. It also includes ordinary signed
radix8 and saturated-carry balanced8. For observed−127…127, ordinary radix8 has
low magnitude≤7 and high≤15, so22 installed binary units suffice; full−128 needs
a separate representation/escape and is excluded explicitly. Saturated-carry
balanced8 is exact on the same support but did not beat ordinary radix8's static
thermal coefficient. No novelty or completed quality claim is made for this
new calibration campaign.

## Completed fresh programmable-digit calibration and quality

The72-case nominal programmable-loading grid completed with45 individual passes; all source hashes were rechecked. Four rows pass all six development cases. These remain the unsigned-loading/lumped-noise sensitivity model, before fixed capacitor mismatch.

| Format | Architecture | Passes | Worst KL | Worst PPL ratio |
|---|---|---:|---:|---:|
| signed_magnitude | common_A10_separate | 2/6 | 0.0178143 | 1.0091689 |
| signed_magnitude | common_A11_separate | 2/6 | 0.0175608 | 1.0092500 |
| signed_magnitude | common_A10_pooled | 2/6 | 0.0311689 | 1.0279737 |
| balanced9 | common_A10_separate | 4/6 | 0.0101828 | 1.0073646 |
| balanced9 | common_A11_separate | 6/6 | 0.0099853 | 1.0086507 |
| balanced9 | common_A10_pooled | 2/6 | 0.0160154 | 1.0149079 |
| signed8 | common_A10_separate | 6/6 | 0.0091318 | 1.0074168 |
| signed8 | common_A11_separate | 6/6 | 0.0087107 | 1.0083743 |
| signed8 | common_A10_pooled | 2/6 | 0.0138275 | 1.0119669 |
| saturated_balanced8 | common_A10_separate | 5/6 | 0.0093928 | 1.0105632 |
| saturated_balanced8 | common_A11_separate | 6/6 | 0.0091631 | 1.0089262 |
| saturated_balanced8 | common_A10_pooled | 2/6 | 0.0142523 | 1.0146596 |

Complete summary. Ordinary signed8 improves this noise/format tradeoff, while saturated balanced8 does not uniformly dominate it. Neither is a new number system. All pooled rows fail; converter-service savings do not compensate the measured-loading noise penalty in these cases. Subsequent fixed-cap mismatch runs invalidate any claim that these nominal passes establish a robust physical core.
