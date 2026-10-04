# Exact W8 digit choices: capacitance versus reconstructed noise

**VERIFIED identities and static workload counts; system quality and physical
PPA unverified.** The [bounded experiment](../../../../../scripts/compiler/metrics/imc_weight_digit_campaign.py)
audits all106,168,320 frozen projection weights, without changing their W8
values or any calibration/quality corpus. Protocol SHA-256 is
`b259a97d58287cee6e5fa808958fb6d7f75b4b5deef5626773904962ec171f75`;
complete data are in [results.json](../../../../../build/campaign/weight_digits/results.json).
Independent circuit-branch review found no algebraic error in the digit,
geometry, common-B noise or charge equations.

The active quality grids retain the earlier optimistic sharing-only thermal
law,2kT/(3C) after a long word. They do not include fresh array-reset noise.
The fully thermalized two-C reset/share law is kT/C, so a new paid reset-noise
control is required before any thermal-qualified system claim. This does not
change the exact digit identities or static coefficient ratios reported here.

## Three exact representations

The existing physical/model decomposition is signed magnitude:

```
L = sign(q)*(abs(q) mod16)
H = sign(q)*floor(abs(q)/16)
q = L+16H.
```

Its low slice can have magnitude15. The original p50 fixture has sum|L|1715
per256-row column, giving120+4*1715=6980 fF. It is not a balanced signed nibble.

Balanced radix16 instead uses `H=floor((q+8)/16)` and `L=q−16H`. Exhaustive
checks over q=−128…127 give L=−8…7 and H=−8…8, with the same exact q. There
is no added compute plane or digital correction. Existing four-magnitude-bit
physical banks can represent magnitude8, but a logical signed four-bit H field
cannot represent all17 values. Forty percent of these actual weights require
opposite low/high signs. Existing shared-sign routing cannot be assumed free.

This does not necessarily require storing nine independent weight bits:
valid L/H pairs still encode only the original256 W8 values. A decoder from
the original eight bits can derive carry and both signs. The configuration
storage versus decoder/switch-routing choice must be implemented and priced;
the sparse programmed-cap netlists do not establish that cost.

A shared digital correction is possible with a different representation:

```
L = q mod16 −8
H = floor(q/16)
q = L+16H+8
sum_i q_ij*x_i = sum_i L_ij*x_i +16*sum_i H_ij*x_i +8*sum_i x_i.
```

Here L=−8…7 and H=−8…7. Centering the old signed-magnitude remainder while
leaving its high digit unchanged instead needs `8*sum_i sign(q_ij)*x_i`, which
varies with output column. The selfcheck contains an explicit counterexample
to incorrectly treating that latter correction as shared.

## Full-weight geometry and noise tradeoff

| Representation | Mean absolute L | Mean absolute H | Opposite-sign slice fraction |
|---|---:|---:|---:|
| Existing signed magnitude | 6.81571 | .89256 | 0% |
| Balanced | 3.98027 | 1.29272 | 40.016% |
| Shared offset | 4.01973 | 1.36124 | 40.274% |

Balanced low magnitude falls41.60%, while high magnitude rises44.83%.
Before converter-fit padding, total matched array+holder capacitance falls
30.44%. Local low median capacitance changes6980→4132 fF and high median
828→1236 fF. Thus retaining unsigned-magnitude digits was a consequential
architecture assumption, but changing it does not uniformly improve noise.

The next table reuses the frozen low14/high13 guard geometry, Cu4,3.75-fF
CDAC units, and integer distributed capacitor allocation. It is a static
comparison at the same converter geometry, not a newly optimized ADC design.

| Mapping and representation | Total connected C / existing | Thermal RMS coefficient / existing | Read RMS coefficient / existing |
|---|---:|---:|---:|
| Separate R256 balanced | .74310 | 1.00204 | .99637 |
| Separate R256 shared offset | .74672 | 1.00323 | .99895 |
| Pooled R1024 balanced | .69293 | 1.14109 | 1.25308 |
| Pooled R1024 shared offset | .70504 | 1.16367 | 1.29884 |

