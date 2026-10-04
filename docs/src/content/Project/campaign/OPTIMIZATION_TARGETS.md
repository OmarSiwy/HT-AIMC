# Analog IMC optimization contract

Updated 2026-09-11 following the user's explicit requests for minimal area,
delay and power, continued breakthrough research, and gm/ID sizing. This
contract governs candidate comparisons in the extended 48-hour campaign.
The old AnalogIOC assumption of unlimited area is superseded by the user's
current objective. Existing failed tests and frozen acceptance gates remain.

## Primary optimization fields

| Field | Quantity minimized | What must be included | How it is established |
|---|---|---|---|
| Area | Total implemented area in mm² at fixed useful resident weight capacity | Storage, every installed capacitor, compute devices, holders, ADC/DAC, references, clocks, calibration state, routing and integration overhead | Device/cap inventory is an initial lower bound; layout/DRC/LVS/PEX is the stronger evidence |
| Delay | End-to-end first-result latency and declared tail latency | Input encoding/loading, compute, hold/acquisition, conversion, digital reconstruction, transport and queueing | Complete physical schedules plus counted digital/service dependencies |
| Power | Average total power at a fixed useful result rate, workload and operating point | Dynamic supply energy, leakage, reference/bias power, refresh/programming, calibration, clocks and transport | Metered physical ports and implementation-specific peripheral estimates, with boundaries explicit |

Also retain energy per useful correct MAC/MVM/token, initiation interval,
sustained throughput, area per resident useful weight, peak current, calibration
time and retention interval. These expose trades hidden by any one primary
field. An idle circuit can have low power while doing no useful work; it does
not beat a running circuit. A pipeline can reduce initiation interval while
increasing area or first-result latency. All three quantities remain visible.

For candidate parameters θ, the core search is

\[
\min_\theta\big(A(\theta),\;L(\theta),\;P(\theta;r_\mathrm{req})\big),
\qquad \theta\in\mathcal F.
\]

The feasible set fixes workload, useful arithmetic/quality, resident capacity,
required service rate and environmental conditions. Candidate θ₁ dominates θ₂
only if it is no worse in every primary field, strictly better in at least one,
and meets the same constraints at the same operating point. Keep nondominated
candidates. A product such as area×energy×delay may be displayed as a secondary
summary after feasibility; it cannot excuse a failed accuracy or throughput gate.
Unknown area, noise or peripheral power is recorded as unknown, never zero.

“Best” means the strongest verified Pareto point among the tested feasible
designs. A globally optimal architecture needs a valid lower bound or an
exhaustive proof over a stated design space; this campaign has neither yet.

## Measurement equations and boundaries

For a completed service containing M useful MACs,

\[
E_\mathrm{MAC}=E_\mathrm{service}/M,\quad
R_\mathrm{MAC}=M/T_\mathrm{II},\quad
\eta_\mathrm{native}[\mathrm{TOPS/W}]=2/E_\mathrm{MAC}[\mathrm{pJ}].
\]

The factor two counts multiplication and accumulation separately. Bitwise
normalized operations, padded work and repeated trials are recorded separately
from useful native operations. A low/high digit pair collectively produces
one W8 MAC; neither slice alone is a complete W8 energy measurement.

At a required useful service rate r,

\[
P_\mathrm{avg}=r E_\mathrm{dynamic/service}+P_\mathrm{static}
+E_\mathrm{refresh}/T_\mathrm{refresh}
+E_\mathrm{cal}/T_\mathrm{cal}.
\]

Amortization intervals and uptime must be stated. Supply current integration
reports both signed net energy and gross positive delivery at each ideal port.
They are different accounting boundaries: ideal reference energy returned by
one port does not prove a real regulator recovers it. Conversely, charging a
current-path supply estimate again after counting that same path at its drain
double counts energy. Physical reference/clock circuits ultimately determine
the chip boundary.

A serial two-stage schedule has approximately `L=Tcompute+Tread`; an ideal
two-bank overlap can approach `II=max(Tcompute,Tread)`, only if actual storage,
switching, reset and transport allow it. More generally,

\[
T_\mathrm{II}\ge\max\left(T_\mathrm{compute\ resource},
\frac{N_\mathrm{conversions}T_\mathrm{conversion}}{N_\mathrm{ADCs}},
T_\mathrm{transport\ resource}\right).
\]

This is a lower bound, not a guaranteed schedule. Converter sharing, exceptional
range corrections and pipeline occupancy can add stalls. Report average,
worst observed and declared percentile service times instead of selecting
only a favorable input.

## Feasibility gates

1. **Useful arithmetic and model quality.** Preserve exact signed W8
   reconstruction for format changes unless approximation is explicitly part
   of the candidate. Current development quality gates require KL≤0.01 and
   observed perplexity ratio≤1.01 on every declared passage/noise-seed case.
   Calibration uses its frozen earlier corpus. Reserved passages remain
   untouched until a candidate and its parameters are frozen. These are
   project quality gates, not a universal analog SNR or published benchmark.
2. **Physical correctness.** Check charge/current conservation, device regions,
   supply/headroom, startup, common mode, complete transient duration,
   feedback decisions, final reset, stability where feedback applies, and
   signal history. An incomplete SPICE run is numerical failure, not proof
   of a physical failure or a pass.
3. **Error budget.** Keep deterministic gain/nonlinearity, random thermal and
   flicker noise, mismatch, drift, clipping and ADC decision history separate
   until their actual joint behavior is verified. The existing dense
   deterministic screen is per-column RMS≤1/8 and max≤1/2 of the declared
   0.1171875-fC charge quantum. It cannot silently follow a new ADC span or
   replace the separately retained historical raw-MAC gate.
