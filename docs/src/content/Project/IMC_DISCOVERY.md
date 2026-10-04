# IMC architecture discovery and falsification

The search produced useful circuit identities, a more defensible readout comparison, and a promising change in accumulation order. **It did not produce a verified novel architecture or a demonstrated improvement over Mythic.** The eight-plane transistor candidates tested here all failed the declared deterministic error gate. A smaller ternary-input charge-pooling fixture passed at nominal and slow/hot conditions after extending its sharing aperture. Its physical ADC, noise, memory, layout and complete workload remain unverified.

The strongest direction retained is to **combine row charges before temporal significance accumulation**, then use a shared charge-domain readout. This changes eight independently erroneous radix ratios into one aggregate ratio. A separate simplification reuses the holder reset switches for final readout connection. Both are implementation hypotheses with substantial prior art around their constituent mechanisms.

This report records a bounded research iteration on 2026-09-10. Supporting investigations are [circuit derivations](IMC_DISCOVERY_CIRCUITS.md), [independent criticism](IMC_DISCOVERY_CRITIC.md), and [primary-source/prior-art review](IMC_DISCOVERY_PRIOR_ART.md). Existing AnalogIOC sources and experiments were preserved; these are research alternatives to the [implementation contract](CONTRACT.md).

## 1. Quantified problem and comparison boundary

Optimize a vector of objectives, rather than one misleading composite score:

\[
\min(A_{\rm total}, E_{\rm accepted\ token}, L_{\rm first\ result}),\qquad
\max(R_{\rm accepted\ token}, R_{\rm useful\ MAC}).
\]

The objectives compete. Extra converters reduce service time but cost area; extra capacitance reduces some noise and mismatch but costs area, drive energy and settling time; buffering reduces initiation interval without necessarily reducing first-result latency. A candidate belongs on a useful Pareto frontier only after satisfying the same accuracy, capacity and operating constraints.

| Quantity | Working constraint or definition |
|---|---|
| Technology | Sky130, nominal 1.8 V; transistor tests use installed sky130A models and pinned Nix ngspice 43 |
| Arithmetic target | Native signed W8/A8 useful MACs for competitive accounting; W4 circuits and ternary screens identified separately |
| Resident capacity comparison | Historical M1076: 79,691,776 logical weight positions and 19,456 ADCs; equal counts do not imply equal area |
| Quality | Same quantized model, corpus/task and accepted output quality; no workload-quality pass established here |
| Local deterministic gate | Six calibration vectors, then RMS error <0.25 and maximum error <1 reconstructed integer-MAC unit; this is a fixture screen, not an eight-bit ADC specification or stochastic yield claim |
| Physical acceptance | Complete acquisition/conversion, actual references/control, mismatch, operating corners, legal capacitors, PEX, storage and calibration costs remain required |
| Area | Include coefficient storage, all installed capacitors/switches, DAC/ADC, clocks/references and wiring; the older contract's infinite-area assumption cannot support this search objective |
| Energy | Sum positive delivery at each individual supply/reference/clock source over reset, compute, sharing, capture and return; add real generator and digital overhead later |

Free variables include row-group size, pooling fan-in, where spatial and temporal accumulation occur, capacitor realization and ratios, switch geometry, voltage swing, activation radix/order, converter range/resolution, analog-state lifetime, number of ADCs, buffering, physical coefficient storage and compiler scale grouping. Process substitution is a separate branch, not a free improvement within the Sky130 comparison.

Useful reporting identities are

\[
\mathrm{TOPS}=\frac{2N_{MAC}}{10^{12}T},\quad
P=E/T,\quad \mathrm{TOPS/W}=\frac{2N_{MAC}}{10^{12}E}.
\]

Bit planes, W4 slices, retries and ADC decisions consume resources but do not multiply useful native MAC count. Tokens/s and tokens/J require a complete model schedule, memory capacity/bandwidth and accepted token execution; they are unknown here.