For independent equal-B local stage noise, charge variance is proportional to
`C_low+256*C_high`. For independent equal-voltage converter read noise it is
proportional to `C_low²+256*C_high²`. The high-slice reconstruction factor16
causes the256 weight. Tables report square roots of the ratios of mean
coefficients. They do not weight actual per-layer dx/dw, dynamic B or model
sensitivity. The exact model replay must include those quantities.

The padded separate design's high capacitor floor hides nearly all the noise
increase. Pooled holders usually exceed that floor, so they pay the extra
high-slice noise. Balanced representation therefore strengthens the separate
baseline as well as the pooled candidate. Its actual aggregate connected-C
proxy is6.32644 µF separate and4.75995 µF pooled, versus8.51360 and6.86933 µF
for signed magnitude. Even4.76 µF corresponds to about2380 mm² at a nominal
2-fF/µm² capacitor area density before storage, spacing, routing or switches.
This remains a severe resident-area limitation, not a claim of beating Mythic.

## Shared-correction cost and failure modes

An exact shared sum needs149,040 additions per token across720 local R256
input groups, or149,520 across240 common-scale R1024 groups in this model's
210 projections. This is input reduction work, not one extra MAC per output
column. Signed256/1024-row sums of A10 magnitudes≤511 need18/20 bits; multiplying
by8 adds three bits. Broadcasting and adding the correction to each output,
and final dw scaling, still consume digital resources.

Pooling that reduction assumes the input groups share scale and exponent.
Otherwise preserve each group's dx/alignment before addition. Digital exact
input sums do not observe physical row-amplitude errors: subtracting an analog
weight offset and restoring its ideal digital value can change the shared
correlated row-noise component. Offset calibration, row-driver noise and
finite reduction widths therefore need explicit tests. Zero weights also
become a physically nonzero low digit in this offset representation.

## Matched physical fixtures

New exports are under
[physical_fixture_balanced](../../../../../build/campaign/system_audit/physical_fixture_balanced).
The p50/p95 labels refer to the original signed-magnitude selection. No columns
or activation words were reselected for balanced weights. Parent hashes,
calibration/development provenance and exact preserved fields are recorded
in each metadata file. Original Wq, xq, B, dx/dw, smoothing, full integer sums
and dequantized partials remain bit-identical; activation archives are byte-identical.

P50 balanced low capacitances are4316/4148/4028/4572/3980/4172/4084/4188 fF.
Its maximum low development charge falls110.97→41.27 fC, while maximum high
charge rises38.74→44.04 fC. These are only the selected three words; frozen
old-stream calibration and new quality evaluation must determine full ranges.

No prior local archive experiment tested these exact representations. Balanced
digits and affine zero-point compensation are established arithmetic, so this
result makes no broad novelty claim. The retained research opportunity is
joint weight-digit, ADC-range, capacitance and noise allocation. The next
system comparison must recalibrate ranges on the same old calibration only,
allow both representations appropriate paid low/high precision, and include
the strongest separate control. Physical sign decoding and independent
slice transfer remain unverified until the exported fixtures are simulated.

## Adversarial sizing bound: equal units are a restriction

There is a stronger ideal thermal-noise baseline than either equal-unit format.
For one representative column or equally weighted homogeneous population, let
`a=sum|L|`, `b=sum|H|` and independently choose unit caps cL,cH. Ignore fixed
overhead, matching floors, ADC loading and read noise. Up to common constants,
matched-capacitor area and reconstructed thermal variance have coefficients

```
A = a*cL + b*cH
N = a/cL +256*b/cH
A*N >= (a+16*b)^2.
```

