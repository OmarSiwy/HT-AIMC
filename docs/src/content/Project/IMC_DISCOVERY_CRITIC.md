# Independent falsification of charge aggregation and alternative IMC mechanisms

2026-09-10. Scope: independent analytical critic and five alternative mechanism branches. Read `AGENTS.md`, `CONTRACT.md`, the current system benchmark and analog-storage handoff before analysis. No existing circuit or benchmark was changed. Numerical checks below used the cached Nix Python/NumPy environment; this branch did not run a new transistor simulation.

**The original-capacitor aggregation identity survives ideal circuit analysis. A claim of eightfold energy improvement at equal accuracy does not. Independent block scales, finite-aperture noise, radix mismatch and prior art are the main remaining obstacles.** No novel architecture or Mythic victory is verified by this report.

## 1. Objective and strongest admissible controls

Minimize complete energy per accepted output, initiation interval, latency and physical area at the same deployed numerical quality. The immediate schedule target is eight row groups of a 1,024-row dot product: aggregate their results before conversion so 256 shared ADCs service 1,024 final outputs in four rounds, instead of servicing 8,192 partials in 32 rounds. W8 still requires correct combination of its coefficient slices. Storage, input quantization, control, references, analog interconnect and output reconstruction belong in the boundary.

The [current equal-resource benchmark](IMC_SYSTEM_BENCHMARK.md) has 366-ns mean array time and a 295-ns converter cycle. Its current converter failed a reserved SS input; isolated array/ADC fixtures are not a demonstrated connected path. The proposed four-round service count is an arithmetic opportunity, not an accepted timing or quality result.

Compare against both:

1. The currently implemented eight independent partial conversions and exact digital reconstruction, including each partial's physical gain and quantization scale.
2. A stronger design control that allocates each independent converter's precision optimally, instead of forcing identical voltage noise or ADC bits on unequal-gain partials.

A passive-loaded baseline is different from a buffered-acquisition baseline. Charge either its loading penalty or its buffer; comparing one architecture with free acquisition and another with a 948-fF acquisition load can predetermine the answer.

