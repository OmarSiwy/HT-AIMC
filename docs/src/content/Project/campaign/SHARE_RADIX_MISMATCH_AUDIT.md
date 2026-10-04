# Charge-sharing mismatch and group-model interface audit

Status: **VERIFIED algebra and actual-code loading calculations; conditional
mismatch sensitivity, not physical yield or end-to-end quality**.

## Group128 model boundary

`scripts/compiler/metrics/imc_group128_precision.py` uses one scalar computational
holder C and an independent equal reference holder C. Its charge variance
2*kT*C+(50uV*C)^2 is dimensionally correct in fC² after converting kT by1e15.
Noise is injected once before the existing deterministic ADC quantizer. Ragged
64-row tails are masked out of physical code loading. The existing geometry's
`connected_C_fF` includes array+computational holder (2C) plus the split-CDAC
physical tail; separately adding `reference_holder_C_fF` produces3C+tail.
It does not represent two weight arrays. The reference circuitry, charge
covariance, dynamic radix matching and ADC mismatch remain unimplemented.

The raw32 model instead pays one scalar kT/C relative to an ideal reference.
Its result cannot be assigned the earlier two-independent-holder FIA fixture's
noise without a new protocol. Both models' ADC calibration minimizes error plus
noise variance, with bits only as a tie-breaker. It does not minimize energy or
latency. Selecting very fine quantization below the50uV read RMS therefore does
not establish minimum-cost resolution.

## Exact recurrence and coordinates

Let A be the array capacitance participating in sharing, H the holder, and Qm
fresh row-driven charge on activation plane m. With previous holder voltage v,

```
v_next = (Qm + H*v)/(A+H)
r = H/(A+H)
v_B = sum_m Qm/(A+H) * r^(B-1-m)
```

Planes run least significant first. At A=H=C the ordinary binary result follows.
For A=C+dA, H=C+dH,

```
(r-1/2)/(1/2) = (dH-dA)/(2C) + O(dC²/C²) = e
```

The distinction between voltage and physical charge matters. If the ADC reads
holder charge H*v, a plane's coefficient relative to the ideal value is
(2r)^(B-m). If one instead multiplies the voltage by nominal C, there is an
additional common factor C/H. That common factor can be separately calibrated;
the varying power of r cannot be removed by one column gain.

After calibrating the most recent plane, a plane k shares earlier has relative
coefficient(2r)^k, approximately1+k*e. Thus a B=10 word has low/high bit-ratio
error about9e. Exact physical tracking H=A sets r=1/2 and also removes charge-
coordinate gain error. There can still be a nominal-voltage gain C/A and actual
ADC-unit error. The raw diagnostic JSON field
`ideal_tracking_holder_remaining_gain_sigma` refers ONLY to that nominal-voltage
coordinate; it must not be described as an unavoidable physical charge error.

Measuring r is not sufficient to recover a conventional dot product from one
already-combined scalar output: the contributions of different input bit planes
are no longer separately observable. Correction requires physical matching,
per-plane compensation, extra partial readouts, or an explicitly qualified
error-aware computation scheme. Per-weight numerator calibration alone does not
correct this activation-bit weighting.

## Actual-code PDK sensitivity calculation

`build/campaign/share_radix_mismatch/audit.py` reads all210 actual GGUF matrices,
original Q8_0 group32 codes and independently regenerated group128 FP16-scale
codes. It uses each group's frozen selected ADC host loading and valid ragged
rows. Results are in the adjacent `result.json`.

For each selected4/8/16/32fF binary MIM capacitor,
C=2u²+0.76u fF and fractional sigma=0.028/u from the existing PDK mismatch
model. Independent selected-device variances sum into dA variance. This assumes
dA/dCselected=1, treats the measured MOS/parasitic/120fF floor as deterministic,
and adds independent bulk-square padding mismatch. The holder is modeled as one
independent bulk-square capacitor of value C, an optimistic implementation
compared with some segmented mosaics. Common process variation, spatial
correlation, MOS parasitic mismatch and actual CDAC correlations are omitted.

```
Var(dA) = sum_selected sigma_Ci² + sigma_padding²
Var(e) = [Var(dA)+Var(dH)-2Cov(dA,dH)]/(4C²)
```

The quoted numbers set Cov(dA,dH)=0. The same per-device mismatch draw must feed
both numerator and dA in a future simulation: independently redrawing dA would
lose real correlations. Selected numerator errors with sign removed and summed
can recover the selected-cap part of dA, but cannot recover omitted unselected
or MOS capacitance sensitivity.

| Median statistic across group-columns | raw32 | group128 |
| --- | --- | --- |
| Nominal C |883.11fF|2791.53fF|
| sigma array capacitance |1.0137fF|1.8200fF|
| sigma bulk holder capacitance |1.1874fF|2.1028fF|
| sigma(r)/r |0.08842%|0.04983%|
| B10 low/high bit-ratio sigma |0.79579%|0.44845%|
| Ideal gain-calibrated uniform-code RMS / code RMS |0.03877%|0.02185%|

