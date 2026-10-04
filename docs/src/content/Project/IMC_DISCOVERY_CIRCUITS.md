# IMC discovery: circuit mechanisms and falsification

Date: 2026-09-10. This independent branch derives circuit candidates for the
user's minimum-area, minimum-delay, minimum-energy, high-throughput objective.
It read `CONTRACT.md`, the current system benchmark and analog-storage handoff,
the array generator, existing charge-sharing experiments, and the user's
analog-compute notes before proposing changes. It changes no production circuit.

**The surviving mechanism is direct reduction of native stored charge across
row groups. Unequal programmed accumulator capacitances can cancel their own
voltage normalization.** This is an exact ideal-circuit identity with a useful
architectural consequence; it is not a demonstrated novel chip architecture.
Noise and radix matching are substantial obstacles. Neither transistor-level
converter integration, preserved workload accuracy, minimum area, nor a victory
over Mythic is established here.

## 1. Quantified problem and evidence boundary

Use the existing resource-matched benchmark as the starting point: 76 logical
1024-by-1024 groups, 79,691,776 W8 weight positions, 19,456 converters, sky130,
1.8 V, two W4 coefficient services per W8 operation. The existing array fixture
actually tests signed W4; full W8 banks, storage and loading remain separate
obligations. Weight and activation precision, output quality and complete power
accounting must match the comparison. Equal converter count is not equal area.

The baseline group interval is

`T0 = 2(366 ns + 32 × 295 ns) = 19.612 µs`.

It projects 8.12684 native TOPS across 76 groups from separate circuit fixtures.
Its converter has an exposed SS85 failure, and its energy omits storage,
reference generators, real mux/control, wiring and other full-chip costs. Read
[the benchmark](IMC_SYSTEM_BENCHMARK.md) and
[the handoff](IMC_ANALOG_STORAGE_HANDOFF.md) for those limitations and the
primary Mythic sources. They are binding limitations on every projection below.

The free variables include row-reduction factor K, charge-transfer topology,
activation exponent B, native capacitance, ADC resolution/range, comparator
topology, switch width, bus length and capacitance, sharing aperture, differential
reference storage, programming density and scheduling. The comparison metrics
are useful MACs/time, complete joules/useful MAC, physical area, first-result
latency, initiation interval and workload error. Tokens/s and tokens/J require
the additional model, memory-service and nonlinear-operation schedule.

For 100/250 TOPS/W, the complete budget is 20/8 fJ per useful MAC. These are
inverse budgets, not predictions. Preserve the current deterministic array
screens, maximum error below 1 MAC and RMS below 0.25 MAC, while separately
evaluating random noise and workload quality. A deterministic screen is not a
stochastic accuracy or ENOB requirement that has already been met.

## 2. Diverse candidate population

| Mechanism | Quantified opportunity or cost | Status and disposition |
|---|---|---|
| Existing holders plus an ideal pipeline | Removing every array/hold delay leaves 18.880 µs, only 3.88% better throughput | VERIFIED schedule bound; insufficient alone |
| Duplicate all holders for ping-pong operation | Same conversion bottleneck; one extra W4-bank holder population is 286.1 nF under the illustrative capacitance distribution below | SPECULATIVE implementation; defer until service count falls |
| Binary regenerative latch as a multilevel memory | Holding 10-bit relative amplitude for 9.145 µs on 304 fF requires net conductance within about 32.4 pS of zero | FAILED as an uncalibrated multilevel hold |
| Copy group voltages to equal capacitors, then join | Computes sum(Sg/Cg), not sum(Sg); scalar output calibration cannot fix unequal coefficients | FAILED by algebra; existing unequal-cap experiment independently demonstrates the problem |
| Join the original matched holders | Conserved charge is proportional to Sg, cancelling nominal Cg; K=8 reduces 32 ADC rounds to four per slice | VERIFIED ideal identity; physical/system candidate remains SPECULATIVE |
| Use unchanged ADC after K=8 native reduction | About 3.48 times worse ADC-induced summed RMS for the illustrative load/capacities | FAILED as an equal-error argument; add resolution/noise budget |
| Current-domain regeneration during ADC multiplexing | Eliminates stored output queue, but keeps read current active and introduces output-resistance/mismatch errors | SPECULATIVE alternative; not a free transplant into a passive array |
| Charge-to-time readout of the reduced node | t=Q/I cancels total node capacitance from the ideal transfer; offset/noise remain charge errors | SPECULATIVE hybrid; ramp/time-domain conversion is established prior art |
| Polarity-reversed dual acquisition | Odd combination cancels fixed offset/even-order error; two array services and storage/control are required | SPECULATIVE hybrid worth testing if sampling offsets dominate |
| Matched floating reference at comparator | Similar impedances can cancel common kickback; roughly doubles held reference capacitance and adds sampled reference noise | SPECULATIVE repair; ordinary differential sensing is prior art |
| Pool row charges before temporal accumulation | One aggregate holder/array ratio replaces eight local ratios; independent ratio variance averages down and dominant common gain can be calibrated | STRONGLY SUPPORTED by conditional mismatch arithmetic; no new transistor test |
| Alternate unequal holder/array roles | rho(1-rho)=1/4−delta² cancels first-order two-step radix error, but adjacent bit coefficients retain first-order error and a holder cannot generate the weighted MAC | Partial identity preserved; no complete viable circuit proposed |

