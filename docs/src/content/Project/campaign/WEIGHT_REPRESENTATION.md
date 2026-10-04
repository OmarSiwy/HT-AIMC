# The clean error floor is chiefly W8 recompilation

**VERIFIED diagnostics, not a hardware improvement.** On the first exposed
passage, keeping the campaign's W8 weights but removing activation and ADC
quantization gives KL .0046754 and PPL ratio1.0071381. Keeping only A11
activation quantization with the original model weights gives KL .000072832
and PPL ratio1.0001804. The combined exact-ADC control exactly reproduces the
previous diagnostic. The dominant clean error is therefore the extra weight
requantization in this pipeline, not the finite ADC.

| Ideal-readout diagnostic | Passage1 KL / PPL ratio | Passage2 KL / PPL ratio |
|---|---|---|
| Campaign W8 only | .00467540 / 1.00713806 | .00464651 / .99691809 |
| A11 only, original weights | .00007283 / 1.00018039 | .00008006 / .99969950 |
| W8 + A11 | .00478016 / 1.00756344 | .00473169 / .99620885 |
| W8 + A11 + finite clean ADC | .00486290 / 1.00837435 | .00494363 / .99755070 |

[Frozen decomposition and exact control audit](../../../../../build/campaign/quantization_floor/result.json).
These components are not additive in a nonlinear network. PPL is measured on
actual next-token labels, whereas KL uses the reference probability
distribution; they need not move together. For fixed logit perturbation δz,
the first-order loss term is (p−e_y)ᵀδz, while small-perturbation KL starts with
one-half δzᵀ(diag(p)−ppᵀ)δz. A smaller output MSE or KL does not guarantee a
smaller PPL on a finite passage. An old comment in `depth_budget.py` equating
KL with the measured change of log-PPL is inaccurate for the actual-label
metric; `Eval.score` correctly computes them separately. That frozen source
has not been edited during active source-audited campaigns.

## What the two weight representations actually store

The [GGUF reader](../../../../../scripts/compiler/gguf_reader.py) decodes Q8_0 in 34-byte blocks:
one FP16 scale d and32 signed bytes q, with W=dq. Consecutive values span the
input dimension of one output channel. `Net` transposes this to input×output.
The original reference is already dequantized Q8_0, not an FP16 source model.

The current [weight quantizer](../../../../../scripts/compiler/metrics/imc_smooth_radix.py)
instead forms W′_ij=s_i W_ij and defines a single d′_j=max_i|W′_ij|/127 across
the full output column. It stores round(W′_ij/d′_j), clipped to−127…127.
Inference divides inputs by s_i and applies d′_j after summation. This retains
one convenient column scale but discards the original32-row scale variation
and rounds the weights again. The smoothing scales were frozen under an older
lower-activation-precision/read-noise search; their benefit must be rechecked
at A11 rather than assumed.

The raw-storage audit reconstructs **all210 tensors bit-exactly** from their
original integer codes and FP16 scales. All106,168,320 original codes are
within−127…127, so the current signed8 magnitude encoding can represent them.
There are3,317,760 FP16 scales, or6.63552MB, giving8.5 stored bits/weight. The
current155,520 column scales use .62208MB at float32. Both counts exclude the
tied output head, which remains clean in the physical-error injector.

Only12,621 of1,658,880 adjacent scale pairs are exactly equal (about .761%).
Most64-row groups therefore cannot combine two original32-row products with
one common weight scale. A digitally scaled partial sum must remain distinct,
or the weights must be requantized/otherwise transformed with a paid mechanism.
Even a power-of-two ratio does not disappear without an actual shift/gain path.

| Weight reconstruction | Matrix NRMSE versus original Q8_0 |
|---|---:|
| Current smoothed output-column RTN | 1.89173% |
| Unsmoothed output-column RTN | .83543% |
| Unsmoothed group64 RTN | .44127% |
| Unsmoothed group128 RTN | .58565% |
| Original group32 codes and scales | exactly zero extra weight error |

These are unweighted matrix moments; activation sensitivity can change their
ordering. [All-tensor audit](../../../../../build/campaign/q8_storage_audit/result.json).

## Paying for original group scales

Exact group32 evaluation has
y_j=Σ_g d_gj Σ_{i∈g} x_i q_ij. The d_gj factors differ across both groups and
outputs, so they cannot generally be moved to a shared row driver or one
post-column gain. Convert each group's two magnitude-bank results, combine
its integer weight digits, apply its stored scale, then digitally accumulate.
The original arbitrary input-channel smoothing cannot be retained in this
factorization because s_i varies within a group. No smoothing, or one constant
s_g per group folded into the digital group scale, preserves the original q.
The latter needs its own input-precision and scale-format evaluation.

| Rows per partial | Two-bank conversions/token | Ratio to current256 | FP16 group-scale storage |
|---:|---:|---:|---:|
| 32 | 6,635,520 | 6.4× | 6.63552MB |
| 64 | 3,317,760 | 3.2× | 3.31776MB |
| 128 | 1,797,120 | 1.733× | 1.79712MB |
| 256 | 1,036,800 | 1× | 1.03680MB |

