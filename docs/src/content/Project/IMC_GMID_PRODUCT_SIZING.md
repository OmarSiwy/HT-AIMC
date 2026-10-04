# gm/ID sizing of a charge-domain logarithmic multiplier

Research round, 2026-09-10. Sources and generated evidence are linked below.

**A bounded deterministic multiplication screen now passes at TT27 and SS85.**
The retained sizing uses four 1.86/0.5-µm NMOS devices, a 600-fF state capacitor,
three minimum transmission gates, 256.893-nA operand reference current and a
1.5× reference-log current. With 1.2-µs acquisition, a read aperture at 1.3 µs
and a complete 1.5-µs word interval, maximum product errors on the fresh short
cohort are approximately **0.878% TT and 0.647% SS**. These are noiseless
positive scalar current results over a centered factor-two operand range.

This improves the initial log circuit's error and timing substantially, at
increased capacitance and current. It does **not** establish a minimum-area
IMC architecture, eight-bit precision, manufacturing yield, or a Mythic win.
The existing normal-number IMC core remains substantially more mature and is
not replaced by this experiment.

## 1. Exact problem and baseline

The requested research direction combines analog sample/hold pipelining,
charge-domain multiplication in logarithmic representation, and conversion
back to linear representation for accumulation. The follow-up specifically
requests inspecting the current commit/core, experimenting with SPICE, and
using gm/ID to minimize product error and delay.

Repository HEAD is `7b8d241d696d58216c3c42cb9d8a9ca25217b663`. That commit
changes only `docs/src/content/Project/NULLSEEK.md`; its historical discussion concerns
the OTA/PWM tile. The current optimization core is the working-tree
`matrix_probe` in [tb_imc_sizing_research.py](../../../../analog/testbenches/tb_imc_sizing_research.py):
actual complementary row switches, fixed signed coefficient capacitors,
real sharing/reset switches, and retained radix accumulation. Its output
is `accj`, reached through the actual `outj → Xsharej → accj` connection.
The modified `top/harness.py` is a simulator runner, not a new topology.

Two **fresh** runs of that exact 128×8 core reproduced the existing strongest
selected baseline. Neither the source nor its old saved artifacts was changed.

| Current normal-number core | RMS / maximum error | Positive interface energy | Average word interval |
|---|---:|---:|---:|
| TT27 | 0.042771 / 0.079342 MAC | 4.499809 fJ/MAC | 366 ns |
| SS85 | 0.103329 / 0.223379 MAC | 4.587238 fJ/MAC | 366 ns |

The generated decks are byte-identical to the archived decks. The three
measured words use 7/6/5 magnitude planes at 61 ns each: 427/366/305 ns.
This reproduces a previously selected three-word cohort, with nine calibration
words and independent corner fits; it is not fresh workload validation.
Both whole-word gates, RMS <0.25 MAC and maximum <1 MAC, pass. There is no
physical ADC, programmable weight memory, extracted layout or transient noise
in that baseline. Exact commands, snapshots and hashes are in the
[reproduction record](../../../../build/research/imc_current_core_baseline/README.md)
and [manifest](../../../../build/research/imc_current_core_baseline/manifest.json).

For the new logarithmic branch, define dimensionless positive operands
`x=Ix/Iref` and `w=Iw/Iref`, initially over `[0.25,4]`, then explicitly over
the restricted mantissa interval `[2^−0.5,2^0.5]`. The product range of the
restricted experiment is `[0.5,2]`. One calibration at `(1,1)` sets a constant
output-current gain; no fitted exponent or input-dependent correction is used.

The declared deterministic gate is maximum relative product error <1%,
including the last 10% of the evaluation interval. RMS error, repeated-reference
error, complete word time, all-source positive energy, capacitance and MOS
gate-area proxy are separately reported. Minimization is a Pareto problem;
no energy or area credit is assigned to a failed computation. The 1% scalar
gate is an exploratory circuit target, not a demonstrated transformer accuracy
requirement. Signed dot-product error must eventually be checked in MAC units
and against the model, especially near cancellation.