The candidate population deliberately includes topology, time-domain,
calibration, dynamic operation, feedback and architectural attacks. The native
charge candidate is retained because it changes the service count, which the
storage-only candidates cannot do.

## 3. Native-charge reduction, derived from first principles

### A–D. Idea, physical explanation, derivation and assumptions

Let group g have weighted array capacitance

`Ag = C0 + Σi cgi`, with `cgi = Cu |wgi|`,

and an accumulator `Dg = Ag`. Weight sign selects the positive or negative row
bus. Voltages below are excursions from a common VCM, not absolute voltages.
For signed ternary activation plane b,

`pgb = Σi wgi xgib`, and `vgb = Cu Vs pgb / Ag`.

Reset the array between planes, retain the accumulator, and process magnitude
planes LSB first. Ideal complete sharing with equal capacitances gives

`hg,b+1 = (hg,b + vgb)/2`, with `hg,0 = 0`.

After B planes,

`hg = (Cu Vs / (Ag 2^B)) Σb 2^b pgb = α Sg / Ag`,

where `α = Cu Vs/2^B` and `Sg` is the signed integer partial MAC sum. Thus

`Qg = Dg hg = α Sg`.

Now join the original held nodes, without copying their voltages onto different
capacitors. If a bus/load capacitor Cb starts at VCM, charge conservation gives

`vR = Σg Qg / (Σg Dg + Cb) = α Σg Sg / Ctot`.

The programmed group capacitances can be unequal. Their factors disappear from
each signal coefficient because they appear once in the voltage denominator
and once in its native charge. Only one final group gain depends on Ctot.

This is the precise distinction from equal-capacitor resampling. If equal Cs
captures each group voltage, its accumulated charge is proportional to
`Cs Σg Sg/Ag`; unequal Ag then produces unequal mathematical weights. For
example, partials (+100, −100) on 300-fF and 600-fF original holders cancel
exactly as native charge, while equal-cap resampling yields a nonzero result.
No scalar final gain restores all possible inputs.

Assumptions are explicit:

1. All groups have equal Cu, Vs and activation exponent B, or explicit physical
   charge scaling makes their α equal.
2. Effective holder and array capacitances match during every local sharing
   phase, including capacitances whose terminals are actually clamped.
3. The readout combines the same stored charge; no invisible voltage buffer,
   destructive preliminary sampling or ideal reconstructed source is inserted.
4. Reset, isolation, input-return and join offsets are absent in this derivation.
5. The intended integer coefficients are proportional to actual unit
   capacitances. Unit mismatch is a separate error.
6. All relevant nodes settle, stay within switch headroom, and are not
   inadvertently clamped by the readout.

Native capacitance reuse removes a particular normalization error. It does not
remove attenuation, kT/C, DAC loading, finite settling or capacitor mismatch.
The prior instruction that unequal capacitances *always* forbid joining is too
strong; the prior warning is correct for arbitrary held voltages or resampled
partials.

### Activation exponent alignment

Local dynamic plane skipping produces `Qg = Cu Vs Sg/2^Bg`. Different Bg
therefore corrupt a direct reduction. One exact repair is choosing
`B = maxg Bg` and executing zero upper planes in the shorter groups: every
extra zero plane halves the prior stored charge, restoring common α. This
costs the skipped sharing/reset services and loses their local noise advantage.

