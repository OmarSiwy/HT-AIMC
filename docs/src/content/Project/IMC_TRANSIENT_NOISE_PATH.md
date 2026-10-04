# Executable path to clocked comparator noise characterization

2026-09-09. Tool/model investigation and isolated bootstrap. Native RC noise
and device model-revision checks now run; an isolated VA derivative repair
restores stationary-noise agreement with native 4.8.2. The sized comparator
passes deterministic migration and exploratory intrinsic-noise replay gates.
Input-referred comparator noise remains unqualified. No PDK, project-flow or
global-configuration change was made.

## Finding

The installed ngspice 43 can measure deterministic decision margin and response
to explicitly injected noise. It does not turn the StrongARM's BSIM noise
sources into stochastic transient currents automatically. Current upstream
VACASK implements that facility and has now been built in the isolated research
directory. Its upstream RC noise gate passes. Its supplied SPICE-compatible
BSIM4 model implements 4.8 rather than the BSIM4.5 selected by this project's
Sky130 files. Native ngspice drain currents and stored charges agree at the
sampled sizes and biases, but four source/body capacitance derivatives and
stationary noise differ across revisions. A finite-difference audit identifies
an incorrect body-charge Jacobian in 4.5; actual clocked traces still need comparison.
The VA port also required a separately compiled derivative repair. Its bounded
clocked sanity check now passes with explicit numerical settings; full sampled
circuit and stochastic convergence qualification remain necessary before a
Sky130 input-noise specification.

Passing deterministic ±1 LSB trials does not establish 100 µV temporal noise.
The estimate in `components/strongarm/strongarm.py` and the deterministic
polarity/delay tests in `tb_strongarm.py` do not close this requirement.

## What exists locally

| Item | Read-only result |
|---|---|
| Project ngspice | `build/ngspice43/bin/ngspice`, version 43, KLU enabled; its store output is `bghwf4iqccaykqw6vv65dq68pn0xnz0x-ngspice-43` |
| PATH ngspice | Version 44.2; use the project resolver to avoid an accidental change |
| VACASK, OpenVAF, Xyce | No executable in PATH or corresponding installed store output found |
| Isolated research stack, now built | `build/research/transient_noise/install/bin/vacask`, pinned OpenVAF, 53 bundled OSDI models and Python runtime assets; upstream RC gate passes |
| Older MVM/AnalogIOC Nix recipes | Present as source files; this is not evidence of installed tools |
| Old AnalogIOC banner | `vacask --version ... || echo 'available'` reports availability even on failure |