Hard experimental constraints are real Sky130 1.8-V MOS devices, grounded
source/body log and exp devices, physical transmission gates, and no ideal
logarithm/exponentiation element. Ideal capacitors, input current sources,
clock sources and a 0.9-V output-current compliance supply remain explicit
testbench assumptions. Variables include gm/ID, length, current-derived
width, capacitor size, switch width, reference current ratio, and phase times.

## 2. Arithmetic and circuit equations

In the ideal saturated subthreshold approximation,

\[
I_D=I_0\exp[(V_{GS}-V_T)/(nU_T)],\qquad s=nU_T.
\]

The three log devices generate
`Vx=V0+s ln(x)`, `Vw=V0+s ln(w)` and `Vr=V0+s ln(κ)`.
Sample `Vx−Vr` across the capacitor. Open the top sampling switch, disconnect
the reference bottom plate, and connect that plate to `Vw`. Ideal charge
conservation gives

\[
V_g=V_x+V_w-V_r,
\quad I_o=I_{o,11}xw,
\quad I_{o,11}=I_{\rm ref}/\kappa
\]

for identical ideal devices. In real devices `Io,11` is measured; dividing
by it is the sole output calibration. Changing κ physically changes the
reference current and the exp-device operating point. Its current is included
in energy. It is not a numerical correction of the output.

**Equal-capacitor sharing is averaging.** Sharing ordinary equal-slope log
voltages and applying a same-slope exponent produces `sqrt(xw)`, not `xw`.
It becomes a product if the encoding slope is twice the exp slope, or if a
physical voltage-stack operation supplies addition. In the negative-control
SPICE run, equal sharing gives 313.1% maximum product error but only 3.264%
maximum geometric-mean error. The arithmetic distinction is experimentally
visible. See the [analytical checker](../../../../scripts/compiler/metrics/imc_log_pipeline_analysis.py).

With top-node parasitics, a simple local approximation is

\[
V_g\simeq V_x+\alpha(V_w-V_r),\qquad
\alpha=\frac{C}{C+C_p}.
\]

The two operands then receive different exponents. A constant gain fit cannot
repair this error. Actual nonlinear MOS gate charge and switch charge require
transient simulation; one constant `Cp` does not fully describe this circuit.

The actual diode log slope differs from the fixed-drain exp slope:

\[
g_\ell=\frac{d\ln I}{dV_{\rm diode}}=\frac{g_m+g_{ds}}{I},
\qquad g_e=\frac{g_m}{I}\bigg|_{V_{DS}\ {
m fixed}}.
\]

Locally, the idealized stack has exponents `ax≈ge/gℓx` and
`aw≈α ge/gℓw`. Finite drain conductance can speed diode settling while worsening
its slope match to the output device. Reference bias adjusts the mean exp
slope; it cannot independently remove both operand errors.

Even perfectly inverse nonlinear log/exp characteristics have curvature error
when their voltages are added. Let `f(u)=Vdiode(Iref exp(u))`. To second order,

