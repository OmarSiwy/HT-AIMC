# Identical-unit current-divider IMC investigation

Campaign branch, 2026-09-11. Status: **amplitude-coded timing failure; fixed-current PWM preserves a conditional full-scale charge-accuracy candidate; physical receiver and supply costs unresolved**. This is an alternative baseline following the wide-input failure of the analog gate-programmed weight cell in [COMPACT_WEIGHT_CELLS.md](COMPACT_WEIGHT_CELLS.md). It is not a novel multiplier claim or a demonstrated improvement over Mythic.

## 1. Question and falsifiable objective

Can an unsigned four-bit weight use enabled multiplicity of identical MOS devices, with one source-current input per row, to remove both a per-row logarithmic voltage converter and a large per-cell analog storage capacitor? The screen requires less than 1% maximum and 0.3% RMS uncorrected relative product error over all 511 nonzero nine-bit input codes, seven nonzero weights, and prescribed unequal column voltages. This is a deliberately strict deterministic gate, not a replacement for the system's noise or inference-accuracy requirements.

Free variables are read-device length and current density. Fixed constraints are Sky130 1.8V NFETs, W=0.42µm identical physical units, grounded bodies, four digital weight bits, source-current excitation, nominal column voltage 0.9V, and real drain-enable devices. Columns contain weights [0,1,2,3,5,8,12,15]. Each contains all 15 physical read devices and all 15 selectors even when few are enabled. Read lengths are 0.15, 0.5, 1 and 2µm; selector length is 0.15µm. Unit full-scale currents are 1, 10 and 100nA. A one-dimensional, single-unit gate-bias calibration at source voltage 0.2V precedes each sweep and is frozen. It does not fit any weight/input products.

The externally supplied row current is

\[
I_{row,i}=I_u x_i\sum_j w_{ij}.
\]

The static sum of weights therefore belongs in a row-current reference/DAC or compiler normalization mechanism. It has a real implementation cost. A signed extension requires the sum of absolute weights and physical sign steering. An all-zero row needs separate handling; only a zero-weight column within a nonzero row is tested here.

## 2. Device identity that survives nonlinear operation

If every enabled unit has the same terminal voltages, geometry and physical selector, let its arbitrary current law be \(f(V_s,V_g,V_d,V_b,T)\). There is no need to approximate this law by an exponential:

\[
I_j=w_j f(V_s),\qquad I_{row}=\sum_j w_j f(V_s),\qquad
I_j=\frac{w_j}{\sum_k w_k} I_{row}=I_u w_jx.
\]

Thus common body effect, common bias drift and a transition between inversion regions need not break the ratio. This is the key control against the earlier gate-programmed weights, whose different gate biases produced different source slopes. It does not remove mismatch between units or unequal drain voltages.

Each physical unit is a read NFET followed by its own drain-enable NFET. One selector shared by a 1/2/4/8 bank would have a count-dependent internal drain drop. Replicating the complete two-transistor unit avoids that deterministic error. The four ideal enable voltages represent SRAM outputs; SRAM devices, row-current generation, bias generation and receivers are not simulated.

For equal per-unit output sensitivity \(\lambda=g_{ds}/I_D\), linearization with a fixed total row current gives

\[
\frac{\delta I_j}{I_j}\simeq
\lambda\left(\delta V_{d,j}-\sum_k p_k\delta V_{d,k}\right),\qquad
p_k=\frac{w_k}{\sum_jw_j}.
\]

Common drain motion is largely rejected; different column motion is not. A weight-one victim at +ΔV with the other active columns at −ΔV experiences approximately \(2\lambda\Delta V(1-1/46)\). A ±50mV allowance and 1% relative error require roughly \(\lambda<0.102\,\mathrm{V}^{-1}\), before leakage and mismatch. Actual BSIM values, rather than a length heuristic, must establish whether this is feasible.

## 3. Simulation boundary and reproducibility

Generator: [tb_imc_unit_current_divider.py](../../../../../analog/testbenches/tb_imc_unit_current_divider.py). Every configuration saves its generator, shared-helper snapshot, frozen calibration, exact generated-deck hash, data hash and complete 511-code responses under `build/research/imc_unit_current_divider/`. The first development command is:

```sh
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --lengths .15 --units-na 10 --out build/research/imc_unit_current_divider/development_tt_L015_I10
```

Output directories must be new. The command intentionally exits with an assertion failure if every candidate fails the full set of drain cases; failed evidence remains saved. The tools are the existing Nix Python environment and pinned ngspice43, with installed Sky130A models. These are fresh simulations, not cached table reads.

The prescribed drain cases are equal voltage, alternating ±5mV, a weight-one victim at either polarity against opposite-polarity peers, and the same three unequal cases at ±50mV. Product accuracy uses actual terminal currents before any output correction. Full-scale normalization is a separate diagnostic, not the pass criterion. The zero-weight current and total drain-current versus forced row-current difference are retained. The latter can contain real substrate leakage and is not by itself an exact KCL residual.

Junction geometry follows the installed Sky130 xschem one-finger template: AD=AS=W×0.29µm and PD=PS=2(W+0.29µm). This is explicit schematic geometry, not extraction. NRD=NRS are set to zero because the preceding study demonstrated numerical current-extraction corruption from vanishingly small internal series resistors at picoampere currents. Junctions remain present. At RSH=1Ω/square, W=0.42µm and 100nA/unit, the omitted nominal resistance drop is about 69nV per diffusion. That estimate supports this limited idealization; it does not excuse junction or layout omission elsewhere.