In ngspice 43, `.noise` linearizes around a DC operating point. `TRNOISE` is an
explicit independent source; its Gaussian amplitude is a sample RMS, not a
device noise model or a voltage spectral density. `setseed` makes experiments
reproducible. These support source-susceptibility experiments and calibrated RC
controls, but ordinary `.tran` does not automatically activate transistor
thermal/flicker sources. Changing the TRNOISE sample interval at fixed sample
RMS also changes the spectrum. [Official ngspice 43 manual, §§1.2.7, 4.1.7,
11.3.4, 11.3.11](https://ngspice.sourceforge.io/docs/ngspice-43-manual.pdf)

The existing Xyce recipe does not provide an installed alternative. An Xyce
small-signal NOISE analysis would still not measure a clocked latch's temporal
decision uncertainty.

## Native transient noise is implemented in current VACASK

Pin the inspected upstream source to
`0212881e5a87cce91476cd86b9f59673f6da8e9a`. Its transient analysis accepts
`noisefmax`, `noisefmin`, `noiseseed`, `noisescale`, `noisemode` and `oversample`.
Nonzero `noisefmax` activates intrinsic white and flicker sources. Both ZOH and
SDE generators exist. The maximum timestep is bounded by
`1/(2 × oversample × noisefmax)`, in addition to ordinary integration limits.
This is implemented functionality, not a roadmap item.
[Pinned transient-noise documentation](https://codeberg.org/arpadbuermen/VACASK/src/commit/0212881e5a87cce91476cd86b9f59673f6da8e9a/docs/cmd-analysis-trannoise.md)

Use the default or full device variants. The faster `sn` variants simplify
noise for ordinary small-signal analysis and are unsuitable for this task.
[Pinned model-variant documentation](https://codeberg.org/arpadbuermen/VACASK/src/commit/0212881e5a87cce91476cd86b9f59673f6da8e9a/README.md)

The older local VACASK recipe pins `robtaylor/VACASK` at
`bcd48e2dd25182f5aaa3392c4e27b4e198372744`. Its inspected transient header lacks
these noise controls. Its install phase copies only the simulator executable,
omitting compiled models and runtime assets. Reusing that recipe unchanged
would not supply the requested infrastructure.

## BSIM version gate: checked in source and installed binary

The installed Sky130 NFET TT card uses `level=54`, `version=4.5`,
`tnoimod=1`, and `fnoimod=1`. The last two select model equations; they do not
enable transient noise in ordinary ngspice `.tran`.

Official ngspice 43's parser explicitly dispatches level 14/54 with a `4.5`
version prefix to `BSIM4v5`; version `4.8` or default selects `BSIM4`. Missing
older device support produces an unavailable-device error. The installed
binary contains the BSIM4v5-specific device errors and parameter-checking
strings, providing evidence that this build includes the older implementation.
No extra simulator process was started to inspect it.
[Exact ngspice 43 dispatch source, lines 318–334](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/parser/inpdomod.c)

VACASK's inspected `devices/spice/bsim4v8.va` accepts versions 4.8.0 through
4.8.3. At lines 3873–3884, any other value emits a warning and selects 4.8.3.
Passing `version=4.5` therefore does **not** request a 4.5 equation set in this
model. [Pinned VACASK BSIM4 source](https://codeberg.org/arpadbuermen/VACASK/src/commit/0212881e5a87cce91476cd86b9f59673f6da8e9a/devices/spice/bsim4v8.va)

A credible Sky130 path needs either a validated BSIM4.5 model exposing native
noise, or an explicitly qualified model migration with device-level and
circuit-level comparisons. A 4.8 exploration can evaluate infrastructure and
topology sensitivity, but cannot be labelled a validated noise result for the
existing 4.5 circuit. No wholesale PDK migration is proposed here.

## Bounded bootstrap manifest

Temporary sources, build trees, compiled models and installation live under
`build/research/transient_noise/`. The initially missing development outputs
were fetched from the signed Nix binary cache and the stack was built there.
`flows/`, external repositories, PDK files and system configuration are unchanged.

| Component | Concrete source / dependency decision |
|---|---|
| VACASK | Official Codeberg repository, commit `0212881e5a87cce91476cd86b9f59673f6da8e9a` |
| OpenVAF-Reloaded | Official GitHub repository, commit `5ed9e63afe70ac95129a78af7b3732e7d431b1e5`, master/OSDI 0.4 |
| Compiler feature | Current OpenVAF supports LLVM 18–21; use a matching development toolchain and explicit Cargo feature, e.g. `llvm21` |
| Cached build tools | GCC, Rust/Cargo, CMake, Ninja, Bison, Flex, pkg-config, Boost 1.89 headers/libraries, toml++ 3.4 |
| Initial missing dependencies, now resolved | SuiteSparse/KLU, LP64 OpenBLAS headers, LLVM/Clang development outputs and static Boost; 24.3 MiB cache download |
| Build selections checked | LP64 OpenBLAS with OpenMP; static Boost 1.89; LLVM21; locked Cargo closure; full compiler/runtime OSDI RC compatibility |
| Optional scope removed | SuperLU_MT; use KLU for the first RC test |
| Runtime installation | Preserve models, includes and Python rawfile/postprocessing support, not just `vacask` |

The pinned source commits were fetched and verified. OpenVAF compiled at two
jobs in 1m21s. VACASK configured, built and installed successfully with all 53
bundled models and runtime assets. The sole packaging adaptation is a local
`suitesparse/` include-path alias to Nix's unmodified headers. Both source
worktrees remain clean. NumPy/SciPy for the upstream regression required a
separate 30.1-MiB SciPy cache fetch. No automatic approval rejection occurred.
The research dependency expressions, scripts, hashes and logs are captured in
the bootstrap manifest
and build handoff.
[OpenVAF build features at the inspected commit](https://github.com/OpenVAF-Reloaded/OpenVAF/blob/5ed9e63afe70ac95129a78af7b3732e7d431b1e5/openvaf/openvaf-driver/Cargo.toml),
[OSDI and build documentation](https://github.com/OpenVAF-Reloaded/OpenVAF/blob/5ed9e63afe70ac95129a78af7b3732e7d431b1e5/README.md)

## Completed RC and native model-revision checks

The exact upstream `test_trannoise1.sim` passes with `SIM_TEST=yes`, seed 0,
and one CPU: 240,004 transient samples, 1.768 s total wall time, and maximum
transient/stationary PSD disagreement **1.287 dB**, below its 3 dB limit. Its RMS
is 6.4504 nV. An independent check of stationary PSD against
`4kTR/[1+(2πfRC)²]` agrees to 9.42×10⁻⁷ relative; the small difference matches
the model's Boltzmann-constant rounding. Postsettling measured variance is
1.00656×`kT/C` for R=1 kΩ, C=100 µF and 300.15 K. A matched `noisescale=0`
control gives exactly zero transient voltage. These are RC infrastructure
checks, not a transistor-noise result.
Upstream run,
independent RC check,
zero-noise control.

`tb_imc_bsim_revision.py`
compares the actual W=3.5 µm NFET input-pair and W=2.25 µm PFET latch sizes,
both L=0.15 µm and nf=1. It preserves every original wrapper bin and changes
only a local copy's version to 4.8.2. A separate copied 4.5 wrapper must first
match the original; compiled model identities confirm NFET bin 26 and PFET
bin 35. Each device has 438 bias points spanning gate drive 0–1.8 V and six drain
biases 0.025–1.8 V, at TT 27°C and SS 85°C, with zero body bias.

Native BSIM4.5 and 4.8.2 agree to at most 4.47×10⁻¹⁴ of peak drain current and
3.60×10⁻¹⁴ of peak intrinsic Cgg. Finite charge data and gate/drain capacitance
row-sum identities pass. The complete 14-field revision comparison does **not**
pass: Cgs/Cgb and Cds/Cdb differ despite matching currents and stored charges.
The earlier current/Cgg summary did not establish equality of every charge
derivative. It does not test the VA model port, stationary noise or clocked-latch
behavior. Native 4.8 also prints a
TNOIMOD=1 deprecation warning; its source still implements that noise branch,
so its spectrum must be compared rather than inferred from DC agreement.
TT results,
SS results.

The same fixture's `--noise` branch gives each device a separate output with a
1-S ideal controlled-source load. This supplies finite noiseless admittance;
an ideal voltage clamp would suppress the measured voltage noise. Actual drain
biases are saved, because drain current shifts them by up to about 1 mV. The
copied 4.5 controls pass. `set sqrnoise` explicitly requests V²/Hz: nine biases
per geometry, 91 frequencies from 1 Hz to 1 GHz, at TT 27°C and SS 85°C.

| Maximum native 4.8.2 / 4.5 output PSD ratio | NFET | PFET |
|---|---:|---:|
| TT 27°C | 1.18580 | 2.43043 |
| SS 85°C | 1.13838 | 1.59606 |

The largest differences occur in the high-frequency part of the sampled
low-bias spectra; these are not universal multiplicative noise factors. The
native source changes both theta limiting and the source-resistance noise
correction, including division in 4.5 versus multiplication in 4.8. The
explicit PFET parameters prevent either theta clamp from activating in this
case. Full source attribution and its limits are recorded in
[the independent audit](IMC_BSIM_NOISE_AUDIT.md).
TT spectra,
SS spectra.

## Full model extraction and VA port gate

`tb_imc_flat_model.py` extracts
the fully evaluated model cards with ngspice's `listing r`, which avoids the
fixed-buffer truncation affecting ordinary expanded listings. Compiled model
audits establish leaf bins 26 and 35; the runnable MOS invocation itself still
names the unbinned family. The extractor explicitly selects those proven
leaves and retains every evaluated instance parameter and scale=1e-6.
It captures 347 NFET and 344 PFET explicit coefficients, including resolved
PFET diffusion terms. Native flat replay matches all 14 measured current,
derivative, charge and capacitance vectors exactly at all 438 biases/device,
at both TT and SS. Simulator defaults remain implicit.
[ngspice 43 listing implementation](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/frontend/inp.c),
TT extraction/replay,
SS extraction/replay.

`tb_imc_vacask_bsim.py` ports
those fixed leaves to the full `sp_bsim4v8` model. It retains all explicit
coefficients except native dispatch parameter `level=54`, retains the bin
bounds and instance parameters, explicitly quotes version `4.8.2`, and sets
polarity and scale. A native 1e-16-A convergence tolerance is too small for
VACASK's residual checks around the internal 1000-S source/drain clamps;
diagnostics show cancellation residuals near 1e-13 A. The port uses VACASK's
default 1e-12-A absolute tolerance, with reltol=1e-8 and vntol=1e-10. The output
comparison gates remain independently fixed.

The unmodified upstream VA port **fails**. Its current curves agree within
about 3 ppm, but its reported gm differs by about 60% of peak. Its stationary
noise is as low as 0.08144× NFET and 0.22377× PFET native 4.8.2 PSD. Four
manual derivative expressions omit gate chain-rule terms that remain in the
native source. Automatic differentiation preserves the current equations,
while the incorrect manual values feed `tnoimod=1` noise.
Unmodified DC failure,
unmodified noise failure.

The isolated four-line patch
restores `tmp1=Gds+Gm*dVgsteff_dVd`, `tmp2=Gmb+Gm*dVgsteff_dVb`, `tmp3=Gm`,
and the missing `Gm*T11` term in the velocity derivative. It follows native
ngspice43 `b4ld.c` lines 2119–2137; two agents independently checked the
expressions. The last term is inactive for the selected cards' vtl=0.
The original source checkout and installed model are unchanged. A separate
OSDI compiled in 4.62 s and is selected only by `--derivative-fix`.
[Native derivative equations](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/devices/bsim4/b4ld.c),
patch provenance.

After this repair, stationary PSD agrees with native 4.8.2 within
**1.06×10⁻⁸ relative at TT** and **3.46×10⁻⁹ at SS**, over the same nine biases
and 91 frequencies per device. The fixed current/gm/gds comparisons pass.
The initial strict DC/capacitance gate failed near zero crossings of a few
capacitance coefficients. Its cause is now isolated: native BSIM creates the
extra source/drain nodes for tnoimod=1 only when a noise analysis is in the
current task; the VA model always creates them. This produces ppm DC shifts
through its 1-mΩ clamps. A matched native task containing both `.dc` and
`.noise` closes the comparison: **all 14 fields pass at every one of the 438
biases/device**, with maximum difference divided by field peak below
9.54×10⁻¹⁵ at TT and 8.00×10⁻¹⁵ at SS. The existing VA raw data was reused;
no coefficients or comparison tolerances changed. The original unmatched
failures remain recorded. This qualifies only the fixed-device 4.8.2 port;
it does not validate native 4.5 noise, other geometries, or a clocked comparator.
Corrected TT DC,
corrected SS DC,
corrected TT noise,
corrected SS noise.
Matched TT DC/charge gate,
matched SS DC/charge gate.

An opt-in 21-bias extension adds six forward cases at normalized body bias
−0.4/−0.6 V and six reverse-drain cases at body bias −0.6 V. Its reverse
drain values −0.2/−0.5 V keep the body/drain junction reverse biased. The
corrected VA/native4.8 noise gate passes at both corners, within 7.29 ppm TT
and 3.03 ppm SS. The native revision discrepancy is much larger in one reverse
case: at normalized VGS=0.1 V, VDS=−0.2 V, VBS=−0.6 V and 1 GHz, TT NFET
output PSD changes from 5.2754×10⁻²⁹ to 7.1049×10⁻²³ V²/Hz. These are
spectra at the fixture's 1-S load, not comparator noise, and demonstrate why
a scalar correction between model revisions is inappropriate.
Absolute PSD audit.

A second, explicitly named **hybrid variant** retains corrected 4.8.2
DC/charge equations and restores the native 4.5 `tnoimod=1` thermal equations:
remove both theta clamps and divide, rather than multiply, the applicable
source/drain noise conductance correction. It does not change fitted model
coefficients. Its small separate patch
and separate OSDI provenance
preserve the unmodified and corrected 4.8 controls. Compilation took 4.53 s.
The hybrid's stationary spectra match native 4.5 at all 21 biases and 91
frequencies/device within **1.306 ppm TT** and **1.037 ppm SS**, with the same
comparison gates. This qualifies the sampled stationary-noise behavior of
these two geometries; it is not a full BSIM4.5 port or a measured silicon model.
Hybrid TT gate,
hybrid SS gate.

The exact nine-MOS StrongARM uses five distinct geometries: input NFET 3.5 µm,
tail NFET 0.42 µm, regeneration NFET 1 µm, regeneration PFET 2.25 µm and reset
PFET 1 µm, all L=0.15 µm. Full-card extraction preserves their selected bins
(N26/N170/N71, P35/P80) and all instance parameters. Native flat 4.5 serialization
matches the original wrapper's 14 fields exactly at 438 biases per geometry,
at TT 27°C and SS 85°C. The separate native 4.8 revision gate fails the four
capacitance fields above; it is preserved as a failure.
Five-geometry TT export,
SS export.

The native getters have the same meanings. The capmod=2 T0<0 branch changes
`dT0_dVb*(1-T5)` in 4.5 to `dT0_dVb*(T4-T5)` in 4.8 when computing
`dVdseffCV_dVb`. This changes the body/source Jacobian entries used by the
simulator. An independent body sweep at VGS=0.1/0.6/1.2 V,
VDS=0.025/0.4 V and VBS=−0.6/−0.4/−0.2/0 V, with centered ±10 µV steps,
finds matching Qg/Qd curves across revisions. Native 4.8 Cgb/Cdb agree with
their numerical derivatives to at most 3.98×10⁻⁹ of field peak at TT and
2.09×10⁻⁹ at SS; 4.5 deviates by up to 2.26% and 2.46% of peak. This supports
an erroneous 4.5 body Jacobian with the same underlying charge equations at
the sampled points. It does not waive the failed migration gate or establish
clocked waveform equivalence.
[Native 4.5 equations](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/devices/bsim4v5/b4v5ld.c),
[native 4.8 equations](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/devices/bsim4/b4ld.c),
TT numerical derivative audit,
SS audit.

The additional five-geometry VA port gate compares the hybrid against native
4.8 with matched noise-job topology at the same 438 biases per geometry. All
14 fields pass at TT/SS, with maximum field-peak-normalized difference
9.88×10⁻¹⁵. A reset-PMOS rail-crossing probe at normalized VGS=0.741±1 µV
and VDS=−1 µV/−1 nV/0/+1 nV/+1 µV/+1 mV also agrees. These port gates
remain distinct from the failed native 4.5-to-4.8 body-Jacobian screen.
Five-geometry port fixture,
rail-crossing port gate.

## One-comparator clocked qualification

`tb_imc_latch_noise.py` uses the
exact exported nine-MOS topology, ideal input sources at common mode 0.9 V,
±2 mV differential input, and 10 fF output loads. Two physical clock/reset
cycles run; the second full 20 ns cycle is compared and charged all positive
delivery from supply, clock and both input sources. There is no SAR/CDAC or
finite input impedance in this fixture.

The first VA settings (reltol=10⁻⁶, abstol=1 pA) failed near a reset-PMOS
drain/source crossing. Newton iterations initially converged, but local-error
rejection drove the timestep into numerical cancellation. Raising the iteration
budget or changing integration method did not fix that strict case. A separate
fast reset-PMOS gate/drain ramp reproduces the failure; slower ramps pass.
This remains a numerical limitation, not an accepted noise run.

An independent numerical convergence study retains those failures and compares
to a native 1 ps reference. At VA reltol=10⁻⁵ and unchanged 1 pA absolute
current tolerance, reducing maximum timestep 10→5→2 ps reduces worst waveform
error 2.736→1.257→0.281 mV. Relative tolerances 10⁻⁴ and 10⁻³ also approach
0.28–0.31 mV at 2 ps. The 10⁻⁴/10 ps point exceeds the fixed 5 mV waveform
gate and is excluded. The accepted deterministic settings are native 1 ps and
VA 2 ps, reltol=10⁻⁵; physical acceptance limits remain 5 mV maximum/1 mV RMS,
100 ps decision time, and 0.5% energy difference.
Convergence study and retained strict failure.

Both input polarities pass deterministic reset, decision, waveform and energy
gates at TT 27°C and SS 85°C. Worst waveform differences are 0.281/0.327 mV,
RMS 26.74/47.79 µV, with identical decision time on a 1 ps grid and maximum
energy differences 0.00328%/0.00159%. This is a bounded clocked migration check,
not a comparator offset or input-noise characterization.
TT clocked results,
SS clocked results.

**Default intrinsic-noise settings fail.** The zero-amplitude noise
control passes, but seed 0 with the original unit noise scale fails before the
clock, at the first ZOH noise-grid boundary near 41.667 ps. SDE mode and alternate
integration methods also fail bounded probes. The recorded TT result separates
the passing deterministic gate from this failure. Noise amplitudes reduced by
10⁶ permit one diagnostic ZOH run; that is not the physical noise model and
cannot support a noise specification. A 1 mΩ/10 fF resistor-capacitor reproducer
also fails ZOH when connected to an ideal 1.8 V source, while a grounded version
without the voltage-source current unknown passes. SDE passes both small RC
variants. Adding exact ZOH grid breakpoints does not fix the comparator: LTE is
tested before breakpoint history reset. This isolates part of the limitation
to the simulator's treatment of stochastic discontinuities and algebraic
source currents, independent of MOS physics.
Stiff RC diagnostic.

A separately named exploratory branch uses SDE mode and the documented
`tran_noiselte=30` stochastic error-estimator floor, with **unit physical noise
amplitude**, unchanged device coefficients and unchanged deterministic signal
gates. Floors 1/3/10 fail the bounded comparator probe. At floor 30, both TT and
SS complete 45 ns: zero amplitude reproduces the noiseless trace exactly,
seed 0 repeats exactly, and seed 1 produces a distinct trajectory. Both tested
seeds resolve the fixed +2 mV input correctly. Each noisy run takes about one
second. The different-seed output separation during regeneration is 43.9 mV
at TT; that is an output waveform difference, **not input-referred noise**.
TT exploratory controls,
SS exploratory controls.

This closes only the executable noise/replay sanity check. Stochastic-floor,
timestep and frequency-parameter convergence, adequate sampling, input source
impedance and the full sampled circuit remain open. SDE white-noise samples
scale as 1/√(2h) for actual step h; the supplied `noisefmax` is not a verified
brick-wall cutoff. Gross positive delivery from ideal sources under random
currents is also not a converter energy forecast. No input-referred sigma,
SNR or BER is claimed.

## First executable experiment after bootstrap

Run upstream `test/test_trannoise1.sim` before touching the comparator. It loads
native resistor/capacitor models, runs both transient noise and stationary
noise on one RC node, and checks their PSD agreement within 3 dB. It uses
NumPy/SciPy plus VACASK's rawfile and test helpers. Invoke it from its test
directory with the isolated simulator and preserved model search paths.
[Pinned self-checking native RC regression](https://codeberg.org/arpadbuermen/VACASK/src/commit/0212881e5a87cce91476cd86b9f59673f6da8e9a/test/test_trannoise1.sim)

Add independent checks before interpreting device noise: zero-noise control;
PSD versus `4kTR/[1+(2πfRC)²]`; variance approaching `kT/C` after settling
when the simulated bandwidth encompasses the RC response; temperature scaling;
and agreement as bandwidth, oversampling and timestep are refined. Use the
finite-band integral when the noise bandwidth is limited. Uniformly resample
adaptive-time output before a Welch estimate. Save seeds and convergence data.

After the BSIM model gate, compare one MOS device's DC characteristics,
capacitances and stationary noise with ngspice 43, then compare the noiseless
clocked latch's decision threshold, reset, delay and kickback. Only then run
native transient noise with the actual common mode, input source impedance,
filter, clock edges and output receivers.

For an initial decision-noise estimate, use 9–13 differential input values
around the measured decision threshold and at least 128–256 realizations per
value. Fit `P(positive decision) = Φ((Vin − Vos)/σn)` and report uncertainty in
`σn`; separately count decisions that fail the output/deadline criterion.
Distinguish static offset from temporal noise. Flicker introduces correlation:
retain realistic history and check correlation across repeated decisions
instead of treating every cycle as an independent sample.

Choose noise bandwidth from convergence, not clock frequency alone. For
example, `oversample=6` at 1/2/4 GHz limits steps to 83/42/21 ps; these are
runtime estimates, not validated bandwidth selections. Start with one latch,
then test the complete SAR sequence to expose inter-decision correlation and
sampling noise. A standalone latch's fitted σ does not close the complete
column readout's effective-noise budget.

## Passive input-filter check: the 100 µV hypothesis remains open

The actual fixture, `analog/testbenches/tb_imc_null_sar.py`, puts an
8 kΩ / 60 fF filter on **each** comparator input. The positive resistor connects
to the floating CDAC top node; the negative resistor connects to the ideal
threshold source. With 12 fF units, the ideal CDAC capacitance seen from its
top node is `Ch = 756 + 12.8 × 192/(12.8 + 192) = 768 fF`.

Consider only these two resistors at 27 °C, with quiet ideal CDAC bottom
references, no MOS capacitance, and fixed total charge on the positive
`Ch`/`Cf` pair. Define `u = Vpositive − Vheld`. Charge conservation gives
`Vpositive = Ch/(Ch+Cf) × u` for this noise mode. Its energy is
`½ × [Ch Cf/(Ch+Cf)] × u²`; equipartition and the RC decay then give

```
Var(Vpositive) = kT Ch / [Cf (Ch+Cf)]    τpositive = R Ch Cf/(Ch+Cf)
Var(Vnegative) = kT/Cf                 τnegative = R Cf
```

The branches are independent in this reduced model. Their stationary RMS
values are **253.10 µV** and **262.81 µV**, yielding **364.87 µV differential
instantaneous RMS at the comparator inputs**. Their time constants are
0.4452 ns and 0.4800 ns. This is neither a full ADC noise estimate nor a
value referred through the real sampled-signal transfer function.

An assumed uniform averaging aperture `A` multiplies each variance by
`2τ/A × [1 − (τ/A)(1 − exp(−A/τ))]`, obtained by integrating its exponential
autocovariance twice over the aperture. Under this hypothetical weighting:

| Averaging aperture | Differential resistor-noise RMS |
|---|---:|
| 0.5 ns | 309.47 µV |
| 1 ns | 269.77 µV |
| 4 ns | 165.11 µV |
| 12 ns | 99.41 µV |

The ideal boxcar crosses 100 µV at **11.852 ns**, spending the whole budget on
these resistors. A comparator's output-ready time does not measure this
averaging aperture: regeneration generally applies a different sensitivity
to noise injected at different times.

An independent Euler–Maruyama simulation of the two physical RC branch-current
equations, initialized at zero and allowed to settle, verifies the result.
Across 8,192 independent trajectories, the largest variance discrepancy over
seven boxcar widths was 3.63%; charge conservation also passed. Reproduce with
the cached NumPy Python and
`analog/testbenches/tb_imc_filter_noise.py`:

```sh
python3 analog/testbenches/tb_imc_filter_noise.py
```

Numeric results are in `build/research/imc_filter_noise_check.json`. Runtime
was under one second. This is a passive stochastic model, not SPICE or MOS
noise data.

MOS input capacitance, time-varying loading, resistor implementation, the
initial common charge, reset/sampling noise, reference impedance and the
actual comparator sensitivity remain uncharacterized. The 768 fF reduction
assumes stiff bottom references and the nominal static split capacitors;
real bottom-switch on-resistance makes holder impedance frequency-dependent.
Additional capacitance
changes both noise and signal transfer; it is not a free remedy. The result
justifies validating or redesigning the input filter before treating the
100 µV effective-read-noise target as achieved.

## Filter sizing must preserve the signal too

The next passive check applies the signal referral in the user's notes 11f
(sampling capacitance) and 19p (noise divided by the gain of the same sensing
phase). Enlarging the two filter capacitors reduces their voltage noise, but
the positive capacitor also loads the finite stored signal. In the settled
ideal split-CDAC model, a uniform bottom-plate step has gain
`a = Ch/(Ch+Cf)` from the unfiltered held residue to the comparator input.
An independent two-node charge-equation solve verifies this gain for the
actual 756/192/12.8 fF split network.

For `x = Cf/Ch`, referring the stationary resistor noise through that gain gives

```
σ²_residue = (Var(Vpositive) + Var(Vnegative))/a²
           = (kT/Ch) × (2/x + 3 + x).
```

This **instantaneous passive model**, with equal filter capacitors and no
comparator aperture, has its minimum at `Cf = sqrt(2) Ch`. It is not an
optimization over complete clocked ADCs.

| Each filter capacitor | Settled signal gain | Comparator-node RMS | Residue-referred RMS |
|---|---:|---:|---:|
| 60 fF, current fixture | 0.928 | 364.9 µV | 393.4 µV |
| 240 fF | 0.762 | 174.4 µV | 228.9 µV |
| 768 fF | 0.500 | 90.0 µV | 179.9 µV |
| 1,086 fF, stationary minimum | 0.414 | 73.5 µV | 177.3 µV |

Thus a seemingly sub-100-µV filter-node result can still miss the useful
signal-referred target. Meeting 100 µV instantaneously in this restricted
model requires at least 2.415 pF of effective holder capacitance even at its
best filter ratio, before any other noise. That is **not** a capacitance floor
for an ADC that integrates noise over a finite sensing interval. With the
current filter, an ideal boxcar would require 13.857 ns for 100 µV referred
through the settled gain, versus 11.852 ns at the comparator nodes. Neither
interval has been demonstrated by the StrongARM.

Reducing resistance changes settling and temporal correlation, but does not
change this equilibrium variance. It also weakens isolation from comparator
kickback. Consequently, the next topology comparison should price a real
integrating preamplifier or changed isolation scheme alongside capacitor
growth. The capacitance sweep and charge-equation assertions run with the
existing passive stochastic check and are saved under
`settled_signal_sizing` in its JSON artifact. No extra SPICE run is required.