\[
\delta\ln(xw)\simeq-\frac{f''(0)}{f'(0)}\ln x\ln w
=\frac{d\ln g_\ell}{d\ln I}\ln x\ln w.
\]

This explains why centered mantissas help and why choosing a faster, stronger
inversion point can damage multiplication. The independent checker obtains
7.03% maximum error for an ideal square-law control even over this small range.

## 3. gm/ID sizing, including self-loading

The supplied notes on fixed-current-density sizing, unknown terminal voltages,
and iterative self-loading were used. Existing
[lookup tables](../../../../analog/schematics/sizing/lookup.py) are real TT27 SPICE
tables at W=10 µm and VDS=0.9 V. They propose a design coordinate; they do not
establish the operating point of a narrow diode-connected transistor.

The sizing order is capacitance/error budget → settling conductance → current
at a chosen gm/ID → width from current density → actual DC/AC verification →
complete switched transient. For a single grounded load,

\[
g_m\gtrsim\frac{C_L\ln(1/\epsilon_s)}{t_s},\qquad
I_D=g_m/(g_m/I_D),\qquad W=I_D/J_D.
\]

Our state capacitor is between **two** finite-impedance diode nodes. Neglecting
their intrinsic capacitances initially,

\[
\tau_{\rm diff}=C\left(\frac1{G_x}+\frac1{G_r}\right),
\qquad G_i=g_{m,i}+g_{ds,i}.
\]

The first population omitted the reference impedance and is retained as an
unsuccessful sizing approximation. The next pass includes it. With equal
reference currents and minimum operand `2^−0.5`, its conservative resistance
factor is `1+sqrt(2)`. The actual final reference current is 1.5× larger and
is checked with measured conductances.

For grounded intrinsic capacitances `cx,cr`, the two-node model has

\[
\mathbf C=\begin{bmatrix}C+c_x&-C\\-C&C+c_r\end{bmatrix},
\quad\mathbf G=\operatorname{diag}(G_x,G_r),
\]

\[
\tau_{\rm slow}=\frac{B+\sqrt{B^2-4A G_xG_r}}{2G_xG_r},\quad
A=C(c_x+c_r)+c_xc_r,\quad
B=G_x(C+c_r)+G_r(C+c_x).
\]

The independent analytical checker verifies this expression against the matrix
eigenvalues. The fresh device characterization supplies diode-port AC
capacitance rather than substituting a transistor's `Cgg` blindly.

Width itself adds capacitance. If `Cload=Cfixed+cΣW`, fixed inversion gives

\[
t_s\simeq\lambda\left[\frac{C_{\rm fixed}}{(g_m/I_D)J_DW}
+\frac{c_\Sigma}{(g_m/I_D)J_D}\right].
\]

There is a self-loading time floor within this model. Increasing width alone
cannot cross it. At table L=1 µm and gm/ID=26, current density is only
2.459 nA/µm and the fixed-drain `ft` proxy is 3.211 MHz. That point creates
very large devices for a sub-microsecond acquisition target. One initial
168.91-µm single-device proposal was rejected by model binning; it is not a
simulated passing device or an area result.

The retained coordinate is **table gm/ID=23 V⁻¹, L=0.5 µm**:
`JD=138.1146 nA/µm`, width 1.86 µm, operand reference current 256.893 nA.
The exp device initially shares that geometry. Its actual operating point
is independently checked, not assumed from the table label.

| Fresh device measurement, retained geometry | TT27 | SS85 |
|---|---:|---:|
| Diode gm/ID at Iref | 22.5328 V⁻¹ | 19.1228 V⁻¹ |
| Diode `(gm+gds)/I` | 22.7027 V⁻¹ | 19.2671 V⁻¹ |
| Diode AC port capacitance | 3.5512 fF | 3.5300 fF |
| Worst sampled small-signal acquisition pole, C=600 fF | 214.59 ns | 253.13 ns |
| Six-time-constant (`ln400`) estimate | 1.286 µs | 1.517 µs |

The pole estimates use the actual 1.5× reference current and minimum input.
They omit switch resistance and charge; they are local estimates rather than
proof of an arbitrary large-step settling guarantee. Transients choose the
actual schedule. The older 1-nA/0.42/1-µm device's measured diode gm/ID was
24.25 at TT, despite its illustrative table-26 label.

Sources: [DC/AC characterization](../../../../analog/testbenches/tb_imc_log_gmid.py),
[candidate data](../../../../build/sim/imc_log_gmid_candidate.json),
[reference-bias data](../../../../build/sim/imc_log_gmid_reference.json), and
[independent critic](IMC_LOG_PIPELINE_CRITIC.md).

Transmission gates are strongly driven switches; their sizing also needs
on-resistance and injected charge across the signal range. Applying saturation
gm/ID equations to them as though they were amplifiers is inappropriate.
The retained switches are Wn=Wp=0.42 µm, L=0.15 µm. For the conditional scaling
`Ron∝1/W`, `Qinj∝W`, increasing both C and W preserves the deterministic
settling/injection tradeoff; it mainly changes noise and physical size.

## 4. Physical experiments and retained failures

All entries below use one-point current gain calibration. Product RMS is over
the non-calibration samples. A fresh short cohort changes ten random pairs;
the fixed diagnostic pairs are deliberately reused. A final `(1,1)` tests
history dependence without recalibrating the gain.

| Experiment | Complete interval | Max product error | Result |
|---|---:|---:|---|
| Original 1 nA, 0.42/1 µm, 200 fF, wide range, TT | 300.2 µs | 10.277% | FAILED |
| Same circuit, centered factor-two range, TT | 300.2 µs | 1.636% | FAILED |
| Original bias forced to 100 ns acquisition/evaluation, TT | 400 ns | 60.077% | FAILED |
| Table gm/ID23, L0.3, series-source sizing, 200 fF, TT | 400 ns | 3.438% | FAILED |
| L0.5, gm/ID23, 200 fF, κ1.5, TT | 1.2 µs | 1.592% | FAILED |
| Same coordinate, 400 fF, proportionally longer acquisition/evaluation | 2.2 µs | 1.071% | FAILED |
| Retained 600-fF geometry, 1.5 µs acquisition/1.5 µs evaluation, TT | 3.2 µs | 0.900% | PASS deterministic gate |
| Same geometry, 1.5 µs acquisition/100 ns evaluation, TT / SS | 1.8 µs | 0.900% / 0.726% | PASS deterministic gate |
| Frozen geometry, 1.0 µs acquisition/100 ns evaluation, TT / SS | 1.3 µs | 0.804% / 1.330% | TT PASS; SS FAILED |
| Frozen geometry, 0.8 µs acquisition/100 ns evaluation, TT | 1.1 µs | 1.458% | FAILED |
| Frozen geometry, 1.2 µs acquisition/100 ns evaluation, fresh short cohort, TT / SS | 1.5 µs | 0.878% / 0.647% | PASS deterministic gate |

The final short TT cohort has approximately 0.313% RMS product error and
SS 0.234%. Complete positive source delivery is approximately 2.768 pJ/word
at both corners. The valid sample is taken 1.3 µs after the start of a word;
1.5 µs includes closing operations and readiness for the next word. These are
configured, tested finite-stream times, not an infinitesimal signal-bandwidth
or universally proven settling-time minimum.

Shrinking only the exp transistor was tested and **failed to improve accuracy**.
For L0.3, table gm/ID23, changing output width from 5.38 to 0.42 µm raises
maximum error from 3.438% to 5.046%. Fresh DC characterization confirms that
width-dependent device behavior changes the exp/log slope ratio; gate-capacitance
reduction alone was an incomplete argument. Higher gm/ID also failed in several
short-period candidates because larger devices loaded the held node more.

Two early 1-pF/1-ms acquisition runs aborted with numerical timestep failures.
They provide no complete accuracy verdict. A nonoverlap-clock diagnostic did
not repair that abort. Original closing clocks also overlapped reference and
operand connections at word boundaries; all new sizing runs explicitly open
the operate path 100 ns before the next sample, and account for closing energy.
The unsuccessful originals are preserved. A larger 9×9 input-grid qualification
also encountered a simulator breakpoint failure; its diagnosis and final outcome
are recorded in the validation addendum below.

Every independent supply/read/clock voltage-source port contributes
`integral max(−Vsource Isource,0) dt`. Operand and reference current sources are
fed from the measured 1.8-V supply: their power is already included in that
supply delivery and is not counted twice. The mean covers complete acquisition,
evaluation and closing intervals; only the first calibration word is excluded.
This is an ideal-source boundary, not measured regulator/clock-generator power.

The source freezes a generator snapshot for each new run. An independent
[result audit](../../../../scripts/compiler/metrics/imc_log_sizing_report.py) checks deck and
snapshot hashes, product arithmetic, declared gates and energy averages.
[All completed sizing points](../../../../build/research/imc_log_sizing/sweep.csv) and
[the finite-population Pareto set](../../../../build/research/imc_log_sizing/summary.json)
retain unsuccessful points. Noise and chip area are not fabricated Pareto axes.

## 5. Pipeline and mixed-format implications

An analog latch here means sample/hold state. Regeneration to a rail does not
retain a multilevel number unless another variable, such as decision time,
encodes magnitude. Two alternating holders can overlap acquisition and readout,
but cannot remove the first result's serial dependency or the ADC service work.

The independent [physical two-bank experiment](IMC_ANALOG_PIPELINE_ROUND.md)
uses real Sky130 switches and two 304-fF holders. It supports a scheduled
395→295-ns initiation interval with the same 395-ns first completion. However,
10.75/10.91-mV capture errors and 2.94/4.56-mV passive-read errors fail its
accuracy screens. A no-isolation fault causes 310.7-mV read error. The proposed
pipeline is therefore not counted as an accurate throughput improvement.

The new log multiplier has not been attached to the normal core's `accj` node.
Its inputs are currents; an actual retained linear voltage needs a paid
voltage-to-current/log interface. Its output is measured against an ideal
compliance supply; a real column integrator changes loading and headroom.

For a true MAC, expand each concurrently represented product before summing:

\[
y=\sum_i s_i\exp(\ell_{x,i}+\ell_{w,i}),\qquad s_i\in\{-1,+1\}.
\]

One exp device after pooling product logarithms cannot recover this sum.
Products `(1,4)` and `(2,2)` have identical summed logs but linear sums 5 and 4.
Signs need steering and exact zero needs a separate mask. Centered mantissas
need explicit exponents; different product exponents must be aligned before
their currents or charges are mixed. Charge sharing remains useful in both
representations, but has different arithmetic meanings and calibration needs.

The strongest retained architectural hypothesis is centered log mantissas,
live local slope references, calibrated static weights, local expansion and
linear charge accumulation, with analog storage only where it amortizes real
service. It remains **SPECULATIVE** until a complete signed two-product sum,
including input conversion and output loading, passes. The present result
does not justify replacing the current normal-number core.

## 6. Noise, area, PVT and comparison limits

At 300 K, `sqrt(kT/600 fF)≈83 µV`. Multiplying by gm/ID≈23 gives a roughly
0.19% single-state relative-noise reference. It omits input/reference device
noise, actual sampling covariance, flicker noise and readout noise. At the
roughly 89-nA minimum exp current, an independent shot-noise model gives
approximately 0.43% RMS for an ideal 100-ns integrated observation. The SPICE
fixture does not implement that noisy integrator. A deterministic 0.9% maximum
does not establish a 1% total-error guarantee.

One-point gain calibration can cancel ideal constant threshold/gain offsets;
it cannot prove immunity to slope-factor mismatch, voltage dependence, switch
mismatch or temperature changes after programming. No foundry Monte Carlo,
transient-noise yield, voltage sweep, FF/SF/FS qualification or PEX has passed.
Each corner is calibrated separately. The fixed κ and geometry across TT/SS
are useful evidence, but stored-log temperature tracking is still untested.

The four compute MOS devices occupy a **4.10-µm² gate-area proxy including
the six switch transistors**, not a layout footprint. The capacitor dominates:
at the official Sky130 nominal 2-fF/µm² MiM area density, 600 fF corresponds
to roughly 300 µm² of single-layer capacitor area before routing and edge terms.
Two supported MiM layers can reduce ideal footprint if stacked; that is still
not an extracted layout. See the [Sky130 device documentation](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html).

Replicating this state at 79.69 million concurrent weight positions would cost
about 23,908 mm² in that single-layer area model. That conditional calculation
rejects naive full replication as a minimal-area architecture. Sharing the
state changes concurrency and must pay its scheduling, fanout and storage costs.

The fresh normal-core benchmark is a 128-term, eight-output charge MAC; the
new block is a single positive product with different range and calibration.
Their errors and energies cannot be compared as matched hardware throughput.
The new scalar's approximately 2.77 pJ is far above the normal core's reported
4.5-fJ/MAC ideal-interface figure, although the boundaries differ. No chip TOPS/W
or winner can be inferred from that mismatch. Historical Mythic comparisons
also require matched weight capacity, ADC count, precision and complete power;
the existing [system benchmark](IMC_SYSTEM_BENCHMARK.md) keeps those gates explicit.

## 7. Prior art and verdict

The broad concept is established: capacitive log summation and exponential
readout appear in [Harrison's Caltech thesis](https://thesis.library.caltech.edu/6076/1/Harrison_rr_2000.pdf)
and [mixed-mode multiplier patent US10594334B1](https://patents.google.com/patent/US10594334B1/en).
The more recent [dynamic translinear multiplier disclosure](https://patents.google.com/patent/WO2025136466A1/en)
reuses a device across sampled log/exp phases and describes pipelined operation.
See the [extended primary-source search](IMC_LOG_PIPELINE_PRIOR_ART.md) for
floating-gate, memory, converter and regeneration variants. gm/ID sizing and
reference-bias adjustment do not themselves establish novelty.

**VERIFIED within stated models:** charge/log arithmetic, the two-node pole
calculation, fresh reproduction of the normal IMC core, and completed deterministic
scalar product screens. **STRONGLY SUPPORTED:** moderate inversion plus adequate
state capacitance and a physically shifted reference improves this particular
log/charge/exp circuit's error-delay tradeoff. **SPECULATIVE:** a useful mixed-format
IMC architecture or new Pareto improvement over the strongest prior hardware.
**FAILED:** the initial 1% scalar gates, short-period corner failures, output-width
shortcut, and accurate capture in the present two-bank pipeline.

The next architecture acceptance test must be an actual signed two-product sum
with paid input conversion and a connected column receiver. Its purpose is to
determine whether sharing log generation and state can recover enough energy
and area to compete with the normal core. A larger isolated scalar sweep cannot
answer that system question.

## Validation addendum

The final short-cohort TT 0.2-ns and 0.1-ns runs differ by at most
2.676×10⁻⁶ in relative recovered product; complete positive energy differs
by 0.00190%. Maximum errors are 0.877420% and 0.877688%, respectively.
The SS 0.2-ns result is 0.647364%. This numerical control supports the
deterministic short-cohort conclusion.

The uninterrupted 102-word validation stream, comprising the initial cohort,
a shuffled 9×9 grid and repeated reference, did **not** complete at either
corner. Both original runs abort at 62.999 µs. An independent diagnostic
removing two electrically redundant zero-volt sensing sources agrees with
its original short control within 3.30×10⁻⁹ relative sampled current but
still aborts on the full stream. Removing only collinear PWL vertices moves
the abort to 124.5 µs; changing only timestep to 0.19 ns moves it to
37.499 µs. This implicates numerical breakpoint scheduling, but the exact
cause remains unresolved. No incomplete trace is extrapolated into a pass.
The [diagnostic record](../../../../build/research/imc_log_zero_source_diagnostic/README.md)
preserves all five controls and transformed decks.

Independent audit also finds a stable 100-ns current observation interval
inside the paid closing interval for the 1.8-µs TT/SS cases. Integrating their
saved current numerically retains the <1% deterministic product gate. This
does not implement an integrator or establish its noise. Reusing the TT
calibration gain on the saved SS 1.8-µs cohort also passes (about 0.5601%
maximum), a useful partial result; it is not an in-run temperature-transition
or programmed-state-retention test. See the [critic addendum](IMC_LOG_PIPELINE_CRITIC.md).

## Reproduction

Use the cached Nix Python/NumPy environment in this workspace; `ngspice` resolves
through the pinned `build/ngspice43` path. Representative passing short test:

```sh
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_log_sizing.py --length .5 --gmid 23 --time-ns 1500 --cap-ff 600 --reference-ratio 1.5 --evaluate-ns 100 --acquire-ns 1200 --seed 97404
```

Add `--corner ss --temp 85` for the fixed SS case, or `--step-ns .1` for the
TT timestep control. `--time-ns 1500` selects the gm/ID-derived geometry;
`--acquire-ns 1200` changes only actual timing while retaining that geometry.
Changing `--time-ns` instead resizes devices and is a different experiment.
Failing single-case screens write their result and then exit nonzero.

The source is [tb_imc_log_sizing.py](../../../../analog/testbenches/tb_imc_log_sizing.py),
using [the physical multiplier generator](../../../../analog/testbenches/tb_imc_log_charge.py).
Reports and testbenches are research additions; production circuits, flow
templates and external notes were not changed.
