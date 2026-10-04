# Split-DAC radix error does not by itself reject the architecture

Status: **VERIFIED conditional arithmetic counterexample; physical ADC
unverified**. The native circuit measures bit0 and bit3 charge-step slopes.
Other bit weights and state independence are assumptions pending the next
physical sweep.

`build/campaign/split_dac_code_critic/audit.py` independently checks archived
result hashes and recomputes the measured coarse/fine ratios:
8.128533587 for native MOS with ideal mutual capacitors and8.259299669 with
contact-coupon substrate parasitics. It constructs all128 levels and checks
250003 numerical inputs against an explicit seven-decision descending SAR.
Detailed levels, edges, reconstruction values and MSE results are in the adjacent
`result.json`.

## Physical levels and actual decision rule

Assume weights [1,2,4,R,2R,4R,8R] in fine-LSB units. Code n=8h+l has level
L(n)=R*h+l, h=0...15 and l=0...7. There are112 unit interior gaps and15 carry
gaps R-7. At R=8.259299669, the carry gap is1.259299669 fine LSB. This is real
nonuniform level spacing under the assumptions; digital calibration cannot
insert missing physical levels.

Nevertheless, it need not materially harm the mean-square objective. All weights
are superincreasing for R>7: each exceeds the sum of all lower weights. A SAR
that tests the next DAC weight and retains it when x>=DAC therefore selects the
largest physical level <=x. It is a **floor quantizer**, not nearest-level
quantization. The independent explicit decision loop matches that floor oracle
for all tested inputs. A different comparator/reference convention can shift
thresholds; this fixture has not implemented that controller.

For a complete128-bin example choose the external input range[0,16R]. The first
127 edges are actual transitions between levels; the upper endpoint16R is an
explicit range convention, not an extra realizable DAC level. This gives sixteen
blocks, each with seven width1 bins and one width(R-7) bin. Different endpoint
clipping rules change endpoint terms and must be specified in a real ADC.

## Calibrating bin outputs, not pretending thresholds moved

For uniform input, the best reconstruction for each measured bin is its center.
That changes digital output values; it does not move physical comparator
thresholds or make the SAR a nearest-level search. Here the center is

```
xhat = R*h + l + 1/2                         if l<7
xhat = R*h + 7 + (R-7)/2                    if l=7
```

Thus exact binary sub-arrays would need only common gain/offset and R plus a
low-code-equals7 correction, rather than an arbitrary128-entry table. Real bit
mismatch or state-dependent transitions can require more calibration storage.
Measuring only bit0 and bit3 is insufficient to establish this compact model.

The mean-square error over the declared uniform range is exactly

```
MSE = [7 + (R-7)^3]/(12R)  fine-LSB²
```

An ideal128-bin uniform quantizer with the **same physical full-scale span** has
MSE=(R/8)^2/12. Comparing equal coverage avoids calling the larger actual span
free extra resolution.

| Result | Native MOS | Contact coupon |
| --- | --- | --- |
| R |8.128534|8.259300|
| Calibrated bin-center MSE, fine-LSB² |0.086499|0.090777|
| Ideal same-coverage MSE |0.086033|0.088823|
| Quantization variance penalty |0.542%|2.200%|
| Gain/offset-calibrated ordinary binary-label MSE |0.087386|0.094330|
| Uncalibrated ordinary binary midrise-label MSE |1.38464|5.38104|
| Physical-weight label without centering MSE |0.345995|0.363108|

The last row is four times the bin-center MSE, because it reports a lower edge
rather than a center. Adding half a fine LSB to physical-weight labels largely
fixes that bias, but differs from the correct center in carry bins. Nearest
physical-level quantization on the same finite range gives0.094555 for the coupon
case, including its distinct endpoint clipping; nearly half the tested codes
differ from the greedy floor decision. It was not substituted as the SAR oracle.

At61.035uV native fine spacing, the coupon bin-center RMS is18.389uV. The ideal
same-span RMS is18.190uV; the increase is equivalent to an independent2.698uV
RMS variance term. This is small compared with the proposed40--50uV additional
read-noise targets, but quantization is already separately included in the
system model. Do not add this total18.389uV inside that additional-read knob or
claim the receiver passes because the incremental quantization term is small.

Actual measured coupon slopes give97.70245uV native step per volt of diagnostic
reference, after the frozen119ns gain calibration. A61.035uV native fine step
therefore needs about0.624703V reference swing under this local linear model,
not the0.587V predicted by ideal capacitor ratios and approximate gain. Reference
range, common mode and signal history need physical qualification at that swing.

## What this establishes and what remains

This is a counterexample to rejecting a circuit solely because a carry gap has
DNL+0.2593: calibrated reconstruction can leave only a2.2% quantization-variance
penalty under the stated assumptions. Analog bridge trimming is therefore not
required by that number alone. Generic weight and code-center calibration are
known techniques, not a novelty claim.

