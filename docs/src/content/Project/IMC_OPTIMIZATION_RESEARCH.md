# AnalogIOC: research directions for useful tokens/s and tokens/J

**Continued sizing and architecture work:** [circuit convergence](IMC_CIRCUIT_CONVERGENCE.md) is the current entry point. It sets 100-TOPS/W minimum and 250-TOPS/W stretch research targets, records actual 128-row charge accumulation and its limitations, and connects full-model readout tests to the energy budget. The following report preserves the initial research/audit findings.

Research date: 2026-09-07. Main recommendation: **build a resident heterogeneous accelerator whose compiler allocates analog precision, digital correction and shared conversion by measured model sensitivity.** Preserve sky130 as a circuit-validation platform. Make a separate production storage/process decision before extrapolating it into a 7B/70B chip.

There are promising improvements in the supplied notes and newer papers. The strongest are noise-aware range adaptation, selective digital precision, legal accumulation before conversion, better activation encoding, and resident KV with explicit refresh scheduling. The investigation also found errors that invalidate several existing speedup claims. Correcting those errors matters because they change which improvements are worth building.

This report is an evidence-backed design recommendation, accompanied by reproducible experiments. It is not a claim of a globally optimal fabricated chip or a demonstrated win over Etched/Mythic. Maximum throughput and minimum energy generally give different designs; infinite area, as allowed in the old contract, does not define a finite maximum throughput. The appropriate result is a Pareto frontier at a fixed package, power, quality and workload.

**New results from this investigation:** protecting 0.833% of weight-MVM MAC work reduced simulated full-depth KL error by approximately 5–8× on the two tested passages; channel interleaving improved one FFN-down tile-quantization result by 6.85 dB with unchanged data-column ADC count; calibrated passive charge averaging worked after sufficient settling, but an unchanged ADC did not preserve the comparison's noise budget. These are respectively model-noise, ideal-converter mapping and transistor-switch experiments—not measured token-rate gains. The model forward was also accelerated 1.83× with checked numerical parity.

## Scope and evidence

Read the repository instructions and authoritative [contract](CONTRACT.md), the manuscript under the user's [Analog Compute research](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/>), relevant note families, circuit generators, compiler, golden model and later falsification studies. The paper is present under **Analog Design/Analog Compute/paper/**; the Digital Design/paper path in AGENTS.md does not exist. Its LaTeX sources were available, including architecture, circuits, laws, evaluation and review decision.

The detailed research is split into [circuits](IMC_CIRCUIT_RESEARCH.md), [architecture](IMC_ARCHITECTURE_RESEARCH.md) and [competitor evidence](IMC_COMPETITOR_RESEARCH.md). Those reports trace the notes to primary papers and distinguish transistor simulation, statistical modeling, silicon measurement and projection. Neither a note derived from a paper nor a paper's abstract makes a result applicable to a different circuit, precision or power boundary automatically.

Working target: 7–8B dense interactive decode, batch one, with context/batch sensitivity and a separate 70B throughput comparison. Physical arithmetic uses the existing 400-mm² die / 70% usable-area assumption. These are study assumptions, not a foundry commitment. Keep exact attention, a consistent tokenizer/checkpoint and a declared quality budget for the primary comparison; MoE, sparse attention and retrained models are separately labeled alternatives.

## 1. The strongest research opportunities

| Rank | Opportunity | Connection to the user's notes and current hardware | Expected benefit and decisive test |
|---|---|---|---|
| 1 | Sensitivity-directed precision plus analog-aware range adaptation | 27k2/27k5/27l11; current full-depth results concentrate error in a small subset of FFN work | Avoid making every array and ADC expensive. Test held-out model quality with physical error replay, then charge the protected work's energy/latency |
| 2 | Shared conversion after one valid mathematical reduction | 27h1/27l3; current post-window converter has substantial settling/static cost | Eliminate actual ADC operations. Compare calibrated passive averaging, active shared integration and digital sums at the same effective precision |
| 3 | Channel mapping that controls partial-sum distributions | 27l7/27k2; compiler already divides each matrix into 16-row chunks | Concentrate difficult channels into a small protected set or distribute load where beneficial. Test fixed calibration-derived permutations against random and unchanged mappings |
| 4 | Replace repeated unary activation work where conversion permits | 27h5/27h9/27g1; current PWM repeats switched-cap transfers | Compare bit-serial, segmented radix and existing PWM including all converters, shift/add, clocks and reference energy |
| 5 | Resident KV with selective precision and scheduled maintenance | 27l2/27l10/27i6; current gain-cell study is tiny and refresh accounting is inconsistent | Remove critical-path KV fetches only after capacity, write/refresh ports and quality close. Keep sensitive/recent values in a protected local path |
| 6 | Dense resident storage and exclusive-expert 3D sharing | 27l1/27l6/27l8; present capacitor tile area cannot hold a large model economically | Share expensive peripheral circuits among infrequently simultaneous resident experts; account for routing skew, idle leakage and wakeup |