Cauchy–Schwarz gives the inequality, with equality at `cH=16*cL`. Original
signed magnitude satisfies `|L|+16|H|=|q|` per weight; opposite-sign balanced
digits introduce cancellation and increase this L1 charge cost. Using the
observed mean digits, the optimized normalized area–noise product is445.07
original,608.30 balanced and665.62 shared-offset: balanced is36.68% worse
in this ideal thermal-only limit despite its equal-unit capacitance saving.

For illustration, matching the original cL=cH=4-fF normalized thermal budget
would give cL≈0.359 fF,cH≈5.738 fF in that ideal optimum. This is **not a
feasible sizing result**: the low unit is below the published minimum MIM
area capacitance, and the omitted fixed/CDAC/read/parasitic constraints are
material. Whole-model sensitivity also weights columns unequally. The bound
identifies a missing stronger baseline and a direction for conditional sizing,
not an achieved area reduction or a universal IMC limit. The active equal-unit
grid remains frozen and is labeled as such.

A smaller representation refinement is also retained separately: ties at
absolute remainder8 should carry toward zero if minimizing total absolute
capacitance. The canonical balanced rule above carries positive ties, increasing
|H| without reducing|L|. Avoiding those carries permits both low+8 and−8 and
changes sign/decode requirements. Existing fixtures and grid definitions are
not silently changed to that later variant.

## Frozen matched representation/precision experiment

The new [checker](../../../../../scripts/compiler/metrics/imc_balanced_precision_campaign.py)
and [protocol](../../../../../build/campaign/balanced_precision/protocol.json) were frozen
before independent calibration and quality evaluation. Protocol SHA256 is
`0cc82515ab53d9fc2c9fec919ec0a170991900a32674538e92a2428712428b6c`.
The original and canonical-balanced representations each receive the same
opportunity to choose10–14 ADC bits and reference span from
0.0625/0.125/0.25/0.5/1/1.25 V, independently per MVM and weight slice.
Both Cu4/Cu8 and common-A10 separate, common-A11 separate, common-A10 pooled
architectures are included. The calibrated choices are shared across every
column in that MVM/slice; column-specific activation tables are not used.

Calibration uses only the old27h3 clean-Q8 first128 tokens. The selector adds
exact noiseless finite-ADC quantization/clipping MSE to independent thermal
and20-µV read-noise output variance, after dx/dw scaling. This is a declared
proxy: it omits noise/quantization/clipping interaction and cross-slice
deterministic-error covariance. The minimum-error policy minimizes that proxy.
The economy policy selects the least depth within10% of its minimum. Both
receive actual noise **before** finite quantization during quality evaluation,
so the final test can reject an optimistic proxy selection.

Both2520-record calibrations completed with frozen source/model/protocol
checks passing before quality began. As an early warning, balanced Cu4
separate economy produces9355/9396 calibration clips at A10/A11, versus
1084/1099 for minimum-error. No quality pass is inferred from those choices.
The minimum-error pooled policy chooses14 bits for208 of420 MVM/slice
settings in both representations; economy predominantly chooses11/12 bits.
These are counts of settings, not conversion-weighted work or latency.

Quality evaluation began only after the prior Cu8 finite-guard grid finished.
Each Cu runs72 cases: two representations, three architectures, two policies,
quantization only or two20-µV+thermal seeds, and the same two exposed512-token
passages. Both KL≤0.01 and PPL ratio≤1.01 must hold for every relevant seed
and passage. Reserved portions remain untouched. Results are written to
`build/campaign/balanced_precision/quality_Cu4.json` and `quality_Cu8.json`.

The resource ledger records conversions, real decisions, clipping, active
planes, connected C, matched padding, coarse fragments, conditional rounds,
rounds×depth, per-MVM maximum-depth×sum-rounds, global14-depth control, and
maximum/histogram of bit counts. A mixed-depth average is not a concurrency
proof. Physical storage/sign/carry decoding, disconnected programming reserve,
ADC reference/control circuitry and actual loaded timing remain unpaid. The
source self-check exactly reproduces the frozen guard geometry and seeded
noise/finite-quantizer ordering for both representations, including ragged
groups; an independent circuit-branch audit found no algebra error in the
declared calibration and schedule equations.

