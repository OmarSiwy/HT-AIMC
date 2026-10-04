# AnalogIOC circuit research: opportunities that survive physical accounting

Date: 2026-09-07. Scope: the local Analog Compute notes and AnalogIOC manuscript, checked against the present circuit generators, testbenches, later accuracy studies, and primary literature. This report is an evidence audit. A fresh companion [charge-averaging experiment](IMC_CHARGE_AVERAGE_EXPERIMENT.md) tests one promising direction. No operational circuit, RTL, compiler implementation, or external research note was changed.

The strongest direction is a **resident, programmable charge-domain weight engine with a physical capacitor implementation, selective precision, and fewer conversions per actual mathematical reduction**. The current evidence does not establish a chip that beats Mythic or Sohu. Several attractive speedups are artifacts of changing the mathematical output, relaxing precision, or dropping conversion counts. Fixing those distinctions reveals useful experiments rather than removing the case for analog computing.

## 1. Evidence hierarchy and the present hardware

Read first: [AGENTS.md](../../../../AGENTS.md) and [CONTRACT.md](CONTRACT.md). Research source: [Analog Compute directory](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/>), especially notes 27g1–g4, 27h1–h10, 27i1–i7, 27l3, and the manuscript's `sec_arch.tex`, `sec_circuits.tex`, `sec_laws.tex`, and `sec_eval.tex`.

Use the following labels when making decisions:

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| Circuit algebra | Charge conservation, required operations, scaling under stated assumptions | Device sizing, parasitics, yield or timing |
| Behavioral/Monte Carlo model | Behavior of the chosen statistical model | Foundry-qualified mismatch distributions |
| Transistor SPICE | Behavior under the supplied netlist, models, controls and corners | Fabricated silicon or unmodeled noise/layout |
| Post-layout extracted simulation | A particular physical implementation under supplied models | Silicon yield without measurements |
| Silicon measurement | Actual measured devices and conditions | A complete different-node LLM system |
| System projection | A conditional architecture forecast | A measured token rate or wall energy |

[OPTIMIZATION_RESULTS.md](OPTIMIZATION_RESULTS.md) repeatedly calls SPICE results “silicon-proven.” Those results are simulations. The local manuscript's own [REVIEW_DECISION.md](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/paper/REVIEW_DECISION.md>) already records serious mathematical and evidence-label problems; inspect current equations individually, since some were subsequently corrected. The manuscript is a local research proposal and cannot validate its own projections.

The present 16×16 weight engine uses capacitor-coded weights, repeated two-phase charge transfer, a biased telescopic OTA integrator, a post-window unary coarse converter, and a SAR residue converter. The code already includes substantial circuit fixes and bias gating. It is not the paper's few-fF integrator/10–20-fF fine-CDAC projection.

| Item | Current generator evidence | Implication |
|---|---|---|
| Unit weight capacitor | Approximately 0.15 fF, ideal SPICE `C` elements | Physical MOM implementation and matching remain decisive |
| Bank ballast | 4 fF per populated bank | About 27 unit-cap equivalents before the weight itself |
| Column ballast | 500 fF | Rail impulses and OTA feedback loading are material |
| Integrator | 200 fF class; OTA bias must be on during integration | Cell dynamic energy is an incomplete budget |
| Fine CDAC | 7.5-fF units, 120-fF total | [LAYOUT_REQUIREMENTS.md](LAYOUT_REQUIREMENTS.md) still says 30-fF units and is stale here |
| Local fine references | Two 5-pF reservoirs per converter | References dwarf the nominal CDAC and need physical area/energy accounting |
| Reference and control implementation | External ideal reference rails and XSPICE control models remain | A closed physical chip requires reference generation, distribution and real control timing |

Sources: [weight_tile.py](../../../../analog/schematics/components/weight_tile/weight_tile.py), [integrator_conv.py](../../../../analog/schematics/components/integrator_conv/integrator_conv.py), [rstring_ladder.py](../../../../analog/schematics/components/rstring_ladder/rstring_ladder.py), [analogioc_top.py](../../../../analog/schematics/top/analogioc_top.py), and [SIZING.md](../../../../analog/schematics/sizing/SIZING.md). These are code observations, not new measurements.

## 2. Two architectural errors to remove before choosing circuits