Joining groups with the same Bg separately is another exact option, with one
conversion per exponent class rather than necessarily one overall. Programmable
charge scaling also works in principle, but its switch/capacitor ratios and
noise must be built and measured. Exponent metadata alone cannot digitally
repair an already mixed sum with unknown individual contributions.

### Mismatch: cancellation ends at the radix

For actual Ag and Dg, define `rho = Dg/(Ag+Dg)`. With ideal numerator Cu,

`hg,b+1 = rho hg,b + Cu Vs pgb/(Ag+Dg)`.

The final native charge is exactly

`Qg = Cu Vs Σb rho^(B−b) pgb`.

For `Dg=Ag(1+e)`, `rho = (1+e)/(2+e)` and

`rho^(B−b) / (1/2)^(B−b) ≈ 1 + (B−b)e/2`.

Every plane receives a different error. A scalar output calibration cannot
remove it. At e=1%, the relative low-plane/high-plane ratio over seven bit
spacings changes by about 3.54%, before cancellation-sensitive inputs amplify
its effect. The existing 1% ratio negative control already fails the local
accumulator's deterministic gate; native joining does not repair that failure.

By contrast, a known difference in Ag between two groups causes no coefficient
error when Dg matches its own Ag and Cu is common. Independent physical unit
errors perturb `Σi cgi sign(wgi)xgib` and remain real weight errors. Correlated
unit scaling can become a final calibration gain only when all affected groups
and references track appropriately.

### Headroom, loading and stability

Passive joining is a positive-capacitance weighted average including the bus's
initial zero excursion. It cannot exceed the extrema of the original voltages;
it cannot provide voltage gain. Local pre-join headroom remains the larger
requirement. An ADC acquisition clamp or a floating split-CDAC node changes the
actual capacitance matrix and must be included explicitly.

For two capacitors C1 and C2 joined through R, the difference mode has

`tau = R C1 C2/(C1+C2)`.

Settling within half an N-bit full-scale LSB requires approximately
`t >= (N+1) ln(2) tau` for a full-scale initial difference. For an eight-branch
star bus, solve `C dv/dt = −L v`, where L is the switch-conductance Laplacian.
The zero eigenvalue is conserved total charge; the slowest nonzero eigenvalue
sets settling. There is no active-feedback instability in the ideal passive
network, but long wires, voltage-dependent switch R and parasitic branches can
make its slowest mode unacceptable. Sampling a local node before these modes
settle defeats the single-node equation.

The energy dissipated in ideal sharing from bus excursion zero is

`Eloss = 1/2 Σg Dg hg² − (Σg Dg hg)²/(2 Ctot)`.

This energy is nonnegative. Switch clocks, input acquisition/reset, reference
generation and eventual readout add to it; it is not complete service energy.

## 4. Noise and area falsifiers

### E. Quantitative calculations, with no stochastic simulation claim

To expose scale, use the *multiset* of eight actual holder values from the
current array fixture: 568, 484, 304, 600, 516, 336, 444 and 424 fF. These are
eight columns of that fixture, not a measured eight-row-group reduction. They
form an illustrative numerical case only. Their sum is 3676 fF. Adding the
existing SAR's 948-fF acquisition load gives Ctot=4624 fF. At 300.15 K,

`sqrt(kT/Ctot) = 29.9366 µV`.

For Cu=4 fF and Vs=0.45 V, the input-referred thermal sensitivity is:

| Common magnitude planes B | Gain (µV/MAC) | Reset-only optimistic RMS (MAC) | Thermalized-holder common-charge RMS (MAC) |
|---:|---:|---:|---:|
| 5 | 12.1648 | 1.6881 | 2.4609 |
| 6 | 6.0824 | 3.3747 | 4.9218 |
| 7 | 3.0412 | 6.7488 | 9.8437 |
| 8 | 1.5206 | 13.4972 | 19.6873 |

The last column assumes independent equilibrium holder noise kT/Dg and
independent reset noise kT/Cb. Conserved-charge noise then has variance
`kT Ctot`, and equivalent MAC noise is `sqrt(kT Ctot)/α`. This describes the
common-charge mode in an ideal fully joined network; finite-resistance local
noise modes and the actual comparator filtering require a switched-noise model.