Only the32-row option preserves arbitrary original scales exactly. The other
rows are grouping/count envelopes; a single scale there requires new
quantization. The256-row group-scale storage in this table is also a distinct
architecture from the current whole-output-column scale storage above.
Counts include ragged576-row matrices, so the aggregate32-row ratio is6.4×,
while an individual full256-row tile still needs eight subgroup reads.
[Shape-exact count ledger](../../../../../build/campaign/q8_storage_audit/partial_sum_counts.json).

FP16 scale multiplication can be implemented through a mantissa multiply and
exponent shift; it is not necessarily a full floating-point unit. Its precision,
accumulator width, throughput, area and switching energy must nevertheless be
counted. More partial reads also imply more converter work or more parallel
converter hardware. Smaller active arrays can reduce read-voltage error but
fixed column/CDAC floors become more costly, as derived in the
[shared-arithmetic report](SHARED_CALIBRATABLE_ARITHMETIC.md). Grouping should
not be credited as a free scale correction or free throughput gain.

## Stronger same-storage rounding controls

Before building the group-scale hardware, a frozen compiler experiment compares
the current smoothed RTN with unsmoothed RTN and ordinary GPTQ under the
**same existing smoothed column grid**. GPTQ uses only the old128 clean
calibration tokens, natural input order, static scales and1% Hessian-diagonal
damping. The existing repository implementation already checks its blocked
updates against an independent inverse-elimination calculation. No scale,
activation-order or hyperparameter search is performed on evaluation data.

Inference retains W8 and the same per-column scale format; calibration changes
stored integer codes, without per-weight gains or a correction sidecar.
The first test uses exact readout to isolate the compiler. New code-dependent
loading, physical mismatch, ADC clipping and circuit timing must be tested
after a compiler candidate survives. Hardware-aware rounding using measured
site coefficients is a later experiment, requiring actual calibration access
and finite measurement error. [Frozen runner](../../../../../scripts/compiler/metrics/imc_w8_compiler_baselines.py).
GPTQ is established prior art, not a new quantization method discovered here.
[Original paper](https://arxiv.org/abs/2210.17323).

## Completed same-storage and original-group controls

The ordinary GPTQ run passed source and exact RTN-control reproduction checks. It improved calibration MSE on 210 of210 MVMs, but did not improve either exposed passage. This is a negative result for the frozen128-token/static-grid/damping protocol, not a claim that GPTQ generally fails.

| Compiler, exact ADC | Passage1 KL / PPL | Passage2 KL / PPL |
|---|---|---|
| Smoothed RTN control | .0047802 / 1.0075634 | .0047317 / .9962089 |
| Unsmoothed RTN | .0033959 / 1.0065618 | .0031859 / .9976910 |
| Smoothed fixed-grid GPTQ | .0049302 / 1.0090479 | .0049382 / 1.0096533 |

[Compiler results and calibration](../../../../../build/campaign/w8_compiler_baselines/result.json). The unsmoothed RTN control improves the clean error somewhat but retains a substantial recompilation floor.

Preserving original group32 codes/scales gives much more margin:

| Raw Q8_0 group32 + A11, exact ADC | Passage1 KL / PPL | Passage2 KL / PPL |
|---|---|---|
| No smoothing | .00045808 / 1.00064384 | .00048068 / .99906889 |
| Group-constant power-of-two smoothing | .00044274 / .99952633 | .00046777 / 1.00222358 |

The power-of-two group scale is derived only from the existing frozen smoothing scales, so no new evaluation fitting occurs. Original integer weights are unchanged; a digital exponent is applied to each group result. [Frozen original-group diagnostic](../../../../../build/campaign/original_q8_groups/result.json). These are clean arithmetic results, with the6.4× conversion and scale-multiply costs still to be paid.

A new physical-budget calibration is now running at Cu4 and40µV additional read noise. It uses actual unsigned C(code), per-group120fF floors, distributed-CDAC host allocation, stationary kT/C and original FP16 scales. The model keeps resident group32 sections separate from reused32-row sites with correlated fixed errors. Phase-dependent holder matching remains an explicit unverified requirement. [Frozen model and self-checks](../../../../../scripts/compiler/metrics/imc_raw32_precision.py).

### Boundaries of the raw32 physical-budget model

The fixed MIM mismatch currently perturbs the charge numerator only. Nominal measured C(code) still sets holder matching, native CDAC allocation, charge-to-voltage conversion and noise. The simulation therefore does **not** verify the correlated numerator/denominator error of a mismatched array. It does not assume that actual per-group capacitance has already been measured: a hardware implementation that uses such measurements must provide calibration access, precision, storage and measurement time. In reuse8, code-dependent holder matching changes with each stored weight phase. A fixed holder without that matching is a different recurrence and needs a separate derivation.

The exponent B is computed from the maximum activation magnitude within each32-row group for each token. This requires a digital magnitude reduction/leading-bit detector and a per-group plane schedule. The counts record the resulting active planes; they do not include the area, energy or latency of producing B. Groups with different B require either local enables on a common ten-plane schedule or independently controlled groups with an explicit synchronization policy. The modeled40µV additional read noise remains a circuit design target, separate from reset/share kT/C and ADC quantization, and has not been verified by the current FIA fixture.

### Paid group32 service and reuse ledger

The210 block matrices contain106,168,320 stored integer weights. Fully resident group32 arithmetic uses that many two-bank physical weight sites and3,317,760 two-bank group outputs. Reuse8 retains32 sites for each logical256-row tile, including the ragged last tile:16,588,800 physical weight sites and518,400 physical two-bank group outputs. Actual average reuse is6.4, with a maximum of8 phases. This reduces physical arithmetic by6.4×, while stored weights and all6,635,520 bank conversions/token remain. The tied output head is excluded from these counts and must be paid separately.

With minimal signed8 banks containing22 unit capacitors/site, Cu4 gives88fF/site installed magnitude capacitance:9.34281216µF resident versus1.4598144µF reuse8. The existing unsigned four-bit bank on both sides instead installs30 units/site:12.7401984µF versus1.990656µF. These are installed arithmetic capacitor sums, **not** connected capacitance and not layout area. Holders, matching trim, CDAC padding, disabled switch load, sign selection, clocks and readout add physical resources; MIM footprint must come from the audited process geometry. Neither nominal capacitance nor SRAM area may be silently counted twice where layers overlap.

A concrete reuse schedule is: read/program one32-row weight group into the sites, reset/sample its input planes, convert the low and high bank, form low+8·high, multiply by that group's original FP16 scale and activation scale, then add into a digital output accumulator. Repeat up to8 phases. A separate latch/holder can overlap a conversion with preparation of the next group only if it preserves the previous charge while the weight-controlled array is reprogrammed. At least two independent holding states, isolation, and their noise/loading are then paid. Pipelining can improve initiation interval; it does not remove the6.4× service demand.

Let t_array include reset, program and all enabled plane dwells, and let t_ADC be paid complete conversion service. With two bank converters working in parallel, a two-holder group pipeline has an optimistic phase interval max(t_array,t_ADC,t_scale); one converter shared by both banks adds a two-conversion service requirement. A physical group with eight resident weight phases takes at least eight phase intervals per vector. Replicating converters/holders can recover service capacity but duplicates the converter and reservoir area/clock energy. Network layer dependencies and ragged utilization still limit whole-model throughput; summing conversion counts alone is not a latency prediction.

Reuse also requires106,168,320 weight bytes to reach local programming controls per token if each group is processed once, plus6,635,520 scale bytes if scales are read once per output partial. Local SRAM reads are internal bandwidth, not automatically off-chip traffic, but are not free. For token rate R, minimum uncompressed aggregate weight-read bandwidth is106,168,320·R bytes/s, and read energy is849,346,560·E_bit per token before decoding, programming and scale reads. Keeping a group programmed across multiple activation vectors can amortize this traffic for batches/prefill, at the cost of intermediate activation storage and a different schedule; single-token autoregressive decoding does not obtain that reuse for free. Original raw storage is8.5 bits/weight before input-group exponents, ECC, controllers or the excluded head.

For a simple passive sharing recurrence with actual array A'=A+δA and nominal holder H=A, r=H/(H+A')≈½[1−δA/(2A)]. A charge contribution injected m shares before read has a coefficient proportional to r^m. Its first-order relative error includes −m·δA/(2A), in addition to its own weight-capacitor numerator error. Thus unknown array/holder mismatch creates a plane-dependent radix error; a single final scalar gain generally cannot remove it. This conditional derivation does not establish the error of the current physical switching topology, but identifies what an extracted recurrence or measured holder-matching loop must check. The current behavioral campaign assumes this error absent.

