# System evidence and campaign acceptance contract

2026-09-10. Independent workload/compiler/system audit for the ten-hour research
campaign. This is an evidence map and experiment contract, not a chip result.

**The current archive contains no accepted noisy, full-depth hardware format.**
The strongest deterministic control is frozen smoothed W8, dynamic A9 in
256-input blocks, with a modeled 11-bit converter. Both deterministic cases
pass the existing joint quality gate, but only three of four corresponding
50-µV noisy cases pass. Reducing weight precision to W4–W7 has not passed that
gate. The next architectural experiment must preserve this distinction.

**Conversion service, legal scale combination, and resident weight density are
the largest unresolved system levers.** At equal historical Mythic weight and
ADC counts, the current fixture schedule projects 8.127 TOPS before substantial
missing costs. Eliminating every array-compute nanosecond improves that fixed
mapping only 3.88%. A faster local multiplier or hold pipeline cannot by itself
close the throughput gap.

## Evidence scope and authority

The archive manifest
fingerprints all **100 Markdown/Python files, 29,855 lines**, in `project_docs`,
`scripts/compiler/metrics`, and `golden`, excluding new campaign reports. It records
document headings and Python definitions, plus git HEAD and working-tree state.
This is complete structural coverage, with detailed reading of the
decision-bearing workload, compiler, architecture, memory and benchmark
passages; it is not a claim to have rerun every historical simulation.
The circuit stream owns detailed transistor evidence.

Git HEAD is `7b8d241`; much of the September research is untracked or modified.
Consequently, HEAD alone does not identify the research being audited. The
manifest and individual frozen experiment hashes take precedence over titles,
commit messages or a convenient old headline.

Authority is, in order: the current user's area/delay/power/throughput objective;
[CONTRACT.md](../CONTRACT.md) and [INTERFACES.md](../INTERFACES.md) for implemented
behavior; exact source and frozen artifacts for evidence; then historical
analysis with its assumptions. The contract's old unlimited-area exploration
premise cannot waive the user's current minimal-area objective. This report
does not silently change the production interface.

| Evidence family | What was checked and what survives |
|---|---|
| `CONTRACT`, `INTERFACES`, `THE_COMPILER_STRUCTURE`, `STATUS`, `METRICS`, `RESULTS*` | Numerical rails, actual integration surface, chronological results, and distinction between a small replicated block and a full model |
| `ERROR_IMPACT`, `DEPTH_BUDGET`, `CSNR_HOLDOUT` | Earlier one-block adequacy and one-point calibration claims are superseded by full-depth and held-out failures |
| `IMC_PRECISION_EXPERIMENT`, `IMC_GROUPED_WEIGHTS`, `IMC_RADIX_FULL_MODEL`, `IMC_SMOOTH_RADIX` | Strongest workload evidence; exact format, calibration, reference and per-case gates |
| `IMC_MAPPING_EXPERIMENT`, `IMC_OUTLIER_PLANES`, `IMC_CAPACITOR_SIZING` | Conditional input-range and precise-path opportunities; physical capacitance, metadata and weight-access costs |
| `IMC_SYSTEM_BENCHMARK`, `IMC_ARCHITECTURE_SEARCH`, `IMC_ARCHITECTURE_RESEARCH`, `IMC_CIRCUIT_TARGETS` | Equal-resource schedule, total work, area/residency and service constraints; assumptions remain distinct from measured blocks |
| `ARCH_THROUGHPUT`, `THROUGHPUT_CEILING`, `PDK_PROJECTIONS`, `CONVTIME_SENSITIVITY`, `COARSE_EARLYEXIT`, `GATING_VALUE` | Useful scheduling identities; several historic throughput/energy headlines depend on invalid quality, area or bandwidth assumptions |
| `CASCADE`, `COMPOSED_RESULTS`, `OPTIMIZATION_RESULTS`, `SERVO_EG`, `NEXT_SESSION` | Preserve physical failures and partial repairs; old gains are not multiplicative credits for a new topology |
| `FLASH_LESSONS`, `MYTHIC_ARCH`, `NULLSEEK`, competitor/prior-art reports | Converter sharing and hierarchical reduction matter; patent topology is not a verified product netlist; old nulling rejection is topology-specific |
| `MOE_MAPPING`, `VERTICAL_3D`, `SOHU_VERIFIED` | Routing and capacity are separate paid resources; no Sohu energy victory follows |
| Remaining IMC circuit/storage/noise/log/SAR reports and all metric modules | Structurally indexed and connected to system consequences; physical details cross-reference the independent circuit campaign map |
| `scripts/golden/model.py`, `scripts/golden/test_golden.py` | Bit-true arithmetic reference and tests for the implemented old path, not validation of the newer W8/A9 physical proposal |