4. **Operating range and yield.** State every tested process corner, supply,
   temperature and mismatch population. TT27 and SS85 are initial controls;
   all five PDK corners and additional supply/temperature conditions remain
   required research coverage for a robust claim. A seed count and confidence
   bound accompany a yield claim; zero observed failures is not proof of
   zero failure probability.
5. **Capacity and service.** Count physical programmable storage, not merely
   compiled ideal weight-dependent capacitors. Fix equal useful capacity and
   converter resources for the relevant comparison, or show their explicit
   tradeoff. Time-multiplexed external weights pay loading/storage traffic.
6. **Numerical validity.** Preserve source/model/deck hashes, numerical
   tolerances and timestep controls. A modified simulator must qualify
   against the native model on the relevant geometry and trajectory. No
   convergence setting is a substitute for matching electrical results.

## Free design variables

| Level | Variables worth searching |
|---|---|
| Devices | Device family, L, gm/ID or current density, W/finger count, actual VDS/VSB, body connection, bias and supply |
| Switches | N/P sizes independently, on-conductance over the real signal range, clock slew, nonoverlap, sampling order, midpoint versus endpoint topology |
| Charge storage | Capacitor technology/units, low/high digit scaling, installed versus connected banks, parasitic exploitation, reset strategy, retained-state count |
| Representation | Linear/logarithmic/current/time domain, signed digit radix, common activation scaling, bit planes, redundancy, differential coding and reconstruction |
| Readout | ADC architecture/depth, fixed charge versus fixed voltage quantum, column sharing, range guards, passive/active gain, decision schedule and calibration |
| Pipeline | Direct native holders versus sampled copies, stage boundaries, banks, resource reuse, asynchronous scheduling, transport and stall policy |
| System | Tile dimensions, memory capacity/reuse, group length, per-layer precision, protection of sensitive operations, calibration/refresh cadence |

Retain branches with genuinely different mechanisms. Current charge-domain,
current/PWM, logarithmic conversion, passive gain, direct native-state pipeline
and representation branches are examples. Failed architectures can contribute
valid subcircuits or identities. New combinations receive independent tests;
separately passing components do not certify their connection.

## gm/ID sizing procedure

The primary local references are the user's
[five-step sizing flow](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/gm-ID Sizing Methodology/16h The Five-Step gm-ID Sizing Flow Replaces SPICE Iteration.md>),
[gain/speed tradeoff](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/gm-ID Sizing Methodology/16i Transit Frequency And Intrinsic Gain Trade Against Each Other.md>)
and [matching versus gm/ID](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Nonlinearity and Mismatch/12s2 At Fixed Area A Mirror Wants The Smallest gm-ID Headroom Allows.md>).
Sampling, switched-capacitor, OTA, pipeline ADC, noise, mismatch and layout
notes also inform the architecture; their approximations must be checked.

For an applicable single-pole amplifier, a bandwidth/settling requirement
sets gm through `gm≈2π fu CL`. Choose L and η=gm/ID using native PDK tables
at the actual VDS/VSB, then `ID=gm/η` and `W=ID/(ID/W)`. Check gm/gds,
gm/(2πCgg), device-region/headroom, total parasitic loading and the actual
noise spectrum. Recompute when self-loading or a model-bin change matters.
Weak inversion's gm/ID plateau does not uniquely specify current density.
The textbook `VDSsat≈2/η` is a strong-inversion approximation; use native
device operating points for signoff.

For pass switches, use measured triode differential conductance at the real
terminal voltages. The relevant equal-capacitor sharing time constant is
`τ=Ron C/2`, and a clamp reset uses `τ=Ron C`. Saturation gm/ID alone does not
set Ron. Actual gate charge, injection, body effects and complementary-device
asymmetry determine the energy/error tradeoff.

For a dynamic comparator, characterize gm/ID, current, capacitances and device
regions along the reset/evaluation trajectory. A finite-window integral of gm
is a diagnostic, not a replacement for time-varying noise analysis. Report
input-referred noise after actual loaded gain, including kickback and signal
history. Independent repeated Gaussian decisions cannot be assumed from a
single static noise number.

The simplified mismatch sensitivity
`δID/ID≈(gm/ID)δVTH+(gds/ID)δVDS+…` explains why maximum gm/ID is not always
the minimum-area precision choice. Current efficiency, matching, headroom
and speed can select different inversion levels. Process-specific mismatch
constants and covariance are required for quantitative yield.

## Baselines, novelty and evidence levels

Use the [SoTA evidence map](SOTA_EVIDENCE.md) and strongest optimized internal
baseline. Macro measurements, chip measurements, vendor specifications and
simulations remain separate. Do not combine peak power efficiency and peak
throughput from different voltages, or claim process normalization by simply
squaring process-node names. The appropriate first comparison is a matched
SKY130 implementation; cross-process competitor claims need explicit physical
and system evidence.

Each retained claim is labeled VERIFIED within its stated model, STRONGLY
SUPPORTED, SPECULATIVE or FAILED. Novelty requires a targeted paper/patent/
thesis search after the specific mechanism is identified. Minimal area, delay
and power are engineering objectives; “different” is not an optimization metric.

## Evidence retention and build cleanup

The user explicitly authorized periodic build cleanup. Keep compact results,
protocols, hashes, source/deck snapshots and failure summaries. The first
cleanup losslessly compresses completed noise raw traces, verifies their full
SHA256 after decompression, then removes only the uncompressed copy. Every
file has a restore record. Active simulations, pinned tools, model dependencies
and source files are excluded. Monitor disk space as new batches complete;
do not confuse disk occupancy with the simulator's active RAM requirement.