A real SAR still requires all seven weights, all carry/state-dependent
transitions, acquisition and hold history, comparator offset and per-decision
noise, kickback, reference settling, calibration error/drift and PVT/mismatch.
Digital calibration cannot repair irreversibly disturbed held charge. Readout
FIA noise, reference-holder noise and nonuniform activation distributions can
dominate this small quantization penalty. Existing group128 noisy quality
results fail independently of this hypothetical fine-DAC correction.

## Update with all seven physically measured weights

`build/campaign/split_dac_code_critic/actual_weights.py` independently verifies
all four source-result hashes in `fia_dac_weights/combined_r3.json`, recomputes
the169ns positive weights and all128 superposition levels, and repeats the
explicit greedy SAR check on250003 inputs. The measured normalized weights are
[1,1.999998909,3.999994106,8.259373156,16.518824531,33.038131834,66.079524100].
All superincreasing margins remain positive; minimum gap is0.99999520 and
maximum gap1.26320156 fine LSB. This computes128 levels from seven physical
measurements; it does **not** physically measure128 complete SAR transitions.

Choose the explicit external range S=2*measured_MSB=132.1590482 fine LSB.
Using the actual seven weights to construct bin centers gives MSE0.09080080.
Using only measured bit0 and bit3 plus binary sub-array weights to construct
centers gives0.09081327. The ideal equal-coverage128-bin MSE is0.08883674.
Thus full-weight quantization variance is2.2109% above ideal; the compact
calibration adds just0.00001246 fine-LSB² beyond full seven-weight calibration.
Its largest center error is0.0071635 fine LSB (about0.437uV at61.035uV spacing).
This supports trying the compact calibration before paying analog bridge trim
or a full arbitrary code table, within the measured regime.

Two independently measured, drift-corrected carry discrepancies are+0.487082
and-1.042799uV output for7→8 and63→64, respectively. With measured gain18.03876,
the larger is0.05781uV native. The largest measured static-code superposition
error, code63, is1.53731uV output or0.08522uV native. Final transition endpoints
also agree closely with their separately initialized static targets. These
numbers bound only the observed cases at0.25V diagnostic steps. They are not
worst-case limits over all codes, opposite carry directions, reference swings,
PVT, mismatch or arbitrary history. The76 characterization frames and their
warmup energy remain paid; the uninterrupted monolithic sequence did not
numerically complete.

## Recommended next complete-search fixture

Implement all seven decisions of a **fine SAR** on the actual isolated FIA
output, retaining the real split network and initially testing compact bit0/3
calibration. Use real bottom-reference rails0.9±0.3125V:0.625V full step. The
locally measured transfer predicts approximately61.06uV native fine spacing
and ±4.03mV coverage. This is sufficient for the illustrative typical raw32
0.25V native span with seven coarse bits and conditional5sigma403uV decision
guard (required residue half-range about2.992mV). It does not cover all selected
raw32/group128 accuracy requirements. The actual0.625V reference swing is2.5
 times the measured0.25V diagnostic swing, so linearity must be retested.

Signed operation requires physical initialization and switching of every bottom
plate between the two reference rails, with control polarity verified against
the actual comparator and charge sign. An ideal assignment of the stored node,
a numerical DAC correction voltage, or an assumed nearest-level oracle is not
acceptable. Evaluate codes and reconstruction against the measured decision
bins, including saturation edges. The original scalar-floor oracle is only a
reference for the correctly initialized search.

The existing200ns fine reset and holder reconnection are too early for a
conservative seven-cycle search. One explicit initial qualification schedule is
trial at80+30j ns, latch evaluation beginning84+30j, decision read102+30j, and
latch reset104--106+30j for j=0...6. The final read is282ns. Keep holder/fine reset
and next acquisition until after300ns, and allow a frame of at least360ns.
Internal FIA reset can also be postponed during this first search qualification
so its clock edge does not obscure search failures; it must remain paid before
next acquisition. This is a deliberately explicit test schedule, not optimized
latency, a working coarse-plus-fine converter, or a throughput result. After
search correctness, measure whether shorter cycles and overlapping reset can
preserve accuracy before making a pipeline claim.

The complete search must expose actual output kickback from every comparator
cycle, reference settling, state-dependent steps, startup, full code coverage
and fresh input history. Noise qualification and a physically integrated coarse
stage remain separate next tasks.

## Independent audit of the implemented causal-prefix controller

The stack branch's `tb_imc_fia_fine_sar.py` implements an unsigned floor search
with a physical signed offset, not neutral-start signed successive corrections.
After common-mode acquisition and isolation, all positive-side DAC bottoms
physically connect LOW at72ns. Trials occur80+32k, actual latch outputs are read
104+32k, and the accepted mask is physically applied106+32k for k=0...6.
Every route change uses real complementary TG edges and break-before-make.
Unprocessed bits stay LOW.

Let w_i be the old positive output weights measured for a+0.25V bottom change,
W their sum and L(c)=sum_i w_i*bit_i(c). With actual rails0.5875/1.2125V,

