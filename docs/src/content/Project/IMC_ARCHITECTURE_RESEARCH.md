# AnalogIOC architecture research: useful tokens per second and per joule

Research date: 2026-09-07. Scope: architecture, compiler mapping, quality, residency, attention, interconnect and scheduling. This is a research recommendation with a standalone mapping experiment, not a validated chip-performance claim. This sub-review does not modify the chip or deployment compiler.

Read first: [AGENTS.md](../../../../AGENTS.md), [CONTRACT.md](CONTRACT.md). Local theory: `~/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/`, especially notes 27l1–27l11 and `paper/sec_arch.tex`, `sec_attention.tex`, `sec_system.tex`. The `Digital Design/paper/` path named in AGENTS.md does not exist in this workspace; the Analog Compute paper source does.

### Corpus coverage and what came from it

This architecture sub-review screened the Analog Compute note filenames and read the relevant 27l architecture/LLM family, with focused re-reads of 27l1–3, 27l6–10 and their limitations, plus 27k2 and 27k5. It read the local paper's architecture, attention and system sections, then traced their claims into the existing implementation and later falsification reports. Circuit/device families and broader paper verification are handled in the companion research; this file does not claim a full reading of every 27/28 note or every referenced PDF.

| Local note | Design insight retained | What this review adds |
|---|---|---|
| 27l1 weight stationarity; 27l7 tiling | Fit the stored model and price wasted/peripheral area | Count actual configured weights and separate resident stage utilization from reload throughput |
| 27l3 analog dataflow | Conversion boundaries trade error against service/energy | Separate passive averaging, physical accumulation and digital sums; count actual ADCs |
| 27l5 wrapper; 27l11 near-memory digital | Digital reductions and traffic belong in the system budget | Local merge trees, per-cut traffic budgets and dependency-aware scheduling |
| 27l6 MoE; 27l8 3D | Conditional access fits capacity-rich memory | Place co-selected experts on separate peripheral banks instead of requiring simultaneous tier summation |
| 27l9 analog CAM | Approximate selection must be followed by scoring | Defer universal top-k gains until realistic dimensions, recall and spill traffic pass |
| 27k2 mixed precision | Spend accurate digital work where it matters | Tensor/output sensitivity allocation and explicit digital residual cost |
| 27k5 pretrained analog adaptation | Train the complete input/weight/output operator | NORA-style noise-aware scale fitting; AFM/LoRA; SAGE-inspired physical grouping experiment |

One mathematical correction in 27l3 matters when applying it: `sigma_total=sigma_stage*sqrt(K)` at unchanged signal amplitude requires **+10 log10(K) dB** stage margin, not the note's +5 log10(K). K=4 costs 6 dB under those assumptions. For parallel partial sums, signal covariance changes too; neither number should be imported without the signal/noise model.

## Recommendation

The strongest candidate is a **resident weight engine with a small digital correction path and a compiler that allocates precision and physical service capacity per tensor**. Reduce converter demand only after the actual full-model error is acceptable. Use independent sessions to fill the resident layer pipeline, and keep reductions near their producers. For a future MoE product, store different experts in separately selectable banks or tiers that share peripheral circuits; this offers a capacity route without requiring all tiers to sum charge simultaneously.

No existing result establishes an optimal chip, a compute-bound full system, or superiority to Sohu/Mythic. Unlimited area in the mini contract makes raw throughput unbounded through replication. A meaningful optimum is a Pareto frontier at fixed model quality, context, batch, latency limit, die/package area and power. The user’s compute-bound requirement is a hard admission condition for points on that frontier.