Fresh read-only verification in this audit: system-benchmark self-check **PASS**;
eight cached-evidence-adapter adversarial tests **PASS**; all fifteen golden
checks **PASS**. A fresh benchmark run is saved separately in
build/campaign/system_audit.
Its ADC development gate passes; its reserved regression gate fails; memory is
unknown; both TT and SS full-system results remain **NOT VALIDATED**. A successful
Python exit is not a successful circuit or quality gate.

## What is actually implemented and measured by the model

The old golden path uses signed W4 `[-7,7]`, signed A8 `[-127,127]`, per-output
weight scale, shared activation scale, differential capacitor codes, high/low
PWM nibbles, event-rate plus fine-SAR outputs, saturation and digital
recombination. Inference rails include `y12 = sat12(16*chi + clo)`, a 20-bit
accumulator and explicit requantization. The GALS interface has handshake,
synchronization, minimum wait and data-hold requirements. New ideal analog phase
clocks do not account for these services automatically. W8, A9 and larger
partial-sum groupings are research paths; the old golden suite does not certify
their hardware support.

The full-depth research evaluator loads **30 layers, hidden width 576, nine
query heads, three KV heads, head dimension 64, vocabulary 49,152**, directly
confirmed from the current GGUF. It computes FP32 on dequantized Q8_0 weights.
Hooks replace the seven learned projections in every layer, totaling
**106,168,320 MAC/token and 210 MVM calls**. The tied LM head adds
**28,311,552 MAC/token**, or **21.05%** of combined weight work, and remains
unperturbed by those hooks. Unique projection plus tied-embedding weights total
**134,479,872**, before normalization parameters. This already exceeds a
79,691,776-weight resident comparison envelope.

Attention QK/AV, KV retention, RMSNorm, RoPE, SiLU, and the tied output head remain
floating in these hardware-MVM experiments. Evaluation is teacher-forced causal
inference, not generated tokens from a complete chip. The tokenizer is the
repository's greedy tokenizer, not a reproduced official BPE evaluation.
Within-run KL and PPL ratios are useful falsifiers; absolute PPL is not a
published model benchmark. Mean KL and observed next-token log-PPL change are
different statistics and both must pass.

## Quality ledger: the strongest baseline is still conditional

All joint gates below mean **mean KL ≤ 0.01 and observed PPL ratio ≤ 1.01 in
each individual case**, relative to the stated Q8_0 baseline. Averaging a failed
case with an improved case is not acceptance.

| Format / intervention | Frozen evidence | Classification |
|---|---|---|
| Old one-block ±8-LSB tolerance / 28-dB whole-model target | Full 30-layer 28-dB noise gives KL 0.4779 and PPL ratio 1.649; earlier rail/unit mapping was wrong | **FAILED** as a full-depth target |
| Full-depth 43.3-dB independent output-noise proxy | One direct point KL 0.0087, PPL 1.0141; correlated errors are worse | Useful exploratory sensitivity, **not an accepted universal SNR specification** |
| Protect layer 11 FFN-down, 0.833% of projection MACs | At 36.74 dB, mean KL improves 0.04756→0.00808, but mean PPL ratio 1.0150 and individual cases fail | **STRONGLY SUPPORTED** sensitivity mechanism; quality not closed |
| Grouped W4 GPTQ, weight-only | KL 0.3402/0.3254, PPL 1.382/1.389 | **FAILED** |
| Grouped W5/W6/W7 variants | No complete ideal-activation joint pass; W7 weight-only passes only 2/4 and ideal A8 cases fail | **FAILED** for tested formats; no reduced-precision capacity credit |
| Unsmoothed W8, fixed tensor A8 | Ideal short controls KL 1.045/0.623 | **FAILED**; activation granularity matters |
| Smoothed W8, R128/A8, calibration-selected alpha | Exposed passages pass, but new 512-token ideal control has PPL 1.010741; noisy holdout 3/4 | **FAILED** acceptance; retain smoothing mechanism |
| Same frozen weights/scales, R128/A9/ADC10 | Ideal controls pass; ADC-only PPL 1.013562 fails; 100-µV noise 2/4, 50-µV noise 3/4 | **FAILED** full acceptance |
| Same frozen weights/scales, R256/A9/ADC11 | Ideal PPL 1.001630/1.009449; ADC-only 1.001382/1.007413; 50-µV noise 3/4 with last 1.017448 | Strongest deterministic **VERIFIED behavioral controls on these exposed passages**; noisy format **FAILED** |

