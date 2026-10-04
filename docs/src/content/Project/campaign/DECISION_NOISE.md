# Conditional StrongARM decision-noise experiment

**Current result: no statistically demonstrated noise improvement from 4-fF or
16-fF internal capacitors.** Fresh 256-seed-per-input cohorts give approximately
403.43, 395.93 and 386.80 µV respectively; paired difference intervals include
zero. These remain conditional component estimates, not qualified converter
noise. The historical checkpoints below are preserved; the final section
contains the stronger independent audit.

Historical checkpoint, 2026-09-11 00:20 UTC. The first 288 transient-noise trials give an input-referred
probit sigma of 444.84 µV, with an approximate 95% profile-likelihood interval
of 357.09–566.46 µV. This does not support an assumed 50-µV raw comparator.

The fixture reuses the previously qualified five-geometry StrongARM export
and the separately built VACASK model: corrected BSIM4.8 electrical equations
with legacy BSIM4.5 `tnoimod=1` thermal equations. The earlier native/port gates
and known limitations remain documented in
[the transient-noise investigation](../IMC_TRANSIENT_NOISE_PATH.md).

Nine differential inputs from −2 to +2 mV use 32 independent seeds each, at
TT27 and common mode 0.9 V. The second of two physical reset/evaluation cycles
is observed. All 288 traces complete, resolve and return to reset. Positive
decision counts are 0, 0, 2, 8, 16, 18, 27, 31 and 32 across the ordered
input levels −2000, −1000, −500, −250, 0, 250, 500, 1000 and 2000 µV.

The maximum-likelihood fit uses
`P(positive)=Φ((Vin−Vos)/sigma)` and gives Vos=92.72 µV. This fitted offset
includes finite sampling uncertainty; it is not a measured mismatch offset.
The sigma interval profiles over offset. Unresolved decisions are separately
counted and would disqualify characterization rather than disappear from the
statistics.

Current settings are SDE noise, unit noise amplitude, stochastic LTE floor 30,
maximum step 2 ps and the existing 2-MHz/2-GHz flicker configuration. SDE white
noise is tied to actual integration steps; `noisefmax` is not an established
brick-wall white-noise cutoff. Independently frozen controls are running with
1-ps steps, LTE floor 100 and 4-GHz frequency parameter, at 64 seeds/input.
They must be assessed before upgrading the estimate.

The inputs are stiff noiseless clamps. The circuit has 10-fF output loads,
zero drawn junction area/perimeter, no CMOS output receivers and no SAR DAC.
It therefore cannot directly supply the final-conversion Gaussian parameter
used in model experiments. A SAR has multiple decisions, thresholds and
history-dependent errors. No converter energy is inferred from gross positive
source delivery under stochastic currents.

For design screening only, 445 µV divided by passive voltage gain G is a
conditional estimate if the same comparator noise and signal transfer survive
the real source impedance. Differential useful-half accumulation supplies an
additional factor two relative to a single pooled holder's charge coefficient,
while retaining both native noise contributions. Neither operation removes
switching, mismatch, reference or headroom constraints.

Source: [decision-noise testbench](../../../../../analog/testbenches/tb_imc_decision_noise.py).
Protocol, per-seed outcomes, source/model hashes and fit are in
`build/campaign/decision_noise/tt_sde30_step2_initial/`; individual physical
decks and raw traces are retained under `build/sim/campaign_decision_noise_*`.

## Numerical controls at 64 seeds per input

Three additional settings each complete all 576 traces, including resolution
and closing reset. The same 64-seed indexing is paired between these controls.

| Maximum step / stochastic LTE / frequency parameter | Fitted sigma (µV) | Approximate 95% profile interval (µV) |
|---|---:|---:|
| 1 ps / 30 / 2 GHz | 388.46 | 330.65–459.73 |
| 2 ps / 100 / 2 GHz | 425.38 | 364.74–503.43 |
| 2 ps / 30 / 4 GHz | 405.54 | 345.19–479.95 |

The intervals overlap, but that alone is not a quantitative convergence proof.
A matched 2-ps/LTE30/2-GHz 64-seed baseline and a 0.5-ps control are running.
The original 32-seed-per-input run is retained; its seed-to-input mapping is
not fully paired with the larger cohort.

New physical-diffusion component fixtures at input widths 3.5 and 7 µm pass
native/hybrid deterministic trajectory gates and now have separate noise
trials. Their geometry and scope are recorded in
[clocked gm/ID sizing](LATCH_GMID.md). No old zero-junction noise number is
silently assigned to those new devices.

## Completed controls and geometry-dependent sizing

Checkpoint, 2026-09-11 01:30 UTC. The matched original-geometry 2-ps baseline
gives sigma **412.46 µV [351.08, 488.14]**; the 0.5-ps control gives
**429.30 µV [368.10, 508.07]**, each from 576 complete/reset/resolved traces.
The tested numerical intervals overlap. This is useful sensitivity evidence,
but a statistical convergence qualification has not been asserted.