### Capacitive compute does not inherently consume its weight

The present weight is the **selected capacitance**, not the instantaneous stored charge. `weight_tile.generate()` chooses binary capacitor elements from `Cp` and `Cn`; a multiply moves charge through those same elements repeatedly. Neither charging nor discharging changes their nominal capacitance. Thus the assertion in [KV_FEASIBILITY.md](KV_FEASIBILITY.md) that the weight engine's consuming read forces HBM backing confuses coefficient storage with operand charge.

This does not mean the existing netlist is a complete programmable memory: weight selections are applied at **netlist-generation time**. A reusable accelerator needs SRAM/latches or another appropriate physical control store plus programming switches. A model-specific mask-programmed engine is a different capacity/flexibility choice. Resident weights still require enough physical cells, configuration bits, routing, and practical model-loading time.

There is direct silicon precedent for SRAM retaining the weight while capacitors do the arithmetic: [CAP-RAM](https://arxiv.org/abs/2107.02388) uses standard 6T storage and shared charge-domain MAC circuitry. Its 65-nm prototype also demonstrates a charge-injection SAR that removes separate sample-and-hold and input/reference buffers. Those are transferable circuit mechanisms; its CNN efficiency is not an LLM token benchmark.

**Action:** price resident SRAM-controlled capacitor codes against streamed weights using the same physical area and model capacity. Do not introduce a compulsory per-token weight rewrite on the grounds that a capacitor was discharged. This is the prerequisite for the user's compute-bound optimization course.

### A digital sum does not eliminate preceding ADCs

[tb_supertile.py](../../../../analog/testbenches/tb_supertile.py) calls `_cal_1col_window` once for every partial. Each call integrates and digitizes that partial. `parallel_output()` then sums those values. Its later “amortization” check merely compares two functions that use the same timing formula. The code therefore performs **K conversions for K digitized partials**, although the model credits one conversion per K windows.

The claimed gain independence also comes from an explicitly injected Python gain model. `series_output()` implements `(s + p) * (1 + eg)`; `parallel_output()` applies `(1 + eg)` once per partial. This checks the chosen recurrence. It does not show that held charge on one physical integrator is multiplied by this gain at every new charge injection.

[tb_cascade.py](../../../../analog/testbenches/tb_cascade.py) does demonstrate a different, narrower operation in SPICE: K windows on the **same W and same integration capacitor**, followed by one conversion of `sum_k(W @ x_k)` with scale `K * D`. Its input generator rejects windows until every running column sum stays below its headroom guard. Consequently:

- The reduced conversion count applies only when those partials belong to one required reduction. K independently required token outputs cannot be replaced by their sum.
- The test relaxes the output LSB by K. Its ±1-LSB tolerance is K times wider in original arithmetic units.
- The test does not implement K different layer transforms or demonstrate arbitrary distinct resident weight blocks feeding one accumulator.
- Accepted traffic is conditioned on headroom; worst-case input admission and fallback cost remain unmeasured.

**Action:** retain separate configurations for digital partial summation, shared-integrator accumulation, passive charge averaging, and actual analog transform cascades. Count every ADC call. A K-dependent speedup is valid only after the compiler identifies legal reductions and the physical dataflow can execute them.

## 3. Highest-value circuit experiments

| Priority | Candidate | Why it could improve tok/s and tok/J | What must be demonstrated |
|---|---|---|---|
| P0 | Physical capacitor cells plus calibrated weight mapping | Recover useful accuracy without buying precision uniformly everywhere | Extracted capacitance matrix, mismatch, full-model loss, total area |
| P1 | Passive charge averaging followed by one ADC | Remove real intermediate conversions without permanently biased summation stages | Correct gain/LSB, input-referred noise, switch injection and legal reductions |
| P1 | Joint choice of unary, binary-coarse and full SAR readout | Reduce decision/settling time and the static energy paid during it | Loaded, matched-accuracy latency/energy distribution across all columns |
| P2 | Binary or segmented activation encoding with charge-domain shift/add | Replace repeated unary PWM transfers with fewer weighted operations | Savings after extra conversion, capacitor and reference costs |
| P2 | Shared ratiometric capacitor/reference structure | Reduce duplicated capacitors and calibration drift | Real distribution loading, coupling and extracted layout |
| P2 | Precision and placement driven by model sensitivity | Protect a small sensitive subset while retaining a cheaper bulk path | Held-out full-depth model accuracy with measured error shapes |
| P3 | IGZO/BEOL gain-cell KV substrate | Longer retention and denser cache could reduce refresh and data traffic | Access to a real process and a complete array/readout demonstration |

These are experiments, not multiplicative gains already earned.

### 3.1 Make capacitor matching a first-class design variable

[tb_cap_mismatch.py](../../../../analog/testbenches/tb_cap_mismatch.py) explicitly states that nominal `tt` runs omit device mismatch and that weight capacitors are ideal elements. Its injected capacitor model, anchored against limited transistor simulations, estimates about **23.4 dB combined CSNR** for its Sky130-derived mismatch assumption. The approximately **25.0 dB mismatch-only result** shows why perfecting the existing converter is insufficient in that model. This is an extrapolated statistical model, not a fabricated-capacitor yield measurement.

The test uses `A_C≈2.8 %·µm` from the PDK and infers area from a nominal capacitor density. The 0.15-fF cell is below the standard drawable MiM device assumed by that area model; a custom MOM structure cannot automatically inherit MiM density, matching and minimum geometry. The [official Sky130 capacitor model](https://foss-eda-tools.googlesource.com/skywater-pdk/libs/sky130_fd_pr/+/refs/tags/v0.10.1/cells/cap_mim_m3/sky130_fd_pr__cap_mim_m3_1.model.spice) is a useful statistical anchor, not a substitute for an actual selected layout.

Build the smallest representative substrate2 weight bank and adjacent switches, extract the full capacitance matrix, and fit **effective weight error**, not just a named capacitor value. Include dummy/edge cells, gradients, clock coupling and switch mismatch. Scaling `C_u` without co-scaling swing and settling is not an isolated accuracy improvement.

Calibrated physical weight mapping is the most relevant unexplored compensation route. Characterize physical binary units, then choose programmable codes, spare units or a small residual path to minimize the resulting model error. A scalar per-column gain cannot remove a general `δW`; nor can a rank-1 LoRA sidecar represent an arbitrary mismatch matrix. Repeat-read averaging removes independent temporal noise, not the same fixed mismatch on every read. All mapping bits and residual MACs belong in the energy and capacity budget.

The later [DEPTH_BUDGET.md](../../../../scripts/compiler/metrics/DEPTH_BUDGET.md) indicates substantially higher full-depth sensitivity than the old 28-dB heuristic, but its approximately 36–43-dB region is a model- and error-shape-dependent study. Do not turn its 43.3-dB KL proxy into a universal physical acceptance threshold. Use exact frozen weight errors and converter residuals over held-out text, context lengths and decoding tasks before spending capacitor area to meet a single scalar target.

### 3.2 Reopen charge averaging with the correct success criterion

[chip_supertile.py](../../../../analog/schematics/top/chip_supertile.py) computes the correct passive divider:

`V_bus = sum(V_k) / (K + C_bus/C_int)`.

It then calls that “lossy” because the bus voltage is smaller than the **unscaled** sum. But a known constant gain is not itself information loss. Charge-domain arithmetic commonly computes a normalized sum. The cheap probe uses ideal initial conditions and ideal switches, so it does not test the actual reasons this architecture might fail: parasitic mismatch, sampled noise, charge injection, comparator noise, or reference tracking.

For independent partial signals of variance `s²`, the bus signal variance is `K*s²/(K+c)²`, with `c=C_bus/C_int`. ADC voltage noise of fixed variance therefore becomes more expensive as K increases. Meanwhile the larger total capacitance changes sampled thermal noise. These terms must be evaluated together; neither “division by K is fatal” nor “one conversion is free” follows from charge conservation.

**Experiment:** hold K real partials, connect through the actual TG layout, convert once, and apply the calibrated digital scale. Compare against K separately converted partials at equal final model accuracy and equal physical resources. Include independent and correlated signals, strong cancellation, zero input, gradients and worst-case all-same-sign activity. If the ADC must gain roughly half a bit per doubling of K to preserve relative accuracy, price that cost explicitly. A successful result is a legitimate conversion-count breakthrough; the existing probe has not ruled it out.

**Fresh bounded result:** the companion [experiment](IMC_CHARGE_AVERAGE_EXPERIMENT.md) now recovers a calibrated sum through transistor TGs at K=1/2/4/8. Slow/hot fast-settling failures are substantial, while a longer acquisition/sharing diagnostic restores the deterministic transfer. A one-cap mismatch control survives scalar calibration. Its separate noise calculation shows that one unchanged ADC does not preserve the accuracy of K independent ADCs; this candidate remains conditional, with no measured chip-level gain.

### 3.3 Shorten conversion time before adding more bias gating

The current design already parks column OTA bias after coarse completion. [GATING_VALUE.md](../../../../scripts/compiler/metrics/GATING_VALUE.md) finds only about **1.09×** further reachable projected tok/J at its N4 operating point, and identifies impossible duty factors in older projections. Lowering bias at fixed inversion often lengthens settling, so `I * t` need not improve. Full rail gating also risks injecting charge into the held residue.

The remaining local lever is the number and duration of useful decisions. [NULLSEEK.md](NULLSEEK.md) proposes replacing the capped coarse unary count with three binary decisions and retaining the four-bit fine SAR. Its approximately **1.62× projected rate gain** is a test candidate, not a measured result. The largest binary reference step may slew the OTA; binary-weighted packet mismatch creates INL that the unary loop avoids. Conversely, sparse columns can finish a unary loop faster than a fixed binary search.

Compare these three candidates using the same real output distribution: current early-terminating unary+fine; binary-coarse+fine; direct SAR with an acquisition interface designed around the compute array. Measure the **maximum completion time over the actual synchronization group**, not the average single-column count. The fine CDAC load, reservoir recovery and comparator clock slew are part of every trial. StrongARM speed at a 100-mV overdrive does not certify near-threshold decisions with sub-mV fine steps.

Shared reference generation is plausible prior art: [Mythic patent US10255205B1](https://patents.google.com/patent/US10255205B1/en) describes a global reference and local accumulators, including binary-weighted reference sequences. It is evidence for that circuit idea, not verification of the exact production M1076 readout or measured energy. Early binary-search decisions can have large residue; a final half-LSB residue bound must not be applied to every trial.

### 3.4 Replace unary work where conversions no longer dominate

[pwm_driver.py](../../../../analog/schematics/components/pwm_driver/pwm_driver.py) correctly explains why a flat pulse across a capacitor does not implement multiplication by duration: its two edges transfer opposite charges. AnalogIOC avoids that error by performing one switched-capacitor transfer per active timing quantum. PWM here is repeated physical work.

For `x = x_lo + 16*x_hi`, a duration-weighted scheme can require `x_lo + 16*x_hi` unit transfers. If two ordinary 0–15 windows are separately digitized and shifted digitally, the arithmetic requires at most 30 active unit transfers for two unsigned four-bit digits instead of 255. The trade is a second conversion and its noise. This is an encoding-level ceiling, not a 8.5× system-speed prediction; signed range, actual activation distribution, guards, settle time and array load change the useful number.

An eight-bit bit-serial path uses eight binary array evaluations but can require eight conversions. A charge-domain shift-and-add path can amortize those conversions, paying accurate capacitor ratios and additional switches instead. Test these alternatives jointly with converter design. Once unary input work is the bottleneck, reducing ADC energy alone does not recover throughput.

The most useful silicon reference is [PICO-RAM](https://arxiv.org/html/2407.12829v1): it reuses local capacitors for DAC, MAC, analog shift-and-add and readout, and reports 4b×4b operation with 0.59-LSB error spread. Its 65-nm measurements span 0.65–1.2 V and −40–105 °C. Efficiency peaks at 40.2 TOPS/W at the low-voltage point, while its frequency rises from 2 to 22 MHz across the voltage range. This demonstrates the circuit trade and the need for a Pareto curve; it does not promise those numbers for an INT8×INT4 transformer engine.

### 3.5 Assign accuracy where the model needs it

[CACTUS](https://arxiv.org/html/2507.09776v1) optimizes the ADC against ideal dot products rather than noisy analog inputs. It reports a three-bit reduction with a six-dB CSNR improvement in a **circuit-aware behavioral model** of a 256-dimensional binary MAC. Its Bernoulli operands, 28-nm parameters and noise model differ from AnalogIOC. Calibrate thresholds on AnalogIOC's actual transfer and validate on held-out operands; do not bank a universal three-bit saving or multiply it by a separate gain that spends the same accuracy margin.

[Heterogeneous Mapping](https://arxiv.org/html/2606.02672v1) supplies a recent GPT-2 precision-sensitivity workflow. Its useful lesson is selective placement and measured sensitivity, not an invariant SNR target for all layers. Protect sensitive projections or channels digitally or with larger/replicated physical units while keeping robust computation analog.

A further **derived design hypothesis** is to allocate capacitor area using sensitivity. If the local loss proxy is `sum_i(a_i/A_i)` because mismatch variance scales as `1/A_i`, and total area is fixed, minimization gives `A_i ∝ sqrt(a_i)`. Thus uniform cell enlargement is generally not the optimum under nonuniform sensitivity. Practical implementation would use a few tile precision classes and calibrated scales. This expression assumes a diagonal positive sensitivity approximation and independent errors; correlated parasitics, different energy per area and fixed pitches require a more complete optimization. It is a proposal for AnalogIOC, not a demonstrated published speedup.

## 4. KV retention: promising device mechanism, incomplete feasibility gate

The 2T gain-cell mechanism is sound: the read transistor senses the stored voltage at its gate, so read current is not intentionally drawn from the storage capacitor. Real leakage and capacitive read disturb remain. [tb_gain_cell.py](../../../../analog/testbenches/tb_gain_cell.py) observes short-term behavior under ideal column clamps; it does not establish long-session accuracy across process and temperature.

[KV_FEASIBILITY.md](KV_FEASIBILITY.md) contains two important numerical errors:

1. It estimates `tau≈27 ms`, derives a roughly **1.7-ms one-LSB retention interval**, then proposes refreshing every `tau/2≈13.5 ms`. Under its own exponential model, a half-time-constant interval changes a stored voltage by about 39%. At 780 mV that is roughly **307 mV, or five 60-mV write-DAC LSBs**. That cadence does not close four-bit retention.
2. Its stated `524,288 cells × 7.5 fJ/write` is **3.93 nJ**, not 3.9 µJ. With a 1.7-ms cadence, the stated cell-write term is about **2.31 µW/head**, before shadow-memory, DAC, wire, reference and scheduling overhead. The document's quoted milliwatt-scale calculation is off by 1000× in this multiplication.

The timing burden is more material: `2048 columns × 150 ns = 307.2 µs` per array sweep. Relative to 1.7 ms, that is **18.1% write occupancy**, or about 36% at a nominal half-LSB interval of 0.85 ms. These figures assume K and V arrays can refresh in parallel and ignore hot/corner tightening; serialized shared resources can be worse. They are recomputations of the document's assumptions, not new device predictions.

Moreover, `tau` came from a few-microsecond voltage slope, not a millisecond retention curve. Different stored codes can leak in different directions. Acceptance should be based on the **read-current/MAC error** after temperature-dependent residency, not only stored-voltage drift. A nonlinear read transistor can amplify a small voltage error. Read-disturb must be measured jointly with leakage and refresh.

The directly relevant external attention work, [Leroux et al.](https://arxiv.org/html/2409.19315v2), combines SPICE with hardware-aware model evaluation; its proposed 65-ns attention pipeline and gain-cell retention should not be labeled silicon measurements. High token cadence also does not determine the lifetime of a KV entry when a session pauses or its context remains resident.

The material technology opportunity is real: [imec's IGZO gain-cell work](https://www.imec-int.com/en/articles/igzo-based-dram-energy-and-area-efficient-analog-memory-computing) reports multilevel storage and small 2×2/4×2 MAC demonstrations, with much longer retention than the present silicon-CMOS assumption. This is evidence for a future substrate, not a large LLM cache or Sky130-compatible process. Preserve silicon-CMOS refresh as the implementable baseline until the production process is chosen.

## 5. Corrections to the local research laws

These matter because the notes are used as premises in subsequent projections.

- **Serial error accumulation:** note 27l3 writes `sigma_total=sigma*sqrt(K)` but then budgets only `5*log10(K)` dB. At fixed signal power the correct penalty is **`10*log10(K)` dB**. The current manuscript's `law:cascade` uses the corrected exponent. Neither expression automatically models parallel partial sums, whose signal variance also changes with K.
- **Summation versus cascade:** independent zero-mean partial signals and independent errors can both add in power, leaving their ratio approximately constant. Coherent same-sign signals can grow as K; cancelling signals can be arbitrarily sensitive. A fixed `K/SNR_stage` term is therefore not a universal charge-accumulation law.
- **Cap mismatch averaging:** note 27i1's `1/sqrt(N)` relative-error improvement assumes a noncancelling sum with comparable contributions. Signed transformer dot products do not satisfy that universally. Compute `Var(delta_W @ x)` using the actual operand covariance.
- **Sparsity/range arithmetic:** note 27h2 defines s as the active fraction, then states that `Delta∝s` makes energy fall as `s²`. In its displayed model `E_thermal∝1/Delta²`, that substitution does the opposite. Fewer decision bits at the same absolute voltage LSB do not deliver the often-quoted thermal `4^bits` saving. Real skipping can save energy; count it only where operations are actually suppressed.
- **Quantization can correct small errors:** a discrete ideal output can be recovered by thresholding noisy values. Therefore the additive-independent-noise bound `SNR_out≤SNR_analog` is conditional; it is not a universal theorem once the quantizer uses the prior lattice. Conversely, fine bits do not repair an arbitrary unknown upstream weight error. The CACTUS analysis identifies the relevant distinction.
- **Thermal bound is scoped:** `12*k*T*4^B` follows from a sampled-capacitor noise budget and an assumed voltage-range/quantization criterion. It is a useful readout/core floor under those assumptions, not a fabricated-chip energy estimate, nor a per-MAC number without dividing by the correct number of contributing MACs. At 300 K and eight bits it is about 3.26 fJ per such sampled result.
- **Nulling does not remove all settling:** early SAR trials can produce large differential residues. A common-mode loop, reference distribution, comparator noise and changing array load remain. A conductance/capacitance cancellation in a flash summing node does not transfer automatically to an OTA-loaded capacitive array.
- **The paper's lattice ceiling is not a universal cutoff:** the `N>=256` and `0.75 mV` figures describe a particular behavioral model; the primary CACTUS paper says the advantage reduces in that regime, while still reporting a 256-dimensional example. Avoid converting that into “lattice benefits die at N=256.”

Primary context for the precision/energy limits: [Gonugondla et al., Fundamental Limits on Energy-Delay-Accuracy](https://experts.illinois.edu/en/publications/fundamental-limits-on-energy-delay-accuracy-of-in-memory-architec/). Local note corrections above are algebraic checks of the supplied research, not additional experimental findings.

## 6. Concrete next acceptance sequence

1. **Physical and statistical baseline:** one extracted representative capacitor bank, loaded column and references; characterize gain, INL, noise and mismatch over supply/temperature. Freeze this error model before optimizing its scalar CSNR.
2. **Same-result readout comparison:** unary+fine versus binary-coarse+fine versus passive-charge/readout options. Count conversions and report total reference/driver/control/OTA energy at matched final accuracy.
3. **Legal reduction experiment:** use actual distinct model reduction blocks, include all intermediate running sums and an overflow fallback, and compare one analog-final conversion with K digital partials.
4. **Encoding experiment:** compare repeated-PWM, two ordinary nibble windows, bit serial and in-array shift/add under the same weight storage, capacitance, accuracy and throughput budget.
5. **Full-model accuracy:** replay frozen physical weight errors and temporal converter errors on held-out prompts. Evaluate perplexity and task behavior; report error tails and layer sensitivity, not merely one-head cosine or a few argmax matches.
6. **KV refresh closure:** all stored codes, hot/cold corners, actual read cadence and pauses, real write references, mandatory refresh scheduling and shadow traffic.
7. **Physical area and power closure:** include SRAM weight controls, reference reservoirs, clock distribution, interconnect, layout parasitics and idle leakage. Only then translate per-operation results to tok/s and tok/J.

The most attractive transferable mechanisms are programmable capacitor-ratio weight stationarity, shared capacitors/references, fewer **real** conversions, and model-sensitive precision. The present research does not support multiplying the older cascade, lattice, gain-servo, duty-factor and supertile gains together, and it does not yet support a claim of superiority to a commercial chip.