The optimistic column deliberately omits all noise newly generated by sharing
switches. Independent freshly reset array noise and one initially reset holder
give the recurrence

`sigma_h² = (kT/Dg)[4^(−B) + Σj=1..B 4^(−j)]`

`= (kT/Dg)[1/3 + (2/3)4^(−B)]`.

Thus its group charge-noise variance is
`kT { [1/3+(2/3)4^(−B)] ΣDg + Cb }`.
This is an optimistic model under independently thermalized resets, not a
universal lower bound for every correlated-noise or active-cancellation
topology. Both models already exceed the deterministic 0.25-MAC screen when
that number is hypothetically applied to random noise. This does not establish
that a language model fails: its accepted stochastic-error budget is unknown.
It does establish that deterministic SPICE agreement cannot be relabeled as
physical sub-MAC precision.

At B=8, α is 7.03125 aC/MAC, only 43.89 electron charges per integer MAC unit.
An assumed 100-µV RMS comparator noise alone becomes 65.76 MAC RMS. Reducing
Cb helps but cannot remove the holder noise. At fixed topology, uniformly
scaling native capacitances and Cu by lambda lowers native thermal MAC noise
as `lambda^(−1/2)`. Ignoring bus noise, the thermalized-holder case would need
lambda≈4930 to reach 0.25-MAC RMS at B=8. That is an area counterexample to
solving this particular absolute-precision target by capacitor enlargement.

No random-noise simulation, mismatch Monte Carlo or extracted-layout noise
result was run by this branch. The arithmetic above is explicitly calculated,
and its stated assumptions are falsifiable.

### F. Equal-error converter comparison

If each baseline group gets an ADC with the same voltage-error RMS sigmaA
and an acquisition path that preserves the native voltage,
reconstructed sum variance is

`var_sep = (sigmaA/α)² Σg Dg²`.

After native joining, one ADC gives

`var_join = (sigmaA/α)² Ctot²`.

Equal ADC-induced sum RMS therefore requires the joined ADC's voltage noise
and quantization error to fall by

`r = Ctot / sqrt(Σg Dg²)`.

For the illustrative capacitor multiset and load, r≈3.4802: **1.799 additional
effective bits** at unchanged voltage range. A nominal ten-bit design might
therefore need approximately twelve bits for this specific RMS comparison.
At unchanged absolute single-partial LSB referenced to mean Dg, the requirement
instead is 3.331 additional bits. These are different accuracy contracts.

An energy law proportional to `2^N` gives
`Ejoin/(8 Esep) ≈ r/8 = 0.435`; a thermal-limit law proportional to `4^N`
gives `r²/8 = 1.514`. Thus conversion count can improve delay while failing
to improve energy at fixed error. This makes ADC operating regime and
workload tolerance decisive. Quantization RMS formulas additionally assume
well-exercised, sufficiently uncorrelated code errors; adversarial or lattice
inputs need direct checks.

The acquisition boundary changes this comparison. If every separate baseline
holder instead passively shares into its own reset 948-fF acquisition load,
its coefficient becomes `(Dg+Cb)/α`. Then
`r_passive = Ctot/sqrt(Σg(Dg+Cb)²) = 1.15873`, only 0.21254 extra bits.
The separate baseline already suffers severe attenuation and additional reset
noise. This control does not make the joined converter intrinsically quieter;
it compares against a weaker sampled interface. Include the actual sampling
topology and its energy/noise in an architectural comparison.

The native analog sampling-noise comparison is less severe: with no bus noise,
the separate and joined paths conserve the same sum of charge-noise variances.
The new penalty comes from bus noise and the ADC's fixed voltage error after
division by a larger total capacitance, not a fundamental new K-fold loss of
all pre-existing charge SNR.

### Area and the ping-pong counterexample

Mean holder capacitance in this small fixture is 459.5 fF. Replicating it over
622,592 W4 partial-output positions requires 286.081 nF of holders. A complete
extra bank adds that amount before switches. In a hypothetical capacitor layer
with usable density d fF/µm², its plate-area budget is

`A = 286.081/d mm²`.