**Readout-interface correction:** C in the frozen raw32 model is one scalar computational holder per magnitude bank, measured against an ideal noiseless reference. It is not a differential-equivalent capacitance. The physical FIA fixture with two independent holders, each C and signal±Vin/2, has differential reset variance2kT/C:91.0µV RMS at1pF versus64.4µV in this model. Its additional read noise cannot be imported without this mapping. These runs therefore test the single-holder/stiff-reference assumption only. A two-holder hardware match needs separately frozen2kT/C analysis, or the physical fixture must establish an asymmetric single-floating-input/stiff-reference implementation with its own common-mode and noise checks. No existing run was silently altered.

### Intermediate grouping diagnostic

A separately frozen exact-readout control recompiles unsmoothed W8 per64/128 rows and output. It stores each maxabs/127 scale in FP16 **before** rounding integer weights onto that scale, retains common A11 activation quantization, and applies activation and weight scales before merging group results. No calibration or evaluation fitting is used.

| Group size | Passage1 KL / PPL | Passage2 KL / PPL | Bank conversions/token |
|---|---|---|---:|
| 64 | .00111822 / 1.00179665 | .00107756 / 1.00144584 | 3,317,760 |
| 128 | .00191481 / 1.00366724 | .00187560 / 1.00288867 | 1,797,120 |

[Corrected frozen result](../../../../../build/campaign/group_size_ceiling_v2/result.json) passes the independent1536-row dense-product oracle and final source audit. Both retain substantially more clean quality margin than the old whole-column compiler, with less service cost than group32. Their noise, finite ADC and physical mismatch are untested. The first implementation incorrectly applied only the first1024-row activation scale after merging a1536-row MVM; its70-row test missed that error. The rejected source/results and explanation remain in `build/campaign/group_size_ceiling/`. Those rejected values are implementation failures and are not evidence against group64/128.

### Group128 differential-readout control

