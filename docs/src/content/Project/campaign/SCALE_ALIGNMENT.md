# Frozen scale alignment and conversion-service experiment

2026-09-10. Development study using the existing full-depth SmolLM2-135M
evaluator. Source: [imc_scale_alignment_campaign.py](../../../../../scripts/compiler/metrics/imc_scale_alignment_campaign.py).
This report will retain every predeclared result, including failures. Reserved
token slices remain unevaluated.

**Noise-scope correction,2026-09-11:** the frozen charge/guard grids below use
independent sharing-stage noise kT/(2C), with long-word variance2kT/(3C).
They omit fresh array-reset and initial holder-reset noise. A fully thermalized
matched two-capacitor reset/share model instead has holder variance kT/C.
The archived passes therefore remain optimistic conditional model results;
the sources and numerical results are preserved. A separately frozen reset-noise
control will follow the current representation grids. See the derivation in
[SYSTEM_EVIDENCE.md](SYSTEM_EVIDENCE.md#fresh-array-reset-noise-is-not-in-the-frozen-stage-model).

## Question and frozen protocol

Can local R256 activation scales be replaced by a physically common R1024
scale, or by explicitly aligned power-of-two scales, without losing model
quality? If so, does combining original held charges save ADC service after
accounting for extra input planes, alignment and required readout precision?

The protocol
was written before any selected corpus evaluation. The two sources are the
largest Digital Design Markdown files by byte count outside `paper/`, selected
using filenames/sizes only: *Floating-Point Exception Handling* and *Dual-Clock
Asynchronous FIFO*. Their first 512 greedy-token IDs are development cases;
tokens 1024–1535 remain reserved. No calibration or alpha fitting uses either
case. Noise seeds are 60001/60002. Each individual result must have mean KL
≤0.01 and observed PPL ratio ≤1.01 relative to original Q8_0 weights and float
activations. Means across cases do not replace these gates.

The frozen SmoothQuant NPZ has SHA-256
`71cacf62925d8a0f3d4959bf6c2c15cd26be9a804136126fe534f8d8827b3836`.
The historical artifact lacks a per-code hash, so the new module checks its
NPZ hash and exactly reproduces its digit-activity and capacitance summaries,
then records a new weight-code hash. Source files, model, corpus bytes and
token IDs are fingerprinted; each run saves its source snapshot and refuses
to overwrite a previous result file. An initial preflight attempt incorrectly
expected the newer per-code metadata key and stopped before any corpus
evaluation; its log remains in `build/campaign/system_audit/scale_preflight_failed.log`.

The full predeclared menu is local R256/A9, common R1024/A9–A12, and power-of-two
R256/A9–A10. Separate and pooled physical readout are evaluated for each common
or power-of-two format. The local arbitrary-scale baseline cannot be pooled
without a real gain operation, which the code explicitly rejects. Each physical
mapping has an ADC11 quantization-only control and two ADC11/read50 noise cases.
The noisy cases include the existing independent `kT/(2C)` stage hypothesis at
300.15 K. ADC full span is 0.5 V: LSB 244.140625 µV, codes −1024…1023, and
reconstructible endpoints **−0.25 V and +0.249755859 V**.

## Arithmetic and physical accounting

After frozen input-channel smoothing, local quantization is

```
dx_g = max(abs(x_g))/(2^(A-1)-1)
q_g  = round(x_g/dx_g)
y_j  = dw_j * sum_g(dx_g * sum_i(q_gi * w_ij)).
```

Common scaling computes the maximum over each logical 1024-row group and applies
that same dx to every constituent physical 256-row group. Power-of-two scaling
uses `e_g = ceil(log2(dx_g))`, actual scale `2^e_g` and corresponding rounded
codes. Zero groups have explicit handling. Weight codes remain signed W8
`[-127,127]`, split into two signed four-magnitude-bit slices with factors 1 and 16.
The factor 16 multiplies the high-slice reconstructed result; it is not a free
analog gain.

For a local holder in one weight slice,

```
C_g = 120 fF + 4 fF * sum_i(abs(weight_slice_i))
Q_g = Cu * Vs * S_g / 2^B,       Vs = 0.45 V.
```

The pooled common-scale path runs the same B on all original local holders,
including a zero-coded local block when another block in that pool is active.
It then joins the original charges:

```
C_total = sum_g(C_g) + C_bus
V_pool  = sum_g(Q_g)/C_total.
```

**Every local 120-fF fixed load remains.** The model does not replace four
holders with one large array having only one fixed overhead. `C_bus=0` is an
explicit optimistic boundary. No gain amplifier, physical join load, reset,
reference or switching noise has been measured by this experiment.

For power-of-two local scales, let `E=max(e_g)` and `d_g=E-e_g`. Compute B local
bits, then apply **d_g additional zero-input halving operations** before joining:

```
Q_g(final) = Cu*Vs*S_g*2^(-B)*2^(-d_g)
y_j       = dw_j * 2^E * 2^B * Q_total/(Cu*Vs).
```

The extra operations count toward local switching work and group critical
plane slots. They inject the same *assumed* per-stage noise as ordinary
computation. Their independent voltage-noise variance is

```
Var(v_g) = kT/(2*C_g) * (1 - 4^(-(B+d_g)))/(1 - 1/4)
Var(Q_total) = sum_g(C_g^2 * Var(v_g)).
```

This differs from noiselessly dividing a finished noisy state by `2^d`:
late alignment operations contribute new noise. The model omits reset noise,
reference correlation, actual switch covariance and join disturbance. These
are conditional arithmetic/noise projections, not transistor-noise validation.

The readout comparison also accounts for a separate local converter's shorter
dynamic magnitude count B_g. For separate 50-µV independent ADC noise, the
equivalent pooled read-noise budget is

```
r = sqrt(sum_g[(C_g * 2^(B_g-B) * 2^(e_g-E))^2])/C_total
sigma_pool_required = 50 µV * r
extra_ADC_bits = max(0, ceil(-log2(r))).
```

For common scales replace `2^(e_g-E)` by one. An all-zero separate block skips
its converter and contributes zero to this budget. The extra-bit expression
compares independent uniform quantization-error variances at unchanged full
span. It does not prove that deterministic errors are independent, or that
an actual ADC offers this adaptive resolution at unchanged time, area or energy.
The fixed physical cases deliberately keep ADC11/50 µV and report their errors.

## Work and scope

The exact model has 210 perturbed MVMs, 106,168,320 projection MAC/token, and
two W8 slice conversions per active output group. R256 requires **1,036,800
final conversions/token**; common R1024 requires **345,600**, a **3× reduction**
after ragged 576-/1536-input groups are counted. The implementation records
useful versus padded MACs, physical local-holder plane events, extra alignment
events, group column-plane slots, conversions, comparator decisions, ideal
voltage range, clipping, capacitance, significance histograms and per-MVM errors.
No nanosecond or joule gain is assigned from counts alone.

All seven layer projections use the experimental arithmetic. Attention QK/AV,
KV, RMSNorm, RoPE, SiLU and the tied LM head remain floating. The latter is
28,311,552 MAC/token, or 21.05% of combined weight work. These teacher-forced
technical passages with a greedy tokenizer are development falsifiers, not a
complete accelerator or public benchmark evaluation.

## Checks and initial results

**VERIFIED arithmetic:** local R256/A9 matches the older radix implementation
with both ADC quantization and identically seeded thermal/read noise; signed
endpoints, zero, ragged groups and unequal-scale charge identities pass;
deliberately unaligned exponent sums and copied equal-voltage averaging fail.
A separate 12,000-draw test of the assumed power-of-two noise recurrence agrees
with its independent analytical variance within **2.29%** (5% fixed screen).
It validates implementation of that assumed noise model, not the physical model.

Initial development results on *Exception Handling*:

| Input/readout | Mean KL | PPL ratio | Joint gate |
|---|---:|---:|---|
| Frozen W8 weight-only | 0.004675 | 1.0071385 | PASS |
| Local R256/A9, ideal readout | 0.005113 | 1.0086204 | PASS |
| Common R1024/A9, ideal readout | 0.005932 | 1.0118112 | **FAIL** |
| Common R1024/A10, ideal readout | 0.005234 | 1.0074823 | PASS |
| Common R1024/A11, ideal readout | 0.004761 | 1.0072472 | PASS |
| Common R1024/A12, ideal readout | 0.004727 | 1.0074615 | PASS |
| Power-of-two local A9, exactly aligned | 0.006114 | 1.0113847 | **FAIL** |
| Power-of-two local A10, exactly aligned | 0.004921 | 1.0092080 | PASS |
| Local R256/A9, ADC11 quantization only | 0.006368 | 1.0134007 | **FAIL** |
| Local R256/A9, ADC11/read50 seed60001 | 0.008181 | 1.0081888 | PASS |
| Local R256/A9, ADC11/read50 seed60002 | 0.007511 | 1.0161599 | **FAIL** |

This first new passage already rejects generalizing the earlier two-passage
ADC-only pass. The useful partial result is that **one additional input bit can
recover the common-scale quantization loss** here. It does not establish a
pooled physical pass.

For common A10 on this passage, matching the separate ADC11 independent-error
budget requires one additional bit for **90.08%** of pooled conversions, two
for **9.89%**, and three for **0.023%**. Required read noise ranges from
**8.56 to 39.33 µV**, depending on actual group, output and input. Power-of-two
A10 requires two extra bits for approximately 35% of pooled conversions and
has up to seven extra alignment cycles in rare groups. It pays **242,898,432
additional local column-plane events** over 512 tokens. Common A10 uses nine
magnitude planes and no exponent-alignment cycles. Thus the arithmetic menu
already favors testing a simple common scale before paying per-group exponents.

The ideal sweep is now complete, including source/hash and original-model
restoration checks: **14/16 individual cases pass**. The second, FIFO passage
passes all eight ideal cases. Common A10–A12 and power-of-two A10 therefore
pass both new ideal cases; their minimum tested precision is A10. Common A9
and power-of-two A9 fail the two-case acceptance gate.

The minimum common A10 candidate then fails all three fixed-ADC11 pooled cases
on the first passage:

| Common A10 pooled readout | Mean KL | PPL ratio | Joint gate |
|---|---:|---:|---|
| ADC11 quantization only | 0.013239 | 1.0130574 | **FAIL** |
| ADC11/read50 seed60001 | 0.018371 | 1.0235745 | **FAIL** |
| ADC11/read50 seed60002 | 0.017467 | 1.0094727 | **FAIL** |

The last case passes PPL and still fails KL. The physical-cost hypothesis needs
more precise readout or another actual change; extra input bits alone do not
remove this converter error. No resized converter has been tested here.

The complete physical grid now passes its execution/source/model-restoration
checks: **24/78 individual cases pass**. The summary below retains all 13
mappings; the quantization column covers both passages, and the noise column
covers both passages and both seeds. Maxima range over all six cases.

| Input format | Readout | Quantization passes | Noise passes | Maximum KL | Maximum PPL ratio |
|---|---|---:|---:|---:|---:|
| Local A9 | separate | 1/2 | 3/4 | 0.008204 | 1.0161599 |
| Common A9 | separate | 1/2 | 2/4 | 0.010566 | 1.0190632 |
| Common A9 | pooled | 0/2 | 0/4 | 0.019559 | 1.0276541 |
| Common A10 | separate | 1/2 | 3/4 | 0.009270 | 1.0145105 |
| Common A10 | pooled | 0/2 | 0/4 | 0.018614 | 1.0235745 |
| Common A11 | separate | **2/2** | **4/4** | **0.008739** | **1.0097473** |
| Common A11 | pooled | 0/2 | 0/4 | 0.017323 | 1.0227651 |
| Common A12 | separate | 1/2 | 3/4 | 0.008431 | 1.0171923 |
| Common A12 | pooled | 0/2 | 0/4 | 0.017842 | 1.0194834 |
| Power-of-two A9 | separate | 1/2 | 0/4 | 0.011947 | 1.0118779 |
| Power-of-two A9 | pooled | 0/2 | 0/4 | 0.036196 | 1.0580002 |
| Power-of-two A10 | separate | 2/2 | 0/4 | 0.011211 | 1.0112529 |
| Power-of-two A10 | pooled | 0/2 | 0/4 | 0.034231 | 1.0433078 |

Every pooled fixed-voltage mapping is **FAILED** on this development gate.
No case clips the ADC, so these failures arise from precision/noise and model
response rather than overflow. Common A11 with separate converters is a
**STRONGLY SUPPORTED development baseline under the assumed noise model**;
it is not a physical or reserved-data pass. A12 does not monotonically improve
the strict observed PPL gate. Input, weight and converter perturbations can
interact, and retaining only the best mean metric would hide this behavior.

The ideal results,
physical results and
aggregate summary retain
each case. No reserved slice has been evaluated. An independent circuit agent
reviewed the implemented charge invariant, extra-cycle noise recurrence and
unequal-significance ADC budget and found no algebraic error under their stated
assumptions.

## Reproduce

Use the repository Nix Python with NumPy and one BLAS thread. Existing output
files are preserved; supply a fresh output directory for a rerun.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_scale_alignment_campaign.py --selfcheck
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_scale_alignment_campaign.py --stage ideal --outdir build/campaign/scale_alignment_rerun
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/compiler/metrics/imc_scale_alignment_campaign.py --stage physical --outdir build/campaign/scale_alignment_rerun
```

Final acceptance requires the complete predeclared grid, retained failures,
source/hash/restoration checks, and then a frozen candidate tested on reserved
data. Any converter resizing or noise-budget change is a new explicitly frozen
physical hypothesis. The [system evidence contract](SYSTEM_EVIDENCE.md) remains
in force for area, service, storage, integration and complete energy claims.

## Follow-up: fixed physical charge quantum

The fixed-voltage failure motivates a separately frozen hypothesis, implemented
in [imc_fixed_charge_campaign.py](../../../../../scripts/compiler/metrics/imc_fixed_charge_campaign.py).
It preserves the preceding experiment and all failures. Its
protocol was written before
any charge-range calibration or evaluation. Execution began only after the
complete preceding grid finished and passed its integrity checks.

A physically fixed split-CDAC quantum is

```
deltaQ = (u / 16) * Vspan
code   = round(Q_MAC / deltaQ)
Q_MAC  = Cu * 0.45 V * sum(S_g) / 2^B.
```

Here capacitance cancels from the noiseless code. It does not cancel from a
comparator's input voltage noise: `sigmaQ = Ctotal * sigmaV`. A fixed charge
range also does not promise freedom from clipping. With `u=3.75 fF` and
`Vspan=0.5 V`, the quantum is `0.1171875 fC`; signed 10/11/12-bit ranges are
approximately ±60/120/240 fC. The separately exported dense W8 physical fixture
already reaches **−153.46 fC** on calibration-only local low-slice data, rejecting
the fixed 10-bit ±60 fC range even before pooling.

The strong local A9 separate baseline, common A10 separate control and common
A10 pooled candidate each independently select their ranges using only the old
27h3 calibration passage's first 128 tokens and clean Q8_0 upstream activations.
For each layer, MVM and weight slice, a single reference span shared by all
columns/groups minimizes reconstructed slice MSE over the frozen grid
`{0.0625, 0.125, 0.25, 0.5, 1.0} V`. Every grid error and clipping count is saved.
No current development data select a range. This explicitly gives the separate
architecture the same opportunity to optimize converter range.

The ADC must fit in one real local holder. For N bits, its equivalent top-node
capacitance is `2^(N−4)*u`, and physical split-DAC capacitance is
`(2^(N−4)+16+1/15)*u`. The first local holder hosts it without data-dependent
reassignment. If that holder is too small, identical positive padding is paid
on both its array and accumulator, preserving radix matching. Reports include
host fit violations before padding, both additions, maximum host and pooled
capacitance, and a connected-capacitance proxy. The proxy excludes disconnected
programming capacitors, weight storage, switches, routing and ADC logic; it is
not layout area.

The menu freezes Cu at 4/8/16/32 fF and scales `u=3.75*(Cu/4) fF`. This preserves
normalized deterministic charge range while isolating noise changes. Increasing
Cu reduces normalized thermal noise roughly as `Cu^(-1/2)`; it does **not** remove
comparator voltage noise because signal charge and dominant weight capacitance
both grow with Cu. The initial family is ADC12/Cu4, with quantization-only,
thermal-only and thermal-plus-read20/read50 cases. Every noisy mode uses the
same two frozen seeds and both exposed development passages. Reserved slices
remain untouched until a complete architecture/precision/noise policy is fixed.

This remains a conditional arithmetic/noise model. In particular, the current
Sky130 wrapper defaults unspecified AD/AS/PD/PS to zero. W/L-only historical
transistor fixtures therefore do not include realistic diffusion junction
capacitance/leakage. Physical qualification requires explicit geometry proxies
and ultimately extracted layout; a pre-junction fixture pass is not sufficient.

### Frozen range calibration and clipping falsifier

Range calibration is complete and fingerprinted in
calibration.json. Across all
210 MVMs, maximum calibration charge is 1142.50 fC for local A9 separate,
936.04 fC for common A10 separate, and **2015.74 fC** for common A10 pooled.
At the largest 1-V reference span, N12 supports approximately ±480 fC. Its
independently optimized ranges clip 790/132,710,400 local conversions,
434/132,710,400 common separate conversions, and 2377/44,236,800 pooled
conversions on the old calibration stream. No current development data fit
these ranges. The full finite N12/Cu4 grid is complete with integrity checks:
**6/42 cases pass**, with no complete surviving architecture. The additional A11
control passes **4/14** individual cases and also has no complete noisy pass.

| Finite N12/Cu4 architecture | Quantization | Thermal only | Thermal + read20 | Thermal + read50 |
|---|---:|---:|---:|---:|
| Local A9 separate | 2/2 | 0/4 | 0/4 | 0/4 |
| Common A10 separate | 2/2 | 1/4 | 1/4 | 0/4 |
| Common A11 separate | 2/2 | 1/4 | 1/4 | 0/4 |
| Common A10 pooled | 0/2 | 0/4 | 0/4 | 0/4 |

Because common A11 separate emerged as the strongest complete phase1 control,
an [additional frozen control](../../../../../scripts/compiler/metrics/imc_fixed_charge_a11_control.py)
uses the same calibration procedure and noise menu in a separate output
directory. It preserves the original phase2 menu/source. This control is
development-selected; it is not an unseen validation case.

A separately frozen [clipping oracle](../../../../../scripts/compiler/metrics/imc_charge_range_oracle.py)
removes only the signed code limits, retaining precisely the same calibrated
charge quantum, input format and weight codes. It contains no noise and has
unbounded integer codes. It is physically unrealizable and receives no PPA
credit. Its bounded controls exactly reproduce the corresponding phase2
quantization-only results, and its source/model-restoration checks pass.

| Common A10 pooled, same quantum | Exception KL | Exception PPL ratio | FIFO KL | FIFO PPL ratio |
|---|---:|---:|---:|---:|
| Finite signed N12 code range | 0.0257162 | 1.0315321 | 0.0255010 | 1.0107495 |
| Unbounded code oracle | **0.0050056** | **1.0059367** | **0.0049984** | **0.9985548** |

The bounded pooled path clips only 3947 of 176,947,200 conversions on Exception,
about **22.3 ppm**, yet these tails dominate its final KL error. Removing the
code limit recovers both strict development gates. The same benefit is available
to the common A10 separate baseline, whose unbounded results also pass both
cases. Local A9 unbounded improves KL but fails Exception PPL at 1.0107592; that
negative result is retained in the complete oracle output.

**VERIFIED diagnostic conclusion:** finite charge range is a major failure
mechanism in this model. **SPECULATIVE circuit opportunity:** use idle native
matching capacitance as coarse feedback plates, or apply measured charge packets
on overrange before a final fine conversion. The separate baseline must receive
the same overflow mechanism. Packet calibration, noise, reset, reference loading,
control, retained analog state and actual service remain unverified. Generic
coarse/fine conversion and charge balancing are existing principles; this result
does not establish architectural novelty.

The static capacitance-fit audit
finds that a 3.84-pF N14 DAC fits **99.65%** of pooled first low-slice holders;
distributing coarse plates over all joined original holders raises the capacity
bound to **99.99%**. By contrast, N14 fits no first high-slice holders and only
7.60% of complete high-slice pools. First-host high-slice padding adds 109% of
that bank's native array-plus-holder capacitance; distributed padding still adds
51.4%. Low/high range asymmetry matters: the calibration pooled maximum is
2015.74 fC low versus 293.93 fC high. Distributed feedback is only a capacity
bound here; no distributed switches, wiring, matching, noise or timing have
been implemented.

Rare overflow count alone does not establish rare latency cost. An endpoint-code
guard must also count valid endpoint bins and report per-token/per-MVM events,
maximum redo depth and whether one slow column stalls the entire tile. A queue
can change that scheduling cost only by paying its state and worst analog
retention lifetime.

### Noise target and finite guard follow-up

The separately frozen [noise oracle](../../../../../scripts/compiler/metrics/imc_charge_noise_oracle.py)
keeps the exact N12 host capacitances and padding, charge quantum and independent
stage/read-noise calculation, but removes code limits. Its seeded nonclipping
control reproduces the original noisy implementation. All source/restoration
checks pass. The complete results
give these individual-case counts:

| Unbounded-code accuracy target | Thermal only | Thermal + read20 | Thermal + read50 |
|---|---:|---:|---:|
| Common A10 separate | 4/4 | 4/4 | 2/4 |
| Common A11 separate | 4/4 | 4/4 | **4/4** |
| Common A10 pooled | 4/4 | **4/4** | **0/4** |

The pooled read20 target has maximum KL **0.00829249** and PPL ratio
**1.00746407**. Pooled read50 reaches KL 0.0129906 and PPL ratio 1.0139200,
failing every case. The common A11 separate baseline passes every oracle noisy
case, including read50. These are **VERIFIED outcomes of an optimistic model**,
not physically verified error budgets: overflow circuitry is absent, and
read20/read50 means one additive Gaussian voltage error per final conversion.
A raw comparator's per-decision noise is not automatically the final SAR
code-error distribution. Static mismatch, decision history, threshold-dependent
noise and correlations remain outside this model.

A new [finite guard model](../../../../../scripts/compiler/metrics/imc_charge_guard_campaign.py)
uses **14 low-slice bits and 13 high-slice bits**, with both first-host and
distributed original-capacitor policies. Its protocol
was frozen before calibration/evaluation. Each architecture independently
minimizes old calibration slice MSE over the expanded reference-span grid
`{0.0625,0.125,0.25,0.5,1,1.25} V`. Host and distributed versions use the same
selected spans. Quality evaluation started only after the noise oracle completed.

Distributed allocation reserves the fine bridge's one equivalent unit in host0,
then assigns integer-unit coarse fragments across original holders. Fractional
remainders remain quiet matching capacitance. If total integer-unit capacity
is insufficient, the minimum positive host0 padding is paid on both array and
holder. The model counts coarse switch fragments, physical DAC excess and
all matching padding. An independent circuit agent found no algebraic error
in these allocation, charge or noise equations under the stated assumptions.
Transistor switching, references, wiring, parasitics, mismatch and extracted
area remain unverified.

The new calibration leaves 10 low/51 high pooled clips and 11 low/53 high
common-A10 separate clips, compared with 2268 low/109 high pooled at N12.
Often the added bits buy a smaller fine quantum: hypothetical 12-bit endpoint
events increase to 1.20 million low plus 40,123 high pooled events over the old
calibration stream. This is a different quantum policy from the earlier 22-ppm
diagnostic. The actual finite model always pays 14/13 decisions; it takes no
rare-event timing discount. Per-MVM/token boundary counts, packet and extra-bit
depths, and conditional 256-ADC round-stall counts are retained. Finite guard
quality results are recorded in the completed addendum below.

### Useful differential halves: static capacity and noise audit

A differential variant computes two useful row subsets, reversing the programmed
weight signs in one subset. With matched branch capacitances `C+=C−=Cb`,

```
Vdiff = (Qfirst + Qsecond)/Cb
sigmaQ_thermal² = sum(all original local charge-noise variances) + padding terms
sigmaQ_read = Cb * sigmaVdiff.
```

A CDAC in the positive branch retains the same native charge quantum. There is
no separate dummy-reference holder in this algebra: both branch thermal terms
were already present as useful compute holders. Matching padding and any new
physical local holders still add noise and area. A common B and activation
scale must remain shared across both halves. Common-mode voltage is proportional
to the difference between the two useful partial sums and is not automatically
constant; comparator compliance/noise must be verified over that actual range.

Fixed interleaved local groups `{0,2}` versus `{1,3}` handle ragged matrices more
efficiently than contiguous halves. In 576 input rows, interleaving gives
320 versus 256 rows; contiguous grouping gives 512 versus 64. The separately
fingerprinted static audit
compares both against the ordinary distributed guarded pool, including the
latter's own ADC-fit padding:

| Useful-half mapping | Low N14 cap increase | High N13 cap increase | Median low read-noise coefficient | Median high read-noise coefficient |
|---|---:|---:|---:|---:|
| Interleaved groups | **9.23%** | **44.97%** | **0.554×** | **0.737×** |
| Contiguous groups | 66.47% | 73.19% | 0.884× | 0.874× |

Median input-referred thermal RMS increases by 1.052× low and 1.214× high for
the interleaved case. Its 95th-percentile read coefficients are 0.579× low
and approximately 0.999× high: there is no uniform factor-of-two read-noise gain.
These cap percentages count array and holder changes; fine-DAC excess, switches,
disconnected programming banks, wiring and full physical storage area are not
included in the ratio.

The separate R256 baseline can also use two useful R128 halves. Giving each
physical holder its own 120-fF overhead, this adds 24.31% low and approximately
99.97% high capacitance relative to its ordinary guarded baseline. At the current
3.75-fF DAC unit, high-bank matching is dominated by the CDAC-fit floor: median
read-noise coefficient remains 1.0× while thermal RMS rises by √2. An optimistic
60-fF split of the old fixed overhead changes the high-bank result very little.

**VERIFIED static bound, SPECULATIVE architecture:** differential matching is
continuous in this auxiliary audit; integer-unit fragmentation and all device
effects remain unverified. No differential model-quality run has been performed.
The baseline may optimize its physical DAC unit and reference span too: 3.75 fF
is a tested anchor, not a proven optimal unit. For example, high N13 with roughly
0.92-fF units and 1.25-V reference span covers about 294 fC using approximately
471 fF of equivalent top capacitance, but matching, switch parasitics, references
and physical realizability of that smaller unit require new verification.

### Completed finite low14/high13 result at Cu4

Both first-host and
distributed runs
completed all42 cases with source, model, calibration and protocol integrity
checks passing. Each has23 individual quality passes. **No candidate passes
all read-noise cases at Cu4.** Reserved corpus portions remain untouched.

| Mapping | Quantization only | Sampling noise only | Sampling +20-µV final read | Sampling +50-µV final read |
|---|---:|---:|---:|---:|
| Common A10 separate, either policy | 2/2 | 4/4 | 1/4 | 0/4 |
| Common A11 separate, either policy | 2/2 | 4/4 | 1/4 | 0/4 |
| Common A10 pool, first host | 2/2 | 4/4 | 3/4 | 0/4 |
| Common A10 pool, distributed | 2/2 | 4/4 | 3/4 | 0/4 |

The first-host pool's worst20-µV KL is0.01001050, narrowly above0.01; its
worst PPL ratio is1.00899554. Distributed pooling has lower worst KL0.00853278
but worst PPL ratio1.01024146, above1.01. These are different failures, and
neither threshold is relaxed. Its worst sampling-only KL/PPL are0.00761561
and1.00631982. The stronger A11 separate control does not restore read margin
once this particular larger CDAC-fit padding is included.

Each512-token passage pays530,841,600 separate versus176,947,200 pooled
conversions, and7,166,361,600 versus2,388,787,200 decisions. With the declared
conditional256-ADC allocation per logical tile, actual rounded service rounds
are2,150,400 versus798,720, a2.6923× reduction; the raw conversion reduction
is3×. Neither is a measured throughput factor.

For the Exception passage, distributed pool quantization has403 clipped
conversions, versus261 for common-A10 separate. Pooled12-bit endpoint events
number3,826,196, or2.1623% of conversions, yet flag44.767% of ADC rounds and
53.617% of logical tile/token steps. FIFO has344 pooled clips and3,701,779
endpoint events. Its worst hypothetical extension reaches four extra bits
and five coarse packets; finite14/13 conversion can therefore still clip.
These counters include valid endpoint codes as escalation guards and do not
credit an unimplemented rare-event schedule. Actual runs always pay14/13 bits.

The static connected array+holder+DAC-excess proxy across all210 resident MVMs
is8.51360e9 fF separate,7.11562e9 fF first-host pooled, and6.86933e9 fF
distributed pooled. Distributed placement lowers this proxy19.31% versus
separate and3.46% versus first-host pooling, while requiring3,515,138 coarse
switch fragments versus3,283,200 first-host fragments. These counts include
physical fine-DAC excess and matched array/holder padding; disconnected
programmability reserve, switches, references, storage and routing remain absent.

Those aggregate capacitances are **8.514,7.116 and6.869 µF**, not nF. At the
nominal2-fF/µm² MIM area density, they would alone occupy approximately4257,
3558 and3435 mm² if fully resident. This illustrative density conversion is
not a layout result: Cu4 itself needs a realizable physical structure, and
perimeter/spacing/storage are unpaid. The scale of this lower-bound cost is
an adversarial warning for the minimal-area objective. Converter reduction
does not by itself establish a resident-chip advantage over Mythic.

### Completed finite low14/high13 result at Cu8

The Cu8 distributed grid
completed all42 cases with integrity checks passing:30 individual cases pass.
It keeps the frozen range choices and doubles the scalable native/DAC units,
while charging actual fixed overhead and fit padding. No ideal stack gain is
inserted into this grid.

| Mapping | Quantization only | Sampling noise only | Sampling +20-µV final read | Sampling +50-µV final read |
|---|---:|---:|---:|---:|
| Common A10 separate | 2/2 | 4/4 | 4/4 | 0/4 |
| Common A11 separate | 2/2 | 4/4 | 4/4 | 0/4 |
| Common A10 pooled | 2/2 | 4/4 | 4/4 | 0/4 |

The pooled20-µV cases have worst KL0.00732924 and PPL ratio1.00705438;
common-A10 separate has0.00883501 and1.00581123. Both satisfy the predeclared
KL≤0.01/PPL ratio≤1.01 gates across both exposed passages and both seeds.
Pooled50-µV worst KL0.01223269/PPL1.01178312 fails. **STRONGLY SUPPORTED
within the declared conditional model:** the finite pooled architecture is now
an equal-quality survivor at Cu8, with both separate controls also passing.
This is not a measured comparator-noise or full-chip qualification.

Connected array+holder+DAC-excess totals16.93601 µF separate and13.52406 µF
pooled, a20.15% reduction. Largest joined capacitances are17.36 pF separate
and61.80 pF pooled; worst added host padding is7.456/7.0215 pF respectively.
The pooled layout proxy has3,524,970 coarse fragments. Static C is paid across
all resident MVMs; at the same illustrative2-fF/µm² density,13.524 µF alone
corresponds to6762 mm². Programmable reserve/storage/routing remain omitted.

Service remains530,841,600 versus176,947,200 conversions per512-token passage,
and2,150,400 versus798,720 conditional ADC rounds:3× fewer conversions,
2.6923× fewer rounds under the frozen resource rule. Quantization-only clips
and12-bit escalation counts are unchanged from Cu4 because scalable signal
charge and DAC step both doubled. The larger capacitor reduces the thermal
contribution; it does not justify using20 µV as an achieved physical read
noise. The separate and pooled50-µV failures preserve that important boundary.