### Noise-aware adaptation can be more valuable than buying more ADC bits

**NORA**, DATE 2025, directly studies the asymmetry seen in AnalogIOC's later tests: output/input perturbations can hurt LLM quality much more than weight perturbations. Its rescaling moves error burden toward weights. The authors report less than 1% accuracy loss for simulated OPT-6.7B versus roughly 30% without rescaling. This is a strong reason to optimize ranges jointly with the analog transfer function; it is not a demonstrated AnalogIOC speedup. Only the primary abstract was retrieved, so a local experiment must be described as inspired by NORA until the complete method is obtained. [NORA primary publication page](https://research.ibm.com/publications/nora-noise-optimized-rescaling-of-llms-on-analog-compute-in-memory-accelerators).

The exact algebraic starting point is `y = xW = (x S^-1)(S W)` for a nonsingular diagonal input-channel scale S. What matters physically is where clipping, DAC/ADC range, fixed weight mismatch and output noise occur around that equality. Simply rescaling the final digital answer does not improve the analog SNR. SmoothQuant already exists in the compiler; the new experiment must optimize the real analog noise/range tradeoff, rather than claim the same smoothing twice.

**Analog Foundation Models**, NeurIPS 2025, provides a stronger adaptation route: hardware-aware distillation with static input/output quantization and device noise. Its tested LLMs retain quality comparable to W4A8 digital baselines. That study keeps attention/KV digital FP16, uses a hardware noise model and substantial adaptation data; it does not validate AnalogIOC's analog KV or rank-1 sidecar. Reuse the methodology with measured capacitor/ADC residuals, and price training separately from deployed inference. [Paper](https://arxiv.org/abs/2505.09663), [author implementation](https://github.com/IBM/analog-foundation-models).

