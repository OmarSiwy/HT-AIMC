# Shared signed-digit codes for an uncertain charge-retention ratio

**VERIFIED bounded arithmetic experiment; SPECULATIVE circuit-sizing method.**
The [source](../../../../../scripts/compiler/metrics/imc_nonbinary_activation_campaign.py) asks
whether one input code table can tolerate a common radix error plus bounded
column variation. It does not give every column its own input code. Two
explicitly hypothetical intervals,0.500±0.001 and0.503±0.001, were frozen
before table construction. These are not measured device distributions.

Protocol SHA-256 is
`9a015c5595d654cfb0a4dbeaab0098fd4fb81c6d8cbff9bf87a8b3fa70be7d0a`.
The results,
tables, source
snapshot and66 independent unpruned checks are retained in that build directory.
Circuit-branch code review found no algebraic error within the declared model.

## Physical model and calibration boundary

Let `r=D/(A+D)` for holder capacitance D and local array A, and let
`kappa=Cu*Vs`. A sharing step obeys `Q_next=r*Q_previous+r*kappa*d`.
For most-significant-first digits `d_j`, physically transmitted in reverse
order, the completed charge is `Q=r*kappa*sum_j d_j*r^j`.

Both binary and ternary candidates receive the same ideal per-column zero
and full-scale511 gain calibration. In calibrated input-code units the result is

```
F_r(d) = 511 * sum_j d_j*r^j / sum_{j=0}^8 r^j.
```

The denominator always describes the original nine binary significant digits.
Ten/eleven physical planes append one/two earlier fractional digits, so the
original nine digit significances stay fixed. At r=0.5 this reduces to ordinary
integer arithmetic with optional0.5/0.25-code fractional digits. Each additional
plane is paid; there is no free rescaling or conversion cancellation.

The gain calibration assumes exact stable r and zero/full-scale response,
without calibration noise, drift, nonlinear ratio changes or cost. It is a
favorable common control, not a physical calibration implementation. A fitted
gain from real calibration MVMs could change both methods' dot-error results;
that stronger weighted-calibration comparison remains unverified.

## Exhaustive bounded search

For each interval and plane count L=9/10/11, enumerate all3^L signed sequences.
For every positive integer0…511, minimize maximum absolute error on11 evenly
spaced r values. Negative operands use exact sign inversion. Binary coding
provides an initial upper bound. A candidate whose nominal-r error exceeds
that bound cannot win and is safely pruned. Ties within1e−12 code units are
resolved by a transition-cost proxy, active digits and deterministic index.

After selection, audit1001 r values across each interval. This is a dense-grid
check, not a proof of the continuous-interval extremum. Separately,66 checks
across both intervals and all plane counts enumerate every candidate without
pruning and reproduce the selected minimum to1e−10 code units. Recurrence,
binary arithmetic, zero and signed W8 slice reconstruction selfchecks pass.

## Result and costs

| r interval | Planes | Worst activation error, binary | Worst activation error, shared ternary | RMS error over codes/r, shared ternary | Mean active digits |
|---|---:|---:|---:|---:|---:|
| .499… .501 | 9 | .5030 | .5030 | .11645 | 5.047 |
| .499… .501 | 10 | .5030 | .5002 | .11783 | 5.064 |
| .499… .501 | 11 | .5030 | .4891 | .11645 | 5.109 |
| .502… .504 | 9 | 2.0110 | .8275 | .19549 | 5.518 |
| .502… .504 | 10 | 2.0110 | .5496 | .14844 | 5.971 |
| .502… .504 | 11 | 2.0110 | .5335 | .12556 | 6.531 |

Binary has4.5 mean active digits and RMS error0.15893 or0.83994 for the two
intervals. Nine ternary planes therefore correct much of the hypothetical
common0.003 radix shift without another plane, but increase active digits
22.6%. Ten/eleven planes cost11.1%/22.2% more cycles and32.7%/45.1% more
active digits for that interval. At the interval centered on0.5, extra planes
barely improve worst error and can worsen average error because minimax is
a different objective. These negative results are retained.