Source trails: [depth budget](../../../../../scripts/compiler/metrics/DEPTH_BUDGET.md),
[selective protection](../IMC_PRECISION_EXPERIMENT.md),
[grouped weights](../IMC_GROUPED_WEIGHTS.md),
[radix full model](../IMC_RADIX_FULL_MODEL.md),
[smoothed radix](../IMC_SMOOTH_RADIX.md).

The R256 control retains the previously selected per-matrix SmoothQuant scales.
They were selected only on the separate calibration stream, but the later
architecture comparisons reuse exposed evaluation passages. Frozen weights
are not the same as an independently held-out architecture choice.
The physical model includes assumed stage noise `kT/(2*Cg)` and independent
50/100-µV final read noise, finite ADC quantization and clipping. It does not
include measured switched-network covariance, coefficient mismatch, reference
correlation, converter kickback or yield. “50 µV” is an input to that model,
not a measured acceptable ADC specification.

## A scale incompatibility that must be tested before pooling

For block g and output j, the quality path computes

```
y_j = dw_j * sum_g(dx_g * S_gj),
S_gj = sum_i(qx_gi * qw_ij).
```

Here `dx_g` changes per token and input block. The frozen smoothing factor also
differs between matrices, so Q/K/V and gate/up cannot all share one transformed
input without additional work or a new shared-scale calibration experiment.

Native holder charge has the useful invariant `Qg = alpha*Sg` when matched
radix capacitances and common bit count B make `alpha = Cu*Vs/2^B` identical.
Joining original holders correctly cancels unequal holder capacitance. It does
**not** perform the missing `dx_g` multiplication. The saved compiler proof
with one scalar `dx` is exact for that earlier compiler stream; it does not
prove exactness for the strongest new quality format.

Three constructive options survive algebra:

1. Quantize each logical 1,024-row reduction with one activation scale; test
   whether additional A bits recover the accuracy lost relative to R256.
2. Restrict local scales to powers of two and align significance physically by
   scheduling the input planes/retention steps. Charge every extra significance
   cycle and every discarded bit; scale metadata alone cannot change voltage.
3. Apply measured local analog gain/reference weighting before the join, or
   retain digitization and exact digital scaled summation. Price that gain or
   remaining conversion service explicitly.

The actual full-depth shape counts are especially relevant:

| Logical reduction rows | Final W8 slice conversions / token | Reduction from R256 |
|---|---:|---:|
| 128 | 1,797,120 | 0.577× |
| 256 | 1,036,800 | 1× |
| 1,024 | 345,600 | **3×**, not 4× |

These exact counts include short groups for 576-/1,536-wide matrices and two
signed-magnitude W8 slices; they exclude the unperturbed LM head. A9 uses eight
magnitude planes. More input bits may reduce input quantization error but
require more physical planes. Their normalized signal amplitude need not grow,
so ADC improvement cannot be credited just from a larger integer code.

## Equal-resource throughput and noise accounting

The historical M1076 comparison fixes **76×1,024² = 79,691,776 logical W8
weights and 19,456 ADCs**, separate from its physical flash-cell count. The
current 128×8 mapping needs 77,824 small logical macros. Eight ADCs per macro
would consume **32×** the comparison ADC count; holding ADC count instead
without sharing would retain only **1/32** of the weight capacity.

With 256 ADCs per equivalent 1,024×1,024 group, each W4 slice produces 8,192
partial outputs and requires 32 rounds. The fresh cached-fixture calculation is

```
Tgroup = 2*(366 ns + 32*295 ns) = 19.612 us
native TOPS = 2*76*1024^2/Tgroup/1e12 = 8.12684
```

