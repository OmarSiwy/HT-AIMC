# Independent critic: logarithmic charge arithmetic and analog pipelines

Research date: 2026-09-10. **No improved complete IMC architecture is verified.** The useful surviving direction is a narrow-range log multiplier with a live slope reference, calibrated resident weights, explicit signs/zeros, and linear charge accumulation. Its area, conversion overhead, speed, precision and novelty remain open. Straight equal-cap sharing with an unchanged exp slope fails multiplication. Pooling product logarithms before one exp fails a dot product for mathematical reasons.

**Later sizing result:** the physical scalar multiplier now passes a bounded deterministic 1% product screen at TT27 and SS85 with fixed geometry and a 1.8-µs word. Section K independently audits this result, its noise/area limits, and the retained faster failures. This is a useful circuit result, not verified 1% noisy precision or an improved IMC system.

This report is independent of the proposing circuit branch. Reproduction is in [imc_log_pipeline_analysis.py](../../../../scripts/compiler/metrics/imc_log_pipeline_analysis.py); its self-checking run writes the numerical record. The fixed seed is 260910. **VERIFIED** below means an explicitly stated identity, numerical calculation or captured simulation result, never a fabricated chip or complete architecture. Source hashes are embedded in the numerical record. The [prior-art branch](IMC_LOG_PIPELINE_PRIOR_ART.md) and [pipeline experiment](IMC_ANALOG_PIPELINE_ROUND.md) supply complementary evidence.

## Problem and comparison boundary

Preserve signed MVM behavior, `y_j = sum_i x_i w_ij`, at the real workload's accepted quality. Compare total joules/MVM, useful MVM/s, first-result latency, installed weight capacity and converter count, physical area, and maximum/normalized output error. The user's minimal-area objective supersedes the old contract's infinite-area exploratory assumption. No arbitrary analog arithmetic block or ideal log/exp source may be counted as a physical solution.

Free variables include representation, dynamic range, exponent grouping, log encoding slope, input fanout, weight programming, cell geometry, sample capacitance, switch phases, exp-device reuse, column compliance, converter allocation and calibration. Hard accounting includes input conversion, signs/zero controls, weight storage, references, analog holders, exp branches, accumulation, ADCs, exponent alignment and digital control. A low multiplier transistor count is not a system-area measurement.

The strongest required comparators are the existing charge-domain IMC path at equal quality/resources, classical static and dynamic translinear multiplication, programmable floating-gate multiply/accumulate, and the [Mythic comparison boundary](IMC_SYSTEM_BENCHMARK.md). That benchmark separates vendor claims from project measurements; its headline 25 TOPS / 3–4 W corresponds to 240–320 fJ/MAC when a MAC counts as two operations. The circuits examined here do not approach a complete equal-resource comparison.

For numerical screens use `s = (gm/ID)^−1 = 1/26 V = 38.462 mV`, 300.15 K, 1.8 V, and positive normalized magnitudes in `[1/128,1]`, unless stated otherwise. These are declared assumptions, not a fit valid over every device bias.

## A. What the proposed primitive actually computes

Let logarithmic encodings be `vx = V0 + Sx ln x`, `vw = V0 + Sw ln w`, for positive magnitudes. Sharing capacitors Cx,Cw with a neutral parasitic Cp gives

\[
v_h-V_0=\frac{C_xS_x\ln x+C_wS_w\ln w}{C_x+C_w+C_p},\qquad
I_o=I_r\exp[(v_h-V_0)/s].
\]

Thus `Io/Ir = x^ax w^aw`, where `ax=Cx Sx/(s Ctotal)` and `aw=Cw Sw/(s Ctotal)`. Product correctness requires **both exponents equal one**.

- Equal C, Cp=0, and Sx=Sw=s give `sqrt(xw)`. This is a useful geometric mean, but **FAILED** as multiplication.
- Equal C and Sx=Sw=2s give exactly `xw`. A matched two-device diode stack can provide an approximately doubled logarithmic slope; real body/source/drain conditions and compliance must be checked. This algebra is **VERIFIED**, not its arbitrary PDK realization.
- Known unequal C can be compensated by separate encoding slopes. A common metadata scale alone cannot correct two different operand exponents after the original operands have been discarded. Even equal attenuation still needs a paid slope/reference change in the exp decoder.

The fixed-seed checker obtains maximum corrected relative error `2.0e−15`. A 51%/49% share with nominal double slopes instead gives up to **10.030%** relative error over the declared input range. A constant gain calibration cannot remove this input-dependent error.

A physically different solution stacks capacitor voltages. Sample a capacitor C with top at vx and bottom at V0, release the top, then move the bottom to vw. With top parasitic Cp referenced to a fixed node, charge conservation gives

\[
v_h=v_x+\frac{C}{C+C_p}(v_w-V_0).
\]

For single-slope logs the exp output is `x w^[C/(C+Cp)]`. At Cp/C=0.05, the checker finds **25.984%** maximum relative error. A scalar offset/gain fit does not remove the wrong exponent. Differential stacking may improve clock/reference rejection but does not make loading vanish. Reference covariance and switch charge must be measured in its actual phase sequence.

## B. Expansion cannot be moved after a pooled logarithmic dot product