**QuaRot/SpinQuant** provide exact full-precision rotation identities that improve digital low-bit quantization. **InfoQuant**, May 2026 preprint, further targets the activation distribution seen by the quantizer. These are useful candidates for heavy-tailed FFN activations, but none automatically fixes analog mismatch. Online rotations cost operations; unstructured orthogonal transforms need not be cheap, and rotations cannot be pushed through arbitrary nonlinearities. Compare static-range quality and total hardware cost after folding only mathematically legal transformations into the weights. [QuaRot](https://arxiv.org/abs/2404.00456), [SpinQuant](https://arxiv.org/abs/2405.16406), [InfoQuant](https://arxiv.org/abs/2605.26175).

There is measured hardware precedent for sensitivity-directed heterogeneous compute: the 2025 TSMC/NTHU processor partitions work across analog memristor CIM, SRAM CIM and small digital units. Its CNN results support the architecture choice, not a transferable LLM TOPS/W multiplier. [Primary paper](https://www.nature.com/articles/s41586-025-08639-2).

### Conversion sharing is promising, but the operation being shared must be specified

IBM demonstrated neighboring tiles feeding shared integration capacitors, including up to 2,048 input rows, with calibration under the combined loading. This supports an active shared-integrator candidate. AnalogIOC's capacitor implementation needs its own charge-transfer, saturation and settling validation. [IBM circuit methods](https://www.nature.com/articles/s41586-023-06337-5).

The four configurations have different economics:

| Configuration | ADC operations for K partial vectors | Cost that must remain |
|---|---:|---|
| Digitize each, then digital sum | K per output column | All K conversions, wider digital accumulator, transport |
| Sequential charge accumulation on one feedback capacitor | 1, if all partials belong to one output | K integrations, hold error, headroom, real access to different weight blocks |
| Calibrated passive average, then one ADC | 1 | Gain normalization, bus/switch mismatch, lower signal scale at ADC, ADC/reference precision |
| K dependent layer transformations | Architecture-dependent | Nonlinearities, changing dimensions, state and accumulated error; cannot be replaced by a sum |

For independent partials with variance `sigma_s²`, a passive bus with `c=C_bus/C_int` has signal variance `K sigma_s²/(K+c)²`. Known attenuation can be normalized. Fixed ADC noise then becomes increasingly significant as K grows. The fresh charge-average experiment tests this distinction; a smaller bus voltage alone is not proof that the operation is unusable.

### Improve the converter and input encoding together

Binary coarse search can shorten the high-code worst case compared with unary counting; the existing NULLSEEK analysis predicts a conditional approximately 1.6× timing benefit. It is not yet a transistor-verified gain. Early termination already makes many unary conversions short, and tile completion follows the slowest active column, including the checksum. Compare complete done-time distributions, not average packet count or comparator clock alone.

The actual PWM driver performs repeated charge transfers. Two input nibbles do not mean two physical compute cycles. A digital shift/add path or analog charge-domain radix accumulator may reduce the repeated work, but extra ADCs can erase the benefit. The experiment should enumerate bits/window, settling time, residue retention, driver energy and conversion count at identical output error. Duty gating is already implemented; [GATING_VALUE.md](../../../../scripts/compiler/metrics/GATING_VALUE.md) makes a wholesale new “83% saving” claim untenable.

## 2. Fresh experiments and reproducibility

Three bounded experiments accompany this investigation:

- [Selective precision](IMC_PRECISION_EXPERIMENT.md): full 30-layer SmolLM2 forward on two held-out note passages; protected tensor, equal-work sham and all-FFN-down controls; two noise levels, seeds and weight modes. This tests whether the previous sensitivity finding generalizes.
- [Charge averaging](IMC_CHARGE_AVERAGE_EXPERIMENT.md): calibrated transistor-switch sharing plus explicit sampling/ADC noise analysis. This reopens the old passive-bus rejection using a meaningful accuracy criterion.
- [Channel mapping](IMC_MAPPING_EXPERIMENT.md): fixed calibration-derived permutations and converter-range policies on real compiler artifacts. This tests the SAGE-inspired mapping opportunity without claiming a reproduction of an unavailable full method.

The [arithmetic audit](../../../../scripts/compiler/metrics/imc_research_audit.py) reproduces the capacity, refresh and energy calculations below using only the standard library. Its PASS checks validate equations and units, not the supplied physical assumptions.

[Iteration speed results](IMC_ITERATION_SPEED.md) documents the implemented model and SPICE-output improvements, parity tests and quick/full commands. SPICE parsing is 1.95× faster on the representative trace and its serialized size is 49.2% smaller; these are host-iteration gains, not changes to chip performance.

```sh
python3 scripts/compiler/metrics/imc_research_audit.py
python3 scripts/compiler/metrics/imc_precision_experiment.py  # numpy + local GGUF
```

Experiment artifacts are under `build/research/` or `build/sim/`; they are not committed. Operational circuit generators, compiler numerics and the golden model remain unchanged. The full-depth research simulator uses faster equivalent attention arithmetic and top-five selection; the SPICE runners use compact waveform output with a backward-compatible parser. Cached Nix Python/NumPy and ngspice were used because constructing a new shell could not access the Nix daemon in the sandbox. The flow templates were not modified.

## 3. Conditions for compute-bound operation

Compute-bound operation is a requirement to demonstrate for each workload. Analog arithmetic removes some data movement, but resident weights alone do not prove the full inference path is compute-bound.

Let `M` be useful MACs/token, `C_eff` sustained MAC/s, `D_j` bytes/token crossing link j, `BW_j` its sustained bandwidth, and `R_j` the service rate of each nonlinear, conversion or memory-maintenance stage. An optimistic overlapped rate obeys:

`R <= min(C_eff/M, min_j BW_j/D_j, min_j R_j)`.

Operations that cannot overlap add latency instead. For external refresh from a shadow store, the necessary link condition is `R*D_decode + C_shadow/T_refresh + traffic_other < BW_sustained`. Capacity is an independent requirement. Evaluate worst-context, temperature and tail latency, not only an average.

For a resident layer pipeline with stage latencies `t_l`, a single autoregressive session has `R_session <= 1/sum(t_l)`. With enough independent requests, aggregate throughput can approach `1/max(II_l)`. A lower bound on concurrency needed to fill that pipeline is approximately `ceil(sum(t_l)/max(II_l))`. Extra idle stages still contribute leakage/retention power. This is why large model size alone cannot establish 100% array utilization.

### The current N4 capacity model does not support its single-die throughput interpretation

The shipped projection uses 256 useful weights/tile, 0.006 mm²/tile, and 280 mm² usable area. Therefore one die holds **11,946,496 weights**, requiring at least **586 dies for 7B** or **5,860 for 70B** if all weights reside in that architecture. These are consequences of that specific model, not estimates for an optimized production chip.

Alternatively, full 7B INT4 weight reload at its quoted 17,915 tokens/s would require **62.7 TB/s at batch one**, before programming and protocol overhead. At batch 64 the ideal amortized requirement is approximately 0.98 TB/s. A netlist regenerated with different capacitor values is not a physical weight-loading mechanism.

The manuscript instead assumes a 512×256-weight tile. Holding usable area at the same 280 mm² produces:

| Paper tile area, all projection-grade | Minimum 2D dies for 7B resident weights |
|---|---:|
| 0.03 mm² | 6 |
| 0.04 mm² | 8 |
| 0.10 mm² | 20 |
| 0.50 mm² | 96 |

Do not mix this large-tile capacity with a 16-row tile's measured settling and mismatch. Do not credit a resistive BEOL crosspoint density to a SRAM-controlled switched-capacitor tile without the storage bits and switches. 3D integration changes capacity, heat and communication; it is not an independent energy multiplier.

### KV refresh can recreate a bandwidth bottleneck

For a generic 32-layer model with 8 KV heads, 128 dimensions/head and 4-bit K/V:

`C_KV = 2 * layers * H_KV * d_head * context * batch * bits/8`.

At context 4,096 this is **128 MiB per session**, or **8 GiB for 64 sessions**. Rewriting that full shadow at a 1.743-ms cadence requires approximately **4.93 TB/s** of aggregate shadow-read traffic, regardless of whether decode MACs occur in analog. Distributed local shadows can avoid off-chip traffic, but their area, power and ports must be included.

The local KV study extrapolates tau≈27 ms from a short nominal simulation. Under an exponential full-scale decay model, one 4-bit LSB permits `T_refresh = -tau*ln(1-1/16) ≈ 1.743 ms`, not tau/2=13.5 ms. At half an LSB it is 0.857 ms. Real read disturb and PVT consume part of that budget.

There is also a separate energy-unit mistake: 524,288 cells × 7.5 fJ is **3.93 nJ**, not 3.9 µJ. The cell-write-only lower bound is about **2.26 µW/head** at 1.743 ms. However, 2,048 column writes × 150 ns consume **17.6% write duty** even assuming K/V and row subbanks operate in parallel; half-LSB refresh raises it to 35.8%. DAC, shadow, transport and controller energy are additional. The old retention GO cannot be inferred from either its power or timing arithmetic.

GQA increases reuse of a KV head across query heads: digital attention intensity is not universally one operation/byte. Sparse/selected attention can reduce work but must satisfy the same declared quality target. Oxide-semiconductor gain cells are a valuable production research track, not a sky130 device substitution.

## 4. What it would mean to beat Mythic and Sohu

The [competitor report](IMC_COMPETITOR_RESEARCH.md) verifies current primary disclosures. Etched reports shipping its first rack in August 2026; current architecture details differ from the 2024 Sohu announcement. There is no substantiated Sohu tokens/J measurement in the reviewed primary sources. Mythic's current M1 advertises 25 TOPS at roughly 3–4 W; Vanguard's 120 TOPS/W belongs to a 2027 roadmap. None is a matched AnalogIOC generated-token benchmark.

At two operations/MAC, `E_MAC = 2000/eta fJ` for eta TOPS/W. Assuming only 7B dense-weight MACs/token, with all other costs zero:

| Operation-efficiency target | MAC energy | Idealized 7B weight-only tokens/J |
|---|---:|---:|
| 8 TOPS/W | 250 fJ | 571 |
| 25 TOPS / 3 W | 240 fJ | 595 |
| 120 TOPS/W roadmap threshold | 16.7 fJ | 8,571 |
| Historical 200 TOPS/W comparison point | 10 fJ | 14,286 |
| Paper's 3.2-fJ/MAC assumption | 3.2 fJ | 44,643 |

These are scale/energy targets, not predictions of competitor token rates. Precision, quality and power boundaries differ. At 32k context the illustrative GQA configuration above adds approximately 8.59B attention MACs/token, already exceeding the simplistic 7B weight term.

One specific paper-to-repository transcription error matters: `sec_eval.tex` writes **256/K*=64 conversions**, which means **K*=4**, while METRICS.md calls that design K*=64. Also, 3.2 fJ/MAC corresponds to approximately 625 TOPS/W at its modeled boundary; it is not simultaneously the paper's derated 100–200 TOPS/W system number. Keep those energy boundaries separate.

The current baseline 2,190.53 pJ per 256-MAC pass is **8,557 fJ/MAC including estimated digital**, or **0.234 TOPS/W equivalent** on the slowed mini simulation schedule. It gives approximately **41,713 tokens/J for the small measured subset**, but only **16.7 weight-only tokens/J when that same per-pass physics is scaled to 7B**. These are different workloads. Even eliminating all conversion energy while keeping its 820.83-pJ integration and 24.6-pJ digital cost only reaches approximately 43.3 such tokens/J: at most 2.59×. A 3.2-fJ production target requires a different complete physical implementation, not bookkeeping alone.

For each comparison, record model/checkpoint/tokenizer, generated output length, prefill/decode separation, context, concurrency, quality, all die counts and power boundary. The historical 500k/8 Sohu figure is not batch-one latency, and 7B versus 70B cannot establish a speed win.

## 5. Recommended implementation sequence

1. **Freeze the quality and accounting harness.** Use a true tokenizer, multiple held-out corpora and a deployed W4A8 baseline. Replay fixed physical weight errors, code-dependent converter residuals, temporal noise and KV error separately and jointly. Record unique useful outputs and actual ADC calls; reject infeasible points instead of clamping K to one and reporting success.
2. **Exploit selective precision and mapping.** The new studies identify concrete candidate work to protect and channel maps to try. Implement per-tensor/row-group precision, static ranges and an exact digital fallback in the scripts/compiler/golden path before choosing higher-power circuits everywhere. Evaluate NORA-inspired scaling and hardware-aware adaptation on top of this harness.
3. **Build one physical weight bank and one shared-conversion macro.** Use substrate2, actual capacitor geometry/control storage, extracted coupling and matched switch layout. Characterize legal row reductions at K=1/2/4 with one ADC, including negative/mixed-sign and worst-case headroom traffic. Preserve the independently digitized fallback.
4. **Choose the loaded converter/input pair.** Compare unary+SAR, binary coarse+SAR, and direct SAR under real column loading; compare PWM versus bit/radix encoding. Measure every supply/reference/clock source, startup, mean/p99 completion and PVT. Keep only nondominated energy/latency/quality points.
5. **Close resident execution.** Commit to a realizable storage substrate and package. Schedule weight layers, KV, refresh, residual operations, expert routing and interconnect with finite resources. Report batch-one latency and saturated throughput separately; include idle energy and model programming amortization.
6. **Demonstrate the competitive result.** Run the same full model, quality and workload against a tuned digital reference and any obtainable competitor benchmark. Only then assert a token-rate or energy win. Silicon is required to turn the final circuit projection into a measured chip result.

Do not prioritize another scalar gain servo, uniform extra ADC bits, blind repeat-read averaging, automatic deep cascades, a universal LVT substitution, or speculative decoding as guaranteed wins. Fixed mismatch does not average away; adaptation cannot repair saturation; low Vt does not guarantee better gm/ID at the chosen operating point; and speculative verification pays extra work on an already compute-bound engine. For speculation, measure accepted tokens per round A and require both `(T_draft+T_verify)/A < T_baseline` and `(E_draft+E_verify)/A < E_baseline`. [Original speculative decoding method](https://arxiv.org/abs/2211.17192).

The best supported direction is therefore selective, resident, heterogeneous analog compute with verified conversion sharing. The remaining uncertainty is which physical configuration satisfies the quality and capacity gates at the lowest energy and highest sustainable token rate. The experiments and bounds here make that choice testable.