The last row is a bounded scalar-code sensitivity, not a transformer accuracy
measurement. Enumerating all unsigned10-bit magnitudes gives
h(q)=sum_m bit_m(q)*2^m*(9-m). Removing the best linear gain from h yields
RMS(h-alpha*q)/RMS(q)=0.43845054. Multiplying by sigma(e) gives the table.
The linear expression agrees with exact(1+e)^k code enumeration at e=1e-5 to
relative9.5e-7. Signed symmetric magnitudes have the same normalized result.
Actual activation distributions, cancellations, group scales and correlations
must be propagated in the full model before making an accuracy claim.

## Fixed holder across reuse phases is a larger failure mechanism

A separate deterministic diagnostic installs H equal to the maximum nominal
array C among the physical256-row tile's phases: eight phases for raw32, two for
group128. It performs no per-phase array padding or holder reconfiguration.
Then r=H/(Aphase+H), even with perfect capacitors.

| Statistic | raw32 reuse8 | group128 reuse2 |
| --- | --- | --- |
| Median r |0.520515|0.5|
| 99th percentile r |0.571570|0.569671|
| Maximum r |0.702243|0.698810|
| 99th percentile B10 low/high coefficient excess |233.35%|223.51%|

One member of each reuse2 pair is the maximum by construction, explaining its
median exactly0.5. Ragged tails contribute extreme unequal loading. The large
relative LSB distortion does not directly equal the total MAC error, but it
unequivocally falsifies assuming ordinary binary transfer with a fixed holder
and changing unpadded array capacitance.

The frozen system models explicitly assume ideal per-phase matching, so these
calculations do not retroactively change their arithmetic results. They identify
hardware that must be paid: configurable holder, compensating array padding,
replica tracking, or a different transfer architecture. Padding to the maximum
can restore nominal r but increases connected capacitance, charge energy and
noise when referred to a fixed charge signal. The reference holder and native
CDAC mapping must track the selected implementation as well.

## Unverified and preserved alternatives

Physical holder trim resolution, calibration/stability across PVT, code-dependent
MOS loading, interconnect, switch injection, capacitor correlations, ADC carry
mismatch and full-depth inference remain unverified. Numerator-only die results
must retain their explicit ideal-radix qualification.

A possible later architecture shares one reference holder among several FIA
columns. Increasing its capacitance to N*C reduces its reference voltage noise
while consuming the same nominal capacitor area as N individual references.
Its errors become correlated across columns, and summed FIA Cgd creates signal
coupling. Neither low-rank calibration nor layer-normalization rejection is
assured after unequal output scales. This is a future charge-matrix question,
not a free-area or noiseless-reference result.

## Candidate physical matching implementations

A full replica programmable bypass bank used as H can track nominal code-dependent
A: use the same installed capacitors and TGs with quiet row sources atVCM and
retain the same code/sign controls. This removes the gross fixed-holder versus
changing-code loading mismatch. It does not remove independent local capacitor
mismatch, array/holder voltage-dependent capacitance differences, or routing.
The computational array's driven rows and retained holder's quiet rows do not
have identical transient bias trajectories.

For Cu4, one low3-bit plus high4-bit weight site installs28+60=88fF regardless
of the active code. Array plus one full replica holder installs176fF/site;
array plus two ping-pong replicas installs264fF/site before bulk reference and
receiver capacitance. With the shared sign selector, the two banks use16+20=36
MOS/site, becoming72 with one replica or108 with two. These are expanded circuit
counts, not layout area. Each retained replica needs its old code/sign controls
held while the computational bank programs the next group: changing the holder's
code changes its capacitance and can disturb the stored result. Control storage,
clock routing and programming energy are therefore part of this architecture.

A grounded-inactive array gives nearly constant installed capacitance and permits
a fixed bulk holder without replica bank TGs. Its physical MIM burden can be
comparable to the replica approach, but its larger connected capacitance reduces
signal voltage and worsens noise referred to fixed signal charge. Its native
read requirements must be re-evaluated. Configurable bulk H or per-phase array
padding are additional implementations, each requiring control, capacitance
matching, state retention and transition-noise accounting.

The system branch independently added a complementary absolute-error diagnostic
in `build/campaign/radix_scalar_gain_bound.json`: at fractional r error0.0498%,
a B10 scalar with one full-scale gain calibration has maximum residual0.02466%
of full scale, rising to0.07397% at three times that pole error. This is
consistent with the modest gain-calibrated RMS reported above and reinforces
that relative LSB/MSB distortion must not be presented as absolute MAC error.
The large deterministic r=0.56967 fixed-holder case still gives approximately
7.27% FS residual after scalar gain correction. These are code-oracle results,
not a physical matching implementation or inference validation.
