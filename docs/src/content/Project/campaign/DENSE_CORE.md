# Dense W8 core sizing and timing

Research checkpoint, 2026-09-11 00:45 UTC. The first complete dense low-slice
run passes the predeclared physical charge-residual allocation, while failing
the older raw-MAC gate. Numerical controls and additional corners are still
running. See [population](POPULATION.md) for the architectural context.

## Frozen physical workload

`build/campaign/system_audit/physical_fixture/` contains independently exported
p50 and p95 load cases, each with eight distinct output columns and 256 rows.
Low and high W8 slices are separate signed radix-16 digits. The three physical
activation words use common signed A10 formatting with nine magnitude planes.
The harness never casts them to int8 or requantizes the selected row subset.
Six independent seed-401 calibration words are limited to ±127 but also execute
all nine planes. Their calibration scope is explicit in each manifest.

The p50 low-slice holder capacitance is 6.980 pF per column. High-slice
capacitances range from 0.372 to 1.512 pF. The p95 low slice is 7.684 pF;
its high slice ranges from 1.160 to 1.880 pF. These loads differ substantially
from the sparse legacy fixture's 0.304–0.600 pF. Sparse-array delay and energy
cannot simply be reused for dense W8.

## gm/ID and conductance at the actual switch bias

The characterization uses 0.90/0.91-V switch terminals, NMOS/PMOS gates at
1.8/0 V and bodies at 0/1.8 V. Every device has L=0.15 µm. It measures ID,
gm, gds, Vth, Vdsat and Cgg; `gm/ID` is evaluated at this finite-current bias.
The relevant settling resistance is `1/(gds_n+gds_p)`. Applying a saturation
lookup to a pass switch would not determine its conductance correctly.

| Equal N/P width (µm) | TT27 resistance (Ω) | SS85 resistance (Ω) | TT NMOS gm/ID (V⁻¹) | SS NMOS gm/ID (V⁻¹) |
|---:|---:|---:|---:|---:|
| 0.42 | 33,492.1 | 83,654.6 | 14.257 | 15.034 |
| 3.36 | 2,616.0 | 3,669.9 | 11.780 | 11.274 |
| 13.44 | 574.9 | 670.6 | 11.757 | 9.848 |
| 53.76 | 204.7 | 204.3 | 15.747 | 11.710 |

These controls retain the legacy zero drawn junction geometry. The full
transient variants separately add the installed xschem one-finger diffusion
expressions, including AD/AS/PD/PS and NRD/NRS. Neither is PEX. Native model-bin
changes make width scaling nonuniform; parallel copies of an identical unit
device are a different implementation from one wider device.

For two equal capacitors C joined by a resistance R, the differential settling
time constant is `R C/2`; reset of one capacitor through R uses `R C`.
At C=7 pF and W=53.76 µm, these small-signal estimates are approximately
0.716 and 1.43 ns at TT. They motivate a wide sharing switch and still wider
reset switch, but do not establish transient accuracy, injection or energy.
The current dense probe uses row width 3.36 µm, sharing width 53.76 µm and
reset width 80.64 µm before further optimization.

## Numerical failure and controlled repair

The original dense waveform aborts at 548.95 ns, the start of the first
word-reset transition. Deleting only redundant flat PWL vertices preserves
every represented voltage exactly, but merely moves the abort to 549 ns.
Changing Gear to trapezoidal integration also aborts at that boundary.
Neither result is scored as a physical MAC failure or success.

A separate physical slew control changes the word reset from 50 to 200 ps,
retaining its start time, remaining clocks, devices and tolerances. It reaches
650 ns and matches all 16 observed array/holder traces exactly before the
changed edge. This identifies a usable schedule for full verification; it
does not prove that the original slew is physically invalid.

Explicit diffusion at the original 10-fA current tolerance aborts at time zero.
A separate full-geometry run uses a declared 1-pA absolute tolerance and the
200-ps reset. Current tolerances and native waveforms remain in each manifest;
no global simulator setting or model was changed. Voltage and product-error
gates remain fixed. A converged electrical comparison is required before
using this run as positive evidence.

