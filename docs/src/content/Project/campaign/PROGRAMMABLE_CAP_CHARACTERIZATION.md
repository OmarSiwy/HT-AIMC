# Physical programmable-capacitor bank controls

The testbench compares ideal compiled capacitances with two physically
switched unsigned 4-bit banks. All 15 unit capacitances remain installed.
Each binary capacitor has a bottom-plate TG to the row and a second TG
that connects its unused bottom either to common mode or its own column.
The latter bypass preserves smaller active loading but adds switch parasitics.
Each physical bank contains 16 MOS devices, before SRAM and sign circuitry.

All 16 codes are tested at row steps ±450 mV, zero and ±225 mV about .9 V.
Columns are clamped at .9 V and delivered charge is integrated. This is a
unit-bank control, **not a loaded array, stored SRAM state, signed multiplier,
noise result or complete IMC demonstration**. Full source/diffusion geometry
and clock/reference energy are included; capacitors and instruments are ideal.

## Frozen gates and numerical qualification

The physical maximum charge-error gate is .1% of each code's full-scale
charge, with code zero normalized to one unit. Numerical integration gets
10% of that budget (.01% FS), checked with ideal capacitors in the same
deck and with independent timestep agreement. The older absolute oracle
failed even ideal capacitors; those failed results remain preserved. The
new relative protocol is separately recorded as version2, not silently
substituted into old result files.

TT27, Cu4 fF, Wn=Wp=.42 µm, L=.15 µm and 8-ns settling pass both the
physical gate and 1→.5-ps timestep comparison. Maximum difference is
.006619% FS, below the .01% numerical allocation. On the finer run,
maximum charge error is approximately .00327% FS. The qualifier applies
only to this clamped unsigned fixture.

## Slow-corner tradeoff

| SS85, Cu4 fF | Settle (ns) | Equal N/P width (µm) | Maximum bypass error (% FS) | Bypass code0 load (fF) | Code15 load (fF) |
|---|---:|---:|---:|---:|---:|
| Original | 8 | .42 | .20834 — **FAIL** | 9.8388 | 62.3361 |
| Wider switches | 8 | .84 | .00736 | 19.7876 | 64.4745 |
| Longer settling | 16 | .42 | .00735 | 9.8388 | 62.3361 |

Both repairs pass the physical and ideal-oracle gates at1 ps and the independent
1→.5-ps timestep agreement check. Wider switches nearly double disabled loading.
Longer settling keeps that loading but costs service time. Grounding unused
bottoms instead keeps approximately60 fF per bank at every code. These
measured AC loads are at1 kHz; full frequency sweeps are preserved.

The 48-bank fixture's total metered energy rises with wider switches. It
also contains compiled and grounded controls simultaneously, so its aggregate
energy is not a per-bank or per-MAC implementation energy. Do not divide it
arbitrarily to claim a core benefit.

## Larger-unit baseline

The same .42-µm switches with Cu8 fF atTT complete all simulations and AC
measurements, but fail the charge gate at8 ns. Doubling capacitor area to
reduce mismatch therefore requires a timing or conductance repair even
before array loading. The measured AC matrix may inform an explicitly
conditional static system comparison; the dynamic failure remains a gate.

## Reproduction

- Source: `analog/testbenches/tb_imc_programmable_cap.py`.
- Numerical checker: `scripts/compiler/metrics/imc_programmable_bank_audit.py`.
- TT: `build/campaign/programmable_cap/w042_tt27_s8_step1/analysis_v2.json`
  and `w042_tt27_s8_step0p5_r1/result.json`; comparison in
  `w042_tt27_s8_step0p5_r1/numerical_comparison.json`.
- SS: `w042_ss85_s8_step1_r1`, `w084_ss85_s8_step1_r1`,
  `w042_ss85_s16_step1_r1`; each contains complete decks, logs and results.
- Cu8: `w042_tt27_cu8_s8_step1_r1`.