```
D(c) = 2.5*L(c) - 1.25*W
held_residue approximately G*Vin + O - D(c)
interior input bin = [(D(c)-O)/G, (D(c+1)-O)/G)
reconstruction = [(D(c)+D(c+1))/2 - O]/G
```

The weight source explicitly defines positive weight as zero-output minus
positive-DAC output, so retaining a trial when the physical latch says residual
>=0 has the correct polarity. The implemented frozen oracle and interior
centers use these equations. Endpoint codes0/127 are flagged rather than given
unjustified centers. A neutral-CM, measure-then-apply signed algorithm would have
different decision thresholds; it is not the implemented controller.

Each prefix replay regenerates the physical sequence from its real initialization,
never copies analog node voltages, and checks that all previous transistor-latch
choices repeat. The final full replay certifies all seven choices. The final
LSB rejection, if any, is applied298ns before the308ns physical-bottom check;
CM reset begins318ns and holder reconnection320ns. Two360ns zero warmup frames
remain paid for each input. New reference sources and all42 new per-route gate
sources enter the final positive-port energy calculation. Digital sequencing
hardware remains unpriced.

The new third OFF TG, larger reference swing, changing decision times and longer
hold make old gain/weight calibration explicitly provisional. The actual code
match against that frozen prediction is a falsification gate, not an assumption
that old calibration applies. In particular, the new latch read occurs12ns after
clock evaluation begins, so the earlier403uV conditional latch noise must not be
imported as its measured noise. Internal FIA reset110ns and input reacquisition
120ns remain real potential disturbances during the isolated search. No fatal
polarity, initialization, endpoint or causal-prefix issue was found in this
source review; numerical and physical results are still required.

## Independent four-case physical SAR certificate audit

`build/campaign/fia_fine_sar_independent/audit.py` independently checks the four
result hashes, all28 prefix-result hashes, identical frozen-calibration files
and their source hashes, and final replay deck hashes. It reads final raw traces
to recompute the31ns native input, every pre-clock residue at90+32k ns, every
rail-resolved latch decision at104+32k, trial bottom voltages, final programmed
bottoms308ns, reset359ns and integrated positive-port energy. Its result is in
`fia_fine_sar_independent/result.json`.

All checks pass for this bounded TT subset. No new simulation or calibration
fit was performed.

| Driven input,uV | Actual native31,uV | Code | Frozen reconstruction error,native uV | Minimum pre-clock output margin,uV |
| --- | --- | --- | --- | --- |
|+377|+381.11538|69|-7.45659|417.278|
|-377|-381.11538|57|+5.74341|417.306|
|+911|+920.94459|78|+18.27304|237.065|
|-911|-920.94459|48|-19.98623|237.029|

Every actual input lies in the corresponding frozen-calibration bin; these
bins have approximately61.08uV width. Acquisition changes the driven value, so
errors relative to driven input are different and must not be substituted for
errors relative to the measured native input. Maximum trial-bottom deviation is
59.50nV. Final reset residual is8.72--9.04uV at held nodes. All pre-clock signs
agree with the later resolved decisions; the margins do not use signals after
latch kickback.

The smallest pre-clock margins correspond to13.14--23.13uV native at frozen
gain18.03876. If, only illustratively, the old403uV latch RMS and Gaussian model
applied, those are0.588--1.035sigma, giving about28%--15% single-decision tail
probabilities. The current latch timing and connected load are different, so
these are not measured error rates. FIA noise is shared across the seven
comparisons, while comparator and switching noise may have other covariance;
independent per-bit noise cannot simply be assumed. Small margins are normal
near quantizer boundaries, and occasional adjacent-code changes do not by
themselves reject an ADC. This comparison establishes why four noiseless code
passes cannot establish receiver noise or inference quality.

Active-frame energy is3.1590--3.1839pJ. Each input also uses two360ns physical
zero warmups costing4.60523pJ total, so the characterized complete sequence is
1080ns and7.7642--7.7891pJ per tested input. Offline prefix replays are simulation
work, not hardware energy; the final replay's two warmups are actual physical
operations and cannot be omitted from the characterized service cost. A
continuous360ns initiation interval remains unverified.

### Quantitative next falsification

The frozen actual-native threshold for code64 is37.721334uV; code65 is
98.800942uV. Test each threshold at±5uV for four new cases, preserving the same
calibration. This probes a major carry and an ordinary fine transition with
approximately90uV output margin, about1/12 of a fine native step. It tests
threshold placement and near-threshold resolution without pretending that exact
threshold inputs must always resolve to a unique noiseless code.

Then test physical history sequences+3mV→just below the code64 threshold and
-3mV→just above it without the intervening two zero warmups. The input drive
must be translated to the intended native voltage through the actual acquisition
boundary, not assigned to the held node. This isolates whether the presently
paid warmup/reset protocol is essential. No frozen coefficients should be fit to
these new points. Full code coverage, opposite carry directions, repeated
stochastic trials, PVT/mismatch and physically integrated coarse conversion
remain separate requirements.