| Priority | Proposal | Why it can improve the objectives | Decisive gate |
|---|---|---|---|
| 0 | Replace aggregate pass arithmetic with physical mapping and a dependency/resource schedule | Prevents memory traffic, idle stages and duplicate conversion savings from masquerading as throughput | Weight and KV capacity fit; link, programming, refresh and reduction service meet the target rate |
| 1 | Per-tensor noise allocation; NORA-style rescaling; selective digital outputs/residuals; hardware-aware adaptation | Avoids making every converter expensive because a small set of outputs is sensitive | Full-depth quality with actual quantization and held-out physical residuals |
| 2 | Resident weight banks with converter sharing chosen from real service demand | Preserves residency while reducing peripheral area and idle power | Extracted area, programming implementation, worst-layer service time |
| 3 | Local online-softmax reductions and GQA-aware placement | Avoids shipping the score vector or repeatedly fetching the KV cache | Full attention dependency schedule; shared K/V read-port contention included |
| 4 | MoE banks/tiers assigned using routing conflicts, with independent gating | Makes total capacity cheap relative to active compute | All experts resident; router/load imbalance and fabric limits priced |
| 5 | Structured sparsity only where the physical tile schedule shrinks | Can remove real work, writes or converter activations | Compiler demonstrates eliminated physical services, with quality unchanged |
| Research | True pre-ADC charge accumulation; stacked charge accumulation | Potentially removes conversions | Actual topology, capacitor/noise budget and transistor-level summation validation |

The ordering is by present evidence and dependency, not by multiplying published speedup factors.

## 1. What the current evidence permits

### Three different weight engines are being discussed

The paper’s `sec_arch.tex` describes a 512×256 eNVM engine, with two 2-bit slices and differential devices. The mini contract describes a 16×16 charge-domain capacitor engine. The implemented weight_tile.py specializes capacitor participation at **netlist generation time**; its `bank()` emits only capacitors selected by the supplied weight code. Runtime programmable weight configuration storage and its write path are not implemented there.

These implementations cannot inherit one another’s density, programming energy, endurance, leakage or wire constraints. A production choice between configured capacitors, SRAM-backed charge-domain CIM and eNVM must include the corresponding physical storage and peripheral circuits.

An earlier claim that charge redistribution destroys the *weight* is incorrect for the present capacitor-code representation. It moves signal charge, while the weight is the capacitor configuration. That charge can be re-excited on the next operation. This differs from a weight encoded as an isolated analog storage-node voltage. Non-volatility is useful for boot/standby, but is not required for runtime weight stationarity if configuration survives powered operation. Conversely, generation-time constants do not demonstrate runtime reprogrammability.

### Earlier quality-based speedups were falsified

[DEPTH_BUDGET.md](../../../../scripts/compiler/metrics/DEPTH_BUDGET.md) supersedes the claimed spare accuracy budget in [ARCH_THROUGHPUT.md](../../../../scripts/compiler/metrics/ARCH_THROUGHPUT.md). In its 30-block SmolLM2 experiment, 28 dB additive error produced PPL ×1.649; 43.33 dB produced KL 0.00875 and **PPL ×1.0141**, not a measured universal +1% PPL threshold. It uses one 256-token passage and a greedy tokenizer, and perturbs weight-MVM outputs without the complete deployed analog error path. Its important finding is concentrated sensitivity: `ffn_down` accounts for 89.7% of the operator-class KL; layer 11 is unusually sensitive. Excluding the hottest layer gives 6.6 dB relief in that experiment, but still does not validate the current held-out converter CSNR.

Do not reduce every converter to 5/6 bits, or endorse K>1, based on the earlier one-block ±8 LSB result. Do not substitute the 43.3 dB figure for a universal hardware requirement either. Re-measure the target with deployed numerics and the physical error distribution.

### Parallel digital summation is not converter amortization

tb_supertile.py calls the real converter for every partial in `measure_partials()`, then adds the resulting K codes digitally. Its step 3 nevertheless equates that schedule to the one-conversion cascade law. For M output columns:

\[
n_{ADC,\,digital\ sum}=KM,\qquad n_{ADC,\,true\ preADC\ sum}=M.
\]

Parallelism can reduce elapsed time by buying K conversion paths; it does not divide conversion energy by K. Digital summation needs sufficient accumulator width, at least `b_partial + ceil(log2(K))` for worst-case integer sums. Summing INT8 partials is exact only relative to those already rounded/clipped partials.

There is also a paper-transcription error: `paper/sec_eval.tex` line 49 writes `256/K*=64`, which implies **K*=4**. [METRICS.md](METRICS.md) line 54 instead attributes K*=64 conversion amortization to that example. The paper's reported 64 is the amortized conversion count in that equation, not the accumulation depth. Neither value validates physical conversion sharing in the mini circuit.