A separate frozen physical-budget run now uses group128, Cu4, two independent equal read holders (2kT/C differential reset variance), and50µV additional differential read RMS. This larger target accounts for the still conditional FIA/latch budget; it is not a measured complete-converter guarantee. The brief40µV calibration was interrupted before any result and preserved separately. New results belong to `build/campaign/group128_precision_r50/`.

The model counts connected actual rows only: the576-row matrices end with64 active rows in their last128-row group. Reuse2 maps two logical128-row phases onto128 physical sites in a256-row tile, with fixed shared mismatch draws. It does not reuse the group32 indexing. There are66,355,200 retained physical sites and518,400 two-bank physical group outputs under this reuse schedule; actual average reuse is1.6 with a maximum of2 phases. The ragged last tile retains128 sites but only64 actual weights; the model assumes unused row capacitance is isolated, and does not yet pay isolation parasitics. The full conversion service remains1,797,120 bank reads/token.

The existing connected-C counter includes one computational array plus its matched signal holder (2C) and fine-DAC excess. The additional reference-holder counter adds C, giving3C plus fine excess for the paired-reference interpretation. This does not duplicate the computational array. Reference reset energy, generation and switching must be paid. The physical matching, reference isolation and covariance assumptions remain unverified.

The reuse2 group128 control is not the smallest arithmetic implementation. For fixed rectangular128-row physical sections shared among S=8 logical groups, shape accounting gives22,118,400 physical sites and172,800 two-bank physical group outputs; average useful reuse is4.8 because of ragged matrices. Minimal22-unit Cu4 magnitude capacitance is1.9464192µF before holder/reference/CDAC/sign/periphery, compared with1.4598144µF for group32/reuse8. Group128 still needs only1,797,120 bank reads/token versus6,635,520 for group32. This potential area/service tradeoff is **SPECULATIVE** until its distinct site correlations, programming schedule and reference/holder behavior are tested. The current reuse2 mismatch results do not qualify reuse8. [Shape-only reuse ledger](../../../../../build/campaign/group128_precision_r50/reuse_count_ledger.json) records G=32/64/128 and S=1/2/4/8/16, including unused rectangular sites and FP16 metadata. Group128 storage is8.1354167 bits per actual weight because ragged scale groups exceed the ideal8.125-bit limit.

### Constant-total grounded-bank remedy: costed boundary

Grounding unselected capacitor bottom plates can keep the signal-array total constant across weight codes. The minimal signed8 implementation needs a three-bit low bank (7Cu installed) and four-bit high bank (15Cu), not two15Cu banks. The existing four-bit TT AC coupon supports constant60fF at Cu4, but the smaller three-bit bank and complete signed transient implementation are unverified. With120fF floor per bank, nominal native totals before CDAC padding are:

| Rows | Low bank | High bank |
|---:|---:|---:|
| 32 | 1016fF | 2040fF |
| 64 | 1912fF | 3960fF |
| 128 | 3704fF | 7800fF |

Constant total removes code-dependent phase loading in the ideal network. It does not remove fixed array/holder mismatch: each physical section still needs verified matching or a static trim/calibration loop. Grounded unused rows remain capacitive loads, including ragged groups. Transient switch parasitics, coupling and PVT may spoil ideal code independence.

For group32/reuse8, installed magnitude capacitance is1.4598144µF and matched signal and reference holders each add1.5842304µF. Including a120fF computational-array floor gives a3C sum4.7526912µF before CDAC/sign/trim/periphery. Group128/reuse8 has1.9464192µF installed magnitude C and1.9878912µF each signal/reference holder, with3C sum5.9636736µF. These are capacitance ledgers, not extracted area or an energy measurement. Smaller voltage kT/C is not a quality benefit by itself: at fixed charge gain the differential output charge variance grows as2kTC+σ_read²C². [Grounded22-unit ledger](../../../../../build/campaign/grounded_22unit_count_ledger.json).

All current bypass physical-budget campaigns still use the TT W=.42 measurement. Later SS amplitude tests required a larger or asymmetric switch, changing off-code loading. These runs therefore do not qualify a PVT-capable bank; the actual selected-width C(code) table must replace them in a separately frozen matched control.

A conditional scaling identity helps explain the group-size tension. If N input rows are partitioned into G-row groups with the **same fixed charge-to-output multiplier γ**, each group has C=Gc+Cf, independent differential thermal variance2kTC, read varianceσv²C² and independent uniform quantization varianceΔQ²/12. Summing N/G outputs gives

`Var_out/γ² = N[2kT·c + 2σv²·c·Cf + σv²·c²·G + (2kT·Cf + σv²·Cf² + ΔQ²/12)/G]`.

Thus the conditional noise minimum is `G*=sqrt[(2kT·Cf+σv²·Cf²+ΔQ²/12)/(σv²·c²)]`. Larger groups amortize reset/ADC floors but increase read-voltage noise expressed as output charge. This is not a sizing result for the neural network: γ, integer weight scales, activation exponent B, ADC settings and cross-group correlations change with G. The frozen per-group numerical model uses actual scales instead. The identity separates the topology-dependent floor from the read-noise cost and explains why larger holders can improve voltage noise while worsening the sum's numerical error.