Local reference notes read: [27g2, sampled noise](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27g2 kT Over C Noise Sets the Minimum Capacitor Size in a Charge-Domain Column Exactly as It Does in an ADC.md>), [27h3, dot-product conversion](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27h3 An Analog CIM Column Is a Data Converter Whose Input Is a Dot Product.md>), and [27h10, null balancing](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27h10 A Null-Balancing SAR Readout Pays for Precision with Matching Instead of Standing Bias.md>). The distinction between compute noise and output quantization is also established by [Gonugondla et al., TCAD, primary paper](https://arxiv.org/pdf/2012.13645). Its minimum-precision criterion uses signal statistics and an explicit clipping allocation; it does not justify a universal ADC bit target.

## 2. The proposed original-capacitor sum

Let group g have array capacitance Cg and a physically matched accumulator Cg. All voltages below are deviations from a common reference. Its settled binary-radix recurrence, processing the least significant plane first, is

\[
h_{g,j+1}=\frac{h_{g,j}+p_{g,j}}2,\qquad
p_{g,j}=\frac{\kappa d_{g,j}}{C_g},\qquad h_{g,0}=0.
\]

Here d is a signed integer plane dot product, Sg=Σj 2^j dgj, and κ is the unit charge scale. Thus

\[
h_g=\frac{\kappa S_g}{C_g2^B},\quad
q_g=C_gh_g=\frac{\kappa S_g}{2^B}.
\]

Joining the ORIGINAL accumulator capacitors to an initially neutral bus capacitor Cb gives

\[
V_b=\frac{\sum_gC_gh_g}{C_T}
=\frac{\kappa\sum_g S_g}{2^BC_T},\qquad
C_T=\sum_g C_g+C_b.
\]

**VERIFIED, ideal model:** arbitrary group capacitance cancels from each signal numerator. It remains in the common denominator, the analog noise, loading and timing. Copying the voltage onto equal capacitors does not implement this identity. Adding arbitrary capacitance to an already computed holder is also not interchangeable with changing the matched array/accumulator pair.

Numerical falsification used 10,000 random signed eight-group integer vectors, κ=4 fF×0.45 V, B=8, a 948-fF neutral load and illustrative capacitances `[568,484,304,600,516,336,444,424] fF`. Charge conservation and the direct integer formula differed by at most 3.47e−18 V. Replacing the original-cap weighting by an equal-voltage average introduced 25.56% relative RMS error on the same synthetic population. The eight capacitor values are the existing fixture's eight OUTPUT COLUMNS, reused only as a heterogeneous numerical example; they are not measured capacitances for eight row groups of one output.

### Independent scaling is an information-loss counterexample

If the deployed model requires yg=ag wg Sg, a bus proportional only to ΣSg cannot recover Σag wg Sg from one post-ADC scalar. With two groups, `(S1,S2)=(1,0)` and `(0,1)` both produce the same bus charge, but scale products `(a1w1,a2w2)=(1,2)` demand different outputs. No calibration of that one scalar observable repairs the loss.

This is directly relevant to particular research paths: [the full-model radix experiment](IMC_RADIX_FULL_MODEL.md) uses per-token, per-input-block activation scales; [grouped-weight experiments](IMC_GROUPED_WEIGHTS.md) additionally require group weight scales before summation. Common B alone is insufficient in those paths. In contrast, the root's new inspection of all seven original saved compiler programming tensors finds scalar `dx_in` and output-only `dw`, so their original integer partials ARE compatible once B is aligned. Do not conflate those original fixtures with the later dynamic-block research paths. The earliest compiler gate must prove scale compatibility, not just integer-sum compatibility. Enforcing one scale across 1,024 inputs can lose the numerical quality previously obtained with 128-input scales.

### Mismatch does not generally become one calibratable gain

Set the actual accumulator to Cg(1+δ) while the array remains Cg. Then

\[
\alpha=\frac{1+\delta}{2+\delta},\quad
\beta=\frac1{2+\delta},\quad
h_{j+1}=\alpha h_j+\beta p_j.
\]

The charge coefficient of plane j, relative to its desired coefficient, is

\[
r^{B-j},\qquad r=\frac{1+\delta}{1+\delta/2}
\simeq1+\delta/2.
\]

Different bit positions have different errors. Exhaustively enumerating all unsigned eight-bit inputs, then applying one endpoint gain correction, gives:

| Cacc/Carray error | Maximum raw error, activation LSB | Maximum error after endpoint gain correction |
| --- | ---: | ---: |
| 0.1% | 0.25099 | 0.06196 |
| 0.5% | 1.25477 | 0.30912 |
| 1% | 2.50909 | 0.61658 |
| 2% | 5.01635 | 1.22656 |

These are radix-input units, not output ADC LSB. The multi-row signed result also depends on weight pattern. A data-dependent capacitance or injection term is more demanding than this fixed-ratio test. Global capacitor variation cancels only when it preserves the actual charge scale and every required ratio; it is not equivalent to local independent mismatch.

## 3. Noise: conserved charge and sensed voltage are different observables

Let ηq be the vector of charge errors already present on the original holders, with covariance Σq. An ideal isolated joining operation conserves total charge, including noise:

\[
\operatorname{var}(\eta_{Q})=\mathbf1^T\Sigma_q\mathbf1.
\]

For independent fully equilibrated reset noise, Var(qg)=kTCg. If the initially reset bus is independent, its Var(qb)=kTCb. The final conserved common-mode voltage then has variance kT/CT. If Cb was initialized ideally without noise, its initial-noise term is absent from that mathematical control. It cannot be omitted from a realizable reset without evidence.

Internal resistor noise transfers charge between isolated capacitors; it does not create net charge. Adding a fresh independent kT/CT common-mode source after already propagating every initial reset source would double count. Conversely, treating the local bus voltage as a noiseless observation of total charge is also wrong.

### Exact two-capacitor counterexample

Combine the local holders into CL, connected through resistance R to the sensed bus capacitor Cb. The conserved mode is

\[
V_{\rm cm}=\frac{C_LV_L+C_bV_b}{C_T};
\]

the fluctuating differential mode d=VL−Vb has

\[
\tau=R\frac{C_LC_b}{C_T},\qquad
\operatorname{var}(d)=kT\left(\frac1{C_L}+\frac1{C_b}\right).
\]

Since Vb=Vcm−CL d/CT, its stationary differential-mode variance is

\[
\sigma^2_{b,\rm diff}=\frac{kTC_L}{C_bC_T}.
\]

With CL=3.676 pF, Cb=948 fF and T=300.15 K, the common-mode RMS is 29.94 µV if every initial capacitor was independently reset at temperature T; the bus differential mode contributes 58.95 µV in full bandwidth. Their quadrature sum is sqrt(kT/Cb), as required by equilibrium. Therefore the phrase “joining adds no thermal noise” is true only for the conserved weighted sum observable, not for a finite-bandwidth or sampled bus terminal.

For an ideal boxcar sensing aperture ta, an Ornstein–Uhlenbeck mode with variance σ² and time constant τ contributes

\[
\operatorname{var}(\bar d)=\sigma^2F(t_a/\tau),\qquad
F(x)=\frac{2(x-1+e^{-x})}{x^2}.
\]

| R in reduced model | τ | Bus differential noise, 2-ns boxcar | Same, 10-ns boxcar |
| --- | ---: | ---: | ---: |
| 1 kΩ | 0.754 ns | 41.25 µV | 22.01 µV |
| 10 kΩ | 7.536 ns | 56.45 µV | 48.35 µV |

**VERIFIED, reduced linear-noise model; SPECULATIVE for the transistor circuit.** A StrongARM's clocked sensitivity is not a boxcar. Its actual aperture, filter poles, kickback, changing capacitance and reset sequence must determine the noise transfer. Opening join switches can freeze differential fluctuations into separately retained nodes. Keeping every holder connected during conversion changes the SAR loading and reference-step response and must be tested in that state.

For equal group voltage noise σ and correlation coefficient ρ, an average has variance σ²[1+(K−1)ρ]/K. At K=8, the factors for ρ=0,0.1,0.5,1 are 0.125,0.2125,0.5625,1. Shared reference noise can therefore defeat an iid averaging argument. This covariance is independent of correlation between the true signals.

## 4. Converter precision and the optimized energy control

First take independent, equally noisy voltage converters with variance σv² and ideal gain-corrected acquisition. Digital reconstruction of total charge has ADC-error variance

\[
\sigma_{Q,d}^2=\sigma_v^2\sum_g C_g^2.
\]

Pooled conversion has

\[
\sigma_{Q,p}^2=C_T^2\sigma_{v,p}^2.
\]

Equal output error therefore needs

\[
\sigma_{v,p}\le\sigma_v\frac{\sqrt{\sum_gC_g^2}}{C_T},\qquad
\Delta b=\log_2\frac{C_T}{\sqrt{\sum_gC_g^2}}.
\]

For equal Cg and zero bus load this is +0.5 log2 K bits, or +1.5 bits for K=8. If both ADCs use the same uniform voltage range, preserving the baseline RMS quantization noise generally requires two extra integer bits. Preserving the voltage-derived unit charge LSB rather than total RMS error requires three extra bits. These are different accuracy specifications.

The heterogeneous example requires +1.468 bits without load and +1.799 bits with the 948-fF bus. If the separate baseline instead passively samples every Cg onto a fresh 948-fF ADC, reconstructing each charge uses Cg+948 fF. Its proper denominator is then sqrt[Σ(Cg+948 fF)²], and the pooled penalty is only 1.159× RMS or +0.213 bits. All acquisition/reset noise terms must also follow that changed boundary.

Deterministic quantization and converter INL need not be independent or uniform. Error correlations can make summing individually quantized results better or worse. Directly replay held-out physical code errors through both schedules; do not use Δ²/12 where the input alphabet or code pattern invalidates it.

### Why averaging does not evade a thermal energy floor

Assume a converter family obeys E=a/σv², with the same a for pooled and independent paths and no fixed invocation cost. Minimize digital conversion energy at allowed total charge-error variance εQ²:

\[
\min_{\sigma_g^2}\sum_g\frac a{\sigma_g^2}
\quad\text{subject to}\quad
\sum_g C_g^2\sigma_g^2\le\epsilon_Q^2.
\]

Lagrange minimization gives σg² proportional to 1/Cg and

\[
E_{d,\min}=\frac{a(\sum_gC_g)^2}{\epsilon_Q^2}.
\]

The unloaded pooled converter needs σp²=εQ²/(ΣCg)², giving EXACTLY the same energy. Unequal-C gains against an identical-bit independent baseline vanish against this optimized control. A new positive bus load makes the pooled floor larger unless it also improves a or replaces a burden paid by the baseline. The general unequal-family result is Ed,min=(ΣCg sqrt(ag))²/εQ².

The root's acquisition-aware numerical control additionally obtains `[CT/(ΣCg+KCb)]²=0.168639` when BOTH architectures pay a fixed passive Cb on each serviced result and only the subsequent ADC voltage-decision noise obeys the independently scalable E=a/σ² model. This ratio is algebraically correct for that component model. It is not a complete thermal-energy gain: at fixed Cb the sampled bus has its own noise floor, which must be subtracted from the permitted error before optimizing residual ADC decision noise. If attaining smaller σ requires changing Cb, then loading, gain and the optimization coefficients change as well. Avoiding seven bus resets or acquisition buffers can be a real saving, but those benefits must be counted as such.

**VERIFIED within the explicit E∝σ−2 model.** This is not a universal lower bound on every ADC architecture. A practical pooled design can still save fixed comparator resets, acquisition, reference switching, control, digital addition and routing. With E=E0+a/σ² and equal C/no bus, it saves (K−1)E0 at equal error. In a technology-limited E∝2^b regime, the +1.5-bit cost is approximately sqrt(8), leaving up to sqrt(8) improvement in conversion energy. Neither extrapolation is a measured 12-bit Sky130 converter.

Current 0.5-V-span quantization RMS is 140.95 µV at 10 bits and 35.24 µV at 12 bits. The single-sample kT/C criterion at 300.15 K requires 208.6 fF and 3.337 pF, respectively, before additional noise allowances. The existing 948-fF acquisition capacitance is not an established 12-bit-noise solution. Bigger original holders help only if their charge is actually part of the measured mode during the complete conversion.

## 5. Five deliberately different mechanism branches

### A. Temporal delta computation with periodic refresh

For a fixed linear layer, y(t)=y(t−1)+W[x(t)−x(t−1)] is exact. With activation correlation ρ and equal second moment, centered stationary increments have variance 2(1−ρ)σx². Delta range improves only when correlation is sufficiently positive; truly event-sparse execution additionally requires many changes below an explicitly budgeted threshold.

If the state update adds independent error ηt, then after L updates Var(error)=Var(error0)+Lση². A repeated offset μ contributes L²μ². Refresh every L steps costs Efull/L per step plus state read/write and event detection. A fixed weight error ΔW telescopes as ΔW[x(t)−x(0)] when the same physical weights implement every update; it must not be modeled as independent random error per increment. Thresholded or nonlinear updates need their own error recurrence.

**FAILED on the available local fixture as a simple energy/range proposal.** For nine existing FFN-down integer activation vectors, mean squared adjacent delta divided by mean squared activation is 1.75083; exact delta zeros are 5.542%, versus 13.817% activation zeros. This tiny development trace does not establish a universal transformer conclusion, but it contradicts assuming adjacent tokens are a favorable delta workload. Physical scaling can also change between tokens. The general approach predates this work: [Delta Networks, ICML 2017](https://proceedings.mlr.press/v70/neil17a.html) exploits thresholded temporal activation changes and evaluates recurrent sensor workloads. Its savings cannot be transferred to autoregressive language tokens without a trace measurement.

Useful retained mechanism: sparse recomputation can target known slowly changing internal state or recurrent sensor inputs; distinguish it from exact next-token hidden states.

### B. Sum/difference and common-mode coding

With z+=s+/C+ and z−=s−/C−, a differential readout can suppress a shared disturbance only after both transfers are correctly normalized. For matched branches and individual noise variance σ² with correlation ρ, differencing produces 2σ²(1−ρ). Independent thermal noise incurs the expected two-branch cost; only the correlated part cancels.

A relative transfer imbalance ε converts common-mode voltage into approximately εVcm. At Vcm=0.9 V, holding that error below half an LSB of the 0.5-V/10-bit ADC requires |ε|<271 ppm if the full common mode leaks through. If a circuit cancels static common mode structurally, use the actual residual disturbance amplitude in this bound instead. Constant offset trim does not correct data-dependent common-mode leakage.

For an orthonormal transformation H, iid noise covariance σ²I remains σ²I under H: merely rotating a dot product cannot improve total noise energy. Unnormalized ±1 transforms can raise signal amplitude but also demand more headroom and switching energy. A transform helps when it isolates a known correlated error mode, reduces clipping or exploits task-specific insensitivity.

**SPECULATIVE:** build a second, complementary physical holder only if measured correlated reference/injection noise exceeds its independent reset and read noise cost. Existing single-ended holders do not supply a free complementary node. The relevant new primary preprint [Charge-CIM / You Only Charge Once 2.0](https://arxiv.org/abs/2608.11116) already describes shared charge compute/conversion and combining paired partial sums during differential quantization. Generic differential pre-ADC merging is not novel.

### C. Null feedback instead of voltage acquisition

A distributed charge-null readout can leave original charges connected and search for Qref(D)=Σqg, ideally avoiding copied voltage holders and a standing OTA. With residual v=(Qsignal−Qref)/CT, a comparator's input-referred voltage noise still becomes CT times as much charge uncertainty. A larger bus suppresses kickback voltage while suppressing the desired residue by the same factor. The balanced quantity and the decision charge step must be tracked together.

For an active current-nulling implementation, finite loop gain changes the array terminal voltage and hence its current; an idealized node obeys C dv/dt=Ierror−gfeedback v with pole −gfeedback/C only while the assumed feedback sign and device regions hold. Added OTA poles, common-mode loops and switching delays can destabilize the full implementation. Active charge transfer can avoid passive division but requires sufficient gain, settling, slew and reference-charge accuracy.

**SPECULATIVE as a new integrated implementation; known mechanism.** [Mythic US10389375B1](https://patents.google.com/patent/US10389375B1/en) discloses comparator-guided mixed-signal nulling and shared readout. [MCRA, TVLSI 2026, primary university record](https://keio.elsevierpure.com/en/publications/mcra-multicolumn-residue-accumulation-analog-compute-in-memory-ar/) places coarse ADCs per column and processes their residues with a multi-input time-domain incremental sigma-delta fine ADC. Its reported 66.2-dB post-layout result is relevant prior art, not a transferable measured energy for this design. The full MCRA circuit paper was not obtained in this branch.

### D. Low-rank or constant-center cancellation

Write W=R+uvᵀ, so Wx=Rx+u(vᵀx). The side path requires nin+nout MACs for rank one, or r(nin+nout) for rank r, instead of nin×nout. It helps only if residual R permits enough smaller capacitors, fewer bits or less clipping to pay for that path. If the residual is still dense at the same precision, operation count rises.

A particularly cheap exact integer special case is per-output centering: wji=rji+cj, yj=Σi rjixi+cjΣi xi. An integer median minimizes Σi|wji−cj|, useful when programmed capacitance tracks that norm. On the existing complete FFN-down Wq, all 576 output medians are zero. The optimal integer-centering L1 ratio is exactly 1.0, so this simple area mechanism is **FAILED on that fixture**. It remains useful for a distribution with a substantial center offset. Static layout capacitance can also remain allocated even when the programmed active-capacitance norm shrinks.

Precision-aware centering is prior art: [RAELLA, ISCA 2023, author-hosted paper](https://people.csail.mit.edu/emer/media/papers/2023.06.isca.raella.pdf) uses Center+Offset encoding and adaptive slicing to reduce analog output ranges. A fixed low-rank correction can compensate some systematic weight error; it cannot predict fresh independent output thermal noise. No high-rank or full-model correction quality was tested here.

### E. Exponent-aware physical scaling and error allocation

Metadata-only rescaling is insufficient if it does not change programmed charge, reference range or physical output gain. The local independent-scale obstacle does admit one exact hybrid for power-of-two scale products. If agwg=a0·2^eg, choose

\[
B_g=B_0-e_g,\qquad B_0\ge\max_g(e_g+b_g),
\]

where bg is the number of actual magnitude bits in group g. Extra zero high-order radix steps implement the required halving after the useful planes. Then

\[
q_g=\frac{\kappa S_g}{2^{B_g}}
=\frac{\kappa2^{e_g}S_g}{2^{B_0}},
\]

and original-cap joining yields the correctly weighted sum after one global reconstruction. Common B is a sufficient condition for equal scales, not a necessary condition for every scale-aware implementation.

**VERIFIED, ideal arithmetic:** 10,000 random eight-group integer vectors, exponent eg from −3 through +3, unequal Cg from 300 through 1,000 fF and 948-fF bus load recovered the target with maximum 3.64e−12 integer-equivalent floating-point error. **SPECULATIVE circuit and quality:** extra decay steps add switching, reset noise and delay, and lower-exponent contributions are strongly attenuated. Choosing power-of-two rather than arbitrary scales can degrade A8 quality. Group weight exponents need the same alignment; per-output scale differences can require per-column scheduling.

This combination must be compared to [Rojkov et al., GR-MAC, arXiv2602.08081v2](https://arxiv.org/html/2602.08081v2). That primary paper describes capacitive exponent weighting, variable total capacitance and digital normalization, effective contributor count, parasitic compensation, and a 22-nm post-layout/mismatch example. It uses a coupling network rather than this proposed zero-step timing construction. General gain ranging, exponent-weighted accumulation and effective contributor count are already known. Novelty of this narrower implementation remains unresolved.

Noise allocation can be added independently: minimize ΣEj(εj) subject to a held-out task-sensitivity budget Σhj εj²≤εtask², then charge hardware that actually realizes unequal references or conversion effort. [NORA, DATE 2025, IBM primary record](https://research.ibm.com/publications/nora-noise-optimized-rescaling-of-llms-on-analog-compute-in-memory-accelerators) is relevant evidence that analog input/output errors and weight errors have different LLM sensitivity. Its published rescaling result does not validate the current compiler or supply this sensitivity matrix.

## 6. Area, timing, PVT and the experiments that could kill the survivor

At the nominal [Sky130 MIM area density](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html#mim-capacitors) of 2 fF/µm², 3.676 pF has 1,838 µm² of capacitor area term and 948 fF has 474 µm². These exclude edge capacitance, spacing, shields, switches, wires and storage circuitry. Reusing original holders does not add their area a second time; duplicating them for ping-pong does. The [2-µm minimum MIM dimension](https://skywater-pdk.readthedocs.io/en/main/rules/assumptions.html#minimum-critical-dimensions) implies about 8 fF of area capacitance for a minimum square. The present 4-fF ideal unit therefore still needs a legal extracted MOM or other implementation.

In an ideal two-node join, settling a full-range step to half an LSB requires approximately (b+1)ln2 time constants: 7.62τ at ten bits and 9.01τ at twelve. A star of eight unequal holders has multiple eigenmodes, and a physically long bus adds distributed RC. Replacing every load with one lumped capacitor can hide the slow modes. Current TG resistance varies with input, PVT and switching state.

Use the following predeclared falsifiers before any complete-chip gain is accepted:

1. **Scale proof:** enumerate mapped block scale products and B values; the charge coefficient of every term must match the mathematical model. Include unequal-scale vectors with the same raw sum as a failing control.
2. **Charge provenance:** verify that physical original holders, with their actual matched array loads, are joined. Confirm no ideal voltage source, Python decision or omitted sample capacitor restores lost gain.
3. **Worst-case cancellation:** compare equal final sums created by very different local charges, including opposite full-range partials, all-zero input, signed endpoints and each activation plane separately. Calibration must be fitted before these inputs.
4. **Connected ADC:** the actual split CDAC must sample/compare the bus, execute physical decisions and drive references. A 948-fF dummy only checks one load condition and cannot validate conversion, kickback or differential decision errors.
5. **Noise and aperture:** propagate reset covariance, reference noise and switch noise through actual clocked sensitivity; test both retaining and opening join switches. A deterministic transient is insufficient.
6. **Mismatch and PVT:** vary Cacc/Carray ratio independently, physical capacitor code, switch geometry, supply, SS/FF/SF/FS and temperature. Repeat fresh input histories after frozen calibration; do not hide failed seeds.
7. **Equal-quality control:** evaluate complete-model output quality with real physical error distributions. The current failed low-bit and read-noise experiments are evidence that the budget is tight.
8. **Complete costs:** measure aggregate supply/reference/gate delivery, extra scale alignment, physical coefficient storage, wire loading and shared-ADC selection. Match resident weights and ADC count to the Mythic comparison, then separately establish area and precision equality.

## 7. Novelty ledger and retained partial discoveries

| Mechanism | Nearest identified prior art | Current claim |
| --- | --- | --- |
| Join analog row partials in a SAR capacitor fabric | [MANTIS, JSSC, accepted 2024](https://arxiv.org/html/2411.07946v1), especially §§III-B2/3 | Known general mechanism; original-cap weight-normalization identity still merits a specific comparison |
| Charge MAC, SAR capacitor reuse and pipelined accumulation | [CF-SAR, TVLSI 2026](https://doi.org/10.1109/TVLSI.2026.3689104) | Abstract confirms substantial overlap; no circuit-level novelty conclusion from abstract alone |
| Charge MAC with differential paired-partial readout | Charge-CIM preprint cited above | Generic proposal already disclosed |
| Exponent-weighted capacitance and output normalization | GR-MAC v2 cited above; [compute-format patent US20240020093A1](https://patents.google.com/patent/US20240020093A1/en) | Known principle; zero-step scheduling variant remains unverified and unproven novel |
| Coarse conversion plus shared residue processing | MCRA cited above | Known architecture family |
| Adaptive range/precision and center correction | Gonugondla, RAELLA and NORA cited above | Existing baselines, not new discoveries |
| Temporal differences | Delta Networks cited above | Known; unfavorable local trace |

MANTIS specifically stores sixteen row partials on equal CDAC sections, shorts them for averaging, and then converts. Its SC amplifiers and signal precision differ from the proposed unbiased original-holder path. Its post-layout discussion also reports capacitive coupling substantially worsening one averaging fixture. Thus it is both a novelty collision and a concrete warning that pre-layout charge algebra can survive while extracted accuracy fails. This is a comparison of mechanisms, not transfer of its performance to Sky130.

The useful retained results are: (i) original-cap charge, rather than equal-voltage copies, eliminates weight-dependent denominator error in an ideal matched radix; (ii) group-scale compatibility is an information condition; (iii) conserved thermal charge does not imply noiseless local voltage; (iv) optimally allocated independent ADCs match the pooled thermal-energy floor under the stated model; (v) zero high-order radix steps can implement power-of-two group scale alignment, at a measurable noise/time cost. The first and fifth survive ideal numerical falsification, while the other three prevent false victories. None establishes first invention.

## 8. Independent audit of the root's new experiments

The root subsequently implemented [the numerical analysis](../../../../scripts/compiler/metrics/imc_native_charge_analysis.py) and [the physical pooling fixture](../../../../analog/testbenches/tb_imc_native_charge_pool.py). This critic inspected their source and the saved artifacts. The numerical source correctly propagates `qnext=rho(q+plane_charge)`, proves exact charge reconstruction, rejects equal-voltage copying and incompatible scales, includes a correlated-noise conservation control, and distinguishes the original seven compiled tensors' scalar activation scale from the later dynamic-block paths. The fixed-load optimized-energy caveat is recorded in §4 above.

The physical fixture has eight groups of FOUR fixed coefficients, ideal capacitors, actual Sky130 row/reset/share/join TGs and a 948-fF capacitive load. It has no ADC, stored programmable weight memory, reference generator, stochastic noise or extracted layout. Each point fits gain/offset using six calibration words and tests eight seeded random words plus zero and signed extremes. The `before`, `joined` and `isolated` observations each fit their own gain/offset; their error improvements are after separate calibration, not an uncalibrated error cancellation measurement. The deterministic screen is RMS<0.25 and maximum<1 in native integer MAC units.

Artifacts inspected on 2026-09-10:

| Fixture | Joined RMS / maximum MAC error | Decision |
| --- | ---: | --- |
| B1, TT27, 40-ns join | 0.02132 / 0.06129 | VERIFIED only for this deterministic fixture |
| B1, SS85, 40-ns join | 0.38801 / 1.04650 | FAILED |
| B1, SS85, 100-ns join | 0.01719 / 0.05116 | VERIFIED only for this deterministic fixture |
| B8, TT27, dedicated join | 6.25056 / 17.67121 | FAILED |
| B8, TT27, added off-TG array load | 5.97356 / 16.18482 | FAILED |
| B8, TT27, reuse holder-reset TG for joining | 4.70358 / 12.67296 | FAILED |

The saved filenames use `build/sim/imc_native_pool_b{bits}_{corner}_{temperature}_j{join}_w0p42_tr0p0_dt0p1`, with `.json` and optional `_balanced`/`_reuse` suffixes. They preserve the weights, exact words, per-observation recovered values and source/netlist hashes. Passing a lengthened B1 SS aperture supports finite settling as a relevant limitation for that point. It cannot explain the B8 error away: the original B8 fixture already has 7.79750-MAC RMS error in its charge-reconstructed pre-join observation. Adding matching off-TG loading or reusing the reset TG is not a sufficient repair in these results.

### Reset-switch reuse: useful failed recombination

The root's minimal topology variant routes each holder's existing reset TG to a shared bus held at VCM during computation. After computing, it releases the bus reset and reasserts holder reset so those same TGs combine charge instead of erasing it. This removes dedicated joining switches from the holders. It is a concrete circuit simplification, but its B8 point above still fails.

Independent objections remain quantitative: a single finite-resistance bus-reset TG must initially charge all holders and Cb; the common bus can move under off-state coupling during computation; bus-reset release injects charge shortly before joining; and reopening holders can sample differential noise modes. At the tested 40-ns point, even separately calibrated isolated error is 3.00340 RMS / 8.51979 maximum MAC. Any future repair should inspect the bus voltage throughout the radix computation and the initial reset history, not just its final mean.

### Early pooling before significance accumulation

The circuit branch independently recombined charge joining with the radix-mismatch objection: combine each plane's LOCAL ARRAY charges into one electrically common retained D, and choose D=ΣAg. Then

\[
h_{b+1}=\frac{Dh_b+\kappa\sum_gp_{g,b}}{D+\sum_gA_g}.
\]

Only the aggregate ratio must equal one. If physical holder components have errors eg, then eaggregate=ΣAg eg/ΣAg and its variance is aᵀΣe a. The branch's [conditional mismatch experiment](IMC_DISCOVERY_CIRCUITS.md) reports 0.1% independent ratio draws reducing median held-out error from 5.6143 to 0.2476 MAC under one final affine calibration; fully correlated draws produce identical early/late errors. This critic checked the recurrence, calibration and covariance logic. The improvement exceeds sqrt(K) because eight distinct group gain errors become one calibratable common gain, not because thermal noise disappears.

This is **STRONGLY SUPPORTED as a conditional mismatch mechanism**, with implementation and novelty still **SPECULATIVE**. The comparison is fair between two analog-pooling schemes constrained to one final calibration. Eight separate ADC outputs permit eight individual digital gain corrections and must be allowed those in the broader baseline. Independent equal-variance ratio draws are not Sky130 mismatch characterization; capacitor area scaling, gradients and correlated coefficient errors change the distribution. The bus also now participates in every plane, so its capacitance must enter the matching condition and its slow interconnect modes must settle repeatedly. No transistor result for this early-pooling circuit was available to this critic at this checkpoint.

## 9. Reproduction details

The numerical calculations in this branch ran with `/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3` and NumPy, without modifying source files. Synthetic charge-sum seed: 271828. Synthetic exponent-sum seed: 314159. Equations and distributions are given above so the checks do not depend on an unstated simulator configuration.

Local negative-control input hashes:

```text
226d36b6df43763ba0ff31e0c750f8996b2f6c5e3dac13325dffc74dc27cad07  scripts/compiler/out/acts/ffn_down.npz
1124c01d8197c5898e81935fb091cf5b81edf8b6aa9370383abc725efc42841a  scripts/compiler/out/programming/ffn_down.npz
```

The delta screen reads `xq` with shape 9×1536 and computes `mean(diff(xq,axis=0)**2)/mean(xq**2)` in float64. The centering screen reads `Wq` with shape 576×1536 and computes integer medians over its input dimension. Neither is a representative full-model benchmark. No synthesized area, extracted layout, new SPICE result, transient-noise result, accepted-token metric or verified novelty claim is produced by this independent branch.