### First completed result

TT27, L=0.15µm, Iu=10nA, 511 input codes per drain pattern:

| Column-drain case | Maximum relative product error | RMS relative product error | Gate |
|---|---:|---:|---|
| Equal 0.9V | 0.07547% | 0.00255% | PASS |
| Alternating ±5mV | 0.94910% | 0.61043% | FAIL |
| Weight-one +5mV victim | 1.72196% | 0.45996% | FAIL |
| Weight-one −5mV victim | 1.54637% | 0.45405% | FAIL |
| Alternating ±50mV | 9.63040% | 6.04210% | FAIL |
| Weight-one +50mV victim | 17.72270% | 4.83311% | FAIL |
| Weight-one −50mV victim | 15.10033% | 4.32343% | FAIL |

The frozen gate bias is 0.74584889V. Along the equal-drain sweep, gm/ID ranges from 26.71 to 28.95/V, gds/ID from 1.163 to 1.670/V, and source voltage from 0.2 to 0.37909V. These values explain the measured drain sensitivity. The largest zero-column current is only 0.000502 times the smallest intended nonzero product, but junction-related current offsets are not zero. This result **verifies the nominal matched-unit DC control**, and **fails the minimum-length implementation under unequal drains**.

## 4. Costs and remaining attacks

For each unsigned four-bit weight the present circuit uses 15 read NFETs, 15 enable NFETs, and at least 24 transistors for four conventional six-transistor SRAM bits. The latter are only counted, not implemented. Assuming all SRAM transistors could use 0.42/0.15µm, the sum of gate areas is a lower bound:

\[
A_{gate}=15(0.42)(L+0.15)+24(0.42)(0.15)\;\mu\mathrm m^2.
\]

It is 3.402, 5.607, 8.757 and 15.057µm² at the four read lengths. Actual cells need contacts, wells, diffusion, supply rails and routing. Summing isolated rectangular diffusion areas is not a rigorous layout lower bound because diffusion can be shared. A comparison with a 15Cu weighted-capacitor cell must use the actual capacitor implementation and all peripheral overhead; no transistor gate-area number establishes an area win.

The source node has the capacitance of every read device, including disabled weights. The local settling time is approximately

\[
\tau_s\simeq\frac{C_s}{\sum_{enabled}(g_m+g_{mb}+g_{ds})}.
\]

At small input current it can grow sharply. For an ideal exponential unit current and fixed total capacitance, the total conductive current after a row-current step obeys

\[
I(t)=\frac{I_t}{1-(1-I_t/I_0)e^{-\eta I_t t/C_s}},
\]

where \(\eta=-\partial\ln I/\partial V_s\). At zero target current the decay becomes \(I(t)=I_0/[1+\eta I_0t/C_s]\). These are analytical warnings, not measured timing results. A current source alone does not instantaneously position the capacitive row node. Floating disabled internal-drain nodes also require transient history tests.

An ideal noiseless row-current constraint anticorrelates independent branch current noise. Under the restrictive equal-excess-factor white-noise model, the output covariance is

\[
S_{out}=2qF\left[\operatorname{diag}(I)-\frac{II^T}{I_\Sigma}\right]+pp^T S_{row}.
\]

If the physical row source has \(S_{row}=2qF I_\Sigma\), the diagonal independent-current result is restored. Source feedback therefore cannot be treated as a free noise cancellation mechanism. The preceding single-transistor study found conditional Sky130 white current noise around twice 2qI in relevant regimes; this read-plus-selector circuit needs its own noise analysis. Column summation with signed cancellation, flicker noise, current DAC noise and receiver noise remain unpaid.

Local unit mismatch is also unpaid. A first-order threshold-mismatch contribution is \(\sigma_I/I\simeq(g_m/I)A_{VT}/\sqrt{WL}\), with an actual process-specific mismatch model required. The weight-one branch has no averaging benefit. A common source removes a weighted mean error but cannot make independent cell errors vanish. Common gate bias and all column voltages remain ideal clamps in this DC screen.

## 5. Prior art and novelty boundary

This branch deliberately tests a strong conventional current-divider baseline. Its operating identity is established prior art:

- Sanz et al., *Microelectronics Reliability* 47 (2007), pp.471–476, DOI [10.1016/j.microrel.2006.05.008](https://diec.unizar.es/intranet/articulos/uploads/mr_07_sanz.pdf.pdf), §2 and appendix: parallel programmable MOS banks implement current division whose linearity does not require linear transistor conductance. The indexed author-hosted PDF was readable through search; direct full download timed out. No new measurements are attributed to our circuit from this paper.
- IBM's [US20210342121A1](https://patents.google.com/patent/US20210342121A1/en), filed 2020-04-30, Figs.2A/B and 6: shared current sources feed weighted switching/current-splitting structures for analog-input × digital-weight MAC, including binary or unary weighting. Its reduced-current-source and compact-switch motivations closely overlap this branch. A specific schematic may differ without creating a new broad principle.
- Yang et al., [*Micromachines* 14(7), 1482 (2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10383279/), §2 Figs.3–5: digitally selectable current-mirror multiplicities implement current multiplication and division; cascodes address accuracy. Measured 55nm results report eight-bit operation, 1µs delay and less than 6.15µW at 1.2V. This is a standalone multiplier/divider, not a whole IMC-chip efficiency baseline.
- [EP4002094A1](https://patents.google.com/patent/EP4002094A1/en), Figs.1–2, discloses current-divider/resistor-ladder computing elements with memory-controlled summation/subtraction routing. It reinforces that current division plus stored sign and weight is not a new IMC architecture by itself.

Potential useful discoveries are narrower: identifying the device region and clamp tolerance where this actual PDK yields a competitive area/accuracy tradeoff, or a verified interface that avoids costly drain regulation without sacrificing integrated charge accuracy. Neither has yet been established. A real receiver, row DAC, mismatch/noise results and extracted area are prerequisites for a system-level Pareto claim.

## 6. Completed length/current sweep and selector reuse

All twelve TT27 direct-enable configurations completed, each with seven drain patterns and 511 codes. No direct-enable configuration passes the full ±50mV specification. The following table reports the worst maximum and worst RMS across all seven patterns; the two maxima may occur in different patterns.

| Read L (µm) | Iu (nA) | Worst maximum | Worst RMS | Conclusion |
|---:|---:|---:|---:|---|
| 0.15 | 1 | 19.3357% | 6.4275% | FAIL |
| 0.15 | 10 | 17.7227% | 6.0421% | FAIL |
| 0.15 | 100 | 16.8599% | 5.5197% | FAIL |
| 0.5 | 1 | 3.5044% | 1.2080% | FAIL |
| 0.5 | 10 | 2.8220% | 1.1729% | FAIL |
| 0.5 | 100 | 2.7564% | 1.0728% | FAIL |
| 1 | 1 | 3.5208% | 1.2554% | FAIL |
| 1 | 10 | 2.8504% | 1.2267% | FAIL |
| 1 | 100 | 2.8061% | 1.0497% | FAIL |
| 2 | 1 | 5.5347% | 2.1486% | FAIL |
| 2 | 10 | 4.8725% | 2.0650% | FAIL |
| 2 | 100 | 4.8484% | 1.6410% | FAIL |

The 0.5µm/10nA version does pass all ±5mV cases, with worst maximum 0.3466% and RMS 0.1176%. Read-device length is not a monotonic remedy in this PDK and bias range.

A compatible mechanism reuses the existing drain-enable device as a cascode: select its gate between 0 and 0.95V, rather than 0 and 1.8V. This adds no read-path transistor, but requires an analog bias selection interface. At TT27, Lread=0.5µm, W=0.42µm, Lselector=0.15µm and Iu=10nA, all prescribed DC cases pass:

| Drain case | Maximum | RMS |
|---|---:|---:|
| Equal | 0.07547% | 0.00255% |
| Alternating ±5mV | 0.08967% | 0.01159% |
| +5mV victim | 0.10912% | 0.00921% |
| −5mV victim | 0.05141% | 0.00839% |
| Alternating ±50mV | 0.21780% | 0.11296% |
| +50mV victim | 0.41317% | 0.08501% |
| −50mV victim | 0.28187% | 0.08398% |

The frozen read gate is 0.728090946V. Source voltage ranges from 0.2 to 0.402369V; read VDS ranges from 0.142464 to 0.166452V. Read gm/ID is 23.47–26.47/V, and its individual gds/ID is 0.500–0.608/V. That individual gds/ID is **not** the terminal sensitivity of the cascoded pair: feedback through the selector is responsible for the improvement. The worst ±50mV victim error corresponds to an approximately 0.042/V effective sensitivity when interpreted by the first-order expression, with leakage included. This is an inferred finite-difference diagnostic, not a directly extracted small-signal parameter.

The gate-area floor of 5.607µm² per unsigned four-bit cell excludes the bias mux. One possible interface adds two NFETs per bit to select 0 or 0.95V using complementary SRAM outputs: eight more devices and at least 0.504µm² additional gate area at 0.42/0.15µm. Its analog transfer, switching and corner behavior are unverified. A transmission-gate implementation costs more; a 0.95V SRAM domain has different verification and supply costs. Thus the present cascode cell is at least 54 read/enable/SRAM devices before bias selection, or 62 under that illustrative two-NFET mux implementation. Cascode and digitally programmed current-divider principles are known; this is a SPICE sizing result.

### Corner falsification

The same physical sizes and selector bias were tested at SS85 and FF−40, each with an independent one-dimensional read-gate bias calibration. These are not fixed-TT-bias corner results. FF−40 passes all seven drain cases, with worst maximum 0.38560% and RMS 0.13909%. SS85 fails even at equal drains: 34.15512% maximum, 1.15266% RMS. The weight-one errors at input codes 1, 2, 4, 8, 16 and 32 are approximately 34.155%, 17.077%, 8.539%, 4.269%, 2.135% and 1.067%, showing a nearly constant output-current offset. Its full-scale weight-one error is 0.06674%, and the zero-weight column carries about 4.39pA.

Explicit junction leakage is therefore material. Static offset cancellation might recover deterministic low-code accuracy, but was not applied to these pass/fail results and would not remove leakage noise. The zero-column current alone is not the entire offset: source-junction leakage changes the current that the active units must supply. **The present raw-current architecture fails the hot-corner gate.**

## 7. Physical history and numerical controls

The transient keeps ideal 0.9V column receivers and applies actual row-current steps to all 120 read devices and 120 selectors. Each constant-current plateau lasts 20µs. Initial state is a DC operating point, not a startup demonstration. Frames include full→1/511, return to full, zero, return to full, 1/64, full and 1/8. The first scoring version inadvertently included the beginning of the following 1ns PWL edge; its frame metrics are invalid and retained only as debugging evidence. Corrected metrics end before the next ramp.

Trapezoidal integration produced a small nonphysical alternating terminal-current component at the settled full-current plateau. Gear-2 controls at 5ns and 2.5ns maximum timestep remove it. The supported values below use 2.5ns; the 5ns control differs by at most 3.5ns in the listed finite settling measurements.

| Transition at Iu=10nA | Time to <1% error | Time to <0.3% error | End-of-20µs maximum error |
|---|---:|---:|---:|
| Full→1/511 | >20µs | >20µs | 1.45865% |
| 1/511→full | 0.15597µs | 0.17597µs | 0.0001485% |
| Zero→full | 0.16954µs | 0.19204µs | 0.0001485% |
| Full→1/64 | 3.11670µs | 3.88920µs | 0.0094522% |
| 1/64→full | 0.13163µs | 0.15413µs | 0.0001485% |
| Full→1/8 | 0.46237µs | 0.57987µs | 0.0011819% |

The sparse endpoint error changes by 0.000749 percentage points between Gear timesteps, supporting the slow-settling conclusion. At the zero-current frame the weight-one column still supplies about 4.78pA at 20µs. Zero is not an independently passed accuracy state. Finite current-source compliance, source-current noise, wire capacitance and a physical receiver remain absent, so these measured settling times are not system latencies. **The unassisted amplitude-coded row fails a fast arbitrary-input schedule.**

## 8. Conditional transistor noise

The noise fixture measures the weight-one column current with a noiseless current-controlled source and a behavioral 1S load. The complete row has an ideal noiseless forced current and stiff gate, drain and bias voltages. It therefore includes intrinsic source feedback and conditional noise correlations, while omitting a real row DAC, bias network and receiver.

Noise analysis exposed a simulator limitation: Sky130's TNOIMOD=1 introduces source/drain noise nodes even when NRD=NRS=0, then ngspice substitutes 1mΩ branches and fails. Restoring the physical approximately 0.69Ω diffusion resistance completed noise but corrupted the low-current operating point; that result was rejected. Two numerical regularizations, 100Ω and 1000Ω per diffusion, give valid operating currents and closely agreeing lower-frequency PSDs. They are not extracted physical resistance values. At full input the maximum source degeneration gm·1000Ω is around 0.000235, while added high-frequency resistor/capacitor noise is visible and must not be ignored.

The table reports one-sided output-current PSD divided by 2qI using the 100Ω control:

| Input x | 100kHz | 1MHz | 10MHz | 100MHz |
|---:|---:|---:|---:|---:|
| 1/511 | 0.9306 | 1.1076 | 1.1154 | 1.2888 |
| 1/8 | 1.7102 | 1.5497 | 2.0259 | 2.4590 |
| 1 | 2.9604 | 1.5892 | 1.4247 | 2.0071 |

The 100→1000Ω PSD change is below 0.054% through 1MHz at these three inputs. At full input it remains about 0.050% at 10MHz and 0.108% at 100MHz. At 1/511 input it rises to 1.24% at 10MHz and 107% at 100MHz: that sparse high-frequency result is **not converged** and cannot support an integrated noise number. Full-input low-frequency flicker is substantial: the ratio is about 78.1 at 1kHz. No transient-noise, sampled-noise, mismatch or full-band aperture claim follows from this table.

## 9. Fixed-current, time-coded cross-pollination

The sparse settling problem motivates keeping the row current fixed and steering each unit between a data column and a matched-voltage dump. Turning the row current off would lose the fixed operating point and repeat the original problem. A read device with matched data/dump cascode selectors uses three transistors per unit, hence 45 read-path transistors plus 24 conventional SRAM transistors per unsigned four-bit cell before bias selection and clock/weight logic. The dump regulator and dumped current are real costs.

For exact nine-bit duration coding the pulse quantum is T/511: 97.8ps, 195.7ps and 626.2ps at T=50ns, 100ns and 320ns. For eight-bit coding these become 196ps, 392ps and 1.255ns. One-percent relative accuracy at the smallest nine-bit pulse would require approximately 2ps timing accuracy at T=100ns, an extremely different requirement from 0.3% full-scale charge accuracy. Both metrics must remain visible rather than silently changing the accuracy objective.

As a conditional analytical comparison, assume independent random signs, uniformly distributed weight magnitudes 1…15, x uniform on [0,1], and white current noise SI=2qFI. With duty-coded integration, signal variance is proportional to E[w²]E[x²] while noise is proportional to E[w]E[x]. A 43dB ensemble SNR then requires

\[
I_uT=10^{43/10}qF\frac{8(1/2)}{(248/3)(1/3)}.
\]

At F=2 this is 9.2809×10⁻¹⁶C, or T=92.81ns for Iu=10nA. Always-biased current costs approximately 1.8V×Iu×8×T=13.36fJ per multiplication, including the portion routed to the dump but excluding all other blocks. This is not a measured energy/SNR result, and flicker, correlations and switching can change it.

The signed-magnitude assumption is also not equivalent to four-bit two's-complement hardware. A fixed negative MSB bus can implement signed weights without a programmable sign mux, but code −1 then enables all 15 units and its noise/power follow that physical count. A sign-steered magnitude implementation adds routing devices. High/low slices for eight-bit weights, row normalization and receiver conversion still need explicit accounting before comparison with a charge-domain macro.

### Physical PWM result and its limits

The new `--followup pwm` fixture contains 360 real MOS devices: 120 read devices, 120 data selectors and 120 dump selectors. It keeps Irow constant, uses complementary 0/0.95V clocks with 50ps edges, and integrates **actual terminal current**, including switching displacement current, over each pulse plus its guard. Weight-enable logic, clock drivers, bias generation, row-current generation and column/dump regulation remain ideal. Explicit junctions are present; successful transients retain NRD=NRS=0.

At 1e−18A absolute current tolerance, the transient aborted before its first edge despite a valid DC operating point. A finite 100Ω port resistance, guessed initialized-state control, and restored 0.69Ω or 100Ω diffusion-series controls did not rescue that strict run. The same physical zero-series-resistance deck completes at 1e−15A and 1e−16A tolerances. Restoring physical diffusion resistance still aborted at the relaxed tolerance and is **unverified**, not treated as a physical failure of the steering principle.

Timestep controls of 100ps and 20ps, and current tolerance controls of 1e−15A and 1e−16A, change the integrated charge by at most 0.00375% of per-weight full scale. This supports the following coarse absolute-error conclusion; it does not establish exact sub-LSB pulse timing or explain every percent of the smallest pulse's relative error.

| Condition | Pulse full scale | Total non-pulse frame budget | Worst relative charge error | Worst per-weight full-scale charge error |
|---|---:|---:|---:|---:|
| TT27, 100ps step, 1e−15A | 100ns | 50ns | 22.6647% | 0.044354% |
| TT27, 20ps step, 1e−16A | 100ns | 50ns | 22.9030% | 0.044820% |
| TT27, 20ps step, 1e−16A | 100ns | 12ns | 22.9042% | 0.044822% |
| SS85, 20ps step, 1e−16A | 100ns | 50ns | 20.5712% | 0.096562% |

The fixed pulse set is [0,1/511,2/511,4/511,1/64,1/8,1/2,1,1/511,1]; it is not an all-511-code transient validation. No pulse-width calibration or output gain fitting was applied. Zero-pulse subtraction is separately recorded and does not resolve the short-pulse relative error. TT source motion stays approximately within 10µV of 0.2V, showing that the data/dump arrangement avoids the large source excursion responsible for the amplitude-coded settling failure. The option named `--pwm-guard-ns` specifies the total non-pulse budget: the maximum pulse begins 5ns into the frame and leaves 45ns or 7ns afterward for settings 50ns or 12ns. The latter gives a **112ns fixture initiation interval**, with a 100ns warmup excluded. This is not an implemented MAC/ADC pipeline latency.

**FAILED:** the original <1% maximum/<0.3% RMS relative-product gate. **STRONGLY SUPPORTED within the stated schematic fixture:** less than 0.05% TT and 0.1% SS full-scale deterministic charge error on the fixed pulse set. A low-code error and a full-scale error answer different engineering questions; neither is suppressed in favor of the other.

The TT 150ns-frame energy control checks that combined data/dump charge differs from Irow×frame by at most 0.000551%. At the tested mean enabled-unit count 46/8=5.75, the 0.9V data/dump ports deliver about 7.7625fJ per column-cell per frame. The two clock ports each deliver about 0.8984fJ positive energy per active pulse per cell, while their **net** energy is close to zero because the ideal ramp sources recover capacitive energy. A physical CMOS clock driver cannot be charged only that near-zero net value. The measured positive gate-bias energy is about 0.0051fJ/cell; its generator remains absent. These quantities exclude the receiver, SRAM, weight-enable muxes, bias/current references, pulse generator, wire drivers and ADC.

A separate assumed 1.8V current-path supply estimate is 15.525fJ/cell for this particular row and 150ns frame, or 21.6fJ at mean weight magnitude eight. This is an alternative estimate for the same delivered current path, **not an independent energy term to add to the measured 0.9V data/dump delivery**. At 112ns it would be 16.128fJ for that mean magnitude. Thus the earlier 13.36fJ analytical value cannot be reused after adding a guard without charging its time. Current storage stays biased while the result goes to the dump.

The clock-to-weight interface also adds area: an illustrative two-NFET mux selecting either a shared clock or ground for each data/dump gate bank would require sixteen more devices per four-bit cell. Together with 45 read-path devices and 24 SRAM devices this is **85 transistors before common clock/bias drivers**, and at least 7.56µm² summed gate area at the assumed minimum mux/SRAM dimensions. Actual pass-high behavior, layout and alternative transmission-gate costs have not been verified.

### Receiver alternatives must be compared explicitly

For 256 rows, all unsigned weights 15, Iu=10nA and T=100ns, one data column collects 3.84pC. A passive integrating drain kept inside the tested 0.85–0.95V interval needs at least 38.4pF; allowing only 50mV total droop needs 76.8pF. Nominal 2fF/µm² MIM density makes the first value approximately 19,200µm² per column before routing; the nominal device density is documented in the [SkyWater device details](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html). This is a bound on that passive receiver choice, **not representative of every receiver architecture**.

A regulated integrating receiver may avoid the large passive capacitor. For scale only, a simple gm-controlled clamp handling 38.4µA with 50mV error would need about 0.768mS; at gm/ID=20/V its bias would be roughly 38µA. At 1.8V over 100ns that is approximately 27fJ per multiplication for 256 rows. This is a rough topology-specific estimate, not a fundamental power bound or an optimized receiver. Its stability, input noise, charge integration, output headroom and sampling need an actual circuit test.

## 10. Next cross-pollination: stored analog weight at fixed bias

The original analog gate-programmed weight failed because different weights had different current-versus-source-voltage slopes. Time-coded steering at a fixed source operating point avoids that particular mechanism. A programmed analog current could replace fifteen nominally matched units, using a read device, two data/dump selectors and a write device plus stored gate capacitance (roughly 4T1C with one write FET, or 5T1C with a write transmission gate). Current-weight × pulse-duration multiplication is conventional prior art; this proposal is an integration hypothesis, not a new arithmetic principle.

At 27°C, 20fF has approximately 455µV RMS kT/C voltage uncertainty. With gm/ID≈23.5/V, this means about 1.07% RMS current uncertainty after an unverified fresh write. Reducing that term alone to 0.3% requires approximately 254fF, about 127µm² nominal MIM area. A program/verify operation can measure static held-charge error after the switch opens, but it needs precision and time. For a conditional F=2 white-current-noise estimate at 10nA, a 0.3% RMS current estimate requires about 3.56µs and 0.1% about 32µs, before flicker or receiver noise.

As an indicative leakage scale only, the SS zero-column current divided by fifteen devices is approximately 0.293pA per selector drain junction. If the eventual write path leaked that current into 20fF, its voltage would move by 14.7µV/µs, or about 0.034% current/µs at η=23.5/V: roughly 8.7µs to 0.3% drift. This is not a storage simulation; the actual write-switch/channel/gate leakage may differ. It shows why program/verify and refresh may occupy comparable times. Fixed-source operation could reduce the earlier source-feedthrough error, but selector/drain feedthrough, sampling noise, retention, signed routing and a real integrating receiver still require independent tests.

## 11. Analytical speed tradeoff: segmented PWM and a radix-16 holder

Increasing Iu from 10 to 100nA while reducing T from 100 to 10ns preserves IuT and the preceding ideal white-noise/current-path energy estimate. It does not preserve transistor operating region at fixed W/L, receiver bandwidth, edge error or clock energy. Scaling W tenfold to retain current density would instead multiply cell gate area and much of its clock load. Neither implementation has been validated here at 100nA.

A full nine-bit 10ns pulse needs 19.57ps resolution. Four-bit digits need 10ns/15=666.7ps resolution, but A8 now uses two passes. Let a=d0+16d1, with both digits in 0…15, and integrate each pulse into an actual receiver capacitor Carr:

\[
Q_k=I_uwT\frac{d_k}{15},\qquad v_k=\frac{Q_k}{C_{arr}}.
\]

If Carr can be disconnected from the receiver and joined directly to a holder Cacc=Carr/15 after each digit, charge conservation gives

\[
V_h' =\frac{V_h+15v_k}{16},\qquad
V_{final}=\frac{15}{256}(v_0+16v_1).
\]

Low digit first therefore gives the correct A8 weighting with one fixed column gain. The equivalent input-normalized charge is \(Q_{eq}=(Q_0+16Q_1)/17=I_uwT(a/255)\). This recurrence is an ordinary switched-capacitor radix mechanism, not a novelty claim. Merely choosing different capacitors to store identical charge and joining them would not weight that charge; the complete repeated acquisition/reset/share operation matters.

The physical charge on Cacc after the two joins is only \((Q_0+16Q_1)/256\). Qeq is an input-normalized equivalent after fixed gain correction, not charge physically retained. The independent critic verified this distinction, all 256 exact digit identities, the noise moments and the capacitor-ratio sensitivity below. The smaller holder's own sampling noise must be referred through the actual signal gain.

The implementation must pay for disconnecting an integrating feedback capacitor, preserving the holder, resetting Carr, reconnecting a stable receiver, and matching the effective 15:1 ratio including parasitics. A continuous-feedback receiver that cannot surrender Carr needs another physical transfer mechanism. A9 needs a third digit or a separately normalized binary top-bit pass; an A8 derivation does not establish its timing or gain automatically.

For uniform independent A8 digits, independently integrated white current noise, equal F, and ideal noiseless recombination,

\[
E[\operatorname{var}Q_{eq}|w]
=qFI_uwT\frac{257}{578}.
\]

This is 257/289=0.88927 times the mean white-noise variance of a single unsegmented pulse with the same IuT. With random independent signs and weight magnitudes 1…15, the exact discrete A8 second moment is E[x²]=511/1530. At F=2 and IuT=10⁻¹⁵C the conditional ensemble SNR is **43.842dB**. This is analytical only: correlated flicker across digits, source-current noise, receiver noise, capacitor reset/share noise and pulse-edge errors are absent. It is not a sampled SPICE SNR result.

The two always-biased 10ns passes cost **28.8fJ per multiplication** at 1.8V and mean weight magnitude eight, before any guard, receiver, clock, weight storage or ADC. Every extra nanosecond of total always-biased schedule adds 1.44fJ/multiply under those assumptions. The ideal minimum per-digit aperture for 43dB in this model is 8.237ns; shortening it still pays two passes. Thus segmentation trades time resolution and potential latency against approximately doubled current-path energy, rather than providing tenfold speed at unchanged total energy.

Peak column current rises to 384µA for 256 rows at weight fifteen, while maximum digit charge remains 3.84pC. An integrating feedback capacitor allowing 0.2V output excursion needs at least 19.2pF, with a 1.28pF radix holder. A 1V excursion would reduce these to 3.84pF and 256fF, but requires a receiver with that verified output range. These output limits differ from the passive input-drain limit: a regulated receiver may hold the drains near 0.9V while its output moves farther. The earlier simple clamp estimate would require tenfold gm and current over one-tenth the aperture, retaining roughly its energy per pass but demanding substantially higher bandwidth.

With a relative Carr/Cacc ratio error ε, the retention is r=1/(16+15ε). After a zero/full-scale gain correction, the reconstructed normalized input is (r d0+d1)/[15(1+r)]. Its first-order worst full-scale error is (15/289)|ε|: a 1% ratio error produces about 0.0519% full-scale error. This gain correction does not remove relative low-digit error or input-dependent parasitics. At T=10ns, a high-digit pulse-width error produces about (16/17)δt/T full-scale error; a 0.3% allocation alone allows approximately 31.9ps. This is an allocation example, not a demonstrated timing generator.

**SPECULATIVE physical candidate; VERIFIED charge-conservation algebra and numerical moment calculation.** The next bounded experiment should first establish actual 100nA read/selector headroom and gm/ID, then test sixteen digit pulses with a frozen bias. Only a surviving pulse cell warrants a real regulated integrator and radix-holder test.

## 12. Audit and exact reruns

An independent agent checked the frozen one-dimensional calibration boundary, current signs, transient frame boundaries, conditional noise probe and PWM energy signs. It found no product-fit leakage. The audit required two explicit limits: initial DC state does not verify startup, and drain/dump charge balance is a settled-cycle diagnostic rather than universal full KCL. Gate/body charge exchange and endpoint stored charge must be considered in any stricter conservation test. Estimated 1.8V current-path energy is not added to measured drain-port energy. Physical source generation, receiver, clock/bias drivers, signed weights, weight slices, random mismatch, sampled noise and extracted area remain unverified.

Representative reruns follow. Every output directory must be new; frozen maps are produced by the first command. The saved campaign results use the named directories above; these commands choose separate review directories to preserve them.

```sh
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --lengths .5 --units-na 10 --enable-v .95 --out build/research/imc_unit_current_divider/review_tt_cascode
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --frozen build/research/imc_unit_current_divider/review_tt_cascode/L0.5_I10.0_frozen.json --followup pwm --pwm-period-ns 100 --pwm-guard-ns 12 --pwm-abstol 1e-16 --step-ns .02 --out build/research/imc_unit_current_divider/review_tt_pwm
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --frozen build/research/imc_unit_current_divider/review_tt_cascode/L0.5_I10.0_frozen.json --followup transient --method gear --step-ns 2.5 --out build/research/imc_unit_current_divider/review_tt_history
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --frozen build/research/imc_unit_current_divider/review_tt_cascode/L0.5_I10.0_frozen.json --followup noise --noise-series-ohm 100 --out build/research/imc_unit_current_divider/review_tt_noise
```

The evidence manifest is `build/research/imc_unit_current_divider/evidence_manifest.json`. It fingerprints completed and failed artifacts, each run's source/helper snapshot, the current source/report and installed model files. A snapshot belongs to its own run; later diagnostic fields do not retroactively appear in older results.

## 13. Bounded 100nA physical followup

The analytical scaling hypothesis was then screened with the same physical unit dimensions. At Iu=100nA, selector bias 0.95V, TT27, read VDS falls to 66.54–92.49mV. Read gm/ID spans 21.24–26.15/V and gds/ID rises to 1.49–2.71/V. Equal drains and all ±5mV cases still pass, but ±50mV fails: worst maximum 1.2740%, worst RMS 0.3111%. Thus unchanged current density and headroom cannot be assumed when compressing the aperture.

A bounded headroom control raises the existing selector ON voltage to 1.05V. The read gate is independently calibrated once to 0.829975743V. No new read-path transistor is added, but the selector-bias generator and actual SRAM/clock selection interface remain unpaid. Read VDS is now 148.20–174.56mV, gm/ID 21.52–26.17/V and individual read gds/ID 0.489–0.580/V. All seven TT drain patterns over 511 input codes pass, with worst maximum **0.32744%** and worst RMS **0.11372%**. At SS85, an independent one-dimensional gate calibration still leaves amplitude-coded low-input leakage error: 3.4155% maximum at equal drains and 3.7098% worst over all patterns. This does not rescue the amplitude-coded architecture.

The new `--pwm-input-bits 4` mode tests all sixteen digit codes, followed by repeated code one and full scale. Each digit has T=10ns, a 666.7ps minimum nonzero pulse, 50ps clock edges and a 12ns non-pulse budget: 5ns before and 7ns after a maximum pulse. One digit occupies 22ns. The tested two-digit A8 schedule would therefore occupy **44ns before a real integrating/radix receiver or ADC adds time**. No physical two-digit accumulator is implemented.

| Selector bias and corner | Maximum timestep | Current tolerance | Worst relative error | Worst full-scale error |
|---|---:|---:|---:|---:|
| 0.95V, TT27 | 20ps | 1e−16A | 2.0806% | 0.138704% |
| 1.05V, TT27 | 20ps | 1e−16A | 1.6041% | 0.106941% |
| 1.05V, TT27 | 20ps | 1e−15A | 1.6041% | 0.106941% |
| 1.05V, TT27 | 5ps | 1e−15A | 1.6104% | 0.107357% |
| 1.05V, SS85 | 20ps | 1e−15A | 2.2232% | 0.148209% |

The 0.95V 5ps/1e−16A control aborted and is retained as a failed numerical run. For the 1.05V candidate, changing tolerance at 20ps changes integrated charge by at most 0.004506% of per-weight full scale; changing timestep from 20ps to 5ps at 1e−15A changes it by at most 0.005034%. These controls support the coarse full-scale bounds, not exact picosecond timing. Successful transients still use zero diffusion-series resistance with explicit junction area/perimeter. The original relative-error gate remains **FAILED**.

In the TT 5ps run, source voltage is within approximately −28.6/+39.7µV of nominal during switching, while its frame-boundary changes remain below 0.827µV. SS frame-boundary changes are below 2.045µV. This supports recovery of the shared source within the explicit budget; it does not prove that every unsaved internal node has returned to an identical state. Drain/dump versus source charge balance differs by up to 0.00694% in the TT control and remains a diagnostic with body/gate/endpoint charge exclusions.

At the tested mean enabled count 5.75, one 22ns digit frame has an alternative 1.8V current-path estimate of 22.77fJ per cell; two digits cost 45.54fJ. At mean magnitude eight, two digits cost **63.36fJ**, rather than the no-guard 28.8fJ estimate. The measured 0.9V drain/dump delivery is about 11.3844fJ per cell per digit, which overlaps that current path and is not added to it. Positive clock-port delivery is about 2.247fJ per cell per active digit at the tested weight count; clock generation, real driver loss and weight-gating loads remain absent. Receiver, signed routing, SRAM, weight slices and ADC costs still need separate implementation.

As an explicitly optimistic diagnostic, applying an ideal noiseless radix recombination to the sixteen measured digit responses gives approximately 0.02789% full-scale RMS error over all 256 A8 combinations and seven nonzero weights at TT, and 0.03746% at SS. This is postprocessing of a fixed-history digit transfer function, **not a 256-code physical two-pass validation**. It excludes holder noise, parasitic ratio errors and changed digit histories. The raw digit errors remain the physical evidence.

Conditional stationary noise at full 100nA input, with 100Ω numerical diffusion regularization, gives PSD/(2qI) of approximately 565.5 at 1kHz, 3.132 at 1MHz, 1.675 at 10MHz and 1.498 at 100MHz. The 100→1000Ω control changes full-input PSD by at most 0.493% through 100MHz and 1.261% through 1GHz. At sparse amplitude input the 1GHz discrepancy is 319%, so that high-frequency result is rejected. The PWM cell uses the full-current operating point, but a stationary spectrum is still not sampled switching noise. F=2 in §11 remains an analytical assumption; flicker correlation between digits, ideal row-source feedback and noise above the simulated band prevent a verified 43dB claim.

The exact algebra enumeration and frozen-result crosschecks are saved in `segmented_pwm_algebra.json` and `segmented_pwm_checks.json`. The first PWM round's earlier manifest/report are preserved as `evidence_manifest_pwm_round.json` and `pwm_round_report_snapshot.md`; the current manifest includes the additional runs. A representative fresh rerun is:

```sh
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --lengths .5 --units-na 100 --enable-v 1.05 --out build/research/imc_unit_current_divider/review_tt_I100
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_unit_current_divider.py --frozen build/research/imc_unit_current_divider/review_tt_I100/L0.5_I100.0_frozen.json --followup pwm --pwm-input-bits 4 --pwm-period-ns 10 --pwm-guard-ns 12 --pwm-abstol 1e-15 --step-ns .005 --out build/research/imc_unit_current_divider/review_tt_I100_pwm4
```

**STRONGLY SUPPORTED:** the stated deterministic digit charge bounds in a fixture with ideal external ports. **FAILED:** the original maximum/RMS relative-product gate. **SPECULATIVE:** a competitive signed A8 IMC tile using a physical regulated integrator, radix holder and pipelined ADC. No area or energy improvement over Mythic is established.


## 14. Fresh prior-art collision: May 2026

Yang et al., [A Reconfigurable Computing In-Memory Macro with Charge-sharing-based Weighted Accumulator](https://arxiv.org/html/2605.30814v1), §§III–V, explicitly combine reduced read-wordline bias as a cascode, identical-cell weight multiplicity, equal-capacitor binary accumulation, and one shared-ramp conversion. Thus selector-as-cascode and current-mode partial sums followed by charge-radix accumulation are established mechanisms. Their 65 nm, 256×127 MAC plus reference-column results are post-layout simulations, not measured silicon. At 7/4/7 input/weight/output precision they report 8.4 TOPS/W and 14 GOPS; the 1023.2 TOPS/W headline uses 1/2/1. The stated latency ratios assume the same ramp ADC in each comparator architecture. These results do not verify our source-fed normalization, steering history, or Sky130 implementation.

Two numerical claims require independent checking before using their noise/timing model. Section IV-B assigns 20 µV sampling noise to 50 fF; directly evaluating sqrt(kT/C) at 300 K instead gives 288 µV before topology covariance. Section III-D's 50 ps settling for a 62 MHz buffer is close to 4.8 mV divided by its reported 88 V/µs slew rate; a slew-time quotient alone does not establish linear settling. These caveats do not remove the architecture's prior-art relevance.

This dated literature append follows the frozen physical-result manifest; the archived report hash in that manifest describes the earlier report snapshot.