chip_supertile.py tests passive capacitor sharing with ideal switches and capacitors. It demonstrates

\[
\Delta V_{bus}=\frac{\sum_k\Delta V_k}{K+C_{bus}/C_{int}},
\]

an average with known attenuation. It does not prove every useful analog sum impossible. Scaling the reference can account for deterministic attenuation, with a noise/range/settling cost that must be measured. An active charge-transfer summing integrator is another untested option. The synthetic recurrence in `series_output()` assumes previously stored charge receives a multiplicative gain each step; it does not establish that a real accumulator has that recurrence.

## 2. Make “compute-bound” an enforceable property

Let R be **accepted output tokens/s**, W_j the work/token at resource j, and C_j its sustainable service capacity. Let Q be transferred bytes/token. A necessary throughput bound is

\[
R\le\min_j C_j/W_j,
\qquad
R Q+\beta_{refresh}+\beta_{maintenance}\le\beta_{available}.
\]

Include converter events, row excitation, digital accumulation, softmax, normalization, routers, links, weight programming and KV writes as resources. Shared resources add demands; independent resources can overlap only when dependencies allow. The memory inequality must have operating margin, including burst and tail-latency behavior, before the point is called compute-bound.

At a fixed quality gate,

\[
E_{token}=E_{active}+\frac{P_{idle}+P_{refresh}+P_{fabric}}{R}
 +\frac{E_{model\ programming}+E_{maintenance}}{N_{served}},
\qquad tok/J=1/E_{token}.
\]

Specify which power terms are already inside `E_active` to avoid double counting. Charge rejected speculative tokens, retries, recalibration and corrections to the accepted-token denominator.

### Capacity comes before the roofline

The shipped N4 projection uses 46,666 physical mini tiles, each holding 256 weights: **11,946,496 logical weights/die**, under that assumed area model. Resident 7B therefore requires at least **586 dies**; 70B requires at least **5,860 dies**, before other storage, mapping waste or redundancy. This is arithmetic on the shipped mini-tile model, not a predicted practical package. The paper’s much larger arrays and different device density are a separate proposal and cannot silently replace it.

At the documented 7B compute-only rate of 17,915 tok/s, reloading approximately 7B INT4 weights every token needs **62.7 TB/s** of delivered weight data at batch one, plus actual programming service. A 1 TB/s interface would cap that example near 286 tok/s before programming and KV costs. Batching B tokens per weight load reduces the weight traffic/token by B, but does not make charge-domain arithmetic itself B times cheaper. This is why batching is useful for an undersized reusable engine even though an already saturated analog MVM resource has linear batch cost. Source of assumptions: [ARCH_THROUGHPUT.md](../../../../scripts/compiler/metrics/ARCH_THROUGHPUT.md), [GATING_VALUE.md](../../../../scripts/compiler/metrics/GATING_VALUE.md).

A complete mapped count should use actual matrices and embedding behavior, rather than treating every parameter as one MAC/token. Require a tile table of matrix slice, storage representation, bit slices, replicas, padding, converter assignment, write destination and layer ownership. A capacity claim must count stored expert parameters, not only active parameters.

### Residency does not imply full utilization

For a resident pipeline with stage latency t_j, initiation interval II_j and one sequence’s recurrent token dependency:

\[
L_{token}\ge\sum_{j\in critical\ path}t_j,
\quad R_{one\ sequence}\le1/L_{token},
\quad R_{aggregate}\le1/\max_j II_j.
\]

Independent sessions needed to sustain the aggregate limit are at least approximately `L_token / max(II_j)`, with additional capacity for scheduling variability. One sequence cannot inject its next exact autoregressive token before the preceding token has reached the output decision. A large total parameter count does not prove all resident tiles are busy: tiles belonging to later layers may wait while earlier layers execute.

