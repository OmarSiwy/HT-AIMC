# Independent review of the charge-null SAR experiment

Review begun 2026-09-09. The prototype performs **ten causal comparator-driven SAR decisions**. Its initial three-input SPICE run fails the numerical conversion gate; stronger reset plus a fixed physical reference trim subsequently passes twelve separate validation inputs at TT/27°C and SS/85°C. The ideal split-capacitor arithmetic is correct. This is a research fixture, not a production converter or evidence of a Mythic benchmark win.

The read-only review covers [tb_imc_null_sar.py](../../../../analog/testbenches/tb_imc_null_sar.py), its saved transient traces, the [Mythic nulling research](IMC_MYTHIC_NULLING.md), and the user's [27h10 note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27h10 A Null-Balancing SAR Readout Pays for Precision with Matching Instead of Standing Bias.md>). No additional SPICE runs were launched by this review. Follow-up circuit changes and final results belong in [IMC_NULL_SAR.md](IMC_NULL_SAR.md).

## Charge arithmetic and initial conditions

For coarse bank `CC=63Cu`, fine bank including its sampled dummy `CF=16Cu`, and bridge `CB=16Cu/15`, the fine coupling is `k=CB/(CF+CB)=1/16`. The effective capacitance at coarse node A is `CC+k CF=64Cu`. Resetting both top nodes to VCM while every bottom plate samples VIN gives

```text
a = VA − VCM = VLO − VIN + VSPAN (16 Dcoarse + Dfine)/1024.
```

The ideal implementation's 1,024 interior-code enumeration and explicit two-node linear solve agree. Keeping a trial when the residue is nonpositive produces the intended floor code. The fine dummy must sample VIN too; leaving it fixed during acquisition changes the input gain.

A fixed parasitic `PA` from A to ground changes the residue amplitude to

```text
a = [(CC+k CF)(VLO−VIN) + Cu VSPAN(Dcoarse+k Dfine)]
    / [CC+PA+k CF].
```

Therefore PA attenuates acquisition and DAC steps together and, by itself, does **not** change the ideal null thresholds. A 60-fF load on the nominal 768-fF CDAC gives a residue gain of `768/828=0.927536`. It still increases loading and worsens the input-referred effect of comparator noise and offset. Transistor capacitance is nonlinear, and switching charge injection does not satisfy this fixed-capacitance cancellation argument.

A parasitic `PB` from fine node B to ground changes `k=CB/(CF+PB+CB)` and therefore changes the coarse/fine bit ratio. An independent numerical sweep gives the following endpoint-calibrated maximum INL with the original 12.8-fF bridge:

| PB | Maximum INL |
|---:|---:|
| 1 fF | 0.0718 LSB |
| 4 fF | 0.2832 LSB |
| 8 fF | 0.5559 LSB |
| 16 fF | 1.0722 LSB |

For a known linear PB, the exact bridge correction is `CB=(192 fF+PB)/15`. This is a circuit-model identity, not evidence that a fabricated bridge can be set or calibrated without area, noise, mismatch or settling cost.

The existing 1% bridge perturbation produces only 0.13846-LSB INL after endpoint correction. It demonstrates sensitivity of the math, but cannot be expected to fail a ±1-LSB converter gate. Use a larger physical perturbation or a tighter explicitly separate mathematical test. The precharged-packet negative control correctly rejects treating passive sharing as unattenuated additive charge injection.

## Physical decisions and observed failures

Every bit in the prototype is latched from the real CMOS receiver driven by the StrongARM. The retained bits feed the trial DAC through XSPICE state and physical CMOS mux controls. The final-bit versus receiver checks establish feedback causality; this is a complete ten-step search, rather than repeated reads of one unchanged threshold. Causality does not establish accurate conversion or a realistic controller power budget.