The frozen precision ledger also exposes a stronger baseline than the earlier
fixed14/13 comparison. The following minimum-error choices are **static
candidate costs while quality is pending**, not accepted Pareto points:

| Format/unit | Separate connected C | Pooled connected C | Reduction |
|---|---:|---:|---:|
| Signed magnitude/Cu4 | 6.99478 µF | 6.82193 µF | 2.47% |
| Signed magnitude/Cu8 | 13.96267 µF | 13.40902 µF | 3.97% |
| Balanced/Cu4 | 4.95968 µF | 4.75210 µF | 4.18% |
| Balanced/Cu8 | 10.13216 µF | 9.26093 µF | 8.60% |

These separate entries use common-A10; A11 costs differ slightly and retain
their own quality tests. Allowing smaller separate ADC depths removes much
of the old fit padding, so the fixed-depth≈20% pooling area reduction is not
the strongest-baseline result. The native weight capacitors remain in both
architectures; pooling primarily reduces converter service and some padding
and fine-DAC excess. The complete comparison must select among the passing
minimum-error/economy policies and retain actual maximum-depth schedule costs.

## Retained radix9 branch

An exact non-power-of-two decomposition is

```
H = floor((q+4)/9)
L = q-9H
q = L+9H = L+(H<<3)+H.
```

For every integer q in−128…127, L lies in−4…4 and H in−14…14. Both fit
the existing four-magnitude-bit cell range; the low bank needs only three
magnitude controls. Radix8 balanced digits reach high magnitude16 at an
endpoint, which would need a fifth magnitude bit or a separately paid special
case. Radix9 avoids that endpoint cost. Reconstruction adds one post-alignment
addition per complete MVM output relative to shift-only high significance16;
its actual arithmetic width, control and energy still require implementation.

The [static screen](../../../../../build/campaign/weight_digits/radix_screen.py) enumerates
radices8…32, original signed magnitude, canonical balanced, and tie-toward-zero
balanced rules. All106,168,320 actual weights and the complete signed8-bit
integer range are checked. The compiler's observed support is−127…127.
The [corrected result](../../../../../build/campaign/weight_digits/radix_screen.json)
has frozen source/model/protocol hashes. Native C includes the120-fF local
overhead and both array/holder replicas, but omits ADC fit padding:

| Representation | Mean absolute low/high digits | Native connected C | Thermal RMS versus original16 | Read RMS versus original16 |
|---|---:|---:|---:|---:|
| Original16 | 6.81571/.89256 | 6.79582 µF | 1 | 1 |
| Canonical balanced16 | 3.98027/1.29272 | 4.72743 µF | 1.1683 | 1.2808 |
| Tie-toward-zero balanced16 | 3.98027/1.26174 | 4.70112 µF | 1.1558 | 1.2556 |
| Signed-magnitude9 | 3.81128/1.92060 | 5.11718 µF | .7924 | 1.0599 |
| Balanced9 | 2.21756/2.32943 | 4.11080 µF | .8622 | 1.2349 |

The conditional noise columns use mean `Clow+radix²*Chigh` and
`Clow²+radix²*Chigh²`, respectively, at common B. They are unpadded static
independent-noise coefficients, not model dx/dw sensitivity or measured noise.
Balanced9 lowers native C13.04%, thermal RMS26.20%, and read RMS3.58%
relative to balanced16. Against original16, its39.51% connected-C reduction
and13.78% thermal-RMS improvement come with23.49% higher read RMS. This is
therefore a retained candidate requiring a matched ADC/quality test.

Installed programmable capacitance changes the comparison:

| Supported weights/representation | Custom or unary max-magnitude units | Conventional binary-weighted units | Direct magnitude/sign control bits | Independently packed digit bits |
|---|---:|---:|---:|---:|
| Full−128…127 original16 | 23 | 30 | 9 | 9 |
| Actual−127…127 original16 | 22 | 22 | 8 | 8 |
| Canonical balanced16 | 16 | 30 | 10 | 9 |
| Balanced9 | 18 | 22 | 9 | 9 |

These are per-weight bank counts before matching holders, switches and storage.
A binary bank supporting magnitudes0…8 still physically contains1+2+4+8=15
units; it cannot claim only8 installed units without another topology/decoder.
A custom/unary bank may reach the max-magnitude bound but pays selection logic
and its own parasitics. Keeping original8-bit q with a joint decoder is another
implementation choice for all representations; its decoder is not free.
For the actual symmetric quantizer, balanced9 has no installed-binary-capacity
advantage over the strongest original baseline. Activated capacitance savings
also assume unused capacitors can be disconnected without unmodeled load/noise.

The [p50/p95 physical fixtures](../../../../../build/campaign/system_audit/physical_fixture_balanced9)
preserve the original column selection, exact q/x, scales, smoothing, full dot
products and byte-identical activation archives. P50 low capacitances are
2300/2460/2288/2380/2404/2412/2484/2400 fF and high capacitances
1320/2696/3244/3400/2504/2592/2616/2372 fF. Labels remain the original
signed-magnitude percentiles, not newly selected radix9 percentiles.

A negative verification result is preserved: the first export failed an
int64 dot-product assertion at an extreme int8 weight. Adding4 before division
had overflowed in the narrow array dtype. The initial static loading helper
had the same weakness, and its narrow reconstruction assertion could wrap as
well. Both failed artifacts were retained; widened int16 digit arithmetic,
complete-int8 endpoint checks and int64 weighted reconstruction now pass.
The corrected balanced9 total is4.11080 µF, replacing the initial4.11239 µF
loading value. Frozen histogram-level formulas were already wide and unchanged.

The independent [quality checker](../../../../../scripts/compiler/metrics/imc_radix9_precision_campaign.py)
and [protocol](../../../../../build/campaign/radix9_precision/protocol.json) were frozen
before new calibration. Protocol SHA256 is
`760f2d3dad25b38576a202ad1838dc770170f65168552b45b793b293d181941b`.
It compares balanced9 with original16 at both Cu4/Cu8, all three architectures,
both precision policies, and the same old-calibration-only depths/spans and
exposed-passage quality gates. Original calibration choices must exactly match
the earlier experiment. New source endpoint, ragged-sum and seeded-noise
quantizer controls pass. Each Cu will run72 cases; calibration is currently
running. Reserved data and existing balanced16 fixtures remain untouched.

Odd-radix arithmetic and nonbinary CIM are established general principles.
The exact weight-format/cell-bank tradeoff needs a targeted prior-art check;
no novelty, full-model quality or physical area claim is made at this stage.

### A separate equal-unit installed-capacity bound

There is a useful distinction between minimizing average activated magnitude
and minimizing installed programmable capacity. Assume two integer digit banks
with independently signed contiguous bounds |L|≤A, |H|≤B, equal capacitor
unit, and q=L+R*H. Covering every integer through127 requires gap-free digit
intervals, hence R≤2A+1. Therefore, for s=A+B,

```
127 <= A+(2A+1)*B = 2*A*B+s <= floor(s*s/2)+s.
```

The minimum integer s is15. A=7,B=8,R=15 attains it exactly over−127…127.
Physical capacitor bases [1,2,4] and [1,3,4], each with independently programmed
coefficients−1/0/+1, cover every low digit−7…7 and high digit−8…8. The
[exact subset check](../../../../../build/campaign/weight_digits/installed_radix15_bound.json)
verifies those ranges and the complete255-value weight coverage. These six
capacitors total15 units before the matched holder. Full symmetric support
through magnitude128 instead needs16 units under the same assumptions.