The current [Mythic M1 product page](https://www.mythic.ai/m-1) specifies 25 TOPS and 3–4 W for the standalone chip. The historical [ISSCC 2022 disclosure](https://www.isscc.org/s/ISSCC2022PressKit.pdf) separately reports 16.6 TOPS and 3.3 full-system TOPS/W at its eight-bit point; its 5.2 TOPS/W array number has a different boundary. The [IEEE CTO presentation abstract](https://events.vtools.ieee.org/m/307323) supplies historical weight and ADC counts. The announced 2027 Vanguard generation is distinguished in the prior-art report. These are different anchors, not interchangeable measurements of one workload.

The strongest local architectural baseline is [the existing equal-resource comparison](IMC_SYSTEM_BENCHMARK.md): two serial W4 services, eight row groups and 32 ADC rounds per slice. It projects 8.127 TOPS using a 366-ns average array fixture and a 295-ns ADC fixture. Its ADC has a preserved failing reserved input; the components have not been integrated. A full eight-plane timing extension gives 8.027 TOPS. Neither is a qualified chip result.

## 2. Knowledge map and candidate population

The supplied circuit notes were used first, especially `27g2` on sampled noise, `27h3` on column/converter accounting, `27f9` on settling, and the local paper. Online searches then covered primary papers, author/institutional manuscripts, patents, official product disclosures, and process documentation. The three supporting reports contain source-by-source comparisons and retrieval limitations.

The common restrictions found in existing approaches are often architectural: separate ADCs for every row partial, equal voltage samplers for differently normalized outputs, independent local radix ratios, fixed conversion effort, or incompatible group scales. Charge conservation and thermal noise are physical constraints; the number and placement of conversions are design choices.

| Candidate/mechanism | Quantitative test or objection | Disposition |
|---|---|---|
| Analog hold/ping-pong only | Even perfect removal of array overhead leaves 64×295-ns ADC rounds and 8.442 TOPS in the old mapping | **FAILED** as a sufficient route to 25 TOPS; storage remains useful |
| Regenerative multilevel latch | Positive feedback amplifies perturbations as well as signal; retaining many levels needs stabilization or quantization | **FAILED** as a free arbitrary-precision analog memory |
| Copy all partial voltages onto equal capacitors | Computes a sum weighted by inverse native capacitances; synthetic scalar-calibrated error 2,510.54 MAC RMS | **FAILED** for unequal normalized partials |
| Join original charge after local radix | Exact ideal sum; new ternary circuit passes after settling repair; all full-A8 versions tested fail | **VERIFIED** identity; **FAILED** tested A8 implementations |
| Add dummy load to restore local ratios | A8 nominal RMS 6.251→5.974 MAC after final calibration | **FAILED** as sufficient repair |
| Reuse holder reset TG as pooling switch | Deletes eight dedicated TGs in the small fixture; A8 nominal RMS 4.704 MAC | **FAILED** present accuracy gate; useful simpler topology |
| Pool before radix accumulation | One aggregate ratio replaces eight local ratios; modeled independent mismatch improves; nominal circuit still 3.704 MAC RMS | **STRONGLY SUPPORTED** mismatch mechanism; **FAILED** present circuit |
| Power-of-two scale alignment using zero upper planes | Exact synthetic weighted sum; example requires 8–14 planes instead of eight | **VERIFIED** arithmetic; **SPECULATIVE** circuit/quality benefit |
| Current-domain active integration | Can sum without passive voltage attenuation; must pay amplifier noise, bias, settling, headroom and memory technology | **SPECULATIVE** alternative; established prior art |
| Time-domain ramp/VCO readout | Changes the state variable, but precision becomes ramp noise, comparator jitter, oscillator linearity and dead time | **SPECULATIVE**; no numerical victory |
| Differential polarity reversal | May cancel repeatable offsets; normally adds a second acquisition and uncorrelated noise | **SPECULATIVE**; closely related known techniques |
| Overflow-adaptive accumulation/fallback | Saves conversions only when detection, stalls and recovery cost less than avoided services | **SPECULATIVE** here; explicit patent prior art |
| Adjacent-token delta computation | On the saved nine-position FFN-down trace, difference MSE is 1.751× activation MSE | **FAILED** local screening assumption; not a universal rejection |
| Median weight centering | All 576 FFN-down row medians are zero; no reduction in total absolute W4 coefficients | **FAILED** on this fixture |

These labels apply to the stated claims. No full-A8 candidate currently passes the physical gates, so there is no measured area/energy/throughput Pareto frontier to advertise. The schedules below are sensitivity studies that select experiments.

## 3. Native-charge pooling: derivation and assumptions

Let `g` index row groups, `b` activation magnitude planes, and `s_g,b` the signed integer dot product for one plane. Let `κ=C_u V_s`, and measure voltages relative to common mode. The array capacitance is

\[
A_g=C_{0,g}+C_u\sum_i|w_{g,i}|.
\]

With fixed row endpoints and settled linear capacitors, its plane voltage is `p_g,b=κ s_g,b/A_g`. Sharing with an initially reset holder `D_g` produces

\[
h_{g,b+1}=\frac{D_gh_{g,b}+\kappa s_{g,b}}{A_g+D_g}.
\]

If `D_g=A_g=C_g`, LSB-first operation gives

\[
h_g=\frac{\kappa S_g}{2^B C_g},\qquad
S_g=\sum_{b=0}^{B-1}2^b s_{g,b},\qquad
Q_g=C_gh_g=\frac{\kappa S_g}{2^B}.
\]

Therefore joining the **original holders** to a neutral capacitance `C_L` gives

\[
V_{pool}-V_{CM}=
\frac{\kappa\sum_gS_g}{2^B(\sum_gC_g+C_L)}.
\]

The weight-dependent denominator cancels in the stored charge. Unequal programmed capacitances alone do not require equal-capacitor voltage resampling or a per-partial gain correction. One final scale remains. This is a consequence of ordinary charge conservation, not a new physical law.

The result requires the same coefficient scale, radix convention and effective completed exponent, an initially known bus charge, settled endpoints, and the effective holder capacitance matching its local array. Unit-capacitor mismatch changes the encoded coefficients; nonlinear switch parasitics can change both capacitances during a cycle. Neither is removed by this identity.

For `D_g=A_g(1+ε_g)`, define `ρ_g=D_g/(A_g+D_g)`. Normalized holder charge evolves as

\[
Q_{g,B}=\kappa\sum_b\rho_g^{B-b}s_{g,b},\qquad
\rho_g\simeq\tfrac12(1+\epsilon_g/2).
\]

The relative plane-weight error is approximately `(B-b)ε_g/2`, which depends on significance. A scalar output calibration cannot generally remove it. In a 4,096-vector synthetic control, even a uniform 0.1% ratio perturbation leaves 0.861 MAC RMS after one fitted gain/offset; 1% leaves 8.570 MAC RMS. These are sensitivity probes, not foundry mismatch predictions.

## 4. Cross-pollination: change the accumulation order

What becomes possible if charge-denominator cancellation is combined with the critic's observation that local ratio errors distort significance independently? Combine the row charges **at every plane**, before creating eight separate temporal histories.

Connect the settled local array nodes through their sharing switches to one holder `D`. Then

\[
h_{b+1}=\frac{Dh_b+\kappa\sum_g s_{g,b}}{D+\sum_g A_g}.
\]

Choose `D=ΣA_g`, including capacitance that actually participates in this phase, to obtain a single half-radix recurrence. Total ideal holder capacitance is unchanged from eight matched holders. This proposal simplifies the number of ratios to calibrate; it does not give a free eightfold capacitor-area reduction.

For independent ratio errors, the aggregate error is approximately `ε_eff=ΣA_g ε_g/ΣA_g`. With identical variances it has variance `σ² ΣA_g²/(ΣA_g)²`, close to `σ²/8` for balanced groups. A shared systematic error is not reduced. In addition, much of the group-dependent gain error becomes one globally calibratable gain.

The circuit branch tested 512 synthetic Gaussian ratio draws on eight 128-row groups, with 128 calibration and 512 evaluation vectors per draw. At assumed 0.1% independent ratio sigma, median output RMS was:

| Architecture/calibration | Median RMS, integer MAC units |
|---|---:|
| Late analog pooling, one final affine fit | 5.614 |
| Eight separate digital partials, eight affine fits before summation | 0.966 |
| Early analog pooling, one final affine fit | 0.248 |

The approximately 3.9× improvement over the stronger calibrated digital-partial control is conditional on this mismatch model. With fully correlated errors, early and late one-fit results are identical. There is no ADC noise, quantization, layout or acquisition model in this experiment. Reproduction and the 1% case are in the circuit report.

The physical risks change with this ordering: the shared wire participates every plane; incomplete settling becomes a repeated radix error; the aggregate reset load is larger; and reference/clock errors can become correlated. The new transistor test reduces pre-read RMS from 7.831 MAC with separate holders to 2.423 MAC with the common holder, but still fails. The analytical benefit has survived an independent critic; the complete circuit has not.

A second recombination reuses reset switches. During computation, clamp the read bus to `V_CM`, making each holder reset TG an ordinary reset connection. At final readout, release the bus reset and close those same holder TGs. They now combine stored charge rather than erase it. This deletes the dedicated join TGs. The shared reset impedance, bus-reset injection and nonoverlap still require measurement; the present implementation fails A8 accuracy.

## 5. Scale compatibility and exponent alignment

Raw charge pooling cannot reconstruct `Σa_g S_g` from `ΣS_g` when arbitrary group scales `a_g` differ. That is loss of information, not a small gain error. The seven original saved compiler tensors checked here have scalar `dx_in` and per-output `dw`, so their row groups share the required scale. Other research paths that introduce independent group quantization scales need separate treatment.

Even with common physical scales, different local plane counts give different charge exponents. Synchronizing each 1,024-row pooling region increases the active 128-row group-plane count by 0–13.46% on the saved three evaluation positions, depending on tensor. This is a count on the existing compiled subset, not a workload-wide latency prediction.

For scales constrained to `a_g=a_0 2^{e_g}`, choose

\[
B_0=\max_g(e_g+b_g),\qquad B_g=B_0-e_g\ge b_g.
\]

After its useful planes, group `g` performs `B_g-b_g` **zero upper planes**, halving the retained state each time. Then `Q_g=κ2^{e_g}S_g/2^{B_0}`, and one final scale recovers the desired weighted sum. The tested exponent range −3…+3 required 8…14 planes and reconstructed 4,096 synthetic vectors exactly in binary floating arithmetic. Arbitrary scales, the quality effect of power-of-two quantization, extra-cycle noise and practical control remain unverified. [GR-MAC](https://arxiv.org/html/2602.08081v2) and the [2025 analog alignment work](https://pure.korea.ac.kr/en/publications/bit-preserving-analog-alignment-based-cross-domain-fp-cim-for-llm/) are important prior-art comparisons.

## 6. Noise, readout and energy: no free precision

Use the charge-error covariance rather than adding independent `kT/C` penalties indiscriminately. For stored charge covariance `Σ_Q`, ideal pooling preserves total-charge variance `1ᵀΣ_Q1`. Internal switch Johnson currents redistribute charge with equal and opposite signs, but can excite differential voltage modes seen by a physical comparator.

For a lumped local capacitance `C_A` connected through `R` to read capacitance `C_L`,

\[
\tau=R\frac{C_A C_L}{C_A+C_L},\qquad
\operatorname{var}(V_A-V_L)=kT(1/C_A+1/C_L).
\]

The differential contribution at the read node is `kT C_A/[C_L(C_A+C_L)]`. The total-charge coordinate can be quiet while the local bus voltage is noisy. Read bandwidth, aperture and switch opening determine which modes are observed. A 200,000-draw linear equilibrium model reproduced the common and bus variances within 0.56% and 0.36%; this is not MOS transient-noise simulation.

For an illustrative capacitance set taken from the prior **eight output columns**, not measured eight row groups, `ΣC_g=3,676 fF` and `C_L=948 fF`. With `C_u=4 fF`, `V_s=0.45 V`, and `B=8`, the nominal charge per integer MAC is only 7.031 aC, about 43.9 electron charges. The pooled gain is 1.521 µV/MAC.

| Conditional noise quantity, 300.15 K | Value |
|---|---:|
| Thermalized conserved-charge coordinate | 29.94 µV, or 19.69 MAC RMS |
| Two-node differential contribution at bus | 58.95 µV RMS |
| Full-bandwidth thermalized read-node voltage | 66.12 µV RMS |
| Optimistic reset-only radix model, excluding sharing-generated noise | 13.50 MAC RMS after reconstruction |
| Assumed 100-µV comparator input noise | 65.76 MAC RMS after reconstruction |

The last rows already show why deterministic sub-MAC transfer is not an accuracy qualification. These are particular noise models and an illustrative capacitance set, not universal lower bounds on every correlated-sampling or active readout architecture. Workload significance depends on output range and model sensitivity, which must be tested.

For independent ADC voltage errors `σ`, a voltage-preserving baseline has reconstructed charge variance `σ²ΣC_g²`. Pooled conversion has variance `σ_pool²(ΣC_g+C_L)²`. Equal error requires

\[
\sigma_{pool}\le\sigma\frac{\sqrt{\sum C_g^2}}{\sum C_g+C_L}.
\]

The illustrative tightening is 3.480×, equivalent to 1.799 extra quantizer bits **only at fixed range and for quantization-dominated error**. However, if every independent baseline read also passively acquires into its own 948-fF load, its coefficients become `C_g+C_L`. The tightening is then only 1.159×, or 0.213 bit. This is a correction to the comparison boundary, not evidence of a noiseless converter. Against an active buffer or a native charge-domain ADC, another comparison is required.

An adversarial energy bound further limits the claim. Assume decision energy `E_g=a/σ_g²` and a fixed charge-error budget `ε_Q²`. Optimizing the separate converters gives

\[
\min\sum_gE_g=\frac{a(\sum_g C_g)^2}{\epsilon_Q^2},
\]

exactly the ideal unloaded pooled-converter value. Pooling can save fixed per-read overhead, avoid repeated acquisition/reset, change practical converter efficiency, or improve latency. It does not evade the optimally allocated thermal decision-energy law. A fixed-load calculation gives a 0.169 ratio for the **decision-noise component** versus repeatedly loaded reads; this excludes the acquisition noise floor, assumes independently scalable decision energy, and becomes invalid if increasing resolution resizes the read capacitor.

## 7. Fresh transistor verification and failed iterations

[The new testbench](../../../../analog/testbenches/tb_imc_native_charge_pool.py) builds eight groups of four signed fixed W4 coefficients, real Sky130 row switches, array reset switches, radix sharing switches, holders, bus reset and pooling switches. Unit capacitance is 4 fF; local nominal capacitances are 132–232 fF; bus load is an ideal 948-fF capacitor. Clocks and references are ideal voltage sources with delivered energy counted. The circuit contains **no ADC, programmable weight storage, extracted wire, capacitor device model, random mismatch or transient noise**.

`B=1` means a signed ternary activation plane, not a signed one-bit arithmetic claim. `B=8` includes −128…127. Calibration is the first six synthetic vectors. Development seed 97102 supplied eight random evaluation vectors plus zero and two fixed signed extremes. After choosing a 100-ns joining aperture, seed 97103 was used for fresh random confirmation at both corners. Fixed extreme controls remained the same.

All numbers below use one independently fitted **final bus** gain/offset per configuration and corner. They do not imply a frozen cross-corner calibration. The gate was not changed after failure.

| Circuit | Corner | Join aperture | RMS / max MAC | Gate |
|---|---|---:|---:|---|
| Original late pooling, ternary | TT/27°C | 40 ns | 0.0213 / 0.0613 | **VERIFIED**, bounded deterministic test |
| Same | SS/85°C | 40 ns | 0.3880 / 1.0465 | **FAILED** |
| Same, only aperture extended | SS/85°C | 100 ns | 0.0172 / 0.0512 | **VERIFIED**, reused development inputs |
| Frozen 100-ns variant, fresh seed 97103 | TT/27°C | 100 ns | 0.00633 / 0.01863 | **VERIFIED**, bounded deterministic test |
| Same fresh seed | SS/85°C | 100 ns | 0.02057 / 0.05147 | **VERIFIED**, bounded deterministic test |
| Original late pooling, A8 | TT/27°C | 40 ns | 6.251 / 17.67 | **FAILED** |
| A8 plus dummy TG balancing | TT/27°C | 40 ns | 5.974 / 16.18 | **FAILED** |
| A8 with reset-TG reuse | TT/27°C | 40 ns | 4.704 / 12.67 | **FAILED** |
| A8 early pooling plus reset reuse | TT/27°C | 40 ns | 3.704 / 9.056 | **FAILED** |

The aperture repair is evidence of a settling limitation in this fixture. It is not evidence that a 1,024-row bus settles in 100 ns. The A8 error already exists before final readout: original holders give 7.798 MAC RMS under their aggregate pre-read calibration. This diagnostic weights holder voltages by nominal capacitances; it does not independently measure total physical charge including nonlinear MOS capacitance. It therefore establishes a model-to-voltage error, without uniquely identifying radix mismatch, injection or nonlinear charge weighting. Dummy balancing does not remove it, so blaming the added selector capacitance alone is unsupported.

Halving the transient step from 100 to 50 ps for the fresh slow/hot ternary case retained the pass: RMS 0.02052 MAC and maximum 0.05125 MAC. This checks numerical sensitivity at that operating point, not noise or an untested corner.

The independent audit reproduced all original error and energy calculations and exposed two important boundaries. Applying the **unchanged prejoin** calibration to the TT ternary bus gives 0.762 RMS / 1.325 max MAC, versus 0.0213 / 0.0613 after final-bus calibration. Therefore final calibration absorbs a material transfer shift; the low fitted residual is not evidence of zero charge injection. Also, early runs read the source hash after simulation while the file could be edited. Their generated-netlist hashes remain valid; source hashes alone should not be used to reproduce those revisions. Later runs freeze the generator bytes at import and store `generator_snapshot.py` with the deck.

Positive-delivery energy is measured over whole synthetic vector slots. For example, the development ternary fixture uses 0.635 pJ at TT and about 0.664 pJ at SS. Extending the SS join from 40 to 100 ns changes that mean little at displayed precision while increasing the slot from 124 to 184 ns. The A8 original uses 3.670 pJ per 32-position synthetic vector. These fixtures have different fanout and dimensions from the previous 128×8 array; neither energy per useful MAC nor their cohort means may replace that workload's measurements.

## 8. Timing and area requirements

Late pooling of `G` row groups changes 32 ADC rounds per W4 slice into `32/G`. Without assuming overlap, use the conditional schedule

\[
T_G=2\left(488\,\mathrm{ns}+T_{join}+\frac{32}{G}T_{ADC}\right).
\]

For `G=1`, no additional pooling time is charged. Two W4 services are the existing benchmark's W8 scheduling assumption; physical W8 loading, exact bank encoding and quality remain unbuilt. A 341-ns ADC is merely the affine extension `65+12×23 ns` of a ten-decision 295-ns fixture; it is not a measured twelve-bit converter.

| Pool fan-in | ADC rounds per slice | Conditional TOPS, 295-ns ADC | Conditional TOPS, 341-ns ADC |
|---|---:|---:|---:|
| 1, no pooling | 32 | 8.027 | 6.991 |
| 2, 100-ns pooling | 16 | 15.014 | 13.185 |
| 4, 100-ns pooling | 8 | 27.032 | 24.033 |
| 8, 100-ns pooling | 4 | 45.075 | 40.826 |

These retain historical weight/ADC counts and assume all groups operate in parallel. They exclude reconstruction, real mux/control/reference delays, memory traffic and the demonstrated accuracy failures. The previously tempting 40-ns case fails even the small ternary SS test and is retained only as sensitivity data in the JSON. Reaching 25 TOPS at those counts requires a complete group service under 6.375 µs. No measured system here meets that requirement at accepted accuracy.

For passive joining, worst-case residual error decays as a sum of RC eigenmodes. A one-pole screen needs approximately `(n+1)ln2` time constants to settle a full-scale step below half an n-bit LSB. Switch on-resistance depends on signal, threshold and temperature; long wires introduce additional poles. These circuits have no intentional regenerative loop, but sampled recurrence stability (`|ρ|<1`) does not establish settling or immunity to charge injection.

The [Sky130 process documentation](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html#mim-capacitors) specifies nominal 2 fF/µm² MIM area capacitance per available layer, with possible stacking. The [minimum-dimension rules](https://skywater-pdk.readthedocs.io/en/main/rules/assumptions.html#minimum-critical-dimensions) list 2-µm MIM dimensions. A 4-fF ideal capacitor is consequently not a demonstrated legal minimum-square MIM unit; a MOM or other implementation needs extraction and matching evidence.

Even taking two perfectly overlaid MIM layers as a nominal 4-fF/µm² area-term estimate, one 4-fF unit per 79.69M logical positions already consumes 79.69 mm² of capacitor plate area term. A programmable multibit weight needs more than one unit, plus storage/sign circuitry; the radix holder also consumes capacitance. This is a sizing illustration, not a strict geometric lower bound with fringe effects or a completed layout. Counting only nonzero ideal capacitors in a fixed-weight SPICE deck substantially understates installed programmable-bank area. Early pooling preserves total holder capacitance; ping-pong duplicates it. No area victory over dense flash is established.

## 9. Novelty assessment and validation decision

Generic analog aggregation, analog-state pipelining, capacitor reuse, radix-half accumulation and charge-based exponent alignment have direct prior art. Particularly close comparisons include [Intel global charge-sharing](https://patents.google.com/patent/US10748603B2/en), [direct original-column pooling into shared ADCs](https://patents.google.com/patent/US20230370082A1/en), [weight-dependent denominator correction](https://patents.google.com/patent/EP4579437A1/en), [MANTIS](https://arxiv.org/html/2411.07946), and [Charge-CIM](https://arxiv.org/html/2608.11116v1). The broader search also checked IBM's shared integrators, CAP-RAM, overflow-adaptive accumulation and several recent alignment/readout papers.

No first-invention claim survives this review. The narrower research opportunity is a demonstrated implementation in which accumulation order, effective capacitance matching and reuse of existing reset/readout ports reduce the **complete** cost at matched quality. The exact combination is not established novel by the bounded search, and the present A8 circuits fail before such a comparison is possible.

The retained findings are:

- **VERIFIED:** ideal native-charge cancellation, scale-alignment arithmetic, synthetic negative controls, seven saved tensor reconstruction checks, and the explicitly bounded ternary transistor tests.
- **STRONGLY SUPPORTED:** early spatial pooling can reduce independent radix-mismatch sensitivity by converting many ratio errors into one aggregate ratio, under the tested mathematical model and its stronger calibrated baseline.
- **SPECULATIVE:** a complete early-pooling/reset-reuse architecture with useful low-noise ADC, smaller area, faster initiation interval and preserved model quality.
- **FAILED:** all tested full-A8 circuit variants; the broad novelty claim; storage-only sufficiency; several normalization, delta and centering assumptions.

Before promoting the surviving direction, the decisive gates are a legal capacitor/ratio implementation, an actual connected charge-domain converter with a measured aperture/noise budget, and calibration/error replay through the same complete quantized workload. The choice between late pooling, early pooling and active integration must then compare area, readout error, all source energy and achieved service time. PVT/mismatch yield, rail/reference coupling, W8 storage, layout and accepted token metrics remain unverified.

## 10. Reproduction and artifacts

Run using the existing cached Nix Python/NumPy environment and pinned ngspice:

```sh
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 scripts/compiler/metrics/imc_native_charge_analysis.py
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_native_charge_pool.py --bits 1 --join-ns 100 --corner ss --temp 85 --seed 97103
/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 analog/testbenches/tb_imc_native_charge_pool.py --bits 8 --early-pool
```

The last command is an intentional failing experiment: it writes its full result and exits nonzero at the unchanged accuracy assertion. `--balance-load`, `--reuse-reset`, `--join-ns` and `--step-ns` reproduce the other controls. The testbench contains a fixed operand/seed specification and stores whole-word energy, outputs, calibration data, netlist hash and simulator path. Generated artifacts are in `build/sim/imc_native_pool*`; algebra, covariance, schedule and compiler-input hashes are in [the analysis JSON](../../../../build/research/imc_native_charge_analysis.json). The [ten-run manifest](../../../../build/research/imc_discovery_manifest.json) records independent fingerprints of the result files and exact on-disk decks, plus source-snapshot availability and the timestep comparison. These research programs do not update the existing system benchmark or turn unknown costs into zero.