An additional independent trace check reconstructed the ten physical `state` voltages immediately before each comparator edge. All 120 trials in the TT validation and all 120 in the SS validation exactly matched the trial codes implied by previously retained decisions. Thus the feedback check is also consistent with the actual DAC state present at each aperture.

The original TT, 27°C, three-input smoke run used 0.84-µm reset switches. It returned `[3, 484, 989]` for ideal codes `[1, 512, 1022]`: **33-LSB maximum error, FAIL**. At 39.9 ns, just before reset release, A still held +12.034 and +14.206 mV on the second and third frames. B was only −0.200 and −0.230 mV from VCM. The first frame began at an already settled DC operating point. The apparent gain/history failure therefore cannot be attributed merely to the fixed comparator filter capacitance.

The circuit lane's first 3.36-µm reset diagnostic returned `[6, 516, 1023]`: the large history error was reduced, but **5-LSB maximum error remains, FAIL**. A digital offset subtraction alone cannot validate the full input range: the saturated high-end code can conceal missing codes, and subtracting an offset after saturation loses information. A physical reference/offset trim or an explicitly smaller usable input range is required before claiming full-range calibrated conversion.

The initial artifact is [the three-input smoke record](../../../../build/sim/imc_null_sar_n1_f3_tt_27_cb0_cu12_iw3p5_sw1p68_rw0p84_t28_e2_cf60.json); the stronger-reset diagnostic is [imc_null_sar_reset_diagnosis.json](../../../../build/sim/imc_null_sar_reset_diagnosis.json). These results are preserved as failed controls, even if later sizing succeeds.

The follow-up fixes the comparator reference at `VCM−1.900 mV` after the diagnostic, without subtracting a correction from saturated output codes. Twelve distinct validation inputs then pass at both TT/27°C and SS/85°C: maximum error 1 LSB and RMS error 0.577 LSB at each corner. The identical RMS values reflect different patterns of integer errors, not identical codes. The [trim-validation artifact](../../../../build/sim/imc_null_sar_trim_validation.json) reports 2.531 and 2.561 pJ per service, respectively, using the corrected measurement windows. This verifies the stated twelve-input deterministic control; it is not an exhaustive transition, noise, mismatch, or full-range PVT qualification. The physical precision/trim reference circuitry remains unpriced.

The initial twelve-input set is not wholly independent of calibration: the 512.25-code input repeats one of the three calibration voltages, under a different preceding input history. Eleven voltage levels are new. Subsequent sizing sees the entire twelve-input set, so it is a development set thereafter. The planned three-frame, eight-column test supplies 21 fresh random voltage levels on columns 1–7 and three previously seen fixed levels on column 0; reporting all 24 as fresh would also overstate independence.

Subsequent capacitor-proportional switches and half-width latch PMOS reduce energy on the calibration replay, but two faster candidates fail the SS development inputs:

| Candidate | TT result | SS result | Accepted across these corners? |
|---|---|---|---|
| 20-ns decision, 0.5-ns clock edge, 2-ns resolution | 1-LSB max, 2.045 pJ | 3-LSB max, 2.105 pJ | No |
| 23-ns decision, 2-ns clock edge, 2-ns resolution | 1-LSB max, 2.093 pJ | 2-LSB max, 2.096 pJ | No |

The corresponding paid cycles are 265 and 295 ns. Neither TT-only speed/energy number is a passing PVT result. These failures are preserved in [imc_null_sar_sized_suite.json](../../../../build/sim/imc_null_sar_sized_suite.json) and [imc_null_sar_sized_slow_edge_suite.json](../../../../build/sim/imc_null_sar_sized_slow_edge_suite.json). The twelve inputs now serve as development tests, since sizing decisions have seen their outcomes; independent random-column inputs must remain a separate check.