### Partial reference-noise cancellation identity, with a negative cost check

If both magnitude-bank reads reuse the same sampled reference voltage e, reverse the low bank's encoded signal polarity and digitally negate its conversion. Under ideal unchanged group scaling, the reconstructed low+8·high reference error becomes `(C_L−8C_H)e`, instead of two independent reference errors. Therefore C_L=8C_H cancels this one common reference term. This is a conditional correlation identity, not a new verified circuit or a novelty claim: the reference must preserve the same sample across reads; gain mismatch, reference drift and conversion kickback spoil cancellation, and computational-holder and additional read noise remain.

The simple grounded group32 implementation exposes its poor cost. With original C_L=1016fF and C_H=2040fF, cancellation requires padding C_L to16320fF. Combined native holder C increases6.01×. The output-weighted independent signal-holder thermal coefficient rises from131576fF to146880fF. Removing reference thermal noise reduces total ideal thermal variance to55.8% of the original two-independent-holder model, but the50µV read-noise coefficient rises from267374656fF² to532684800fF², almost2×. At the current noise and area objective, this direct padded implementation is not an attractive candidate. The useful retained insight is that read-reference covariance is architectural, while its cancellation must be evaluated together with signal scaling and paid capacitance.

### Offline ADC tolerance frontier

The group128 frozen calibration grid supports a lower-cost candidate without blanket depth truncation. For each MVM/bank, retain settings whose deterministic calibration MSE plus declared2kT/C+50µV variance is at most1.05× that bank's frozen minimum. Pareto-filter by ADC decisions and connected computational-plus-reference capacitance, then choose minimum decisions, minimum C and finally minimum calibration proxy. This preserves rare13/14-bit range requirements.

The candidate changes412/420 bank settings. Decisions fall22.754688M→19.910016M/token (12.50%); connected-plus-reference C falls14.755925→14.613655µF (0.964%). The sum of per-bank proxies rises2.956%, with maximum individual rise4.985%. Most reads become11-bit/span.5; minimum native LSB increases4.727→18.956µV. Calibration clipping rises2112→145654 bank events, so this is an offline **SPECULATIVE** cost candidate, not a quality pass. A5% per-bank proxy bound is not a5% network KL/PPL bound. Reference generation, span-dependent switching energy and physical DAC granularity still require pricing. [Frozen-grid candidate and assertions](../../../../../build/campaign/group128_precision_r50/adc_tolerance_1p05.json). Current full-model runs retain their original choices.

### Completed group128 physical result: FAILED

Both fixed-die runs completed with source audits passing. All16 primary2kT/C+50µV cases fail the KL≤.01 gate; worst KL=.0166854 and worst PPL ratio=1.0313277. This includes both passages and resident/reuse2 schedules. Mismatch-only finite-ADC diagnostics pass7/8, with reuse2/die1/passage1 failing PPL=1.0116202. Thus good ideal group128 quality does not survive this physical-noise budget. [Completed summary](../../../../../build/campaign/group128_precision_r50/summary.json).

The next frozen bracket uses group64,2kT/C+50µV, and the actual N.50/P.70 TT bank loading. It keeps unsmoothed FP16 group scales and uses resident/reuse4 sites per256-row tile. This source change is explicit: comparing against prior group128 also changes switch loading, so it is not an isolated group-size experiment. Calibration uses only the old128 clean tokens; original raw32 and group128 artifacts remain unchanged.

The frozen group64 measurement uses a four-bit programming bank for **both** magnitude digits; the low digit uses only codes0–7 but retains the unused fourth bit's circuitry. Its installed coupon topology is therefore30 units/site. The22-unit area ledger describes a prospective three-bit low/four-bit high topology and must not be presented as the physical area of that four-bit-loading simulation. The actual three-bit bank's AC/transient results will require a separate matched model.

### Unequal digit-bank capacitor sizing identity

A constant-total signed8 low7-unit/high15-unit pair need not use equal physical unit sizes. For G rows, independent differential reset noise and ideal scale recovery give thermal output variance proportional to `7/CuL + 64·15/CuH`, while installed arithmetic capacitance is proportional to `7CuL+15CuH`. Lagrange minimization at fixed installed C gives `CuH/CuL=8`. In the no-floor limit the read-voltage contribution is proportional to `7²+64·15²` and is independent of those unit sizes, so increasing a unit size cannot remove that read-noise floor.

At an88fF/site budget, the unconstrained solution CuL=.693fF is below the available MIM coupon range. Using a2.77fF low unit instead leaves CuH≈4.574fF and lowers the ideal thermal coefficient about12% relative to equal Cu4. At176fF/site, the same low unit leaves CuH≈10.441fF and lowers it about22% relative to equal Cu8. These are analytical sizing candidates only: actual MIM footprint/fringe capacitance, fixed floors, switches, CDAC allocation, matching and signal recovery require a new paired model. The bank-dependent charge-to-digital scale must be implemented, not treated as free per-weight calibration. This is an established constrained-noise allocation principle rather than a novelty claim.