The independent [bypass noise identities](PROGRAMMABLE_CAP_MATH.md) show
that disabled capacitors retain internal noise modes. This deterministic
test does not qualify a system model that omits them. Local mismatch,
SRAM impedance, sign selection, row drivers and array-level state loading
remain separate requirements.

## Conductance-guided intermediate width

A new native gm/ID/admittance sweep coversW=.42/.50/.56/.63/.70/.84/1.0µm
at seven common-mode biases .45–1.35V and finiteVDS10mV, SS85, explicit
.29µm diffusion. Worst measuredRon is77.93/54.41/46.62/36.99/32.23/24.26/20.15kΩ
respectively. An illustrative34fF node and .1% settling estimate
`Ron*C*ln(1000)` gives18.30ns at.42µm,8.69ns at.63µm and7.57ns at.70µm.
The34fF includes an assumed2fF parasitic allowance on the32fF high-bit cap;
it is a screening approximation, not extracted transient proof.

At the .70µm worst sampled bias (.9V), actualN/P gm/ID are13.36/9.33V⁻¹.
The .70µm fullbank transient passes both charge and ideal-oracle gates at1ps;
its independent.5ps numerical control is pending. This is a smaller candidate
than the earlier.84µm repair, not a proven global optimum. Exact bias data:
`build/campaign/bank_sizing/ss85_width_r1/result.json`; source:
`analog/testbenches/tb_imc_bank_sizing.py`.

### Finer width screen and retained negative

At8ns/SS85, W=.50/.56/.63/.70µm gives maximum bypass errors
.05629/.02400/.005832/.006259% FS at1ps. Corresponding code0 loads are
11.8068/13.2471/14.9648/16.5828fF. The .70µm case also passes independent
1→.5ps agreement. The .46µm case fails the physical gate; .48µm and
finer .50µm controls are pending. Thus the worst-bias RC estimate is a
conservative screen, not the actual nonlinear settling integral or optimum.

Completed transient CSVs may now be stored as `transient.csv.gz`; each was
decompressed and SHA256-verified before its raw copy was removed. Source,
result and AC matrices remain uncompressed. Per-file `transient.archive.json`
records hashes and the restore command. Maintenance source is
`analog/testbenches/imc_bank_artifacts.py`; twelve completed traces freed
2,020,922,564 bytes without discarding failed outcomes.

### 14:36 UTC sizing checkpoint

W=0.50 µm independently qualifies at 1/0.5-ps timesteps: all numerical and
physical gates pass, maximum inter-step difference 6.6185e-5 of per-weight
full scale; fine-step bypass error 0.0005626643. W=0.46 gives 0.001017411
and fails the 0.001 gate; W=0.48 gives 0.000746998 at 1 ps and passes that
single-step gate. Its 0.5-ps control is running as
`w048_ss85_s8_step0p5_r1`; no convergence claim until completion.

14:37 UTC: W=0.48 finer timestep completed. Independent numerical comparison PASS; worst fine-step bypass error 0.0007467509009 of per-weight full scale. W=0.50 fresh eight-amplitude control remains live. Another 471,292,145 bytes of completed bank traces were losslessly archived with SHA-256 readback.

### Fresh-amplitude falsification and coupon projection

The W0.50 SS85/8ns result DOES NOT generalize to the frozen fresh amplitudes
[.413, -.073, .137, -.389, .021, -.271, .319, -.149] V. At code8 and +.137 V,
bypass error is -0.0363674 fC, or 0.002525515 of per-weight full scale:
**FAILED** the unchanged 0.001 gate. The compiled-cap oracle still passes
at 2.96615e-5 FS. A finer timestep and W0.70 matched fresh-input control
are running. The original five-amplitude W0.48/W0.50 qualification remains
valid only in its stated scope; neither is a robust sizing winner.