## Delay variable exposed without changing the baseline

The previous plane period was
`Tplane = Tend_sample + 2.4 ns + Tleading_reset`, tying trailing recovery to
the 16-ns leading reset interval. The research generator now accepts an
independent trailing recovery parameter. With its default omitted, the
generated SPICE deck is byte-identical to the prior version.

Reducing trailing recovery from 16 to 8 ns would change 61→53 ns per plane,
or 549→477 ns for nine planes, if product-error checks pass. This is a proposed
timing change, not a measured speedup. TT/SS sparse loading controls precede
dense qualification. Final held-state readings still occur after row return
and array reset, so shortening recovery cannot hide those disturbances.

## Reproduction and scope

- [Dense workload testbench](../../../../../analog/testbenches/tb_imc_dense_core.py)
- [Preserved numerical controls](../../../../../analog/testbenches/tb_imc_dense_convergence.py)
- [Explicit geometry and waveform transformations](../../../../../analog/testbenches/imc_research_geometry.py)
- Evidence: `build/campaign/dense_core/`, including exact decks, source/fixture
  hashes, logs and incomplete traces.

All capacitors remain ideal components; compiled weight-dependent capacitors
are not a demonstrated programmable SRAM cell. Reference and clock sources
are ideal, with their delivered energy metered. Physical ADC conversion,
noise, local mismatch, routing and complete-memory area remain separate gates.

## First complete dense result

`p50_low_tt_reset200ps_geom_atol1p` completes all six calibration and three
development words, with explicit 0.29-µm diffusion, 200-ps word-reset edges
and declared 1-pA current tolerance. Single-plane RMS/max error is
0.0007/0.0070 MAC. Final product RMS/max is 1.16994/3.04222 raw MAC after the
frozen six-word affine calibration: **FAILED** against the archived 0.25/1
raw-MAC limits.

The measured gain is approximately 0.4928 µV/MAC. Therefore the same final
residual is **0.57657 µV RMS / 1.49924 µV maximum**, equivalent to
0.004024/0.010465 fC using the nominal 6.980-pF native capacitance. Against the
independently predeclared 0.1171875-fC charge quantum, the worst column has
0.05562-LSB RMS and 0.08930-LSB maximum residual. All eight columns pass the
provisional RMS≤1/8 and max≤1/2-LSB deterministic allocation. This screen
does not include random noise, calibration drift, mismatch or a physical ADC.
The old failure is retained rather than relabeled.

Positive delivery is **85.9514 fJ per useful low-slice MAC**, with **549 ns
per nine-plane word**. This includes the ideal core clock/reference ports;
it excludes the high slice, converter, SRAM, physical clock drivers and
reference generation. The geometry/tolerance control without drawn junctions
and a shorter 7.6-ns share aperture are independent ongoing experiments.

## A rejected retention-identification shortcut

Fitting only the voltage immediately before sharing and immediately before
opening gives an apparent r≈0.5016 and 45–109-µV residual. It omits clock-edge
injection and subsequent held-state movement, so its suggested approximately
−45-fF trim is **rejected**.

Using the complete-cycle recurrence
`h[k] = r*h[k−1] + b*plane_sum[k] + offset`, restricted to the calibration
planes and excluding each word's first reset plane, gives
**r=0.50001966–0.50002920**, with 0.152–0.203-µV fit residual. The corresponding
first-order trim proposal is only −0.55 to −0.82 fF, and has not been simulated.
The observation instant is part of the circuit model; apparent capacitor
ratio error cannot be inferred while leaving switching offsets unmodeled.

The independent postprocessing source is
[imc_dense_physical_audit.py](../../../../../scripts/compiler/metrics/imc_dense_physical_audit.py).
`physical_audit.json` retains both gates; `retention_cycle.json` records the
separate complete-cycle calibration fit.

## Recovery timing controls