Fewer ADC decisions can cost more reference energy. For the split DAC, a conditional switched-capacitance proxy is `Csw=[2^(n−4)−1+16]·3.75fF`; actual SAR activity and driver losses are unmeasured. The unguarded5%-proxy candidate increases summed Csw·span² by1.981× for group128 and1.646× for group64 because lower depth often doubles the reference span. A separate offline candidate constrains this proxy not to increase for any bank. It saves group1282.28% decisions and13.24% reference CV² proxy, with calibration proxy+0.999%; group64 saves.911% decisions and5.98% CV² proxy, with calibration proxy+1.268%. These are conditional cost frontiers, not measured power or quality improvements. The corresponding `adc_tolerance_reference_CV2.json` and `adc_tolerance_1p05_CV2_guard.json` live in each group campaign directory.

Including the120fF floor and50µV read term reduces the attractive unequal-Cu thermal-only gains. A one-dimensional convex search at fixed installed capacitance and minimum Cu=2.77fF selects low2.77/high4.574fF at88fF/site and low2.77/high10.441fF at176fF/site. Total modeled thermal-plus-read variance improves8.41%/10.79% atG32,6.07%/7.04% atG64, and3.94%/4.15% atG128. [Conditional numerical sizing ledger](../../../../../build/campaign/grounded_unequal_cu_ledger.json). Matching, CDAC, actual capacitance geometry and whole-model quality are not included.

Early group64 differential results do not yet establish a robust point: first-passage resident seed61001 passes both dies, but seed61002/die1 fails PPL=1.017326 although KL=.008812 passes. The second die passes that same seed. Complete paired controls continue; a single seed's pass is not an architecture qualification.

The actual N.50/P.70 three-bit TT coupon now provides bypass C0=9.980125fF/C7=30.202634fF and grounded28fF for all codes. This supports the low-bank constant-total AC value; it does not supply a complete signed8 array. A shared-sign low-three-bit transient passes, but the corresponding high-four-bit shared-sign fixture fails its charge-error gate. A different direct three-TG-per-bit low bank passes with different off-code loading. Current system tables remain unsigned-only. A next signed model must use the selected signed topology's actual loading and timing for both banks, rather than attach a free sign function to these measurements.

Shared readout also changes noise covariance. Current50µV draws are independent per group conversion. If a shared converter instead has a perfectly common residual voltage offset or low-frequency component e across phases, group reconstruction gives variance `σe²(Σg γg Cg)²`, compared with `σe²Σg(γg Cg)²` for independent draws. The FP16 scales and charge-recovery multipliers γg are positive, so coherent accumulation can be severe. A real time-shared implementation must specify residual offset calibration, chopping or measured covariance; the independent-noise model is not automatically a model of a reused FIA.

A fixed-radix mismatch must be judged by absolute product error as well as relative LSB/MSB distortion. Enumerating all1024 input codes in the ideal recurrence `S(r,q)=Σj bj r^(10−j)`, with fixed fractional pole error±.0498%, gives worst fullscale error≈.0991%. One noiseless fullscale scalar gain calibration reduces residual worst-code error to.02466%FS; at three times that pole error, residual is.07397%FS. This does not make the transfer perfectly binary, but suggests a grounded constant-total array may tolerate small fixed matching error with a paid per-section gain calibration. By contrast, r=.56967 from code-dependent loading still leaves7.2746%FS after scalar correction. [Exact finite-code bound](../../../../../build/campaign/radix_scalar_gain_bound.json). Finite calibration noise, reference accuracy, FP16 gain storage, numerator mismatch and transistor nonlinearity are excluded; no physical pass follows from this bound.

### Completed group64 physical result: no robust winner

The selected-width group64 runs completed with both source audits passing. All16 physical cases pass KL≤.01, but only12/16 meet the joint PPL gate. Die1 resident passes1/4 and reuse4 passes3/4; die2 passes4/4 for each. Worst PPL ratio is1.01732595 for resident and1.01177894 for reuse4. Mismatch-only8/8 pass. [Completed conditional result](../../../../../build/campaign/group64_precision_r50/summary.json). These results improve the group128 noise failure without establishing a robust physical point.

The authorized grounded group32 optimistic control now calibrates original Q8_0 weights with constant low28/high60fF per row,2kT/C and50µV additional read RMS. It validates those constants against actual unsigned AC records, preserves the old raw32 fixed numerator-error draws, and pays signal/reference holders and CDAC padding. It intentionally omits the unresolved signed topology, measured covariance and fixed-radix mismatch, so it is an optimistic quality test of the increased-capacitance cost rather than a complete hardware model.

### Fixed physical DAC with early termination (offline bound)

`scripts/compiler/metrics/imc_sar_early_stop_ledger.py` reuses the frozen calibration grid to evaluate fewer decisions while retaining the original physical DAC depth N, native capacitance, reference holder, and reference voltage. Effective depth b uses charge quantum ΔQ_b=2^(N−b)ΔQ_N, so nominal full range is unchanged. The equivalent existing grid point `(b, span_N*2^(N−b))` supplies deterministic MSE; its noise is discarded and replaced with the ORIGINAL physical DAC/holder noise. Missing equivalent grid points remain unexplored, not rejected.

The precise quantizer is `clip(floor(Q/ΔQ_b+0.5),−2^(b−1),2^(b−1)−1)*ΔQ_b`. Its positive endpoint is half nominal full range minus one coarse quantum. A circuit must implement the corresponding half-coarse-LSB decision threshold/centering; simply discarding low bits from a completed conversion does not establish this behavior. This is established variable-resolution SAR territory, not a novelty claim.