For products `pi=xi wi`, `sum ln pi = ln product pi`; exponentiation returns a product of products. The two product lists `[1,4]` and `[2,2]` have identical pooled logarithms, yet their sums are 5 and 4. Therefore **no decoder of that one pooled scalar can recover both dot products**, independent of device quality. This information-loss counterexample is **VERIFIED**.

The constructive options are to expand each concurrently evaluated product into a linear current/charge before summation, or execute an explicit log-domain addition recurrence:

\[
\ln(e^a+e^b)=\max(a,b)+\ln(1+e^{-|a-b|}),
\]

\[
\ln|e^a-e^b|=\max(a,b)+\ln(1-e^{-|a-b|}).
\]

The latter needs magnitude comparison, nonlinear correction and sign/zero handling; opposite nearly equal operands are particularly sensitive. It has not removed accumulation complexity.

With R rows and M columns, row-shared input logarithms require R conversions per vector, but fully parallel local expansion still requires R×M exp branches. If only E expanders are installed, their work contributes `II >= R M t_exp/E` under uniform non-overlapped exp service. Resident log weights can amortize programming conversion across tokens. Exact activation-log caching across multiple projections is also possible; cache lifetime, row distribution and analog fanout remain physical costs.

**A diode logs current, not a held voltage.** A linear-voltage/charge input needs a transconductor or voltage-to-current servo before a diode logarithm, unless the preceding stage already supplies a suitable current. Root's scalar experiment below starts with ideal current operands. It therefore does not validate charge→log conversion. Conversely, integrating exp current supplies a linear charge, but subsequent logarithmic stages again need the appropriate input interface.

## C. Device equations, PVT and what calibration can remove

The working weak-inversion approximation is

\[
I_D=I_0\exp\left(\frac{V_{GS}-V_T}{nU_T}\right)
\left(1-e^{-V_{DS}/U_T}\right),\quad U_T=kT/q,
\quad g_m/I_D\approx1/(nU_T).
\]

