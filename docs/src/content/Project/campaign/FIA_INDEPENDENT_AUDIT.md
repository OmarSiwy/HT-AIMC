# Independent FIA current-noise and acquisition-boundary audit

Status: **VERIFIED mathematical normalization; conditional compact-model
characterization; physical receiver noise remains unverified.** This audit does
not promote a 20 µV receiver pass or a fundamental impossibility result.

The summed-current oracle uses differential input ±v/2, G=Σgm/2 and independent
one-sided drain-current PSD S=ΣSi. White covariance is Sδ(t−t')/2, so the minimum
variance within this observation model is [2∫G²/S dt]⁻¹. The documented factors
are correct. A more optimistic observer with access to each individual device
current has information (1/2)∫Σ(gmi²/Si)dt. Cauchy–Schwarz ensures this information
is at least that of the sum. Independent recomputation gives:

| Coordinate | Summed-current RMS | Four-current oracle RMS |
|---|---:|---:|
| L.18 Wn22/Wp44 | 33.341577 µV | 31.874012 µV |
| L.30 Wn36.6667/Wp73.3333 | 36.305156 µV | 33.631798 µV |

Both are **current-observation models**. Neither proves the floor of a complete
FIA with changing terminal charges, source rails, floating input holders and
reset history. Capacitive signal paths, internal noise correlations and differing
state transfers must be included before invoking an information bound on the
physical receiver. The gamma extraction is a native terminal-current definition,
not a universal MOS gamma. No correction from the unrelated zero-VDS Nyquist
model discrepancy is justified.

The component script splits total into reported flicker and its remainder. The
reconstruction check is algebraic, rather than an independent sum of every native
source. Positive remainder and measured frequency flatness support its use as a
quasi-static white coefficient. They do not establish switched flicker covariance
or source independence after connection to the complete circuit. The original
author has been notified and is correcting the wording.

## Signal-transfer sanity

Independent integration of the measured gm/gds trajectories with only the
explicit250fF output capacitor gives gains22.1974 and35.1863, versus native
21.4936 and30.5843 at L.18/L.30. By contrast, Γ/C gives63.1592 and57.3253 and is
not credible for this finite-gds amplifier. Including snapshot intrinsic drain
and drain-junction capacitance, and the time derivative of gate–drain charge,
reduces gain discrepancies to1.10% and4.43%. These partial models still omit
latch input, overlap, reset/off-switch and source-rail admittance. The correct
form is d[C(t)v]/dt, with cross-charge signal derivatives; inserting C(t) only
into C dv/dt misses part of the signal transfer.

Evidence: `build/campaign/fia_noise/independent_oracle_r2/result.json` and
`independent_cmatrix_r2/result.json`, with helper sources adjacent. Initial
failed audit attempts are preserved. No measured signal-gain fit was used to
choose the capacitance in these calculations.

## Native holder, acquisition and reset accounting

A holder thermalized through a resistor and then acquired from a stiff source
through another resistor does not automatically accumulate two kT/C terms.
For acquisition duration T and time constant τ,

Var(h_end)=exp(−2T/τ) Var(h_start)+(kT/C)[1−exp(−2T/τ)].

If the reset already produced kT/C, the result remains kT/C. The acquisition
replaces the initial mode progressively. An independently noisy sampled source,
a second disconnected load, or a separate reference holder needs its own joint
covariance; it cannot be silently treated as a stiff noiseless source. Conversely,
reacquiring a fresh sample is not equivalent to repeatedly reading the same
stored sample. Repeated reads preserve and correlate native sample noise.

The separate complete reset/share recurrence yielding stationary kT/C remains
correct under its declared ideal-resistor, fresh-reset and equal-capacitance
assumptions. It must not be added to another kT/C term representing the very
same holder mode. For the standalone FIA's2.4pF holders, full independent
acquisition gives about41.55µV per side and58.76µV differential atTT27. These are
outside the active-device oracle. Whether they consume the20µV allocation depends
on whether that allocation is additional receiver noise or total sampled-input
noise. Current evidence must keep that boundary explicit.

## Passive gain and charge conservation

N equal capacitors totaling CA, acquired in parallel and then stacked, have
series capacitance Ceq=CA/N². With a reset load CL the ideal gain is
N/(1+N² CL/CA); the gain is not N at arbitrary load. Open-circuit stored energy
is conserved: (1/2)(CA/N²)(Nv)²=(1/2)CA v². A measured downstream FIA input
capacitance therefore loads the stack, rather than granting free voltage gain.

The ideal independently thermalized stack-plus-load formula
Var(input-referred)=kT/CA·(1+N²CL/CA) already includes both native stack and load
thermal modes under its stated connection boundary. Adding a separate native
kT/CA to that total would double count. It does not include every real switch
mode. Crossed differential stacks must use the actual joint covariance and
signal vector; a second independent reference bank is not noiseless. Splitting
one total CA into N sections also does not create N statistically independent
observations of a preexisting sampled input noise value.

## Charge-curvature implications

The pipeline phase audit rules out late settling as its dominant fullrange
error and shows that switch ON-state and release charge largely cancel.
Half-width dummy devices improve local cancellation but worsen input-charge
curvature; they are rejected. A physically derived differential ±signal pair
would cancel even-order transfer terms without fitting heldout values, but the
existing extrema imply residual odd error still of several MAC and it costs a
second path or second acquisition. It is not a demonstrated solution.

Moving critical switching to a regulated near-constant-voltage node, or using
properly paid constant-overdrive switching, could reduce signal-dependent channel
charge. Body effect, overlap/junction charge, input loading, headroom and driver
noise prevent assuming exact cancellation. Neither mechanism is yet derived and
verified for this core. This audit recommends a complete charge-conserving model
before more blind width changes or an empirical heldout polynomial correction.

## Native port-capacitance follow-up

The stronger independent port audit measures each frozen native device with a
1A AC drain probe and then a1V gate probe, holding source/body at their actual
biases. With the noiseless1000S instrument, Ydd=1/Vd−1000 and
Ydg=−(1000+Ydd)Vd_gate. Thus Im(Y)/ω includes native overlap, junction and series
contributions without relying on ambiguous intrinsic-capacitance field names.
At1MHz the real ports reproduce native gm/gds within0.004%/0.022%. The source
also preserves100kHz and10MHz points; these are stationary snapshots.

Using the full port Cdd/Cdg in the charge-form one-state model gives:

| Coordinate | Model gain | Native gain | Relative difference | Conditional final-sample white RMS |
|---|---:|---:|---:|---:|
| L.18 | 21.572384 | 21.493569 | +0.367% | 37.838040 µV |
| L.30 | 31.009659 | 30.584297 | +1.391% | 36.643449 µV |

No measured gain was used to fit C. Total output C is285.225–285.617fF and
309.210–309.375fF respectively. Including Cdg's time-varying signal contribution
changes gain by only +0.00613 and −0.01167 here; it does not reveal a large hidden
signal path. The initial native signal gains at40ns are0.01014 and0.00587; these
are reported separately from the model's zero initial output signal.

For unit differential input define q=C(t)y−D(t), where D is the differential
drain–gate charge derivative. Then dq/dt=G−gds(q+D)/C. Independent white drain
noise gives dVar(q)/dt=−2(gds/C)Var(q)+SΔ/2. The helper integrates each local
constant-coefficient step exponentially. Thus the final-sample estimates include
the finite-gds weighting absent from a uniform ideal current integrator.

Evidence: `independent_ports_r1/result.json`,
`independent_port_ltv_r1/result.json`, with exact native decks, raw AC responses,
and helpers under `build/campaign/fia_noise/`. Missing latch/reset/source-rail
admittance, gate-noise transfer/correlation and complete switched-noise
qualification remain explicit. This is stronger quantitative support for an
unfavorable noise coordinate, not a fundamental physical lower bound.

Finally, FIA input capacitance inferred from stiff/floating signal-gain ratios
is an effective trajectory proxy. A second proxy from terminal attenuation is
also conditional. Their numerical range is not a proven bracket on loading of
a different reconfigured passive stack. A connected stack/FIA must propagate
its own charge state and joint covariance; its active gain and noise transfer
cannot automatically inherit those of the stiff-input characterization.

## Floating 1 pF input qualification

`build/campaign/fia_noise/independent_floating_ltv_r2/` extracts native
Ydd, Ydg, Ygd and Ygg at16 time points for all four FIA transistors, using the
actual1 pF floating-input trajectory. All gate/drain ports include native
overlap, junction and series effects. The two-state coordinates are
y=V(an)-V(ap), v=V(ip)-V(in). The charge equations are

```
q = C(t) [y,v]^T
C = [[Cout+Cdd, -Cdg], [-Cgd, Ch+Cgg]]
dq/dt = -[[gds,-gm],[0,0]] inv(C) q + [in,0]^T
```

Port quantities average the summed N/P devices over the two symmetric branches.
This preserves gate charge and includes drain-to-gate feedback. It uses
d[C(t)v]/dt, not C(t)dv/dt. Source/body differential AC voltages are clamped by
nominal symmetry; rail noise conversion under mismatch remains omitted.

Predicted final acquired-input gain18.65453 compares with native18.50865
(+0.788%). Predicted input retention0.842757 compares with native0.846117
(-0.397%). The zero-output/unit-input initial mode gives gain18.65107.
The capacitance matrices, in fF, change from
[[285.611,10.826],[8.502,1046.443]] to
[[285.378,19.160],[8.067,1063.349]]. The asymmetry is a device charge derivative,
not a passive reciprocal capacitor network.

The independently obtained native drain-current white PSD drives the charge
covariance through Pdot=A P+P A^T+B, with B11=sum(device one-sided PSD)/2.
The conditional added final-sample noise is40.2753 uV input-referred. Including
the earlier conditional403 uV latch noise divided by measured18.50865 gain
gives about45.8 uV quadrature, before other receiver terms. This has no proven
margin to the scalar40 uV additional-read budget; it is not a complete receiver
noise result or a fundamental lower bound. The first single-frequency ngspice
noise attempt did not produce the required spectrum plot; r1 is preserved and
r2 uses a three-point frequency sweep with the1 MHz point.

**Native noise is a separate initial covariance, not added twice.** If two
independent1 pF computational holders each have kT/C noise, the initial
differential RMS is91.0387 uV. That mode propagates through the signal transfer;
it is not additional transistor read noise. This corresponds to differential
equivalent capacitance0.5 pF. In contrast, raw32's scalar kT/C model at1 pF
has64.374 uV RMS relative to a noiseless reference. These are different
interfaces and cannot be equated. A single floating holder plus stiff VCM
reference may avoid a separately sampled reference's kT/C, but its asymmetric
signal/common-mode trajectory needs new physical validation.

The illustrative initial covariance is Cstart*diag(0,2kT/Ch)*Cstart^T,
specifying a signal-like input perturbation with zero output voltage at40ns.
It does not derive the actual acquisition/reset covariance: acquisition opens
30.2ns while output reset stays on to39.2ns. Switch noise, output reset,
reservoir noise, correlated gate/drain noise and that preceding phase graph
remain unpaid. Using kT times inverse of the active nonreciprocal C matrix
would be invalid. These limitations prevent promotion to full noise VERIFIED.

## Conditional colored flicker and correlated offset screen

`build/campaign/fia_noise/floating_flicker_r1/` contains fresh native stationary
flicker PSDs for the same16-times/four-device1 pF floating trajectory. An initial
assumption that all devices follow exactly1/f failed: the model uses NMOS
f^-0.84 and PMOS f^-1. The failed assumption and raw spectra remain preserved.
`floating_flicker_r2/result.json` uses the measured exponents; the power-law fit
matches the1Hz--1GHz native spectra to relative3.2e-9.

This conditional model represents each independent transistor's current noise
as sqrt(A_i(t))*xi_i(t), with stationary unit process spectrum1/f^EF and perfect
same-device cross-time coherence through that amplitude modulation. The
native stationary spectrum alone does not prove this switched-process model.
For the two-state charge dynamics, backward adjoint lambda(t) gives the final
input-referred current sensitivity. The calculated variance is

```
Var = sum_i integral_f |integral_t lambda_1(t)*sqrt(A_i(t))*exp(-j2*pi*f*t) dt|²
                       / f^EF_i df
```

This retains floating-input Cgd feedback and finite gds. Its independent white
adjoint integration gives40.275356uV, agreeing with the earlier forward charge
covariance40.275277uV within2ppm. That is a transfer/normalization cross-check,
not an independent stochastic transistor simulation.

| Low cutoff, high cutoff1GHz | Flicker RMS, native uV | Ideal two-aperture subtraction,360ns separation |
| --- | --- | --- |
|0.001Hz (extrapolated below measured1Hz)|50.793|50.155|
|1Hz|49.339|50.155|
|1kHz|45.184|50.155|
|1MHz|30.039|44.688|

At1Hz lower cutoff, adding40.275uV white in quadrature gives63.69uV FIA-only;
adding the earlier conditional403uV latch noise divided by measured18.50865
gain gives approximately67.31uV. These are conditional added receiver noise,
separate from native holder acquisition noise. Reset, switching, reservoir,
reference, gate/drain noise covariance and complete physical qualification are
still absent, so they are not a proven full-circuit lower bound.

For identical apertures separated by360ns, ideal offset subtraction multiplies
the colored spectrum by4*sin²(pi*f*360ns). It leaves50.155uV flicker and would
double independent white variance, producing about75.9uV FIA-only before the
physical auto-zero sampling/storage costs. Thus this screen does not support
ordinary two-sample auto-zero as an automatic remedy. The implied1Hz-cutoff
flicker covariance between those samples is about1176.6uV², correlation about0.48:
some noise is shared offset, but much remains time-varying over a conversion.
Averaging many offset observations or a different bias/geometry can alter this
tradeoff, but requires a paid mechanism and revalidated signal/noise model.

## Longer-channel recombination after the flicker finding

The parent ran matched actual1pF-input controls at L0.30um with Wn/Wp
36.6667/73.3333um and L0.50um with44/88um. The independent audit repeats native
four-port extraction and native white/flicker PSD at each geometry's own
trajectory. No gamma or1/f area rescaling substitutes for those measurements.
All controls retain2pF reservoir,250fF output and the improved acquisition/reset
switches. Earlier white-only results remain unchanged.

| Coordinate | L0.18 | L0.30 | L0.50 |
| --- | --- | --- | --- |
| Native acquired-input gain |18.5086|23.1979|23.5463|
| Native input retention69ns/31ns |0.8461|0.6810|0.6152|
| Coupled-model gain discrepancy |+0.79%|+1.65%|+2.16%|
| Conditional added white RMS,uV |40.275|39.689|43.861|
| Conditional flicker RMS,1Hz--1GHz,uV |49.339|34.873|27.837|
| Quadrature FIA-only RMS,uV |63.690|52.833|51.949|
| With prior403uV/gain latch estimate,uV |67.309|55.616|54.696|
| Native20uV-frame ideal-port energy,pJ |2.202|1.994|1.827|
| Four FIA transistor sum(W*L),um² |23.76|66|132|

The area row is gate-area arithmetic, not placed layout or total receiver area.
The additional input loading is directly visible in native input retention.
L0.30 input-port capacitance grows from about102.84 to147.24fF over the aperture;
L0.50 grows from170.58 to265.56fF, above the explicit1pF holder. Long-L signal
models have larger discrepancies, so the0.884uV FIA-noise difference between
L0.30 and L0.50 is not a sufficiently robust basis to declare L0.50 the winner.
Both improve the colored-noise coordinate substantially relative to short L,
with lower measured event energy but greater area and loading.

The ideal360ns auto-zero control leaves flicker35.605/28.443uV for L0.30/L0.50
and still doubles independent white variance. It does not automatically recover
the read-noise target. Changing the assumed low cutoff changes the ranking;
a1MHz cutoff is not a free calibration mechanism. Physical tracking, reset,
reference and storage operations would have to realize any claimed offset
suppression.

Artifacts: `independent_floating_l030_r1`, `independent_floating_l050_r1`,
`floating_flicker_l030_r1`, and `floating_flicker_l050_r1` under
`build/campaign/fia_noise/`. Source, native AC/noise decks and raw spectra are
retained. These results justify reconsidering longer-channel designs after
including flicker; they do not validate a complete50uV receiver, PVT/mismatch,
new SAR latch timing or transistor transient-noise performance.

Measured current-reuse effective gm/ID for the positive20uV branch is
36.426/38.506/39.099 V^-1 for L0.18/0.30/0.50. This is the aperture-integrated
sum of N/P gm divided by average N/P branch charge, as defined in the native
fixture; it is not the gm/ID of an individual transistor. The modest improvement
in this metric does not by itself predict the much larger flicker reduction or
remove gate-capacitance penalties.

## One paid reservoir-size control at L0.30

The parent tested `tt_l030_wratio_cres3p0_holder1p0_r1`: reservoir3pF instead of
2pF, otherwise unchanged L0.30 Wn36.6667/Wp73.3333,1pF input holders and250fF
outputs. Fresh native port/PSD extraction uses that actual trajectory.

| Metric | Reservoir2pF | Reservoir3pF |
| --- | --- | --- |
| Native acquired-input gain |23.19787|26.28546|
| Native input retention69ns/31ns |0.681005|0.640844|
| Coupled-model gain discrepancy |+1.65%|+1.03%|
| Conditional white RMS,uV |39.6893|36.0881|
| Conditional flicker RMS,1Hz--1GHz,uV |34.8731|34.6570|
| Quadrature FIA-only RMS,uV |52.8334|50.0346|
| With old403uV/gain latch proxy,uV |55.6162|52.3308|
| Native20uV-frame positive-port energy,pJ |1.99374|2.61484|
| Measured current-reuse effective gm/ID,V^-1 |38.5058|38.0516|

The extra reservoir increases event energy31.2% and reservoir capacitance50%,
with unchanged66um² active gate-area proxy. It reduces white noise but barely
changes flicker; no1/sqrt(C) noise law was assumed. The combined conditional
receiver still does not meet50uV before omitted noise sources and new SAR timing.
Referring modeled output noise through the measured rather than model signal
gain changes the3pF FIA-only estimate from50.0346 to50.5208uV, illustrating the
remaining transfer-model uncertainty near the target. This substitution is not
a validated model repair.

Artifacts `independent_floating_l030_cres3_r1` and
`floating_flicker_l030_cres3_r1` under `build/campaign/fia_noise/` retain all
native spectra and charge-model calculations. White adjoint and forward
covariance agree within6ppm. Native flicker exponents remain0.84/1.0. This
controlled point preserves a useful white-noise mechanism while showing that
reservoir enlargement alone has diminishing value once flicker dominates.