For a driver resetting to zero each plane, a simple squared-voltage proxy is
twice the active-digit count. For a driver retaining its prior level, the
proxy sums squared successive digit changes, including start/end reset.
In the shifted interval that second proxy rises from binary5.0 to8.961,
9.637 and10.379. Neither includes actual row capacitance, short-circuit power,
clocking or zero-plane analog reset costs. A straightforward shared lookup
requires512*L*2 bits, or1.125/1.25/1.375 KiB per table. Distribution, lookup
latency, table replication and per-plane sign control still need pricing.

The tables freeze before weighted tests. Real p50/p95 W8 low/high coefficients
use independent per-slice column ratios held constant across all plane counts.
Inputs are128 uniform signed words,128 clipped heavy-tail words and the three
existing development fixture words. These tests are independent of table
selection, but are not untouched full-model corpus validation.

For shifted-r p50 development words, binary dot RMS304.56 MAC becomes46.66,
37.64 and29.10 with9/10/11 planes. The p95 fixture gives425.23→74.46,49.57
and43.23 MAC. These improvements do not imply those absolute errors satisfy
the dense physical or model budget. Fixed r, ideal gain calibration and noiseless
linear superposition are essential assumptions; sharing/switch noise and
fixed weight errors are absent.

## Prior art and retained hypothesis

Noninteger radix coding and robustness to component errors are established
ideas: [beta encoders](https://scholars.duke.edu/publication/767444) and the
[golden-ratio encoder](https://arxiv.org/abs/0809.1257) explicitly address
imperfect quantizers/gains. Input radix recoding and signed-digit weight
representations also appear in [prior CIM work](https://arxiv.org/abs/2101.02419).
The local archive's redundant differential-weight programming experiment is
different from this shared activation table, but its existence also prevents
any broad claim that coding around mismatch is new. A targeted search for the
exact bounded-column-r activation-table formulation remains incomplete.

The retained hypothesis is narrow: if a cheaper physical cell has a stable
common radix offset with a sufficiently small column spread, shared signed
digits might trade row switching for reduced analog matching/trim requirements.
Next steps need a calibration-only measured r distribution, frozen new tables,
real signed row-drive validation, full weighted gain/noise modeling and the
strongest alternative of simply repairing the capacitor ratio. No area,
energy, throughput or novelty advantage is established here.

Root's later calibration-only end-of-cycle fit on the explicit-geometry dense
p50 fixture gives r approximately0.50001966…0.50002920, with0.152–0.203-µV
fit residual. A misleading pre-opening fit omitted edge injection and was
rejected. The hypothetical0.503 interval studied here is therefore not an
optimization needed for that nominal dense circuit. Intentional mismatch or
a cheaper differently sized cell would need its own measured interval.

## Exact continuous-interval certificate

A separate checker
and result
close the gap between grid points without modifying the frozen tables or
selection algorithm. For one code x, let N(r)=Σd_j*r^j and D(r)=Σj=0…8*r^j.
D is strictly positive on both intervals. Proving

```
U*D(r) + (511*N(r) - x*D(r)) >= 0
U*D(r) - (511*N(r) - x*D(r)) >= 0
```

therefore proves the absolute code error≤U everywhere in the interval. The
checker converts each polynomial into the Bernstein basis with exact rational
arithmetic. Nonnegative coefficients certify positivity on the complete
interval; where the coefficient hull is inconclusive, exact de Casteljau
bisection certifies both halves. No floating-point root finder or sampled
positivity assumption enters that proof. Every code0…511 in each table and
each binary control is checked. A positive polynomial requiring subdivision
and a negative-endpoint polynomial provide acceptance/rejection controls.

| Retention interval | Binary upper bound | Ternary9 | Ternary10 | Ternary11 |
|---|---:|---:|---:|---:|
| .499–.501 | .50303663 | .50303663 | .50024855 | .48908195 |
| .502–.504 | 2.01104610 | .82751949 | .54956304 | .53346830 |

**VERIFIED exact continuous bounds:** all certificates pass. The bounds are
rounded upward within2e−8 code of the previous dense-grid maxima. The
.499–.501 ten-plane case needs at most six subdivisions; the other cases
certify directly. This proves the frozen tables' bounds, not that their
sampled-grid selection is globally optimal for the continuous minimax problem.
It adds no device, energy or full-model validation.