Classical MOS translinear loops use sums of junction/gate voltages to form products and quotients, but matched slopes, appropriate body conditions and output compliance are actual requirements. The published treatment includes multiplier/divider circuits, noise and bandwidth limitations. See [Andreou and Boahen, 1996](https://web.stanford.edu/group/brainsinsilicon/documents/96_journ_JAICSP_Trans.pdf). The calculations below are independent consequences of the stated approximation, not quoted process specifications.

Even at `VDS=4UT`, the omitted reverse-current factor is 1.8316%. For a 0.1% bound on that factor alone, `VDS >= UT ln1000`: **178.7 mV at 27°C, 213.2 mV at 85°C**. Output resistance, DIBL and body dependence remain additional errors. Stacked devices need enough drain compliance individually; voltage headroom cannot be inferred from the log signal swing alone.

For equal sharing let `beta=S/(2s_exp)`. A slope error produces `p_hat/p = exp[(beta−1) ln p]`. Over a product range of 16384:1, ±1% beta error produces −9.248% / +10.191% extreme error. A conservative symmetric slope bound for 1% relative product error is **0.1025%**. Narrow mantissas in `[1/2,1]` relax that bound sevenfold, to **0.7178%**, because their product log range is only ln4. Centering each mantissa in `[2^−1/2,2^1/2]` gives the same total range and additionally halves the largest distance from a unity calibration point.

Double-slope encoding consumes **373.2 mV per operand** over 128:1, versus **53.32 mV** over a factor of two. These are signal spans, excluding reference levels and device headroom.

If a fixed log voltage programmed at 27°C is read at 85°C, holding n unchanged, its exponent becomes `300.15/358.15=0.83806`. The smallest normalized product is then read **4.814× too large**. A matched same-temperature translinear loop can cancel common UT; a retained voltage does not automatically do so.

One constructive reference is a live `DeltaVref=s_local ln2` generated from matched diode devices carrying a 2:1 current ratio. Store dimensionless log2 codes or capacitance ratios and regenerate voltages from this reference. This cancels common slope temperature dependence in the ideal model. It does not cancel ratio error, finite gm, reference noise/fanout or per-cell slope mismatch. Temperature compensation is established prior art: [US8207776B1](https://patents.google.com/patent/US8207776B1/en) discusses logarithmic slope temperature correction. This proposed integration is not established novel.

A useful calibration decomposition is

\[
I/I_r=G x^{a_x}w_{prog}^{a_w}.
\]

For a static desired weight w, programming `wprog=(w/G)^(1/aw)` removes G and the static weight-path exponent, if the write range and feedback resolution support it. The remaining error is `x^(ax−1)`. **One-point per-cell write/verify can legitimately remove static gain, but cannot establish input-slope accuracy.** This suggests focusing shared precision on the activation coupling while calibrating the stored weight path. It must be verified with multiple activation values after programming, including reserved inputs.

The local sky130 mismatch file specifies `vth0_slope=3.356e−3` and `vth0_slope1=7.356e−3`; TT models apply an independent Gaussian coefficient divided by `sqrt(l*w*mult)`, with the larger coefficient used in some bins. Source: `~/.volare/sky130A/libs.ref/sky130_fd_pr/spice/sky130_fd_pr__nfet_01v8__mismatch.corner.spice` and the corresponding `__tt.pm3.spice`. The first coefficient alone gives the following **conditional untrimmed threshold contribution**:

\[
\sigma_{\ln I,one}\simeq A_{V_T}/(s\sqrt{WL}),\qquad
\sigma_{\ln I,4}\simeq2A_{V_T}/(s\sqrt{WL}).
\]

A four-independent-device loop needs approximately **304.5 µm²/device** for 1% RMS from that contribution alone; one independent exp device needs 76.1 µm². At 0.1%, these areas are 100× larger. **These are not recommendations to oversize every cell or a foundry Monte Carlo result.** Static threshold terms can often be trimmed into resident weights. The model also contains voff/toxe variation; equal global corners, or `nfactor_slope=0`, do not prove absence of slope mismatch. Direct Monte Carlo with the actual programming procedure is required.

## D. Sampling, leakage, current noise and signed cancellation

For two independent ideal samples of kT/C noise, charge-conserving equal sharing has variance `kT/(2C)`. No additional kT/C is added merely because charge is conserved through the joining switch; actual sampled differential modes depend on the topology and observation time. With double-slope encoding and exp slope s, log-product variance is

\[
v=\sigma_{\ln p}^2=kT/(2Cs^2).
\]

For Gaussian log error, output mean bias is `exp(v/2)−1` and coefficient of variation is `sqrt(exp(v)−1)`. At C=20 fF, the favorable model yields **0.8369% CV** and 35.0 ppm mean bias. A 0.1% CV target requires **1.401 pF per operand sample** before log-device, reference, exp-current or ADC noise. Unaveraged addition of two independently sampled single-slope logs has four times this capacitor requirement at the same target; double-slope averaging trades signal swing for noise. These counts change with correlated sampling and must not be treated as a topology-independent bound.

Hold droop gives `eta ≈ Ileak thold/(Cs)`. A 20-fF log holder needs net leakage below approximately **7.69 pA** for 1% error over 1 µs. Switch opening offsets are often more severe: 1 mV becomes about 2.63% exp error. The separate pipeline experiment's approximately 10.8-mV capture error would correspond to about 32% multiplicative error if applied directly at this slope. Its 1-mV linear-storage screen is consequently not a high-precision log-storage qualification.

For the saturated weak-inversion shot-noise model, one-sided `SI=2qI`. Ideal rectangular integration over T gives `var(Q)=qIT`, hence relative RMS `sqrt(q/(IT))`. A single independent branch therefore needs:

| Per-product RMS target | IT | Current for 100 ns | Branch energy at 1.8 V |
|---|---:|---:|---:|
| 1% | 1.602 fC | 16.02 nA | 2.884 fJ |
| 0.1% | 160.2 fC | 1.602 µA | 288.4 fJ |

At 25 TOPS, the 0.1% case spends **3.60 W in one branch per MAC alone**. This is a conditional warning, not a universal MAC energy bound: the required per-product accuracy depends on the dot product and workload. Input/reference branches and flicker noise can add cost, whereas correlations change propagation. A recent primary log-ADC paper also analyzes translinear shot noise, but its 180-nm simulated converter targets a different range/speed regime and does not validate this IMC: [Communications Engineering, 2026](https://doi.org/10.1038/s44172-026-00589-5).

For signed products pi with y=sum pi and small independent log errors of RMS sigma,

\[
\frac{\sigma_y}{|y|}\simeq\sigma\frac{\sqrt{\sum_i p_i^2}}{|y|},\qquad
\frac{|\delta y|}{|y|}\le\epsilon\frac{\sum_i|p_i|}{|y|}
\]

for bounded individual relative errors epsilon. Independent positive/negative-bank current noise depends on the sum of magnitudes even when their difference nearly cancels. More precisely, with output charge scale Q0 and independent shot noise, `var(y_hat)=q sum|pi|/Q0`.

Do not apply the cancellation factor to every noise source. A fully common multiplicative error gives `delta y=eta y`. For jointly Gaussian equal-variance log errors, pairwise correlation rho, and mean-corrected outputs, the exact variance is

\[
\operatorname{var}\hat y=(e^{\sigma^2}-e^{\rho\sigma^2})\sum_i p_i^2
+(e^{\rho\sigma^2}-1)y^2.
\]

The checker verifies this with 200,000 draws per case. At 1% log-error RMS, products `[1,−0.999]` give **1413.5% relative output RMS** for independent errors, versus **1.000%** for fully common errors. At exact zero, relative error is undefined; the independent absolute RMS is 0.01414, while fully common errors cancel exactly. The reported Monte Carlo is this mathematical noise model, **not foundry mismatch or transient-noise SPICE**.

A possible partial insight is to reuse one calibrated exp device across terms so its fixed gain error is common. This exchanges spatial mismatch for service time and storage. Input-dependent transfer error and independent shot noise persist. It is a candidate scheduling tradeoff, not evidence of a new free cancellation mechanism.

## E. A low-current row logarithm has a fanout/speed gate

A diode log has a local time constant `tau=Cload/gm=Cload*s/I`. With 1024 simultaneous 20-fF samples, `Cload=20.48 pF`. A 100-ns, 1% settling target requires approximately **gm=0.943 mS**, **Imin=36.3 µA** at gm/ID=26. A 128:1 input current range then reaches **4.65 mA per row** if the same static diode directly drives every sample.

This is not only a linearized tail argument. For an ideal exponential diode driven by a stepped input current, define z=Idiode/Iin. Then

\[
\dot z=\frac{1}{\tau}z(1-z),\qquad
z(t)=\left[1+(1/z_0-1)e^{-t/\tau}\right]^{-1}.
\]

The 128→1 transition needs 4.607 low-current time constants to reach 1% current error; the 1→128 transition needs 9.439 high-current time constants. The exact falling-step requirement is 36.291 µA. At 1.8 V for 100 ns the static row branch delivers **6.532–836.15 pJ**, or **6.38–816.55 fJ/MAC** amortized across those 1024 columns, before product expansion and control.

Buffering, staged acquisition, local log caches, adaptive precharge, exponent ranging or a different translinear interface can escape this particular direct-drive cost. Each changes the resource/energy/noise model and needs its own test. Simply declaring the log converter shared does not remove its load. Bigger low-noise capacitors make this fanout burden worse.

## F. Numerical and transistor verification retained, including failures

The new analytical checker asserts corrected/incorrect identities, zero-aware signed expansion, the scalar information-loss counterexample, and noise covariance. Its quantization experiment uses 8192 synthetic signed 128-term dots, 5% exact zeros, one sign bit and eight magnitude bits in both formats, with 255 nonzero levels plus zero. Only input quantization is included.

| Nonzero magnitude distribution | Linear output CSNR | Log output CSNR | Linear nonzero operand relative RMS | Log nonzero operand relative RMS |
|---|---:|---:|---:|---:|
| Uniform on [1/128,1] | 51.291 dB | 42.041 dB | 1.270% | 0.5513% |
| Log-uniform on [1/128,1] | 46.085 dB | 42.139 dB | 4.542% | 0.5516% |

Here `CSNR=20 log10(||y||2/||yhat−y||2)`. Log quantization improves individual relative accuracy, especially for small values, yet loses this dot-product normalized-error comparison. Neither observation proves neural accuracy or universal superiority. Nonuniform programmed log levels could exactly represent a fixed integer weight alphabet; that is a different representation from uniformly spaced log codes and needs its own programming precision/area accounting.

Root's physical scalar fixture tb_imc_log_charge.py was independently inspected. It uses three grounded diode-connected sky130 NMOS log devices for x,w and a reference; native transmission-gate capacitor stacking; and a grounded NMOS exp device with drain biased at 0.9 V. W=0.42 µm, L=1 µm, nominal reference current 1 nA, and C=200 fF. The schedule is 200 µs acquisition plus 100 µs evaluation and 0.2 µs control allowance. Calibration is **one scalar at (1,1), independently recalibrated for each corner/configuration**. These are frozen records available when this report was written:

| Operation / range | Corner | Maximum product error | RMS product error | Declared 1% gate |
|---|---|---:|---:|---|
| Native stack; each operand [0.25,4] | TT27 | 10.277% | 4.129% | FAILED |
| Native stack; each operand [0.25,4] | SS85 | 10.151% | 4.321% | FAILED |
| Native stack; each operand [2^−0.5,2^0.5] | TT27 | 1.636% | 0.7340% | FAILED |
| Native stack; each operand [2^−0.5,2^0.5] | SS85 | 1.675% | 0.7437% | FAILED |
| Equal-cap average; each operand [0.25,4] | TT27 | 313.056% | 98.548% | FAILED |

The average control's maximum geometric-mean error is only **3.264%**, supporting the incorrect-arithmetic diagnosis. Narrowing the range helps the physical stack substantially, but it still fails the declared gate and presently uses **300.2 µs per scalar word**. The captured positive delivery is approximately 1.95–2.64 pJ/word across these stack cases; it is not an array fJ/MAC or high-throughput measurement.

A separate fast narrow-range TT27 run, with 100 ns acquisition, 100 ns evaluation and 200 ns control allowance, gives **60.077% maximum / 25.685% RMS product error** in a 400-ns word. Its 7.272-fJ positive delivery is an energy measurement of a failed computation, not a Pareto improvement. Frozen record: `imc_log_charge_stack_tt_27_c200p0_a0p1_e0p1_i1p0_w0p42_s97402_dt0p1_m0p0_span0p5.json` under `build/sim/`.

Frozen result names under `build/sim/` start `imc_log_charge_stack_{tt_27,ss_85}_c200p0_a200p0_e100p0_i1p0_w0p42_s97402_dt50p0_m0p0`; narrow cases append `_span0p5`. The average control substitutes `average_tt_27`. Noisy device yield, PEX, signed accumulation, input voltage-to-current circuitry and output converters are absent. Separate per-corner calibration is not evidence that a programmed state survives a temperature transition. Subsequent experiments should be reported separately, preserving these failures.

## G. Constructive population and recombination

| Candidate | Physical opportunity | Decisive cost or falsification gate | Status |
|---|---|---|---|
| Double-slope logs + equal sharing + exp | Correct multiplication without an ideal voltage summer | Doubled signal span, matching, sampled noise, per-product exp and log generation | VERIFIED algebra; SPECULATIVE PPA |
| Native voltage stack + exp | Removes the average factor using a physical SC operation | Operand-dependent parasitic attenuation and switch injection | Initial implementation FAILED; later bounded pass audited in K |
| Live local log reference + centered mantissa + calibrated weight | Small log range and common-temperature tracking; weight-path gain can be programmed out | Activation slope, reference distribution, input ranging, exponent alignment and calibration cost | SPECULATIVE strongest hybrid |
| Same-device dynamic translinear cell + separate analog state | Converts some spatial mismatch to common/dynamic error | Reused device cannot do conflicting phases simultaneously; hold error and independent noise remain | STRONGLY SUPPORTED mechanism; prior art |
| Shared activation-log cache across projections | Amortizes expensive log acquisition when exact same activations recur | Buffers/fanout/retention and exp service remain; workload reuse must be counted | SPECULATIVE architecture |
| Positive local exp currents + sign steering + grouped linear accumulation | KCL correctly performs signed MAC after expansion | Compliance, positive/negative noise, current load, converter allocation | STRONGLY SUPPORTED principle; unverified integration |
| Regenerative latch as log-to-time encoder | `t=τ ln(Vtrip/|vin|)` preserves magnitude in decision time plus sign | Offset, kickback, variable τ, metastability, timing resolution, timestamp/ramp hardware | SPECULATIVE project variant; prior art |
| Log operations only at multiplicative/normalization boundaries | Avoids unnecessary representation transitions through signed linear layers | Needs whole-model comparison and a concrete useful boundary | SPECULATIVE application |

For the strongest hybrid, write `x=sign(x) 2^ex mx`, `w=sign(w) 2^ew mw`, with centered mantissas. Use a matched live slope reference, store dimensionless weight codes, form the mantissa product, expand locally, and steer its sign into linear accumulation. **Different ex+ew must be aligned before their currents/charges are mixed.** Options include exponent buckets with later digital accumulation, binary current gains, or weighted integration time. A single scalar metadata factor after a mixed sum cannot repair different per-term scales. This is the same scale-alignment constraint exposed in [the native-charge critic](IMC_DISCOVERY_CRITIC.md).

Cross-pollination question: what becomes possible if narrow log mantissas are combined with native charge pooling? Correctly scaled linear product charges could be pooled before conversion, reducing ADC service count while log representation replaces a multibit weight structure. The required evidence is simultaneous: paid exponent alignment, accurate signed product charge, preserved charge gain under pooling and equal-error ADC energy. Passing either primitive alone is insufficient.

For the regenerative branch, the decision time rather than the final rail stores log magnitude. A current ramp can turn that time into a voltage/charge, but adds a ramp/reference and hold path. Small timing error implies relative magnitude error `sigma_v/|v|≈sigma_t/τ`; at τ=100 ps a 1% target needs approximately **1 ps RMS timing precision**. Input offset/noise becomes `delta_v/v`, worsening near zero. Regenerative log conversion is already disclosed in [US20120176262A1](https://patents.google.com/patent/US20120176262A1/en). No SPICE proof of this branch exists here.

## H. Prior art and novelty limits

Log/exp arithmetic and translinear product/divider circuits are established. Floating-gate multi-input translinear elements directly combine capacitive input coupling with exponential current responses; see [Minch et al., Caltech primary record, 1996](https://authors.library.caltech.edu/records/tysa2-xdc36). More recently, [Sonnadara and Shah, 2025](https://www.nature.com/articles/s44335-025-00022-8) demonstrate programmable MITE arithmetic on a 350-nm FPAA, including measured multiplication for 10–50 nA input currents and current-domain accumulation. Its operating range, programming and test setting do not establish sky130 IMC precision or speed.

The 2026 logarithmic-converter paper cited above explicitly uses capacitor voltage dividers to set power-law coefficients and reports 180-nm PDK/layout simulation. Thus adjustable capacitance exponents are also close prior art. Regeneration-based logarithmic ADC and temperature-corrected log circuits have patent disclosures cited above. The separate [prior-art audit](IMC_LOG_PIPELINE_PRIOR_ART.md) identifies additional dynamic same-device, pipelined SC log/exp and memory multiplication disclosures. No candidate in this report is called novel merely because its derivation was independent.

Local theory sources used include the notes *Below Threshold the Drain Current Is Exponential Not Zero* and *Weak Inversion Current Flows by Diffusion With an Exponential Law* in the user's circuit-design vault, plus the project's contract and benchmark. External primary sources were checked because the notes alone do not establish current prior art.

## I. What remains unverified and the next decision gates

The most informative next circuit is a **complete signed two-product sum**, including real input-domain conversion, two physically manipulated log states, exp devices, sign/zero steering and the existing linear charge interface. Use a declared accuracy gate derived from the real workload. Program weights on a separate calibration cohort; test unused activation values and cancelling products. Then exercise a temperature transition without silently replacing the programmed state.

Measure acquisition versus minimum nonzero input and fanout; supply/control/input delivery; every device region and column compliance; transient noise and foundry mismatch with programming; timing-step convergence; both serial and pipelined operation; and a loaded converter interface. A small high-current demonstrator is insufficient unless scaling preserves current density, capacitance and noise accounting.

**VERIFIED:** stated ideal arithmetic, information-loss counterexample, conditional analytical budgets, synthetic quantization/noise calculations and the recorded failed scalar screens. **STRONGLY SUPPORTED:** corrected log multiplication, linear current accumulation, common-error cancellation and analog sample/hold scheduling as established mechanisms. **SPECULATIVE:** the live-reference/mantissa/weight-calibration hybrid, regenerative alternative and every system-level superiority claim. **FAILED:** unchanged-slope average as a product, one exp after pooled product logs as a dot product, and the initial scalar stack's declared 1% gate. Later sizing passes are audited below. No successful full-chip PVT, mismatch, noise, layout, task-quality or Mythic PPA comparison has been demonstrated.

## J. Follow-on gm/ID sizing critique: improve time to an accurate product

The follow-on sizing objective is minimum energy/area at a declared maximum product error and time-to-accuracy. Merely settling to a biased final value is not success. Define `t_accuracy` as the earliest time after which `|Iout(t)/Iideal−1|` remains below the frozen gate through the observation interval. If the final static result fails, `t_accuracy` is unqualified, even if internal settling is fast. Keep settling to the circuit's own final value as a separate diagnostic.

### Slope and curvature must be characterized at the correct drain condition

For a diode-connected input log transistor with fixed source/body,

\[
g_{log}=\frac{d\ln I}{dV_{diode}}=\frac{g_m+g_{ds}}{I},
\qquad g_{exp}=\frac{d\ln I_o}{dV_g}=\frac{g_m}{I_o}
\]

at the exp device's fixed drain. In an ideal unloaded stack, the local operand exponent is `ax=g_exp(Vgate)/g_log(Ix)` and similarly for w. A gm/ID lookup at VDS=0.9 V is therefore insufficient to prove matching to a diode at VDS=VGS. Output conductance can speed a diode node while changing its logarithmic slope unfavorably.

The independent DC/AC characterization by the circuit branch confirms the distinction. At W=0.42 µm, L=1 µm, Iref=1 nA, the nominal gm/ID=26 planning coordinate actually gives TT27 diode gm/ID=24.2518, diode log slope=24.5455, and exp slope=24.2343 per volt. Their ratio is **0.987322**. At SS85 it is **0.986728**. The measured diode-port AC capacitances are 1.1919/1.0603 fF at TT/SS, excluding the exp gate and external sample capacitor. These are device DC/AC results, not complete product accuracy. Targets above the lookup branch's actual gm/ID peak are explicitly invalid rather than silently attainable by interpolation.

Even with perfectly inverse log/exp characteristics, moderate inversion introduces a second-order interaction. Let `f(u)=Vlog(Iref exp u)`, with centered input log excursions a,b. Expanding `f^{-1}[f(a)+f(b)−f(0)]` gives

\[
\delta\ln p\simeq-\frac{f''(0)}{f'(0)}ab
=\frac{d\ln g_{log}}{d\ln I}ab.
\]

For centered factor-two operands, `max|ab|=(ln2/2)^2=0.1201`. Allocating 1% log error entirely to this term requires approximately `|d ln g_log/d lnI|<0.0833`; practical allocation must be tighter because other errors remain. For a strong-inversion ideal square law that derivative is −1/2. The checker verifies the local expansion and finds **7.032% exact maximum error at the four centered-mantissa corners** with perfectly inverse square-law devices. Thus perfect matching alone does not turn a strongly nonlinear inverse pair into a logarithmic multiplier. Narrowing range reduces this curvature error quadratically.

A constructive alternative is a row-shared regulated log amplifier holding its log transistor drain at the same fixed voltage as the exp devices while servoing the gate to match input current. It can remove the diode gds slope difference and supply capacitive fanout drive, at the cost of an amplifier. This is established log-amplifier practice, not a newly discovered topology. Directly tying the exp drain to its held gate would load/discharge that state and does not supply free compliance matching.

### Width-dependent loading creates a speed floor

For `g=gm/ID`, current density J=ID/W, fixed load C0 and parasitic load cW proportional to sized width,

\[
t_{settle}\simeq\alpha\frac{C_0+cW}{gJW},\qquad
W=\frac{\alpha C_0}{t_{settle}gJ-\alpha c},\qquad
t_{settle}>\frac{\alpha c}{gJ},
\]

where alpha is the required time-constant count. This condition explains why increasing width at a fixed inversion level eventually stops improving speed. At g=26, L=1 µm and archived J=2.459 nA/µm, each 1 fF/µm of jointly scaled load adds a **72.0-ns 1%-settling floor**. The naive fixed-200-fF/100-ns calculation gives I=354.2 nA, W=144.1 µm, but omits the capacitance of those large devices.

The checker reuses the archived TT27/VDS=0.9 V tables, deriving a **one-fixed-drain-Cgg proxy** from `Cgg/W=gJ/(2πft)`. This is not the actual tied-diode-port capacitance; tying drain to gate changes the charge derivatives, and final geometry can change current density.

| L (µm) | Planning gm/ID | J (nA/µm) | Fixed-C width (µm) | One-Cgg settling-floor proxy | Width including that one-Cgg proxy |
|---:|---:|---:|---:|---:|---:|
| 0.15 | 26 | 185.69 | 1.908 | 0.478 ns | 1.917 µm |
| 0.3 | 26 | 3.216 | 110.16 | 48.02 ns | 211.90 µm |
| 0.5 | 26 | 2.327 | 152.21 | 105.28 ns | No finite solution in this proxy |
| 1.0 | 26 | 2.459 | 144.06 | 228.25 ns | No finite solution in this proxy |
| 1.0 | 22 | 195.20 | 2.145 | 4.914 ns | 2.256 µm |

At L=1 µm, changing planning gm/ID from 26 to 22 costs only 18.2% more current in the naive fixed-load equation while drastically reducing width. That makes moderate inversion worth exploring, provided its **actual** slope/curvature and transient accuracy pass. Shorter L also improves speed but worsens output-conductance sensitivity. The actual device/port measurement must replace these proxies before selecting a final design.

### The reference is a second finite-impedance node

The native-stack acquisition capacitor connects logx to logref. With conductances Gx,Gr and no other capacitors, its differential time constant is

\[
\tau_{diff}=C(1/G_x+1/G_r).
\]

For xmin=2^−0.5 and otherwise constant slopes, this is **2.414 C/Gref**, not C/Gref. A stiff-reference approximation underestimates acquisition time. With grounded intrinsic capacitances cx,cr, the capacitance matrix is `[[C+cx,−C],[−C,C+cr]]`. The exact slow linearized time constant is

\[
\tau_{slow}=\frac{B+\sqrt{B^2-4A G_xG_r}}{2G_xG_r},
\quad A=C(c_x+c_r)+c_xc_r,
\quad B=G_x(C+c_r)+G_r(C+c_x).
\]

For equal G and cx=cr=cg this reduces to `(2C+cg)/G`. Adding an arbitrary twice-Cgg load is not equivalent to solving both coupled nodes. Real shared references introduce still more attached cells and routing, and must be included in fanout/correlation analysis. Large transitions remain nonlinear and require a transient test after this pole estimate.

### Wider switches can trade settling error for held-state error

For a fixed switch topology and bias, approximate `Ron=r0/W`, residual injected charge `Qerr=q0 W`. Then

\[
t_{sw}\simeq\alpha r_0 C/W,\qquad
\Delta V\simeq q_0 W/C,\qquad
t_{sw}\Delta V\simeq\alpha r_0q_0.
\]

Scaling C and switch width together improves kT/C but need not reduce deterministic switch error at fixed speed. TG cancellation, clock edge shape, bottom-plate timing and charge partition can change q0, so this is a conditional design tradeoff, not a fundamental lower bound. Log precision multiplies the residual voltage by g_exp. Choose switch geometry from both settled acquisition and retained-product error, not Ron alone.

The proposed frozen acceptance sequence is: screen a fixed nominal input set at the existing 1% maximum-product gate; retain every failed point; select on total positive delivered energy, t_accuracy and declared geometry/capacitance; then test a separate fixed-seed cohort and all specified corners without changing calibration rules. Final tests must include low-after-high transitions, both operand orders, zero/sign routing once integrated, source/reference loading, hot hold leakage, transient-step refinement and random noise/mismatch with the actual programming procedure. Report transistor W×L and total capacitance as separate **area proxies** until physical layout is available. A candidate that fails accuracy does not enter the energy/delay Pareto frontier, however small its raw energy or nominal phase duration.

## K. Independent audit of the passing sized scalar multiplier

The later sizing wrapper finds a bounded survivor: L=0.5 µm, all four core NMOS widths 1.86 µm, nominal table gm/ID=23, Iref=256.893 nA, reference-diode current **1.5 Iref**, Cstate=600 fF, and three TGs with Wn=Wp=0.42 µm and L=0.15 µm. The input magnitudes lie in `[2^−0.5,2^0.5]`. Acquisition is 1.5 µs, evaluation 100 ns, followed by 200 ns of scheduled closing allowance. Switch nonoverlap is enabled and the final stimulus repeats `(1,1)`.

The independent checker now audits saved records when present. It verifies the netlist and generator-snapshot SHA256 against JSON, checks the zero-valued offset source and absence of behavioral nonlinear circuit sources, parses the raw current/power trace, and recomputes endpoint error, complete observation-window error and full-word energy. These checks pass. The key original passing snapshots have generator hash `a7a4f3c7c55e25e388e71ad2c8eb1ac33e598e517e18b2627cfdeecd59645591`; all individual netlist hashes and result paths are in the generated analysis JSON's `saved_passing_audit` section.

There is **no ideal log/exp element or numerical exponent correction in this circuit**. The postprocessing uses only `Iout/Iout(first 1,1)` for a one-point gain calibration. The 1.5 reference factor is an actual current-source stimulus driving the reference diode. It moves the exp device's operating point and slope physically; it is not a fitted power applied to the reported current. The wrapper records the chosen gm/ID=23 coordinate. Some earlier scalar JSONs also contain a hard-coded diagnostic `lookup_reference_gm_ID=26`; that is not the sized operating point and should not be used as its measured gm/ID.

| Fixed geometry, seed 97403 | Acquisition / evaluation | Word interval | Max error over declared read window | Endpoint RMS error | Complete positive delivery | Screen |
|---|---:|---:|---:|---:|---:|---|
| TT27 | 1.5 µs / 0.1 µs | 1.8 µs | 0.900176% | 0.312733% | 3.356963 pJ | PASS |
| SS85 | 1.5 µs / 0.1 µs | 1.8 µs | 0.726470% | 0.208134% | 3.356368 pJ | PASS |
| TT27, shorter acquisition | 1.0 µs / 0.1 µs | 1.3 µs | 0.804136% | 0.294611% | 2.416118 pJ | PASS |
| SS85, same shorter acquisition | 1.0 µs / 0.1 µs | 1.3 µs | 1.329772% | 0.420889% | 2.416311 pJ | FAILED |
| TT27, still shorter acquisition | 0.8 µs / 0.1 µs | 1.1 µs | 1.457893% | 0.492453% | 2.039793 pJ | FAILED |

An earlier long-evaluation SS85 control also passes at 3.2 µs and 5.888089 pJ; it does not establish a faster point. Shortening acquisition changes residual settling, which can accidentally cancel a static error; the TT-only 1.3-µs pass is therefore not a common-corner timing qualification. The artifacts distinguish each configuration and preserve failures.

Seed 97403 contributes **ten new random operand pairs**, alongside nine fixed noncalibration pairs and the repeated `(1,1)` point. It is not twenty independent new random tests. The repeated reference differs from the first by approximately 0.10 ppm at TT and 0.98 ppm at SS in the 1.8-µs runs. This supports deterministic state restoration in this sequence, not sampled-noise or long-term drift immunity.

### Calibration and timing survive additional bounded checks

The declared read window covers the last 10% of evaluation, so it is only **10 ns** for the 100-ns evaluation setting. The audit confirms the entire window rather than a favorable isolated sample. It also identifies an available **100-ns** interval from 2 ns before the sample to 98 ns after it, ending immediately before the operate switch starts opening. Integrating the saved current over this fixed interval and applying a single calibration integral gives 0.900176% maximum product error at TT and 0.726470% at SS. The maximum instantaneous errors throughout those 100-ns windows are 0.900443% and 0.726710%.

This supports a deterministic 100-ns current observation inside the already paid schedule. It is **not a physical integrator, ADC, or noise simulation**; loading and compliance of a real readout must be added. The observed output is currently an exp transistor draining into an ideal fixed 0.9-V source.

An unexpected partial result survives another adversarial check: reusing the **frozen TT first-point gain** on the SS85 1.8-µs trace still passes, with 0.560093% maximum window error. Thus these two particular saved corners do not require separate recalibration to pass this cohort. This is arithmetic reuse between two separate corner simulations, not an in-run temperature transition, PVT sweep or programmed-state retention experiment. It must not be generalized to arbitrary corners or device mismatch.

### Energy accounting passes; conversion dominates the boundary

The reported positive delivery includes acquisition, evaluation and closing time; its mean excludes only the first calibration word. The audit independently integrates the saved `delivered` trace. Circuit-source inspection confirms VDD, the fixed read drain source, and every true/complement clock are included. The ideal input current branches draw from VDD, so their 1.8-V supply cost is included rather than omitted as a free stimulus.

For the TT 1.8-µs point, the three input log branches account for **2.954046 pJ**, the fixed 0.9-V read port for **0.399641 pJ**, and the remaining fixture delivery is approximately **3.28 fJ**. The near-identical SS energy has the same dominant costs. A real reference/current generator, log input transconductor and read amplifier are absent; their efficiency, headroom and quiescent power are not validated. Conversely, a future architecture may amortize a row-shared log input and reference, cache weights, or gate unused exp current. Such savings require a new circuit/resource accounting boundary rather than simply deleting these measured terms.

The scalar fixture consumes about 3.36 pJ per product, already above Mythic's 240–320 fJ/MAC headline by roughly an order of magnitude, and contains no accumulator/ADC. This is a **scope-limited unfavorable comparison**, not a conclusion that every shared log architecture loses: sharing and stored weights could change the cost. It prevents claiming that this scalar pass alone beats Mythic.

### Precision and physical area remain decisive limits

The smallest recorded TT output is 88.572 nA. In the conditional independent saturated-exp shot-noise model `SI=2qI`, ideal averaging yields **0.4253% RMS over 100 ns**, or **1.3450% over 10 ns**, for that output branch alone. The existing deterministic gate leaves only approximately 0.10 percentage points of worst-case margin at TT. A 600-fF kT/C reference estimate is 83.1 µV RMS at 27°C, corresponding to approximately 0.191% multiplicative RMS at slope gm/ID=23. The actual active log/hold noise covariance may differ, and input/reference, switch and readout noise are still missing. Therefore this result is **not verified 1% noisy precision, eight-bit yield or acceptable signed-dot-product accuracy**.

Current-output noise may be averaged in the 100-ns interval identified above; fixed sampled-state error is not removed by averaging the same held state longer. A noisy two-product cancellation test and a real loaded current integrator would discriminate those two limitations directly. Monte Carlo must include the same allowed gain or weight-programming calibration; raw threshold mismatch before calibration alone is not a valid rejection of the calibrated architecture.

The four core devices and six TG devices total only **4.098 µm² of W×L**, an active-gate-area proxy. The 600-fF ideal capacitor is much larger physically. Sky130 specifies nominal MiM area capacitance **2 fF/µm² per layer** and permits two layers to be stacked: [official device documentation](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html). Ignoring edge terms, its plate footprint is approximately **300 µm² in one layer or 150 µm² with ideal stacking**, before contacts, routing and layout-dependent parasitics. Gate W×L alone consequently cannot substantiate minimal area.

Replicating this state at every one of the benchmark's 79,691,776 weight positions would imply approximately **23,908 mm²** of single-layer plate area, or 11,954 mm² with ideal two-layer stacking. This is a conditional replication calculation, **not a proposed chip-area measurement**. Amortizing state across a row or column, sharing expanders, or encoding weights as thresholds changes both the circuit and its throughput. Those are the necessary next architecture questions.

**Audit outcome:** the positive scalar deterministic pass survives source, calibration, timing-window and energy checks. Its physical reference bias is a useful mechanism for compensating slope error. High-precision noise/yield, layout area, signed accumulation, converter integration, large fanout and a useful chip-level Pareto improvement remain unverified. The result is retained as a **VERIFIED bounded deterministic simulation**, with the broader architecture **SPECULATIVE**.