This is a density-parameterized accounting example, not extracted sky130 area;
metal overlap with underlying devices, routing, legal dimensions and memory
layout determine die area. The 4-fF MOM primitive remains unimplemented in this
repo. Check the [Sky130 capacitor device and rule documentation](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html)
before turning ideal capacitance into an area claim. A second W4 coefficient
bank and arbitrary full-model weight populations need their own accounting.
Duplicating holders to obtain at most 3.88% throughput is therefore unattractive
before fixing converter service count.

## 5. Further failures and recombinations

### Pool first, then accumulate significance

Combining the native-charge identity with the radix critic produces a stronger
hybrid. Evaluate all K local array nodes for one activation plane, then connect
them simultaneously to a **single electrically common holder** D. The holder
can be physically distributed, but remains one state. Charge conservation gives

`h_b+1 = [D h_b + Cu Vs Σg pgb]/[D + Σg Ag]`.

Choosing `D=Σg Ag` restores the exact half recurrence. Only one aggregate ratio
must match, rather than K local ratios. The same total nominal holder
capacitance is retained; this does not give a free capacitor-area reduction.
The global bus must settle every plane, with its capacitance included in the
matched ratio. Shared controls, reset sequence and long-wire poles can consume
the benefit.

Suppose group holder components have relative ratio errors eg and nominal
areas proportional to Ag. Then

`e_pool = Σg Ag eg / Σg Ag`.

With covariance matrix Sigma and normalized weights `ag=Ag/ΣAg`,

`var(e_pool) = a^T Sigma a`.

Independent equal-variance errors give
`sigma_pool = sigma sqrt(ΣAg²)/ΣAg`, approximately `sigma/sqrt(K)` for similar
Ag. Fully correlated ratio error does not average down. Moreover, early pooling
turns group-dependent gain errors into a common final gain; one scalar
calibration can remove that common component, although bit-dependent radix
error remains. This explains why end-to-end error may improve by more than
sqrt(K) without implying better physical capacitor matching.

A fresh **algebraic, conditional mismatch experiment** freezes seed 914611,
eight groups of 128 rows, signed weights −7 through +7 with 20% random
population, and A8 activations including −128. It generates 128 calibration
and 512 held-out words. The native Ag values are 380, 512, 528, 476, 608, 472,
464 and 456 fF; `sqrt(ΣAg²)/ΣAg=0.356359`. For each of 512 Gaussian holder-ratio
draws, fit one final gain/offset on the calibration words and evaluate the
held-out error. Held-out signal RMS is 4567.654 MAC.

| Assumed ratio sigma | Late-pooling median / 95th-percentile RMS (MAC) | Early-pooling median / 95th-percentile RMS (MAC) |
|---|---:|---:|
| Independent, 1% | 57.9495 / 83.9944 | 2.4585 / 6.9366 |
| Independent, 0.1% | 5.6143 / 8.3341 | 0.2476 / 0.6747 |
| Independent, 0.01% | 0.5704 / 0.8347 | 0.02510 / 0.07179 |
| Fully correlated, 0.1% | 0.72474 / 2.08071 | 0.72474 / 2.08071 |

The fully correlated control asserts agreement of both methods for every draw.
This is not PDK mismatch data, yield or a full noise Monte Carlo. Gaussian
variances are assumed; array coefficient errors, junction charge, bus mismatch
and timing are absent. One final calibration is a deliberate interface rule:
late joining cannot digitally correct eight individual gains after they have
already been combined. Per-group physical gain trims would be a new competing
architecture with costs that this comparison does not include.

**Stronger calibration baseline:** eight independently read partials can each
receive their own gain/offset correction before digital addition. The critic
requested this control, and the same operands, calibration split and first
1024 ratio draws were rerun with eight separate affine fits. No ADC noise or
quantization is added to any candidate in this comparison.

| Assumed independent ratio sigma | Eight separately calibrated partials, median / 95th-percentile RMS (MAC) | Early pool with one calibration, median / 95th-percentile RMS (MAC) |
|---|---:|---:|
| 1% | 9.97290 / 14.48463 | 2.45848 / 6.93661 |
| 0.1% | 0.965515 / 1.41828 | 0.247569 / 0.674704 |