| Explicit-diffusion variant | Decisions | Fitted sigma (µV) | Approximate 95% profile interval (µV) |
|---|---:|---:|---|
| TT, input W=3.5 µm | 288 | 366.72 | 292.23–470.42 |
| TT, input W=7 µm | 288 | 346.38 | 276.03–444.33 |
| TT, W=3.5 µm, 4-ns clock rise | 576 | 387.10 | 329.49–458.12 |
| TT, W=3.5 µm, 4-fF internal drain caps | 576 | 328.85 | 279.91–392.05 |
| SS85, W=3.5 µm | 576 | 476.09 | 408.22–563.44 |

All traces satisfy the existing completion, resolution and final-reset gates.
The apparent width/capacitance improvements are not statistically established
by these overlapping intervals. The 7-µm input pair also lowers actual loaded
N16 stack gain from 10.6313 to 10.3272 and increases its energy. A noise-only
width comparison would therefore overstate the useful benefit.

The larger full-diffusion baseline cohort is a separate matched control, not
a replacement for the 288-trace result. Every cohort retains its own model,
geometry, seed indexing and numerical settings.

New runs can save only the required observable nodes and source currents.
`compact_io_control/result.json` repeats one identical seed/deck with both
save policies and confirms all eleven retained vectors are bit-identical.
The raw file falls from 12,247,029 to 2,283,463 bytes; the physics and time
steps do not change. Earlier full raw files remain preserved.

For actual repeated decisions, see [latch correlation](LATCH_CORRELATION.md).
Finite-band stochastic simulations do not establish real slow trap-memory
behavior, and stiff input clamps do not reproduce loaded kickback.

## Matched sizing cohort and fresh-seed validation

The 576-trace full-diffusion default completes at **455.26 µV
[387.51, 538.79]**, versus **315.82 µV [268.82, 376.51]** with16-fF
internal drain capacitors. The previous4-fF case is **328.85 µV
[279.91, 392.05]**. The corresponding deterministic ideal-port energies are
114.25,167.83 and127.99fJ/decision. These matched small cohorts initially suggested a noise improvement at an
energy cost. The fresh larger cohorts below do not confirm that suggestion;
neither the default-to-capacitance nor incremental4→16-fF benefit is established. They do not establish loaded
converter noise or physical trap-memory behavior.

A frozen new-seed validation compares all three sizes at256seeds per input,
using seed base197700 instead of97700. Each result remains separate; cohorts
with reused seeds or different seed-to-input mappings are not merged as if
they were independent. The larger old default fit also demonstrates why the
earlier366.72-µV point should not have been promoted to a settled specification.


## Fresh 256-seed-per-input cohorts: apparent benefit not confirmed

All three separately frozen fresh cohorts completed 2304 traces each, with
resolution and closing reset. The nine inputs each contain 256 distinct seeds,
paired between device variants using base197700. The older 64-seed results
remain historical and are not pooled with this validation.

| Internal capacitance per drain | Sigma (µV) | Approximate 95% profile interval (µV) | Positive ideal-port energy (fJ) | Ready at ±2mV (ns) |
|---|---:|---|---:|---:|
| Default | 403.432 | 372.204–437.280 | 114.25 | 2.050 |
| 4 fF | 395.927 | 365.280–429.145 | 127.994 | 2.154 |
| 16 fF | 386.802 | 356.861–419.254 | 167.831 | 2.386 |

An independent audit verifies unique seed/index/input grouping, unchanged
resumed records and parent hashes. The 943/937/953 retained earlier cases
remain unchanged; the resume runner also revalidates their saved decks and
traces rather than resimulating favorable outcomes. Failed outcomes would
remain visible. Independent Fisher-scoring maximum likelihood reproduces all
three sigma estimates within 0.00024µV.

Paired, input-stratified influence-function estimates give the following
approximate 95% intervals for sigma differences:

- 4 fF minus default: −7.505µV [−55.200,+40.190].
- 16 fF minus default: −16.630µV [−66.071,+32.811].
- 16 fF minus4 fF: −9.125µV [−35.938,+17.687].

These conditional asymptotic intervals account for paired seed outcomes and
assume independent realizations across seeds and a probit link. They support
the absence of a demonstrated benefit more directly than comparing marginal
interval overlap. They do not prove equal noise or rule out a smaller benefit.
The Eσ² point estimates worsen approximately 7.9% and35.0% for4 fF and16 fF,
respectively; those ratios are screening estimates, not statistically qualified
energy-noise rankings. Added capacitance also delays the deterministic decision.

Do not retain328.85µV as the settled4 fF comparator parameter. Any downstream
screen using it needs relabeling or sensitivity analysis with the fresh
395.93µV estimate and its uncertainty. Stiff inputs, hybrid-model fidelity,
finite flicker setup and absent loaded ADC remain unchanged limitations.

Audit source: `analog/testbenches/tb_imc_decision_cohort_audit.py`. Results:
`build/campaign/decision_noise/fresh_cohort_independent_audit.json`. Original
fresh cohort names are `tt_iw3p5_geom_n256_fresh_resumed`,
`tt_iw3p5_geom_ci4_n256_fresh_resumed` and
`tt_iw3p5_geom_ci16_n256_fresh_resumed`.