An explicit internal-drain reset experiment, guided by the user's [19u2 precharge note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Comparators/19u2 Precharge Gives the Input Pair Saturation and Erases Node Memory.md>), adds two PMOS switches from the input-pair drain nodes to VDD during comparator reset. Their supply energy and clock-gate delivery enter the existing measured ports. The three-input SS smoke pass does not survive the twelve-input development set: maximum error is 3 LSB, RMS 1.258 LSB, and delivery 2.190 pJ at 23-ns decisions. Restoring the reduced-latch design to the original 28-ns decisions and 4-ns resolution interval without internal resets also fails: maximum error 2 LSB, RMS 0.816 LSB, delivery 2.120 pJ. See [the memory controls](../../../../build/sim/imc_null_sar_memory_controls.json).

The added switches do accomplish their intended precharge action. Across the saved predecision states, the drain nodes reach 1.79984–1.80001 V, with maximum differential 0.140 mV. The longer-window control without these switches has drain voltages 1.1600–1.3153 V and maximum differential 105.6 mV. Receiver settling still leaves at least 1.76 ns before the latch deadline in the explicit-reset case. Therefore unresolved digital output is not the observed failure. Equalizing drain precharge is insufficient to restore conversion accuracy: the new devices also change the transient charge coupled into the held input. Varying input/trial voltages contribute to the observed drain differences; these aggregate ranges do not independently isolate previous-decision memory. The two controls also differ in clock timing, so their kickback magnitudes cannot be used to assign a quantitative isolated-device benefit. No direct-reset efficiency or accuracy improvement is accepted from these tests.

The next repair retains full 1.68-µm input-acquisition switches while grading only the reference switches. With the half-width latch, 23-ns decisions, original 2-ns edges and unchanged trim, both twelve-input development sets pass: 2.1604/2.1961 pJ, maximum error 1 LSB, RMS 0.577/0.645 LSB at TT/SS. The 295-ns cycle improves service rate by 16.95% relative to 345 ns. Relative to the same original twelve-input passing fixture, delivery falls 14.63% at TT and 14.24% at SS. These comparisons include the measured acquisition/reset costs.

The corresponding eight-column TT check completes 24 conversions with maximum error 1 LSB, RMS 0.456 LSB, and 2.01013 pJ per service. An independent trace audit confirms all 240 actual trial DAC states and eight distinct input streams. Integrating the seven positive-delivery group traces over one contiguous window, then dividing by `3 frames × 8 columns`, reproduces 2010.12895457 fJ per service; this independently verifies phase partition and normalization. The differing input mix prevents attributing the lower energy versus the single-column cases to reference amortization.

**The eight-column SS check fails: maximum error 6 LSB, RMS 1.514 LSB, delivery 2.05381 pJ. The 295-ns candidate is therefore not accepted.** An independent trace check verifies all 240 SS trial states and reproduces its contiguous-window energy exactly, so these failures do not arise from a mistaken decoded trial history or energy normalization. Column 2's second input is at code position 250.904, but the converter returns 256; column 6's first input is at 637.082, but returns 640. At the erroneous 256 trial, the predecision residue is only +70 µV and changes to −407 µV during evaluation. At the erroneous 640 trial it is already −153 µV and changes to −1.65 mV. Receiver margins exceed approximately 1.89 ns. These are wrong analog coarse branches with resolved digital outputs. The strict suite stops at this failure before reaching its physical bad-bridge control. See [imc_null_sar_wide_acquisition_suite.json](../../../../build/sim/imc_null_sar_wide_acquisition_suite.json). These random voltages are now development evidence for any subsequent sizing change.

One concrete sizing hypothesis remains: a capacitor driven at its bottom while the common top floats presents approximately `Ci(1−Ci/Ctotal)` to the switch. Sizing reference switches proportional to Ci alone therefore does not equalize their settling times. With a nominal 768-fF coarse bank, the second and third coarse branches have approximately 1.5 and 1.75 times the MSB branch's RC under the existing rule. The fine node has a different effective total capacitance, and transistor/wire loading also changes these ratios. This is an analytical explanation to test, not a demonstrated repair or permission to claim the failed point's speed/energy as accepted.