Hiding all array time only reaches **8.44193 TOPS**. Last-partial queue wait is
**9.145 µs**; sixteen partials per final W8 output require at least fifteen
additions plus scales/gains. Immediate compute/convert avoids this queue but
the modeled serial schedule becomes 42.304 µs/group, or 3.768 TOPS. Reaching
16.6 or 25 TOPS at the current round count requires ADC whole cycles below
138.6 or 88.2 ns, before added overhead. These are requirements, not achieved
circuits. A full eight-plane timing extension of the particular mean-six-plane
array cohort lowers the original projection to 8.027 TOPS.

TT/SS fixture-only costs are **32.666/33.520 fJ per useful W8 MAC**. Shared
muxes, retention, reconstruction, physical weight storage, clock/reference
generation, routing, complete noise, and model quality remain absent. The
reserved ADC suite fails, even though its development cohort passed. These
numbers are **SPECULATIVE system projections using real partial-circuit anchors**.
They are not chip efficiency.

The archived M1 headline is 25 TOPS at 3–4 W, arithmetically 240–320 fJ/MAC;
the separate ISSCC 16.6-TOPS / 3.3-full-system-TOPS/W point corresponds to
606.1 fJ/MAC. Do not mix its 5.2 array TOPS/W with full-chip power. The benchmark
links the [Mythic product source](https://www.mythic.ai/m-1),
[Mythic-authored IEEE abstract](https://events.vtools.ieee.org/m/307323), and
[ISSCC press kit](https://www.isscc.org/s/ISSCC2022PressKit.pdf).
Current product/SoTA updates belong to the independent fresh-literature stream.
Equal weight/ADC counts still do not establish equal die area, technology,
model quality or whole-chip power.

Pooling is primarily a service/overhead opportunity, not free thermal precision.
Let individual held voltages be `vg = alpha*Sg/Cg`. Independent ADC voltage
noise yields reconstructed variance

```
variance_separate = sum_g(Cg^2 * sigma_g^2)/alpha^2.
variance_pooled   = Ct^2 * sigma_p^2/alpha^2,
Ct = sum_g(Cg) + Cbus.
```

With equal Cg, negligible Cbus and equal original ADC noise sigma, one pooled
ADC needs `sigma/sqrt(K)`, or approximately `0.5*log2(K)` additional effective
bits at unchanged full scale: one bit for K=4, 1.5 bits for K=8. If converter
energy is `a/sigma^2`, optimizing separate converter precision at fixed
reconstructed variance gives energy proportional to `(sum Cg)^2`; the pooled
converter costs proportional to `Ct^2`. There is no unloaded thermal-energy
advantage under this model, and bus load worsens it. Savings may still come
from fixed conversion/control overhead, area sharing and fewer serialized
operations. Real converter scaling must replace this illustrative law.

Holder/reset noise is a separate covariance problem. A joining resistor
redistributes differential fluctuations but cannot inject unconstrained new
total charge into an isolated network. Do not add independent `kT/C` terms to
every switch event without deriving the conserved modes, reset connection and
sampling sequence. Conversely, do not delete reference, reset or readout noise
because the ideal charge sum is invariant.

## Residency, dynamic work and area cannot remain outside the objective

The present executable benchmark leaves **19 input budgets unknown**, including
weight programming, memory and fabric bandwidth/energy, attention service,
nonlinear work, startup, leakage/maintenance, capacity and model quality. Null
means unknown, not zero. Its memory gate requires physical capacity and at least
1.2× service margin against the chosen compute schedule; a resident assertion
does not manufacture physical weights or SRAM bits.

For its 8B-class shape example there are 7.5036 billion weight MAC/token and
8.0279 billion stored weights; for 70B, 69.4996 and 70.5482 billion respectively.
These are explicit shape examples with untied embedding storage, not the SmolLM
checkpoint. At W8, streaming the 8B active weights at 10,000 token/s requires
**75.0 TB/s** before overhead, or **1.17 TB/s at batch 64** if every loaded
weight is reused across that batch. A 1.2× margin exceeds 1.4 TB/s. Weight
residency removes this traffic only when the model actually fits.

The existing illustrative eight-die envelope, 400 mm²/die at 70% usable area,
provides 2,240 mm². Resident weight footprints must then be below **0.279 µm²
per 8B weight** or **0.03175 µm² per 70B weight**, including relevant storage and
periphery. At an assumed 2-fF/µm² density these areas are only 0.558/0.0635 fF
of capacitor area per weight. The old 8-fF ballast alone violates those budgets
by about 14×/126×. This is a useful inverse budget, not a foundry layout claim.
The previous OTA-topology search tested 810 configurations across 12,960
conditions and found no package-resident pass; its best energy point still used
33.27 µm²/weight. Smaller local current does not fix that storage limit.

At 4k context in the same assumed envelope, a 1-TMAC/s attention engine limits
the 8B/70B resource rates to approximately **931/186 token/s**. Batch 64 with
16-bit KV needs **32/80 GiB**; a 32-GiB allocation fails the latter. Lowering
weight energy from 20 to 8 fJ/MAC (100→250 TOPS/W) therefore does not increase
the modeled throughput under those unchanged attention limits. It reduces only
one energy account. The full serial dependency schedule can be slower still.

The gain-cell feasibility evidence is a useful block result: approximately
27-ms retention time constant, about 4.3-µV disturbance/read, and **1.7-ms
refresh-free four-bit lifetime** under its tested assumptions. It does not
establish long-context KV precision or remove the digital shadow, refresh,
write bandwidth, hot-corner and accumulated-read costs. MoE ideally saves
active-weight work by k/E only when inactive resources are gated; total expert
storage and dispatch/all-to-all service remain. Proposed 3D stacking primarily
buys capacity; an eight-layer charge-summing implementation and its thermal
noise were not demonstrated by this repository.

## Invalidated shortcuts and useful retained mechanisms

| Archived shortcut | Why it failed / relevant history | What remains useful |
|---|---|---|
| One-block ±8-LSB tolerance permits 6.8× faster whole model | Recombined-rail unit error and accumulated depth; `05c7539`, `ac6b3fb` | Layer/tensor-specific precision experiments with full-depth reference |
| One operating point calibrates a column | Circular fit inflated CSNR by 14.2 dB; `5856c12` | Frozen multi-input calibration and reserved pattern/history tests |
| More parallel converters give an 8× chip win | Area and hold storage were omitted; `0e7e7b0` | Count converters and resident weights jointly; share fixed overhead |
| Larger N automatically raises TOPS | Old OTA virtual-ground load scales with N; `9c85e75` | Hierarchical/passive/current-domain alternatives can change the load law |
| Shorter converter solves old precision | Coefficient mismatch dominates; `25c8c18`, `7b8d241` | New OTA-free SAR remains open; the rejection was not universal |
| All ideal analog sums are interchangeable | Copied-voltage caps attenuate unequal Cg; dynamic block scales need physical weighting | Original charge invariant and explicit arithmetic-scale alignment |
| Mean six-bit radix time prices dynamic A8/A9 | Dynamic block max normally fills seven/eight magnitude bits | Runtime bit detection only earns skipped planes actually present |
| W4 local quantization NMSE predicts acceptable model | GPTQ reduced local NMSE strongly but full-depth KL/PPL still failed | Calibration objectives should include model sensitivity and physical error |
| 0.85% digital residual needs 0.85% storage/access hardware | Dynamic support can touch every weight; exact shadow and peak service cost remain | Static protected tensors/support and paid shared precision islands |
| Supply gating removes all OTA static cost | Integrator must remain awake; active held residue suffers supply injection | Gate idle experts; optimize complete operation time/current product |
| Analog latch alone yields a chip speedup | Current equal-resource mapping is 96% ADC service; hold capture itself failed strict accuracy | Overlap can reduce bubbles when receiver occupancy and retention are paid |
| Smaller log multiplier energy implies IMC improvement | Latest restricted scalar uses current operands, long acquisition and 600-fF state; no signed full reduction or ADC removal | Mantissa/exponent/translinear subcircuits merit separate amortization tests |
| Sohu 35–60 token/J is a measured target | No corresponding vendor power measurement in archived audit | Match model, batch, context, latency and complete power when new data exists |

Old N4 tables also disagree on mini-tile area by 5.8× and exclude weight-load
time. Their 1.83×-Sohu headline depends on unsupported cascade precision and
does not survive the full-depth audit. None is a baseline against which to
declare a newly improved chip.

## Ranked architecture mechanisms for this campaign

Rank reflects ability to change the complete frontier, not novelty by itself.
The three leading mechanisms should remain separate until evidence supports
combination.

| Rank | Mechanism | Potential system benefit | Fastest falsifier / limiting cost |
|---:|---|---|---|
| 1 | Scale-aware reduction before conversion: larger legal row group, original-charge pooling, or bounded active/current summation | Cuts actual serialized ADC work and digital partial transport; R256→R1024 is 3× fewer services on this model | Frozen-scale quality test; precision/load/noise penalty; real joined receiver |
| 2 | Shared arithmetic capacitor with dense digital weight storage, independently addressed groups | Changes resident density and converter sharing together; removes per-weight capacitor replication | Drawable SRAM/selector/cap/route area and worst access/service occupancy, not a gate-area proxy |
| 3 | Precision allocation by full-model sensitivity plus a small paid exact path | May permit smaller readout/caps for most work while protecting a few harmful transformations | Original-Q8 joint gate on new data, peak exact-engine service, complete weight access and area |
| 4 | In-place conversion or multi-use array/ADC capacitance | Removes destructive copy attenuation, buffer and duplicated sampling load | Real source impedance, kickback, code-dependent capacitance and frozen corner regression |
| 5 | Combine the two W8 weight slices before conversion | Another 2× service-count opportunity | 16:1 significance, increased range/noise and mismatch; do not grant equal-cost ADC |
| 6 | Current/time-domain maintained sum with duty-cycled direct null readout | May replace passive hold queue and its loading law | Array/static current, IR drop, signed cancellation, comparator precision and resource-normalized service |
| 7 | Block-floating/log mantissa architecture with shared conversion and digital exponents | May separate dynamic range from local multiplication and enable state reuse | V/I/log acquisition, exponent alignment, zero/sign, cancellation, mismatch and actual exp-per-product count |
| 8 | Conditional work removal: static low-rank/outliers, temporal deltas or expert sparsity | Reduces useful scheduled work and traffic when data supports it | Full-depth quality, detection/refresh work, input correlations, extra states and worst-case service |
| 9 | Hold/latch pipelines, extra ADC replicas, local TG/bias optimization | Fills bubbles or reduces one local cost | Weak standalone leverage in present converter-bound mapping; area, retention and all clocks paid |

The cross-pollination worth testing first is **common physical significance from
block floating point + original holder charge summation + in-place converter
sampling**. The proposal is **SPECULATIVE** until all three use the same scale,
capacitance/noise model and schedule. An exact behavioral identity is necessary
but cannot supply the converter's missing precision or physical area.

## Concrete acceptance contract

Before a candidate is promoted, freeze a record containing: model/checkpoint
hash; tokenizer and token slices; weight codes/scales; exact signed formats and
zero handling; input scaling; output scale and saturation; physical row/column
groups; plane/slice/ADC work; precision fallback; corner, mismatch and temporal
noise model; circuit/source hashes; calibration algorithm and data; complete
energy/time boundary; area/storage and service requirements.

1. **Arithmetic:** signed endpoints, zero, cancellation, unequal scales,
   unequal capacitance, ragged groups and exponent alignment pass independent
   identities. Deliberately wrong scale/capacitance controls must fail.
2. **Behavioral quality:** every case independently meets KL ≤0.01 and PPL
   ratio ≤1.01 against original Q8_0. A failing ideal control prevents a noisy
   hardware-format acceptance claim. Development and reserved validation remain
   separate; every failure stays in the result table.
3. **Physical mapping:** a real source→state→receiver path reproduces the
   signed reduction across frozen fresh stimuli and PVT. All acquisition,
   reset/closing, reference, control and final-read work is paid. Numerical
   convergence is checked. Passing deterministic transfer does not pass noise,
   mismatch, layout or yield automatically.
4. **Resource accounting:** match logical weight capacity and converters at
   minimum; add actual storage/selector/routing/clock/reference area before an
   area victory. Count useful native MACs once, not once per bit. Timing includes
   ADC service, queuing, hold lifetime, partial reduction, attention and memory.
5. **Frontier:** compare at the same accepted quality, workload and resource
   envelope. A candidate must improve at least one of area, total joules or
   complete service time without worsening the others; otherwise state the
   explicit tradeoff. Unknown terms keep chip metrics unvalidated. The
   100/250-TOPS/W milestones mean complete 20/8-fJ native-MAC-equivalent costs,
   not merely a low-energy arithmetic cell.

## Proposed test 1: freeze and test scale alignment before circuit pooling

New isolated module proposal: `scripts/compiler/metrics/imc_scale_alignment_campaign.py`.
Do not overwrite existing SmoothQuant, radix or frozen result files. The
predeclared protocol
was written before evaluating any selected corpus slice. It fingerprints the
frozen smoothing NPZ (`71cacf62925d8a0f3d4959bf6c2c15cd26be9a804136126fe534f8d8827b3836`)
and two new Digital Design notes selected solely as the two largest Markdown
files by bytes outside `paper/`:

- `Floating-Point Operators/Floating-Point Exception Handling.md`
- `Network-On-Chip/Dual-Clock Asynchronous FIFO.md`

Use greedy-token slices `[0:512]` for the complete predeclared development
menu. Keep `[1024:1536]` untouched until one architecture/precision choice is
frozen. These are additional technical passages, not broad language benchmarks.
Noise seeds are fixed at **60001/60002**. Hash content and exact token IDs; reject
short/mutated inputs, missing frozen scales or changed source/reference hashes.

Controls: original Q8_0; frozen W8 weight-only; original R256/A9 deterministic
and R256/A9/ADC11/read50. Candidate menu: common R1024 activation scales at
**A9/A10/A11/A12**, and R256 **power-of-two local scales at A9/A10** with
explicit exponent alignment. No refitting on these notes. Report every candidate,
not only the best. First evaluate ideal arithmetic; then the fixed physical
ADC11, 4-fF unit, 120-fF fixed load, ±0.45-V excitation, 0.5-V-span and 50-µV
noise hypotheses. Compare separate and pooled conversion at the same final
output-error definition; do not reuse the old ADC noise unchanged by assertion.

For powers of two, set `eg = ceil(log2(max(abs(xg))/qmax))` and encode
`qg = round(xg/2^eg)`, handling all-zero blocks explicitly. A final reference
exponent E requires multiplying each integer partial by `2^(eg-E)` before the
physical sum. Record the full exponent spread, required extra planes/decays,
discarded bits if bounded, reference fanout, and any extra conversions. Include
an intentionally unaligned raw-sum control that must disagree for unequal eg.

Output per tensor and token: ideal/quantization/noise errors, KL/PPL, ADC clipping,
number of active groups, useful/padded work, physical bit planes, slice and final
conversion counts, exponent histogram and alignment cycles, effective gain,
capacitance and shared-reference requirements. High-level speed credit derives
from these counts, not nominal K alone. Success means a surviving joint-quality
configuration with an explicit reduction in paid ADC service; no silicon or
novelty claim follows.

## Proposed test 2: connected reduction with an equal-error system ledger

Use the accepted arithmetic policy from test 1 to generate frozen signed
four-group and eight-group operands. Include cancellation, unequal coefficient
loads/scales, maximum history transitions and ragged/zero groups. Compare
separate conversion with a real pooled or actively weighted receiver at equal
reconstructed error, the same available ADC count, and the same logical weight
positions. Source waveforms may not be replaced by ideal held output voltages.

Measure acquisition→retention→join→conversion→reset, all positive source delivery,
worst pending-output lifetime and state disturbance. Separate development and
reserved corner/stimulus cases; retain failed traces. Derive noise covariance
for the actual switch states, then validate its assumptions or label the noise
result conditional. Use the measured transfer/error distribution in the full
model rather than substituting a convenient global Gaussian SNR.

The executable ledger must retain every conversion, replica, added holder and
alignment cycle; apply measured whole-cycle ADC time and precision-dependent
energy; charge digital scale/exponent/reduction work; and report area/storage
and service gaps as unknown. Include negative controls for dropped W8 slices,
ignored extra ADC rounds, zero-cost unknown memory, copied-capacitance averaging,
and omission of closing reset. A pass is a reproducible reduction in full paid
service or energy at accepted quality. A local charge-transfer or multiplier
pass without that result remains a useful subcircuit, not the campaign outcome.

## Campaign audit addendum: explicit device geometry and readout gates

The Sky130 wrapper defaults omitted diffusion areas/perimeters AD/AS/PD/PS to
zero. Historical W/L-only transistor simulations therefore omit realistic
junction loading and leakage; their deterministic transfer and energy results
must be labeled accordingly. A new physical candidate must specify a defensible
pre-layout diffusion geometry, retain the old result as a control, and repeat
the relevant delay, retention, energy and corner checks. This is still a geometry
proxy until layout extraction, not PEX. Numerical `gmin` convergence cannot
replace missing physical junctions.

Connected MAC→ADC qualification requires two separate gates: converter code
against its actual preconversion state, and code against the complete intended
quantized dot product after a frozen development calibration. Record raw MAC
error as well as ADC-code error; finite ADC resolution does not justify silently
relaxing the latter. Reject/report overrange independently before clipping the
expected code. Energy includes a settled closing reset after the final scored
word. Calibration words and validation words must be explicitly disjoint and
named, even when a short run is only an initial conversion sanity check.

A sampled matched reference may cancel deterministic common-mode disturbance
while adding independent noise. For example, two independently sampled 568-fF
holders at 300.15 K have differential thermal RMS `sqrt(2kT/C) = 120.8 µV` under
the basic sampled-capacitor model. Correct noiseless decisions at ±50 µV do not
qualify 50-µV input noise. Full-system noise credit requires the actual
correlations, reset state and physical integration window.

### Consistent deterministic precision units

Preserve the historical raw-MAC error gate as a strict regression control, but
also score physical charge and converter-code error. A raw integer MAC unit
does not have constant physical significance across activation radix and load:

```
Q_per_MAC = Cu*Vs/2^B
V_per_MAC = Q_per_MAC/Ceff.
```

With Cu=4 fF and Vs=0.45 V, a dense B9/6980-fF column has 0.003515625 fC and
0.50367 µV per MAC. One dense MAC is exactly the same charge as 0.25 MAC in
the older sparse B7/568-fF fixture, where that charge gives 6.1895 µV. At the
specific 0.1171875-fC converter quantum, both are 0.030 ADC LSB. Therefore
preserving the old 0.25-MAC gate in the dense fixture tightens physical charge
accuracy fourfold; a one-MAC dense residual is not inherently a model failure.

For a fresh physical screen, predeclare deterministic residual RMS ≤1/8 actual
ADC LSB and maximum ≤1/2 LSB after calibration on named development words.
Report coherent offset/gain separately and retain the old gate's PASS/FAIL.
At the preceding quantum this allocation is 0.0146484-fC RMS, or 2.0986 µV
and 4.1667 MAC in the dense fixture. This is a provisional converter error
allocation, **not** an accepted model-quality law. Use each column's actual
reference span, calibrated charge step and effective admittance; nominal C
times voltage is only an approximation when nonlinear device charge matters.
Complete system acceptance still requires injecting the measured residual
and its fixed/history-dependent components into the frozen full-model test.

### Fresh array-reset noise is not in the frozen stage model

The campaign's frozen charge/guard/representation models use an independent
sharing-stage variance kT/(2C), starting from a noiseless holder. This gives
`Var(VB)=(2/3)*(kT/C)*(1-4^(-B))`. That is an optimistic sharing-only model,
not the complete thermal noise of reset plus sharing.

For two equal grounded capacitors C, assume the fresh array reset is fully
thermalized and independent of the old holder, and the subsequent isolated
sharing resistor fully thermalizes its differential mode. The conserved common
voltage is `(Va+Vh)/2`, with variance `(kT/C+Var(Vh))/4`. The differential
voltage has equilibrium variance2kT/C; one holder receives one quarter of
that variance. Thus

```
Var(Vh,new) = Var(Vh,old)/4 + kT/(4C) + kT/(2C)
           = Var(Vh,old)/4 + 3kT/(4C).
```

An initially thermalized holder has variance kT/C after every completed stage.
With initial holder variance `eta*kT/C`, the result after B stages is
`(kT/C)*(1-(1-eta)*4^(-B))`. Summing independent native holder charges gives
`Var(Qsum)=kT*sum(Cg)` for eta=1, rather than the frozen long-word
`(2/3)*kT*sum(Cg)`:50% more variance and22.47% more RMS. Zero-input states
that the compiler skips digitally must still follow their declared physical
reset/clock policy; no ADC noise should be added to a conversion never taken.

This addition follows the phase covariance, not a blanket kT/C charge for
each transistor. With a noiseless initial holder, one fully settled share has
array and holder marginal variance3kT/(4C) and cross-covariance−kT/(4C);
their total charge variance remains exactly the fresh array's kT*C. Fresh
independent reset removes that cross-covariance before the next cycle.

Finite reset/share time, aperture, nonlinear device charge, off-switch coupling,
row/reference noise and their correlations can modify this ideal model. A
small physical switched two-C noise experiment is required to qualify the
phase model. Old grid sources/results remain immutable and explicitly
optimistic; the next separately frozen original/radix9 comparison must price
array reset and initial holder reset before claiming thermal-qualified quality.
