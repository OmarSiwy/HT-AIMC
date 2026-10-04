# Clocked comparator sizing with gm/ID

**Current sizing interpretation:** fresh 256-seed-per-input noise cohorts do not
confirm a statistically significant benefit from internal drain capacitance.
The deterministic energy and delay penalties remain. Historical gm/ID
trajectories below are valid characterization; none establishes an optimum.

Checkpoint, 2026-09-11 00:45 UTC. The input pair is characterized along its
real reset/evaluation trajectory. A single assigned gm/ID number cannot
describe the whole dynamic latch: body voltage, drain voltage, tail current
and regeneration change throughout the decision.

The two-cycle fixture uses ±2-mV differential ideal inputs at 0.9-V common
mode, a 2-ns clock edge, 10-fF output loads and the existing 0.42-µm tail.
All devices have L=0.15 µm. New widths use separately exported native PDK
model bins, retaining native BSIM4.5; the noise-capable hybrid is qualified
against that reference for each sizing.

| Input width / geometry | Integral gm over 25–27 ns (fF) | Active input gm/ID range (V⁻¹) | Peak intrinsic Cgg (fF) | Positive ideal-port energy (fJ/decision) | Ready from clock start (ns) |
|---|---:|---:|---:|---:|---:|
| 3.5 µm / zero junction | 278.39 | 11.81–21.58 | 2.93 | 100.71 | 1.943 |
| 7 µm / zero junction | 363.04 | 11.60–22.55 | 5.94 | 114.47 | 1.886 |
| 3.5 µm / 0.29-µm diffusion | 272.19 | 11.97–22.33 | 2.91 | 114.25 | 2.050 |
| 7 µm / 0.29-µm diffusion | 337.21 | 12.13–24.05 | 5.86 | 134.27 | 2.007 |

Values shown are the positive-input branch. The negative-input branch is
also simulated and retained. The active gm/ID range uses gm above 10% of its
trajectory peak and |ID|>1 pA; it does not divide by reset leakage. Intrinsic
Cgg omits overlap capacitance, and the finite-window gm integral is a sizing
diagnostic, not a noise integral or a universal noise formula.

Both widths and both geometries pass the existing native/hybrid trace,
decision-time and energy gates. At 14-µm input width the native model export
passes exact serialization, but the hybrid transient aborts: **UNVERIFIED**
for dynamic noise. Its failure log is retained. Native4.8 derivative-field
differences from4.5 remain known limitations of the hybrid, even where the
specific dynamic trajectory comparison passes.

For a passive stack, larger input transistors also increase loading and
kickback. Their noise must be divided by the actual loaded signal gain, and
their extra decision energy must be paid. Statistical noise runs for the
3.5- and7-µm physical-diffusion fixtures are ongoing. There is no demonstrated
complete-column optimum yet.

Sources: [clocked sizing testbench](../../../../../analog/testbenches/tb_imc_latch_gmid.py),
[native model exporter](../../../../../analog/testbenches/tb_imc_latch_model_export.py).
Evidence is under `build/campaign/latch_gmid/`, with exact exported models,
source hashes, time-dependent device parameters and both simulator traces.

## Clock slew, internal capacitance and hot/slow corner

Checkpoint, 2026-09-11 01:30 UTC. These additional 3.5-µm input-pair fixtures
all include 0.29-µm diffusion and pass the same deterministic native/hybrid
qualification. Internal capacitance means equal grounded capacitors on the
two input-pair drain nodes; it is not extra input or output capacitance.

| Case | gm integration window (ns) | Integral gm (fF) | Active gm/ID (V⁻¹) | Ideal-port energy (fJ) | Ready (ns) |
|---|---|---:|---|---:|---:|
| TT, 4-ns clock rise | 25–29 | 506.735 | 6.81–21.67 | 114.352 | 3.296 |
| TT, 4-fF internal capacitors | 25–27 | 286.811 | 14.60–22.22 | 127.994 | 2.154 |
| TT, 16-fF internal capacitors | 25–27 | 299.234 | 14.78–21.98 | 167.831 | 2.386 |
| SS85, original 2-ns rise | 25–27 | 151.236 | 14.56–18.96 | 119.466 | 2.578 |
| SS85, 4-fF internal capacitors | 25–27 | 153.150 | 14.43–18.89 | 133.000 | 2.734 |

The longer clock edge increases the finite-window gm integral but has not
demonstrated lower noise. The internal-capacitance variant has a lower fitted
noise point estimate with overlapping uncertainty intervals and 12% more
ideal-port energy. See [decision noise](DECISION_NOISE.md). Additional
internal capacitance is established comparator practice, not a novelty claim.
Loaded-source kickback and complete-conversion quality remain separate tests.

The added rows were completed by 02:00 UTC. The matched TT 64-seed-per-input
noise cohorts give 455.26 µV for the original physical geometry, 328.85 µV
with 4 fF and 315.82 µV with 16 fF. The last two confidence intervals overlap
substantially; four times the added capacitance has not established a further
noise improvement. Fresh 256-seed-per-input cohorts use a separate seed base
and retain the original fitted-noise procedure. No complete-column optimum
is inferred from these ideal-input measurements.


## Fresh-cohort correction to the sizing interpretation

The independently audited 256-seed-per-input cohorts give default 403.432µV,
4 fF395.927µV and16 fF386.802µV. Approximate 95% paired difference intervals
include zero for every comparison; see [decision noise](DECISION_NOISE.md).
The earlier 64-seed point estimates 455.26/328.85/315.82µV are preserved as
historical observations, not the current sizing basis.

The finite-window gm integral rising 272.19→286.811→299.234 fF did not establish
a commensurate decision-noise improvement. It omits time-varying noise
weighting, regenerative dynamics and the remainder of the trajectory.
Capacitance still increases deterministic ideal-port energy 114.25→127.994
→167.831fJ and ±2mV decision time 2.050→2.154→2.386ns. With fresh noise
point estimates, Eσ² worsens about 7.9%/35.0%; uncertainty prevents treating
those point ratios as a proven statistical ranking.

Retain the default as the lower-energy characterization baseline unless a
loaded-source or complete-converter test demonstrates a compensating benefit.
A 4 fF variant may still help a separately measured kickback or timing constraint,
but its older 329µV noise estimate is not a qualified justification. No new
geometry or optimum is inferred from this audit.