The sparse connected-capacitor fixture passes TT with 8-ns trailing recovery
(318-ns mean word versus 366 ns), but **fails SS85** with 0.3994/1.2312-MAC
RMS/max over all columns. At 12-ns recovery SS85 passes, with
0.18059/0.51683-MAC RMS/max and 342-ns mean word. These cases use the archived
zero-junction geometry and no ADC; they cannot qualify dense timing. A matched
TT 12-ns run also passes, with 0.04330/0.07925-MAC RMS/max.

## Balanced digits and smaller switches: development results

Checkpoint, 2026-09-11 01:30 UTC. These runs retain the original W8 products
exactly but recode each weight as `q = 16 H + L`, where
`H=floor((q+8)/16)` and `L=q−16H`. Low and high digits can have opposite signs;
the necessary sign storage and decode are not implemented by the ideal
weight-dependent capacitor generator. The frozen p50 low-slice capacitances
become 3.980–4.572 pF. High-slice capacitance and reconstructed noise increase;
the system result cannot be inferred from the low slice alone.

| Physical low-slice case | Row/share/reset widths (µm) | Share hold (ns) | Word (ns) | Ideal-port delivery (fJ/MAC) | Held residual RMS/max (µV) | Worst column RMS/max (provisional ADC LSB) |
|---|---|---:|---:|---:|---|---|
| Original digits, wide | 3.36/53.76/80.64 | 15.6 | 549 | 85.951 | 0.577/1.499 | 0.0556/0.0893 |
| Original digits, shorter share | 3.36/53.76/80.64 | 7.6 | 477 | 85.949 | 1.071/2.876 | 0.1035/0.1713 |
| Balanced digits, wide | 3.36/53.76/80.64 | 15.6 | 549 | 70.486 | 0.645/1.437 | 0.0301/0.0488 |
| Balanced digits, smaller/shorter | 1.68/26.88/53.76 | 7.6 | 477 | 48.423 | 1.278/2.924 | 0.0779/0.1141 |

All four pass the predeclared physical residual allocation, and all four
**fail** the archived raw-MAC gate. In particular, the last case has
1.5801/3.8779 raw-MAC RMS/max error. Reducing only the sharing interval lowers
delay without appreciably lowering ideal switched-source energy. Reducing
switch widths and low-digit capacitance lowers that energy but increases
residual error. These are TT27 development results, not complete W8 MAC or
ADC measurements. Matched original-digit small switches, balanced high slice,
p95 load and SS85 are separate tests, not presumed passes.

The zero-junction 1-pA control completes at 83.621 fJ/MAC and 549 ns, with
0.8124/2.0827-µV held error. It passes the provisional physical screen and
fails the raw-MAC screen. Geometry changes therefore cannot be summarized as
a universal error penalty. A full-diffusion 0.1-pA control is still running.

Exact cases and independent `physical_audit.json` files are retained under
`build/campaign/dense_core/`; no failed result or acceptance gate is replaced.

## Completed matched controls, 2026-09-11 13:30 UTC

The original-digit small-switch case `p50_low_tt_geom_fastsmall_r1`
completes at **63.2941 fJ/slice-MAC and 477 ns**, but **fails both gates**:
65.4065/192.5769 raw-MAC RMS/max, and worst-column 3.4561/5.7197
provisional ADC-LSB RMS/max. Its 32.6093-µV aggregate held RMS error is
substantially larger than the balanced-digit case using these same widths
and schedule. Smaller devices are therefore not qualified for the original
dense loading. The earlier 48.423-fJ balanced result is a combined
representation/sizing improvement, not a width-only improvement.

Balanced high slice `p50_balanced_high_tt_geom_fastsmall` also completes:
**33.0726 fJ/slice-MAC, 477 ns**, raw-MAC RMS/max .730061/1.982726
(old gate **FAILED**), worst-column physical RMS/max .03754/.05608 LSB
(provisional screen **PASS**). Adding two isolated fixture energies does
not establish a complete W8 MAC energy; joint operation, readout, memory,
control and the matched original high slice remain unqualified.

Interrupted old runs remain incomplete. In particular the 0.1-pA full-diffusion
control timed out before its final frame; it is not a positive numerical check.