The early-pooling median improvement is approximately 4.06 and 3.90 times
against this stronger baseline, rather than about 23 times against late pooling
with one calibration. Residual bit-dependent radix error survives all affine
fits. These ratios are median-over-draw comparisons, not guaranteed
per-realization improvements, foundry yield, or full-system accuracy gains.
The mechanism remains the aggregate ratio and its covariance; assumed equal
relative mismatch across unequal capacitances is not a Pelgrom model. A real
layout must supply area dependence, coefficient correlations and gradients.

Reproduce the numerical experiment in the existing Nix Python environment:

```python
import numpy as np
rng = np.random.default_rng(914611)
K, R, B = 8, 128, 8
W = rng.integers(-7, 8, (K, R)) * (rng.random((K, R)) < .20)
A = (120 + 4*np.abs(W).sum(axis=1)).astype(float)
x = rng.integers(-128, 128, (640, K, R))
planes = np.stack([np.sign(x)*((np.abs(x) >> b) & 1)
                   for b in range(B)], axis=-1)
p = np.einsum('ngrb,gr->ngb', planes, W)
exact = np.sum(p*2.**np.arange(B), axis=(1, 2))
ey, ex = exact[:128], exact[128:]
cy = ey-ey.mean()
ratio_state = rng.bit_generator.state
def error(v):
    train = v[:128]
    slope = np.dot(cy, train-train.mean()) / np.dot(cy, cy)
    offset = train.mean()-slope*ey.mean()
    return (v[128:]-offset)/slope-ex
for sigma, correlated in [(.01, False), (.001, False),
                           (.0001, False), (.001, True)]:
    late_rms, early_rms = [], []
    for _ in range(512):
        e = (np.full(K, rng.normal(0, sigma)) if correlated
             else rng.normal(0, sigma, K))
        rho = (1+e)/(2+e)
        late = np.sum(p*rho[None, :, None]**
                      (B-np.arange(B))[None, None, :], axis=(1, 2))
        ep = np.dot(A, e)/A.sum()
        rp = (1+ep)/(2+ep)
        early = np.sum(p, axis=1) @ rp**(B-np.arange(B))
        late_rms.append(np.sqrt(np.mean(error(late)**2)))
        early_rms.append(np.sqrt(np.mean(error(early)**2)))
    print(sigma, correlated, np.percentile(late_rms, [50, 95]),
          np.percentile(early_rms, [50, 95]))
    if correlated:
        assert np.allclose(late_rms, early_rms, rtol=1e-7, atol=1e-9)
print('PASS conditional mismatch comparison; not PDK Monte Carlo')
```

After the setup and first experiment above, reproduce the stronger baseline
using its saved pre-draw random state:

```python
rng.bit_generator.state = ratio_state
exactg = np.sum(p*2.**np.arange(B), axis=2)
calg = exactg[:128]
centeredg = calg-calg.mean(axis=0)
for sigma in [.01, .001]:
    separate_rms, early_rms = [], []
    for _ in range(512):
        e = rng.normal(0, sigma, K)
        rho = (1+e)/(2+e)
        qg = np.sum(p*rho[None, :, None]**
                    (B-np.arange(B))[None, None, :], axis=2)
        calq = qg[:128]
        gain = np.sum(centeredg*(calq-calq.mean(axis=0)), axis=0)
        gain /= np.sum(centeredg**2, axis=0)
        offset = calq.mean(axis=0)-gain*calg.mean(axis=0)
        separate = ((qg[128:]-offset)/gain).sum(axis=1)
        separate_rms.append(np.sqrt(np.mean((separate-ex)**2)))
        ep = np.dot(A, e)/A.sum()
        rp = (1+ep)/(2+ep)
        early = np.sum(p, axis=1) @ rp**(B-np.arange(B))
        early_rms.append(np.sqrt(np.mean(error(early)**2)))
    print(sigma, np.percentile(separate_rms, [50, 95]),
          np.percentile(early_rms, [50, 95]))
print('PASS separate-calibration baseline arithmetic; no PDK yield claim')
```

Moving reduction before significance accumulation is not by itself a novelty
claim. Its value here is a precise circuit reason to compare this schedule
against late pooling: it changes which mismatch is calibratable. This is the
new candidate generated by cross-pollinating charge conservation with the
failure analysis of local radix matching.

### Regeneration cannot preserve arbitrary amplitude for free

Near its metastable operating point, a regenerative latch obeys

`C dv/dt = (gm−gout)v + in(t)`.