The exact-1× pipelining claims in ARCH_THROUGHPUT and “no idle tiles” conclusion in GATING_VALUE are identities **within a divisible-work, perfect-occupancy model**, not proof about a mapped resident transformer. Benchmark batch-one inter-token latency separately from steady-state multi-session throughput. Map/replicate bottleneck stages according to their service demand, then charge added weight capacity and idle leakage.

Speculative decoding is not the first efficiency lever for a saturated, compute-bound analog machine. It costs verification work on rejected tokens. It is nevertheless not universally impossible: otherwise idle resident stages or separate draft resources can improve one-session latency. Test `E_verify + E_draft + E_reject < n_accepted E_baseline` and the actual scheduled latency, rather than importing GPU gains or declaring a topology-independent ban.

## 3. Highest-value algorithm/architecture change: target the sensitive errors

The local depth result makes a strong case for **heterogeneous precision and range allocation**, not a stronger global converter specification.

1. Replay held-out physical residuals conditional on input range, weight pattern, output code, column and temperature on the full quantized model. Preserve deterministic per-device error across tokens; vary read noise per use. Include saturation. Use a correct tokenizer and held-out corpus/task evaluations. A single pooled Gaussian SNR cannot represent every error shape.
2. Compare per-output/group ranges, static tensor rescaling, outlier-channel bypass and rotations before adding ADC bits. For `y=Wx`, `W'=WS` and `x'=S^-1 x` preserve the exact product for invertible diagonal S. The quantized/noisy products differ; optimize S with the measured noise and range constraints. Multiplying a clipped output afterward cannot recover lost information.
3. Give only the sensitive outputs a digital or higher-precision route. If fraction f of MACs uses energy e_d and the rest e_a, `E/MAC=(1-f)e_a+f e_d+overhead`; measure f and the extra service time. Do not assume that one sensitive tensor means one easily isolated channel. A low-rank residual costs `r(n_in+n_out)` MACs versus `n_in*n_out` dense MACs, but rank r must be learned and validated.
4. Adapt the model to the calibrated residual errors. Only after quality passes should the compiler spend remaining margin on reduced conversion time, fewer conversions or smaller capacitors.

Relevant verified primary work:

- **NORA, DATE 2025** explicitly optimizes rescaling to move error burden away from sensitive inputs/outputs toward more tolerant weights. Its author-reported simulated OPT-6.7B example reduces roughly 30% untreated accuracy loss to below 1%. This is especially relevant to the local observation that fixed weight error and additive output error with equal SNR are not equally harmful. It is not a AnalogIOC gain measurement. [IBM primary publication](https://research.ibm.com/publications/nora-noise-optimized-rescaling-of-llms-on-analog-compute-in-memory-accelerators).
- **QuaRot / SpinQuant** use exact full-precision model invariances to reduce outliers, with random or learned rotations. Evaluate both ordinary quantization and analog output-range effects. Some transforms can be folded into stored weights; others require runtime Hadamard/rotation work and must be charged. Arbitrary rotations do not commute through SiLU or RoPE: use the architecture-valid transformations. Digital W4A4KV4 success does not itself establish analog accuracy. [QuaRot paper](https://arxiv.org/abs/2404.00456), [SpinQuant paper](https://arxiv.org/abs/2405.16406).
- **Analog Foundation Models, NeurIPS 2025** adapts pretrained LLMs using hardware-aware training and teacher-generated data. The authors report models including Phi-3-mini and Llama-3.2-1B retaining performance comparable to W4A8 baselines under their analog noise and range assumptions. Use the method with AnalogIOC’s residual model rather than importing its noise setting. [Paper](https://arxiv.org/abs/2505.09663), [author code](https://github.com/IBM/analog-foundation-models).
- **AHWA-LoRA, 2026** offers a cheaper adaptation path with fixed analog base weights and external low-rank adapters; its reported digital/analog pipeline overhead is scenario-specific. Start with a digital adapter as the correctness reference, then evaluate whether an analog sidecar saves total energy at the measured precision. [IBM primary publication](https://research.ibm.com/publications/efficient-transformer-adaptation-for-analog-in-memory-computing-using-low-rank-adapters).

These are complementary experiments, not independent speed multipliers. A successful rescaling or adaptation buys an error budget once.

### NORA-style rescaling on the actual capacitor engine: proposed experiment

The compiler already runs SmoothQuant with alpha=0.5 in `compile_matrix()`. Merely renaming that operation does not implement NORA. Its present objective mainly balances input/weight ranges; a noise-aware search must score **output ADC range, measured code-dependent INL, per-pattern charge-transfer error and end-to-end sensitivity** as well. The author-hosted NORA abstract and paper identity were verified; full text was not obtained through available tools. The following equations are an independently derived experiment, not a claim to reproduce NORA's exact optimizer. Primary links: [IBM abstract](https://research.ibm.com/publications/nora-noise-optimized-rescaling-of-llms-on-analog-compute-in-memory-accelerators), [author publication page](https://yayuehou.github.io/publication/2025-09-22-DATE-NORA), [IEEE DOI](https://doi.org/10.23919/DATE64628.2025.10993217).

For positive diagonal input scaling S and output analog gain A:

\[
x'=S^{-1}x,\quad W'=AWS,\quad y=A^{-1}(W'x').
\]

If the **physical** pre-ADC result is `W'x'+epsilon_o`, digital unscaling produces `y+ A^-1 epsilon_o`. This can reduce output-referred additive error only if physical signal gain/range utilization actually increases while avoiding clipping. It does not eliminate input or weight error; those transform to `A^-1 DeltaW S^-1 x` and `WS epsilon_x`. The achievable compromise depends on the target noise covariance and range limits.

For this implementation the distinction is load-bearing: a uniform `W→aW`, `x→x/a` followed by fresh per-output INT4 and per-tensor INT8 normalization leaves Wq, xq, D and physical capacitor/PWM stimuli unchanged. Weight scale grows by a, input scale shrinks by a, and their product is unchanged. **This is a required null control.** Per-output row rescaling alone also cancels through per-output weight normalization. Such metadata-only rescaling cannot improve physical CSNR. Input-channel-specific S can change quantized weights and stimuli, and therefore can have a real effect.

Available implementation knobs are static smoothing factors, capacitor codes, PWM input scaling and affine digital output scales. Per-column converter reference/gain hooks exist in the testbench; these must be realizable as physical trims if used in a product. Changing packet charge, integrator capacitance or excitation amplitude to implement A is a circuit change with energy, load, saturation and calibration costs, not a free compiler multiply.

Bounded experiment plan:

1. Fit all decisions on an independent calibration split. Compare current alpha=0.5 with a small alpha grid and a direct positive-diagonal search scored on converter-inclusive error. Keep full quantization and clipping in the forward operator; do not optimize Gaussian error alone.
2. Run scalar and per-output normalization null controls, plus the exact unquantized identity. Report the actual differences in Wq/xq, physical charge histogram, D, clipped fraction and coarse evaluations.
3. Reuse measured converter residuals only where the new operating points overlap calibration support. For changed capacitor patterns and ranges, collect new held-out SPICE residuals. A measured output error is not automatically iid or independent of inputs.
4. Evaluate each candidate at full depth and fixed accepted quality. Include reordering/scaling work, calibrated range switches and any physical A cost. A claimed noise benefit must survive against existing SmoothQuant and an equal-cost precision allocation control.

### SAGE-inspired grouping: a new result in this review

The SAGE authors describe training-free input-channel grouping to reduce output kurtosis and improve analog mapping, with mixed-precision tile support. [Primary author description](https://zhenyu001225.github.io/), [ICCAD 2025 DOI](https://doi.org/10.1109/ICCAD66269.2025.11240907). Unlike arbitrary whole-output scaling, a fixed permutation changes which terms meet at a finite 16-row analog tile while preserving `WP^T Px = Wx` exactly.

The new [mapping experiment](IMC_MAPPING_EXPERIMENT.md) tests 224 golden conditions using the existing real layer-0 INT4 weights/INT8 inputs, six token positions for mapping/range fitting and three for evaluation. The original upstream quantization was already fitted on the nine-token compiler stream, so this is a holdout of the **new placement decision**, not independent full-model deployment validation. Exact integer/float MVM invariants and matched data-column ADC/pass counts passed. Checksum conversions are excluded; deployment must regenerate checksum programming and include the permutation network's area, delay and energy.

Two candidates deserve follow-up. With the existing per-tensor D policy and nibble conversion, saliency **interleaving** improves FFN-down converter SQNR from 44.28 to 51.13 dB at unchanged D=1 and conversion count. Clustering instead harms it. With the merged path and proposed independent row-tile D, **clustering** improves FFN-down from 16.51 to 24.31 dB at unchanged conversion count, but needs D up to 14 and increases mean coarse evaluations from 1.519 to 1.773. Thus grouping must match range granularity; neither result is a measured token or energy gain, nor a reproduction of the full SAGE method. These concrete effects show why physical grouping is a more useful experiment than applying a universal SNR multiplier.

## 4. Reduce locally, then move activations

Use the exact online-softmax merge. Each bank returns `(m,l,o)`, where `m=max(s)`, `l=sum exp(s-m)` and `o=sum exp(s-m)v`. Merge two banks with `m=max(m_a,m_b)`, `alpha=exp(m_a-m)`, `beta=exp(m_b-m)`:

\[
l=\alpha l_a+\beta l_b,\qquad o=\alpha o_a+\beta o_b.
\]

The output is `o/l`. This preserves exact dense-attention mathematics; finite arithmetic and analog errors still need validation. It removes the need to export all T scores and intermediate attention probabilities. Keep the merge close to bank groups and make only reduced `(m,l,o)` cross die boundaries. The principle is independently established by the IO-aware exact attention literature. [FlashAttention](https://arxiv.org/abs/2205.14135).

The two array-pass description in `sec_attention.tex` is only valid when the required rows, token banks, periphery and reduction capacity operate in parallel. Context beyond one bank adds more banks and merging work. Do not hide attention under the *same token’s* FFN: the FFN consumes the attention output. Overlap is available across independent tokens/sessions or appropriately independent suboperations, and must be shown in the schedule.

GQA reduces stored KV head count relative to query heads. Honor that in placement instead of storing a full cache per query head. Shared KV is not automatically shared compute: different query heads require different products and may contend for bank read paths. Quantify the replication-versus-time-serialization trade. Changing an existing MHA model to GQA is a model adaptation with quality cost, not a transparent compiler rewrite. [GQA primary paper](https://arxiv.org/abs/2305.13245).

At every fabric cut report bits/token, fanout, hops, sustained bandwidth, tail latency and pJ/bit. A multicast tree can distribute x once per branch rather than one packet per tile; local partial-sum trees can avoid shipping every partial. This is an architecture proposal, not a free-energy assumption. Require `R × bits/token < available bit/s` on each cut, including refresh and maintenance where they share the cut.

## 5. MoE and 3D: exploit conditional access before simultaneous summation

The clean MoE accounting is

\[
P_{active}=P_{shared}+kP_{expert},\qquad
P_{stored}=P_{shared}+EP_{expert}.
\]

The E/k ratio applies to the expert portion versus evaluating all E experts, not the whole transformer, nor a speedup over a GPU that already evaluates only k. For a matched model, low active weight count does not reduce the capacity needed to keep all experts resident. Swapping an expert into a gain-cell bank on every route may recreate the memory/programming wall.

Prefer a future bank/tier organization in which rarely co-selected experts share periphery. The IBM/Micron 3D-MoE work explicitly studies a one-tier-at-a-time constraint; conditional activation can mitigate it without assuming simultaneous charge accumulation across tiers. Its accelerator benefits are simulated. [Paper](https://www.nature.com/articles/s43588-024-00753-x), [author short paper](https://openreview.net/attachment?id=J23gohVY9s&name=pdf), [author simulator](https://github.com/IBM/3D-CiM-LLM-Inference-Simulator).

A concrete mapping objective is to minimize co-selection conflicts between experts sharing a converter bank, subject to capacity and link locality. For routing probabilities p_e and expert service times t_e, a shared bank g must satisfy

\[
R\sum_{e\in g}p_e t_e<1,
\]

before burst margins. For independent uniform routing, the expected number of distinct experts active across B tokens is `E[1-(1-k/E)^B]`: E=64,k=2 gives 2 experts at B=1, 40.8 at B=32, 62.9 at B=128. This measures touched experts, not balanced utilization. Popular experts can be the throughput bottleneck even when almost every expert is touched.

Use independent expert bias/rail domains where the stored state survives gating. [GATING_VALUE.md](../../../../scripts/compiler/metrics/GATING_VALUE.md) already shows why active-column rail gating can disturb held charge; expert-level gating at a reset boundary is a different operating case. Charge wake/recalibration energy and always-on storage leakage.

[VERTICAL_3D.md](VERTICAL_3D.md) proposes a distinct, riskier route: many layers contributing to the same analog sum. Its automatic `+0.5 log2(L)` converter-bit penalty assumes fixed absolute output LSB; fixed relative output accuracy with rescaled range is a different requirement. Its resistive IR constraint also cannot simply be applied to an ideal switched-capacitor implementation. Neither observation establishes a free stacking gain: real summing capacitance, bus impedance, noise covariance, selectors and thermal gradients still decide the result. Keep separate ledgers for stacked capacity with shared converters, simultaneous charge sum, and independent active-die stacking.

## 6. Sparsity and other alleged multipliers

Deja Vu establishes that contextual sparsity can be predicted and exploited in particular LLM implementations. For AnalogIOC, require the predictor/placement to remove **tile services**, not merely scalar MACs from an abstract count. Column gating can save conversion energy even when other columns prevent latency reduction; row gating saves excitation but does not remove a nonempty dot-product conversion. Larger tiles make random all-zero tile skips less likely. Offline neuron permutations and grouped sparsity can improve physical alignment, with scale metadata and both FFN matrices permuted consistently. [Deja Vu primary paper](https://proceedings.mlr.press/v202/liu23am.html).

The ARCH_THROUGHPUT claim that gathering active weights is “free” because weights are already reloaded is too strong: irregular gather, packing, indexing, destination writes and predictor misses all consume resources. Conversely, immutable resident arrays can still gate structured expert/tile/column groups; useful sparsity does not require arbitrary runtime weight gathering. Rotations that spread outliers can also destroy sparsity, so these techniques must be evaluated jointly.

Converter replication, shared-converter banking, reduced ADC precision, larger arrays, analog accumulation and stacked tiers compete for area, noise margin and service capacity. Their reported gains do not multiply. Speculative tokens, switching to a different MoE checkpoint, a shorter attention window or approximate retrieval change the workload/quality boundary unless shown otherwise.

## 7. Concrete experiment order and deliverables

1. **Accounting falsifier:** generate one mapped-workload ledger and event trace for the current SmolLM2 case plus a declared 7B and 70B workload. Report stored/active parameters, ADC events, writes, SRAM/DRAM/link bytes, stage busy time and accepted outputs. Reject unsupported capacity and conversion-amortization points rather than extrapolating them.
2. **Quality allocation sweep:** use full-model deployed quantization plus held-out converter residual replay. Compare existing mapping, NORA-like scales, group/output scales, supported rotations, selective digital bypass and hardware-aware adaptation. Produce quality versus total energy/latency, with a proper tokenizer and multiple prompts/tasks. Do not infer quality from top-1 agreement alone.
3. **Physical macro comparison:** lay out a representative configured-capacitor macro, including storage/configuration, converter and row routing; compare converter sharing against parallel converters using actual area and service rates. This resolves the present contradictory area models before spending area on speed.
4. **Resident pipeline simulation:** place the selected macros, allocate copies to bottleneck layers, include fabric and refresh queues, and sweep sessions until service-rate or latency bounds become active. Report batch-one latency and aggregate tok/s separately.
5. **Only then** evaluate true pre-ADC accumulation, MoE bank/tier sharing and other device/process changes against the accepted baseline.

A candidate succeeds only if it improves accepted tok/s or tok/J at the same declared model quality and workload while satisfying capacity, memory service, physical implementation and timing constraints. A circuit simulation is labeled simulated; compiler work counts are derived; hypothetical node, stack and system results remain projected until validated at their stated boundary.