This is an ideal representation bound, not a physical cell-area optimum.
Three-way bottom selection, capacitor matching, noise, storage, programming,
and `16H-H+L` reconstruction still cost resources. Direct storage of six
ternary controls needs12 binary bits; retaining original8-bit q needs a paid
joint decoder. Conventional binary-weighted banks still install22 units for
this radix15 choice. Unequal low/high unit sizes or non-contiguous digit sets
fall outside the stated bound. Radix15 is retained as a later programmable
topology control; the active radix9 and balanced16 grids remain unchanged.

## Completed balanced16 quality grid

Both [Cu4](../../../../../build/campaign/balanced_precision/quality_Cu4.json) and
[Cu8](../../../../../build/campaign/balanced_precision/quality_Cu8.json) complete all72
cases with final source/model/calibration integrity checks passing. The
[summary](../../../../../build/campaign/balanced_precision/summary.json) retains all24
configurations and their full paid service/capacitance counters. Every entry
below requires both passages, quantization-only and both noise seeds:6/6 is
the gate; five successful cases do not qualify a configuration.

| Format/Cu | A10 separate minimum | A10 separate economy | A11 separate minimum | A11 separate economy | A10 pool minimum | A10 pool economy |
|---|---:|---:|---:|---:|---:|---:|
| Original16/Cu4 | 5/6 | 6/6 | 6/6 | 5/6 | 6/6 | 6/6 |
| Balanced16/Cu4 | 6/6 | 5/6 | 6/6 | 5/6 | 6/6 | 6/6 |
| Original16/Cu8 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 | 6/6 |
| Balanced16/Cu8 | 5/6 | 4/6 | 5/6 | 5/6 | 6/6 | 6/6 |

Totals are68/72 individual passes at Cu4 and67/72 at Cu8. All failures are
on the Exception passage's PPL gate; none is hidden by averaging. In
particular, every balanced16/Cu8 separate configuration fails at least its
quantization-only PPL case. Larger capacitors do not force monotonic quality
when their frozen precision/range optimization also chooses a different
quantizer. No threshold or calibration choice was adjusted after these results.

The useful Cu4 economy pool has worst KL0.00899861 and PPL ratio1.00850402,
connected-C4.748597 µF,2.038137 billion ADC decisions and9.159168 million
rounded bit-service steps per512-token passage. Its maximum ADC depth is13.
The strong original Cu4 A10 separate economy control also passes all6, with
6.925364 µF,6.265405 billion decisions,25.380352 million rounded bit steps,
and maximum depth13. Relative to that baseline, the candidate reduces the
connected-C proxy31.43%, ADC decisions3.074×, and rounded bit service2.771×.
It pays1.76–1.82% more column-plane events across the two passages because pooling shares the largest
activation plane count within each logical group.

The per-MVM maximum-depth controls are27.273216 million steps for that
separate baseline and9.267200 million for the candidate; fixed global14-depth
controls remain30.105600 and11.182080 million. These are explicit alternative
service schedules, not measured asynchronous throughput. The best original
Cu4 pooled economy control uses6.817964 µF and2.080801 billion decisions;
balanced16 reduces connected C30.35% but decisions only2.05% relative to it.
The strongest balanced16 separate minimum-error control also passes, leaving
only about4.26% additional connected-C reduction from pooling itself.

**STRONGLY SUPPORTED only under the frozen optimistic noise model.** These
are full-depth development-model results with2kT/(3C) sharing-only thermal
noise and an assumed independent20-µV final read error. Array-reset noise,
initial holder reset, measured ADC correlation, installed programmable storage,
weight switches, real references and complete PPA remain unqualified. The
new reset-noise control may invalidate these survivors. Reserved corpus slices
remain untouched. The separate radix9 grid is still running.