A new optional projection imports the audited isolated-coupon capacitance
matrix. The 1260-nm coupon sets Cu=4.07454 fF (not nominal4 fF), with
0.06928/0.28183-fF top/bottom-to-substrate capacitances. Binary bits sum
1/2/4/8 identical isolated units; installed inactive capacitors remain.
The ideal compiled-cap oracle uses the same mutual Cu. Column plate
orientation is explicit, and the matrix source is hashed into each run.
This is a linear lumped projection, NOT full-array PEX: inter-unit wiring,
resistance, capacitor PVT, matching and voltage dependence remain absent.
Running W0.70 SS85 with the TT coupon projection isolates the effect of
fixed plate loading; it does not qualify capacitor corners.

### 2026-09-11 14:55 UTC — actual-bias N/P sizing

The W0.50 fresh-input failure is now numerically confirmed: ideal oracles
and independent timestep agreement PASS while the physical gate FAILS;
fine-step bypass error0.002525403. W0.70 fresh inputs independently PASS
at1/0.5ps, worst fine-step error0.000189651. The1260nm coupon projection
atW0.70 also passes at1ps (0.000336267); finer timestep remains running.

A denser native0.05V bias grid, individually probed N/P port admittances,
and gm/ID values reveal the previous0.15V grid understated worst Ron.
For equalW0.70, worst Ron is37.73kΩ rather than32.23kΩ. All reconstructed
N/P sums agree with measured equal-width ports. A49-pair fixed-bias screen
is saved in bank_sizing/ss85_pair_ports_fine_r1/pair_screen.json.
Total transistor width, worst Ron and inactive terminal C are separate
Pareto objectives; saturation gm/ID alone is not a switch-sizing rule.

The selected Wn0.50/Wp0.70 pair passes fresh amplitudes at1ps, with
0.000286416 worst error. Compared with equal0.70, totalwidth decreases
14.29%, bypass C0 decreases16.58276→14.00005fF (15.57%), and aggregate
48-bank ideal-port energy over the same eight frames decreases732.783→
718.356fJ/frame (1.97%). These are clamped-bank metrics, not macro area
or per-MAC energy. Finer timestep, original full-scale amplitudes and
matched TT loading are running before claiming a qualified sizing choice.

15:00 UTC: W0.70 coupon-projection0.5ps control aborts at122/192ns
with ngspice timestep-too-small at vdd#branch; waveform-completeness
assertion correctly rejects it. Source/deck/partialtrace/log are preserved.
A distinct0.4ps control is running. The1ps coupon result remains provisional;
it is not numerically qualified by the successful ideal-cap bank control.
Asymmetric0.50/0.70 originalfive-amplitude SS85 control also passes at1ps;
its finer fresh-input and TT runs remain active. Sixcompleted banktraces
were losslessly archived, freeing1,490,597,665bytes withhashreadback.

### 2026-09-11 15:20 UTC — 3+4-bit banks and paid sign routing

Asymmetric Wn0.50/Wp0.70 SS85 fresh controls now PASS independent1/0.5ps
agreement; worst fine-step bypass error0.0002864007 FS. The separateW0.70
coupon projection also PASSes1/0.4ps agreement, error0.0003362792; its
failed0.5ps run remains a numerical failure, not silently discarded.

The TB now explicitly supports3-bit (7Cu,12MOS unsigned) and4-bit
(15Cu,16MOS unsigned) banks. Actual3-bit TT AC gives bypassC0=9.980125fF,
C7=30.202634fF and groundedC=28fF for everycode atCu4. Thus the lowbank's
previous four-bit lookup included unused circuitry and cannot simultaneously
be described as an electrically matched22-unit3+4-bit physical design.

A real per-cell sign SPDT selects row or its complementary voltage before
the magnitude-bank switches. Both ideal row source ports are counted in the
aggregate positive energy. At2x sign-switch width it adds4MOS, but adds
66.7% total switch width to3-bit banks and50% to4-bit banks. Sign/weight
control logic and real row drivers remain unimplemented. Negative3-bit SS85
fresh control passes at0.000458094 FS. Negative4-bit FAILS at0.006349415,
code15: added series resistance cannot be ignored.