With net positive conductance it exponentially amplifies differences into a
binary decision; with net negative conductance it decays. To preserve a
nonzero stored amplitude within relative error 1/1024 for 9.145 µs at C=304 fF,
the net conductance magnitude must satisfy approximately

`|gm−gout| < C ln(1+1/1024)/t = 32.45 pS`.

Against even an illustrative 10-µS device transconductance this is only 3.25
parts per million, before offset, flicker noise and nonlinear transconductance.
This quantitatively rejects an ordinary uncalibrated regenerative latch as a
ten-bit multilevel memory. It remains useful as a binary decision element or
short-lived dynamic preamplifier. A timed regenerative gain of eight needs
relative rate control of roughly `(1/1024)/ln(8)=0.047%` for ten-bit gain
accuracy; it also amplifies input noise. Nothing here demonstrates that control.

### Native charge plus time-domain readout

Apply a controlled discharge current I to the reduced node and detect its
return to VCM. For an initial excursion vR,

`t = Ctot vR/I = α ΣSg/I`.

The deterministic transfer does not depend on Ctot: this hybrid combines the
native-charge invariant with a charge-to-time converter. But comparator offset
deltaV creates charge error `Ctot deltaV`; current error creates gain error;
current noise integrates over time; and local high-frequency noise or kickback
can alter threshold crossing. Therefore the same attenuated voltage still
limits detection. A time representation relocates the quantizer; it does not
erase thermal precision cost.

For the illustrative capacities, `Σ|w| = (3676−8×120)/4 = 679`. With activation
magnitude at most 127, a worst-case sum is 86,233. At B=8 its charge magnitude
is 606.33 fC. Completing a full-range return in 100 ns requires at least
6.063 µA; resolving one integer MAC by timing requires about 1.16 ps. This
rejects a cheap 100-ns ramp as an exact-integer-MAC readout, while a much coarser
workload-approved quantizer may remain viable. Magnitude −128 and realistic
weight banks extend the range and must be accounted for separately.