## Energy and claim boundaries

The port-power expression correctly applies positive-delivery rectification to each source before summing. It includes the ideal stimulus/reference supplies, physical comparator and CMOS gates, external clock delivery, and delivery from XSPICE output bridges to actual gate loads. It does not include XSPICE state-machine internal switching, physical reference generation, clock generation/distribution circuitry, extracted wiring, transient noise, or mismatch.

The initial finite-transient mean is 2.267 pJ per 345-ns cycle. It should not be treated as the steady-state service cost: reset/acquisition start high in the DC solution; only two subsequent reset transitions are paid across three frames; the next reset edge begins in the preceding frame's final 0.1 ns. Thus the original phase labels also assign part of reset to the prior tail. The corrected implementation adds one full warmup conversion and measures each requested input over `[frame−0.1 ns, frame+period−0.1 ns]`, including its paid leading reset transition. The phase intervals tile this complete period without a gap or duplicated edge. Startup is excluded rather than averaged into the service energy. The final appended reset is simulated beyond the measured interval; it should not be described as an additional reset charged to the last result. Sequence-dependent reset/acquisition energy remains specific to the tested input order.

The prototype's shared static VHI/VLO rails and separate local matched CDACs test a charge-cancellation principle. They do **not** reproduce the companion patent's shared binary-weighted reference waveform with small local accumulators or mirrors. That distinction matters because the local capacitor banks currently determine precision, while reference generator area and power remain idealized. [Mythic US10255205B1, claims 4–9 and Figure 4](https://patents.google.com/patent/US10255205B1/en).

Reusing the CDAC as an IMC accumulator also imposes a specific matching constraint. The existing binary radix update requires equal array and hold capacitances: `h_next=(Cacc h+Carr partial)/(Cacc+Carr)` becomes `(h+partial)/2` only when `Cacc=Carr`. The measured 128-row fixture has columns with nominal Carr of approximately 304–600 fF; the fixed 768-fF effective CDAC cannot replace those holders without changing the recurrence. The comparator filter and device loading must also enter the complete connected hold capacitance. Per-column CDAC sizing, array ballast, or another proved accumulation schedule must be modeled. Alternatively, sampling a separate holder pays the **948-fF** input-acquisition capacitance, rather than the 768-fF coarse-node effective capacitance. Under a simple initially neutral passive-sharing assumption, a 696-fF holder would retain only `696/(696+948)=0.4234` of its signal. Actual switch states, parasitics and offset charge must be included before applying that illustrative ratio to a circuit.

The updated normal CLI enforces numerical acceptance and stops on unexpected failure. Only `--allow-failure` bypasses that gate and explicitly labels the result diagnostic. The 30% wrong-bridge case must remain an expected accuracy failure with otherwise completed physical feedback; the exhaustive ideal check gives 4.064-LSB endpoint-calibrated INL for that perturbation. This is a stronger negative control than the earlier 1% case.

The null-current patent supports local comparator-guided balancing, with a common-mode circuit in its differential embodiment. It does not establish that the prototype matches a shipped chip or supply measured converter efficiency for this design. The note's one-LSB-at-every-decision claim is incorrect: an early SAR residue can be a large fraction of full scale. Its derived TIA bias saving cannot be applied again to an accumulator that already has no standing OTA. [Mythic US10389375B1](https://patents.google.com/patent/US10389375B1/en).

The strongest completed finding is that the ideal charge search is sound, saved physical feedback is causal, and the fixed-trim twelve-input control passes two corners with complete service windows. The remaining acceptance work includes broader transitions and range coverage, physical calibration circuitry, matrix acquisition/accumulation integration, and noise-aware model validation. The measured modeled service energy already exceeds the earlier 1.984-pJ W4 and roughly 0.7-pJ W8 per-conversion residual budgets before other missing chip costs; a functional result does not yet meet the efficiency target.

## Simulator compatibility audit: model identity must be checked

The frozen eight-column Sparse/50-ps benchmark reports 56.303 s in subcircuit/parameter expansion and 462,697 lines after expansion. Its log explicitly selects no compatibility mode. The physical hierarchy contains 888 `nfet_01v8` and 880 `pfet_01v8` instances. The installed PDK places all 180 NFET and 108 PFET model bins inside their respective MOS subcircuits, so native expansion copies large local model lists for every instance. Selecting only those two PDK families would retain this per-instance replication.

The exact official `ngspice-43` Git tag was obtained for this read-only audit: commit `2af390f0b12ec460f29464d7325cf3ab5b02d98b`, local source `/tmp/imc-ngspice43-audit`. The installed Nix derivation specifies version 43 with no patches. In `src/main.c:990–1000`, `-D ngbehavior=hsa` sets a string variable before standard initialization, user initialization and circuit loading. Initialization files can override it; the actual circuit log must confirm `Compatibility modes selected: hs a`. No global startup file needs changing. [Official release source](https://sourceforge.net/p/ngspice/ngspice/ci/2af390f0b12ec460f29464d7325cf3ab5b02d98b/tree/src/main.c).

**This is not automatically an identical-model optimization.** `src/frontend/subckt.c:636` enables early bin pruning for HSPICE/Spectre modes, using float32 comparisons with `minimum <= dimension < maximum`. Native `src/spicelib/parser/inpgmod.c:222` also admits either boundary within an absolute 1-nm tolerance. `INPpas1` visits model definitions in source order, while `INPmakeMod` prepends them to the model list; final bin selection returns its first admissible match. Consequently ascending foundry bin definitions produce the following source-predicted differences at L=0.15 µm, independently checked against the installed TT and SS files:

| Width, µm | Native → HSA NFET bin | Native → HSA PFET bin |
|---:|---:|---:|
| 0.42 | 170 → 161 | 107 → 107 |
| 0.735 | 89 → 89 | 89 → 89 |
| 0.84 | 80 → 71 | 89 → 80 |
| 1.00 | 71 → 62 | 80 → 71 |
| 1.26 | 62 → 53 | 71 → 62 |
| 1.68 | 53 → 44 | 53 → 44 |
| 2.25 | 35 → 35 | 35 → 35 |
| 3.36 or 3.50 | 26 → 26 | 26 → 26 |

The benchmark lane subsequently ran a compiled-model audit on all twelve distinct MOS geometries in the frozen TT fixture. It confirms **seven model-bin changes**, exactly as predicted above for those geometries, while W/L, `nf=1`, multiplier and junction geometry remain identical. The 0.735/1.26-µm additions and SS entries in the table remain source predictions rather than compiled checks. Expanded model records fall from 1,728 to 12, demonstrating that early pruning works. The full-PDK twelve-device DC audit takes 3.990 s in native mode and 3.903 s with HSA; this small probe does not measure full-SAR acceleration. Its expected model-equivalence gate fails, and the lane stops before a full-SAR HSA timing claim. See [the compiled-bin audit](../../../../build/research/imc_null_hsa_bin_audit.json). An independent review of its device records confirms all seven differences and the identical geometry fields.

All fixture MOS devices default to `nf=1`, so HSA's use of W/nf for binning does not itself change their dimensions. Other HSA branches affect multiplier propagation, power expressions, early scale handling and DC-sweep convergence. The selected MOS models have no power operators; the closed fixture has no explicit multipliers or behavioral sources and runs a transient. No additional active semantic conflict was identified. HSA remains the officially recommended SKY130 mode, but adopting it changes the selected device models here and requires circuit revalidation. It cannot be recorded as a performance improvement that preserves the existing models. [Ngspice SKY130 guidance](https://ngspice.sourceforge.io/applic.html).

After an operating-point or transient analysis, `showmod m : version lmin lmax wmin wmax` supplies a compact parameter audit; spaces around the colon are required. The benchmark also uses `set altshow` with `show m : w l nf ad as pd ps m` to obtain untruncated compiled model names. Its expanded listings preserve model names/counts but warn that long parameter lines are truncated; those listings must not be reused as complete simulation decks. No SPICE was run by this review lane. [Ngspice 43 manual, §13.5.83](https://ngspice.sourceforge.io/docs/ngspice-43-manual.pdf).

## Passive filter: signal attenuation enters the noise budget

For the ideal split CDAC after all bottoms settle to stiff references, eliminating the fine node gives a holder capacitance `Ch=756+12.8−12.8²/(192+12.8)=768 fF`. A filter capacitor `Cp` behind the positive input resistor adds to this capacitance at equilibrium. The settled residue gain is therefore `a=Ch/(Ch+Cp)` for both the sampled input and the DAC contribution. An independent NumPy check over all 1,024 code states and four filter capacitances reproduced this gain. It does not move ideal null thresholds, but amplifies input-referred comparator/filter errors.

For a stationary resistor-only model, a floating positive holder and independent negative branch tied through an identical resistor to an ideal reference give `var_p=kT Ch/[Cp(Ch+Cp)]` and `var_n=kT/Cp`. Dividing their sum by `a²` gives `var_input=(kT/Ch)(2/x+3+x)`, where `x=Cp/Ch`. At 300.15 K the minimum occurs at `x=√2`, yielding 177.340 µV RMS for Ch=768 fF; 100 µV would require Ch≥2.41531 pF within this model. The existing Cp=60 fF gives gain 0.927536 and 393.374 µV RMS input-referred instantaneous resistor noise.

This calculation does not establish a clocked-ADC noise floor. A finite aperture or averaging changes the noise covariance and potentially the signal gain; sampled reset noise, switch noise, comparator noise and parasitic capacitances also need their actual acquisition/evaluation schedule. It is a sizing check for the stated stationary instantaneous model, not a validated transistor-noise result.

## RC grading and fresh-input audit

The RC-aware repair widens only the coarse weight-256 and weight-128 reference
switches to 1.26 and 0.735 µm. It preserves the 295-ns cycle, full acquisition
switches and −1.9-mV trim. The twelve-input TT/SS development checks pass at
2176.88/2170.78 fJ per service; the development eight-column checks pass at
2025.16/2059.68 fJ. The physical 30% bridge-error control fails as intended,
returning 27/512 for targets 31/511, with intact causal feedback. These completed
gates are in [the RC suite](../../../../build/sim/imc_null_sar_rc_suite.json).

The separately frozen seed-9952 eight-column set passes at TT but **fails at SS**:
the third measured frame, column 7, returns 807 for input code position 809.307.
Maximum error is 2 LSB. The first wrong branch rejects trial 808 despite the
input being above it; the recorded predecision residue is +773.8 µV and changes
to −2208.9 µV during evaluation. Therefore this repair is still not accepted
across the completed checks. Its earlier passing development suite is not
evidence of convergence over fresh inputs.

An independent raw-trace audit of both development and fresh SS cases checks all
240 physical trial states per case, independently reconstructs final codes, and
integrates the seven delivery traces over one contiguous interval covering
exactly three measured frames. Division by 24 column services reproduces
2059.6842597 and 2060.8349742 fJ respectively. Thus the fresh failure is not a
digital decode or phase-energy-normalization error.
[Independent trace results](../../../../build/research/imc_null_rc_independent_trace_audit.json),
[fresh SS result](../../../../build/sim/imc_null_sar_rc_fresh_ss.json).

## Physical VCM-start branch: read-only topology audit

The experimental branch uses the user's three-level schedule: ten comparisons,
nine one-way capacitor changes, and a final read-only bit. Each column has its
own isolated VHI/VLO/VCM rails. During acquisition, the VCM rail floats and all
bottoms sample that column's input; isolation prevents columns with different
inputs from shorting through a shared rail. Merging the unused LSB capacitor
with the dummy makes it 24 fF and preserves the 192-fF fine-bank total and the
nominal 79-Cu acquisition load.

The actual retained bit selects a physical direction mux, followed by a second
TG mux selecting that rail or VCM. A delayed valid signal permits the FF and
direction path to propagate before the capacitor changes. Source accounting
includes the new physical inverters, two-stage TG paths and reference-isolation
switches. The trial assertion reconstructs ternary states from measured bottom
voltages. This checks topology and causality; the extra resistance, overlap,
rail motion and common-mode error still require physical input coverage.

The initial three-input TT/SS calibration replays pass at 1432.40/1459.77 fJ;
these narrow checks do not establish a new accepted converter. Their original
postdecision sample occurred after the intended DAC update. Future VCM runs
sample at latch-start +0.8 ns, before valid starts at +1.5 ns, so the reported
evaluation disturbance excludes that deliberate update. The old smoke energy
and codes are unaffected, but its postdecision residue must not be interpreted
as isolated comparator kickback.

## Native-pruner implementation review

The isolated opt-in native-bin experiment retains a union of every model bin
that could match a supported literal geometry, preserves original card order,
and leaves final native model selection unchanged. Unlike the HSA branch it
retains native endpoint tolerance. Unsupported geometry, parameter scopes,
active randomness or conflicting scale settings must retain the original deck.

Literal geometry does not bypass numparam rounding: its `fetchnumber` reads
with `sscanf("%lG")`, and `double_to_string` writes 15 digits after the decimal
in scientific notation. For the allowed direct `{w}`/`{l}` wrapper bindings,
the helper must reproduce `sscanf → %.15e → INPevaluate`, then apply native
scale. Using the raw invocation's `INPevaluate` result alone can miss a bin
near the strict 1-nm tolerance boundary. Duplicate geometry assignments must
be rejected even when the duplicate has a different expression.

Even zero times AGAUSS may consume RNG draws. The nominal-only guard therefore
requires each stochastic model/parameter expression independently to be a
literal nominal plus a zero global MC switch times AGAUSS, optionally times a
deterministic factor; substring membership in a model card is insufficient.
It forbids active circuit stochastic sources and scope/control overrides.
This proof concerns audited valid PDK expressions; it does not claim to
preserve arbitrary malformed unselected-model diagnostics.

The ngspice43 BSIM4v5 model-ask implementation has another audit trap: ten
parameters are listed and writable but have no `b4v5mask.c` read case:
`lintnoi`, `llambda`, `lvtl`, `lxn`, `wlambda`, `wvtl`, `wxn`, `plambda`,
`pvtl`, `pxn`. Their `showmod` values are not valid coefficient evidence.
Exclude only these unreadable fields from the runtime fingerprint, document
the limitation, and preserve their actual selected-card coefficients. This
does not establish that the parameters are absent or electrically inactive.

## VCM physical startup-pulse review

The opt-in first-frame comparator pulse spans 0.2–7.2 ns with the current
2-ns edges. Both CDAC top nodes remain clamped and no SAR decision latch fires
there. All later frames retain the original clocks; a complete physical
warmup conversion still precedes the measured interval. It is a paid startup
operation rather than an imposed initial voltage or omitted acquisition.

The matched TT8 one-measured-frame control preserves all eight final codes,
80 trial states and 80 causal decisions. Maximum sampled residue change is
0.0355 µV; receiver-ready time changes by 3.78 ps. Measured positive source
delivery changes by 0.0371%, while separately integrated warmup delivery rises
by 106.84 fJ/column. Startup accounting explicitly excludes initial DC stored
charge. The comparison integrates the full delivered-power channels and
uses the same per-column service normalization.

Whole-run transient iterations fall from 502,937 to 78,373; observed wall time
falls from 568.1 s to 94.5 s for this matched input/control. The original
comparison JSON placed these whole-run iteration counts inside a `warmup`
object; the corrected artifact names them at top level. This is one functional
speed observation, not universal runtime scaling or full converter acceptance.
[Comparison artifact](../../../../build/sim/imc_null_sar_startup_equivalence.json).

The first 24-code TT8 VCM suite result passes ±1 LSB at 1350.54 fJ/service.
The subsequent SS8 development case fails by up to five LSB at 1377.14 fJ;
input code position 763.817 produces 768. The strict runner stops, so this
point is not accepted and its energy cannot headline an accurate converter.
The stiff-HI/LO topology remains a separate rejected experiment after its
TT12 run ended incomplete, despite passing three calibration inputs.

## Reference-width and bottom-voltage audit

Independent review of the scalar-holder SS85 column-5 replay confirms the
same three input voltages, frozen −700-µV trim, acquisition/reset/comparator
sizes, initialization and timing before and after reference sizing. The deck
diff changes only six reference-TG subcircuit widths and the title. Scaling
occurs before the minimum-width floor, so it does not double every small
device. Acquisition remains at 1.68 µm in these runs. A discovered option
guard hole allowed scaled acquisition when `wide_acquisition` was false;
the API and CLI now require both wide acquisition and RC grading for a
non-unit reference-width scale. Existing results already used both flags.

For this exact history, codes improve from 588/747/768 to the target
587/746/763. Positive delivery changes from **1382.817232 to 1431.706544
fJ/service: +48.889312 fJ, or +3.53549%**. Signed net delivery changes from
821.001862 to 819.496135 fJ/service, **−0.18340%**. These are distinct energy
boundaries; the positive-delivery increase must not be replaced with the net
decrease. The separate TT calibration comparison increases positive delivery
by 2.11674%, so it is not the same-case SS comparison.
[Original holder replay](../../../../build/sim/imc_null_sar_vcm_negative_hold_replay_ss_col5.json),
[Wider-reference replay](../../../../build/sim/imc_null_sar_vcm_negative_hold_refs2_replay_ss_col5.json).

The new commanded-rail targets use actual earlier receiver decisions, with
correct bit activation timing and a doubled fine dummy. Independently
assembling both capacitor-node equations from all saved bottom voltages
reproduces the reported weighted error for all 30 repaired decisions within
1.58e-10 µV. Its maximum is 0.232918429 LSB. The metric excludes filter/MOS
loading and acquisition/comparator offset; it is a settling diagnostic,
not a complete input-error or noise bound. Bottom errors already include
local rail droop, which must **not** be added again from the separately
reported reference-error channels.

At trial 768, the exact holder replay's MSB error falls from −8454.121 to
−424.509 µV; weighted bottom error changes from −2292.812 to −113.730 µV.
The comparator's predecision differential moves from +201.427 to
+2396.956 µV, while its negative gate changes by only +1.241 µV. This strongly
supports the reference-settling repair, while switch injection and loading
also change with width. The −13.5-µV figure above belongs to the older
no-holder case and must not be substituted for this paired control.
No new SPICE was run for this review; the larger strict circuit suite remains
the qualification gate.

The completed `imc_null_sar_vcm_negative_hold_refs2_suite.json` now passes all
five development controls: TT/SS 12-input scalar cases, TT/SS 24-code shared
eight-column cases, and the expected failing bridge control. Independently
reconstructing every code and ten trial thresholds from the saved decisions
matches the artifact; all phase/component energy sums also reconcile. The
shared cases remain within one LSB at 1417.243 fJ/service TT and 1451.395 fJ
SS, under the stated ideal-source/XSPICE boundary. The 30% bridge perturbation
produces 27/509 versus 31/511 with valid feedback, correctly failing transfer
accuracy by four LSB. This is development evidence for the fixed reference
width, not yet the reserved-input qualification or a noise result. This review
uses the completed saved results and does not rerun SPICE.