| Frozen campaign | Original decisions/token | Candidate | Reduction | Calibration clips before → after |
| --- | ---: | ---: | ---: | ---: |
| Group128 | 22,754,688 | 20,270,784 | 10.916% | 2,112 → 2,112 |
| Group64 | 39,822,948 | 36,755,838 | 7.702% | 5,249 → 5,245 |
| Grounded original group32 | 82,941,750 | 75,066,016.5 | 9.495% | 62,416 → 62,401 |

Each bank retains total deterministic calibration MSE plus declared noise within 1.05 times its frozen minimum. This is not a full-network quality guarantee. Connected capacitance, reference capacitance and reference CV² proxy remain exactly paid. Comparator/logic decisions are the only credited reduction; real switching energy, reset activity, timing overhead and threshold centering need a circuit check. All three source-hashed artifacts are named `adc_fixed_dac_early_stop_1p05.json`. Existing quality runs remain unchanged. **VERIFIED offline accounting; SPECULATIVE physical implementation and quality retention.**

### Weighted polarity modulation across reused receiver phases

A bounded cross-pollination candidate uses known chopping rather than assuming repeated receiver noise is independent. For one output, let partial charge Q_g recover to output through factor γ_g, with holder C_g. Physical polarity s_g∈{−1,+1} and digital undo produce

`y = Σ_g γ_g s_g [s_g Q_g + C_g(n_c + η_g)]`
`  = Σ_g γ_g Q_g + n_c Σ_g γ_g C_g s_g + Σ_g γ_g C_g s_g η_g`.

For independent η_g, variance stays `σ_η² Σ_g(γ_g C_g)²`. A receiver offset common to that actual reuse sequence contributes `σ_c²(Σ_g a_g s_g)²`, where a_g=γ_g C_g. The unmodulated common-noise contribution is `σ_c²(Σ_g a_g)²`. Thus cancellation depends on recovered output charge gain, not merely group count or weight scale. Gain error remains multiplicative and is not removed.

For positive a_g, assigning the next sign opposite the running residual guarantees final absolute residual ≤max_g a_g (induction using |r−a|≤max(|r|,a)). This is a worst-case bound, not an optimal partition or measured network gain. Equal coefficients and even group counts cancel a perfectly constant receiver error; a single group cannot benefit. For a measured temporal covariance matrix R, actual variance is `(a⊙s)^T R (a⊙s)`, so alternating signs only helps the corresponding correlated/low-frequency modes. A rapidly changing or anti-correlated noise process may not improve.

Scheduling must partition only groups accumulated into the SAME output and sharing the SAME physical receiver. Never average unrelated outputs. Separate radix banks have different γ and C; receiver assignment and chronological conversion order determine which groups can be jointly partitioned. Dynamic activation exponent B changes γ per invocation; a static sign schedule optimized for stored scales alone cannot claim the dynamic bound. Exact online greedy scheduling would require coefficient magnitude formation/comparison and residual state per served output, alongside the already-paid digital partial accumulation. A fixed alternating schedule costs less but has only its explicit weighted residual as a guarantee.

Physical costs include input/weight sign modulation before the sum (or a matched differential input swap), digital output sign undo, switching charge and settling for both polarities, and a receiver path whose offset remains downstream of the modulation. Existing signed weight multiplexers do not prove that this extra global polarity operation is free; offset generated before a swap may transform differently. Charge injection, asymmetric positive/negative settling, finite common-mode rejection, saturation, kickback, and reference noise require separately measured transfer/covariance. Static sign metadata can be one bit per partial; dynamic control may avoid stored bits but adds computation and activity. No noise, delay, energy or area benefit is credited to the frozen quality campaigns. **SPECULATIVE architecture; algebraic invariance and conditional covariance identity VERIFIED.**

### Original raw32 conditional campaign completed

Both source-audited die jobs completed all24 cases each: **48/48 pass**, comprising32 physical-noise and16 fixed-mismatch-only cases. Across resident/reuse8 and common/group32-power2 A11 input scaling, worst KL is0.00331941 and worst PPL ratio1.00626385. The frozen artifact is `build/campaign/raw32_precision/summary.json` with input hashes and mode-specific results.

This validates only the original optimistic conditional model: old unsigned W.42 TT loading, one computational holder kT/C with a noiseless reference,40µV independent additional read noise, ideal phase-dependent holder matching, and numerator-only fixed mismatch. The actual signed dual-holder receiver is not that model. The grounded2kT/C+50µV controls remain separate and were still running at this checkpoint. Two exposed passages, two fixed dies and two noise seeds do not establish yield or held-out robustness.

The separate early-stop quality cohort is now frozen in `grounded_group32_early_stop_r50`, using `imc_grounded_early_stop_quality.py`. An independently implemented binary comparator tree passed92,286 threshold/endpoint/tie probes for physicalN9–14 and retainedb8…N−1. Every midpoint is an integer original fine-DAC code because2^(N−b) is even; exactlyb comparisons reproduce the specified coarse round-to-nearest/clamped quantizer. Original physical capacitance/reference and random draw sequence remain paid. This establishes ideal threshold representability, not a transistor-level switching sequence or reference settling.