Time-domain conversion using retained in-array capacitors is not novel:
[PICO-RAM, Sections III–IV](https://arxiv.org/html/2407.12829v1) reuses local
capacitors for input conversion, MAC, significance combination and readout, and
uses a dual-threshold time-domain ADC. It also explicitly identifies capacitor
matching and additional parasitics as limits. Its process, memory structure and
measured metrics cannot be transferred to this sky130 candidate.

### Native charge plus polarity reversal

If acquisition error is `q(S)=αS+q0+q2S²+q3S³+...`, two evaluations with opposite
row polarity give `(q(S)−q(−S))/2 = αS+q3S³+...`. Fixed offset and even-order
terms cancel. This may address the existing millivolt capture offsets better
than preserving a corrupted sample for longer. It requires two physical array
evaluations, a charge subtraction path and repeatable offsets; grounded-bottom
holders do not already provide the opposite differential node. Independent
sample noise, switch injection, settling and reference generation remain paid.
This is a testable recombination, not a validated repair or novel chopping claim.

## 6. Adversarial gates for the surviving circuit

### G–H. Failure modes and PVT/mismatch obligations

| Attempt to falsify it | What would reject the candidate |
|---|---|
| Distinct real groups, varied norms | A scalar gain fails held-out mixed-sign sums after direct joining |
| Different activation exponents | Unaligned groups produce coefficient-dependent errors; verify zero-plane alignment explicitly |
| One changed holder/array ratio | Bit-pattern-dependent gain survives calibration |
| Reset, source return and previous input history | Residual charge or injection changes a result for identical final operands |
| Actual SAR loading, positive and negative nodes | ADC acquisition destroys charge or introduces asymmetric kickback |
| Near-zero cancellation and full-range inputs | Offset dominates small results, or large local nodes violate headroom |
| Earliest/latest mux slot | Leakage and thermal drift exceed the workload error budget |
| Slow/fast process, supply extremes, temperature | A fixed aperture no longer settles, or switch leakage/radix changes |
| Unit mismatch, correlated gradient and routing | Charge coefficients change differently across groups |
| Physical switch and reference noise | Full-model quality or the stated noise allocation fails |
| Extracted bus and legal caps | Area or the slow RC mode erases the projected conversion savings |

A passive Laplacian has no growing modes, but the real comparator/reference
loop can still be unstable, metastable or history-dependent. Full transistor
PVT and layout are obligations, not labels inferred from nominal algebra.
The root experiment is the independent checker for the smallest actual
row-driven joining circuit; its result and exact scope are reported separately.

## 7. Prior art and novelty assessment

### I. What has and has not been distinguished

The local circuit notes correctly direct attention to charge conservation,
kT/C, input-referred conversion error and analog dataflow. Some notes contain
strong product-level inferences about Mythic; the system handoff narrows them
to patent disclosures. Use the narrower evidence boundary.

- [CAP-RAM](https://arxiv.org/abs/2107.02388) already uses a charge-injection
  SAR without separate sample/hold or input/reference buffers. Native charge
  sensing and eliminating redundant acquisition are not new claims.
- [PICO-RAM](https://arxiv.org/html/2407.12829v1) is direct prior art against
  broad claims of capacitor reuse or analog significance combining.
- [MANTIS, Sections III-B2–3](https://arxiv.org/html/2411.07946) computes row
  partial sums and combines them by charge sharing in a SAR CDAC. This is
  particularly direct prior art against broad claims of analog partial-sum
  aggregation before conversion.
- [GR-MAC, Section III-D](https://arxiv.org/html/2602.08081v2) discusses
  variable-capacitance normalization and explicit parasitic compensation of
  recursive capacitive ratios. A general claim of new normalization-aware
  capacitance sizing would be too broad.
- [Charge-CIM, Section IV-B](https://arxiv.org/html/2608.11116) maps oppositely
  encoded partial sums onto differential ADC inputs to add them during
  conversion. It is prior art against broad claims of polarity inversion plus
  differential partial-sum reduction; it is distinct from repeating the same
  signal in both polarities to cancel acquisition offset.
- [Yang et al., 2026, Section IV-A](https://arxiv.org/html/2605.30814v1)
  explicitly derives equal-capacitor binary-weighted accumulation. Its Eq. 6
  is the same local half-recurrence; that recurrence is not novel. The inspected
  text does not establish the unequal-native-capacitance group invariant.
  Its stated 20-µV kT/C noise at 50 fF should not be copied: the elementary
  RMS calculation at 300 K is approximately 288 µV. This discrepancy does
  not invalidate its charge-conservation equation.
- [Mythic US10255205B1](https://patents.google.com/patent/US10255205B1/en)
  discloses local multilevel charge accumulators; [US10389375B1](https://patents.google.com/patent/US10389375B1/en)
  discloses shared column readout. These are disclosed mechanisms, not proof
  of a particular shipped multilevel result pipeline.

The narrow possible contribution is an implementation that deliberately makes
the *same native capacitor* both the source of weight-dependent normalization
and the charge carrier for a later reduction, combined with verified exponent,
radix and readout treatment. `Q=CV` is elementary; independently deriving its
application is insufficient to claim novelty. The separate prior-art branch
performs a wider search. No patentability or exhaustive novelty determination
is made here.

## 8. Decision and remaining work

### J. What remains unverified

Retain native-charge row reduction, particularly early pooling before temporal
accumulation, for circuit testing because it can change
32 converter rounds into four per slice while preserving the ideal sum. Retain
the time-readout and polarity-reversal hybrids as distinct next candidates.
Reject storage-only speedup claims, unchanged-ADC equal-error claims,
equal-cap resampling of unequal normalized outputs and an uncalibrated
regenerative multilevel latch.

For a projected readout cost with N decisions, a useful sensitivity calculation
is `Tadc(N)=65 ns +23N ns`, taken only as a linear extension of the existing
ten-decision/295-ns fixture. N=12 gives 341 ns, and an ideal K=8 group would
take `2(488 ns +4×341 ns +Tjoin)=3.704 µs+2Tjoin`. This is a service-count
projection, not measured speed or power: increased precision changes CDAC,
noise, matching, reference drive and control, and can invalidate this period.

Before claiming a surviving architecture, require actual joined-row transfer,
physical ADC decisions on that node, stochastic error propagated through the
same workload, W8 mapping and storage implementation, all supply/reference/
clock energy, real mux wiring, legal capacitor area and complete PVT/mismatch
qualification. The useful partial discovery is the cancellation identity and
its exact limits. It survives ideal algebra; a breakthrough claim does not yet
survive the remaining tests.