A distinct topology uses three actual mutually exclusive TGs per magnitude
bit, selecting positive row, negative row, or idle. It removes the shared
series mux and requires sign/bit decoding. At unchangedbit widths,3-bit
has18MOS vs16 shared, but10% lower total transistor width. Initialfresh
negative3-bit test passes at0.0000204316 FS. Compared withshared sign,
aggregate24-bank fixture energy is188.808 vs227.541fJ/frame (17.02% lower),
but bypassC0 rises12.855828 vs10.500037fF (22.44% higher). This is an
area/loading/error tradeoff, not a complete power win. Finer timestep and
4-bit direct-sign control are running. Positive sign, capacitor projections,
mismatch, dynamic SRAM programming and fullarray operation remain unqualified.


## 2026-09-11 15:52 UTC — separate signal coefficient from loading

`scripts/compiler/metrics/imc_bank_transfer_export.py` exports integrated charge for
all eight actual stimuli separately from each code's column admittance,
with source/deck hashes. Its affine diagnostic self-check passes.
For signed four-bit direct selection, Wn/Wp=.50/.70, SS/85°C,
1260-nm coupon BOTTOM connected to column, the original worst charge error
is 0.08530% FS at 1 ps. Fitting gain and offset to the first two exposed
stimuli (+.413, −.073 V) yields a worse maximum residual on the other six:
0.14228% grounded / 0.14205% bypass, both at code8. Thus a simple affine
fit is not automatically a repair for the signal-dependent error. These
are exposed diagnostics, not independently selected calibration/validation.
The full exact samples remain available for an array model; total loading
must never substitute for the multiplication numerator.


A targeted gm/ID/admittance-informed followup uses Wn=.56/Wp=.70 µm with
TOP-column coupon orientation. The prior actual-port screen predicts worst
finite-VDS resistance 42.454 kΩ versus 45.029 kΩ at .50/.70; sum width grows
5%, and maximum isolated OFF terminal capacitance grows .80997→.85293 fF.
This tests whether modest NMOS sizing can retain the smaller TOP-column
shunt while repairing settling. These local screen quantities are not bank
or macro area/power. The new physical transient is pending; no pass assumed.


### Numerical control and unequal-unit continuation

The signed TOP-column1260nm0.5ps control aborted at146ns/192ns on
`vrow#branch`; this is FAILED_NUMERICAL, not a completed physical error test.
Its log/partialtrace/failure_summary.json are retained. A separate0.4ps
control is running. The original complete1ps charge-gate failure is unchanged.
TT signed direct3/4-bit BOTTOM-column1260nm tests both pass initial1ps;
exact integrated signal samples and loading are in each transfer_export.json.
The new3-bit1000nmBOTTOM-column SS85 control passes1ps, enabling a physically
smaller low-digit candidate. Independent finer control is still required.


## 2026-09-11 16:09 UTC — orientation/sizing Pareto points

The admittance-selected Wn=.56/Wp=.70µm TOP-column1260nm signed4bit
candidate completes1ps with worst0.0944144%FS grounded (0.0944109%bypass),
passing the0.1% gate. GroundedC0=62.15732fF; mean positiveport energy across
the same48bank/eight-stimulus fixture is763.684fJ/frame. Finer0.4ps is active.
The Wn=.50/Wp=.70 BOTTOM-column point passes independent1/.5ps comparison,
with0.08530%FS coarse error, grounded65.34557fF and745.750fJ/frame.
Thus TOP trades~4.88% lower grounded column loading for5% more total switch
width,~2.40% higher aggregatefixture energy and smaller charge-error margin.
Neither isolatedfixture energy nor width is a completeMAC or layout metric.
The TOP.50/.70 point remains a physical1ps failure, with its0.5ps numerical
abort separately preserved and0.4ps control active.