Prior-art boundary: [Yip and Chandrakasan's resolution-reconfigurable SAR ADC](https://dspace.mit.edu/bitstream/handle/1721.1/95486/myip_jssc_m10389_manuscript.pdf) explicitly studies5–10bit operation (author manuscript metadata/abstract located; full PDF fetch unavailable in this check). More generally, [Molev-Shteiman and Qi's2018 maximal-entropy-reduction SAR preprint](https://arxiv.org/abs/1811.11102) relates average comparison count to output entropy for nonuniform inputs. [Safarpour et al.'s2019 tracking SAR preprint](https://arxiv.org/abs/1905.08895) narrows the search using bounded sample-to-sample variation. These are existing ideas, not campaign inventions; a grouped IMC reuse schedule does not automatically satisfy the temporal tracking assumption. Entropy-shaped decision trees could preserve full quantizer precision, but would require stored/adaptive distributions, arbitrary DAC transitions, worst-case latency and reference-energy accounting before any benefit is credited.

### Actual unequal-coupon independent arithmetic check

`imc_unequal_coupon_ledger.py` independently reproduces the extracted1.00/1.36µm versus equal1.26µm coupon comparison using source-hashed matrix results, without reading the root comparison ledger. For32rows,120fF floor,2kT/C at300K and50µV additional independent read noise: low/high nativeC changes1095.82688/2211.05760fF →779.78976/2505.99360fF. Signal recovery uses mutualCu2.71535/4.66865fF, separately from substrate loading. The per-weight22unit footprint is52.1752→51.8128µm² (−0.6946%); total mutual89.63988→89.0372fF. Recovered thermal/read/total variance ratios are0.86896431/0.97905873/0.91292363, respectively. The small total-ratio difference from a27°C root calculation follows the explicit300K versus300.15K temperature convention.

This is a real coupon geometry allocation within the old footprint budget, not the earlier imaginary continuous-C optimization. It still excludes routing, MOS extra loading, CDAC, denominator and holder mismatch, signal-dependent transient errors, and physical sign/control service. Source-hashed G32/64/128 and40/50/67µV sensitivity rows are in `grounded_unequal_actual_coupon_ledger.json`. **VERIFIED lumped arithmetic; not a system-quality or delay improvement.**

An independent pipeline-agent audit confirmed the fixed-DAC early-stop quantizer semantics and original-N capacitance/noise preparation. There is no ideal threshold/range blocker to the separate cohort; physical switching/reset remains unverified.

A conditional unequal-cap loading budget is in `grounded_unequal_extra_loading_budget.json`: holding the baseline and candidate low bank at their coupon-only values, the G32/50µV candidate can absorb165.479fF additional HIGH-bank loading (5.171fF/row) before the predicted total output-noise variance equals the equal-coupon baseline. This solves `A ΔC²+B ΔC=variance_margin`, with `A=64σv²/Cu_H²` and `B=64(2kT+2σv²C_H)/Cu_H²` in consistent fF units. This is not a matched MOS loading allowance: both real baseline and candidate have additional transistor/routing C and must be compared with actual tables.

### Per-decision receiver noise is a separate model boundary

`imc_sar_noise_correlation.py` reproduces `sar_noise_correlation_diagnostic.json` byte-for-byte (seed912616,200,000 samples per18settings). With an ideal balanced SAR tree, uniform interior input and white unit-RMS noise, assigning fresh independent noise to every comparison differs from assigning one noisy input sample to the entire conversion. At12bits andΔ/σ=.15, total output RMS is.72291σ for independent decisions versus1.00294σ for one common sample; atΔ/σ=1 it is.90706σ versus1.04107σ. Quantization is included in these values; thermal holder noise is omitted equally.

This counterexample shows why a transistor comparator/FIA RMS cannot simply be relabeled as complete-ADC output RMS without its temporal covariance and decision schedule. It does NOT justify reducing the frozen50µV noise target or substituting these uniform-input factors into network quality. Actual white, flicker, reset, reference and sampling contributions may have different correlations; decision-dependent gain/settling and clipping also matter. All current quality campaigns keep their declared one-sample equivalent-read-noise model. **VERIFIED numerical ideal-tree diagnostic; physical interpretation unqualified.**

The exact original Q8_0 code histogram also supports a conditional mismatch-moment improvement with the unequal coupons. Mean low/high magnitudes are3.5502373/4.9057470. PDK typical-RC parameters givewc=w−.025µm andσ_nominal=.028/wc; because the random term applies the nominal MIM model capacitance, keeping extracted added mutual deterministic gives effective signalσ=.028/wc*Cmodel/Cmutual. Equal/low/high effectiveσ are2.21964%/2.79448%/2.05713%. With independent replicated unit errors, expected coefficient variance isσ_L²E[low]+64σ_H²E[high]. The unequal/equal variance ratio is0.86704867 (RMS ratio0.93115448). `grounded_unequal_coupon_fixed_mismatch_moment.json` records the histogram, coupon and exact PDK parameter-file hashes. This is a fixed-coefficient population moment, not redrawn-perMVM noise, physical yield, scale-aware task loss, or full-model validation. Correlated mismatch, denominator, holder, SAR and extracted-parasitic variation remain absent.
