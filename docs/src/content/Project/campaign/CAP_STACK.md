# Passive voltage boost of a native holder

This experiment asks whether a retained MAC voltage can be sensed at larger
amplitude by reconnecting its physical storage capacitors from parallel to
series. It is a new **SPECULATIVE integration candidate**, not a new generic
switched-capacitor principle. The first fixture uses external physical
acquisition, not an array or complete converter. Prior-art checking is
separate; no novelty is claimed.

The source is tb_imc_cap_stack.py.
It has two matched stacks, real Sky130 transmission gates, an actual
acquisition phase, explicit output load/reset, series connection, and return
to parallel storage. Optional sensing uses the actual balanced StrongARM from
the [dynamic-readout round](DYNAMIC_PREAMP.md). The nominal total capacitance
of each stack is 6.98 pF, chosen to investigate a larger native column holder.
That is a sizing hypothesis; the fixture does not implement that real column.

## Charge, loading, and noise identities

Let one holder consist of N capacitors Ci whose sum is CA. During computation
or acquisition, all top plates are joined and all bottom plates sit at VCM,
so every capacitor stores the **same result voltage h**. These are segments
of one holder, not unrelated row-group partial sums. Reconnecting their
voltages in series gives open-circuit output Nh and series-equivalent
capacitance

\[
C_\mathrm{eq}=\left(\sum_i\frac1{C_i}\right)^{-1}.
\]

A separately reset load CL initially at VCM then produces

\[
G=\frac{N}{1+C_L/C_\mathrm{eq}}.
\]

For equal segments, Ceq=CA/N², so

\[
G=\frac{N}{1+C_LN^2/C_A}.
\]

The equal partition maximizes Ceq and gain for fixed total CA by the
arithmetic/harmonic mean inequality. Unequal capacitors still have open-circuit
gain N if they began at the same voltage; their unequal internal node charges
must be preserved. The source's ideal self-check solves the full ladder
capacitance matrix for equal and unequal segments at N=1,2,4,8, rather than
assuming every internal node has zero charge.

The load must genuinely start at VCM. If it instead acquires h along with the
parallel holder, the gain is `(N+C_L/Ceq)/(1+C_L/Ceq)`, a different baseline.
The test has a separate output-reset switch, measures actual output state,
and counts the reset port. MOS charge injection can violate the ideal reset
assumption even when the differential matched-stack offset largely cancels.

After loading and isolating the output, equal segments return to parallel
with voltage `G h/N`. This charge loss is real. A passive boost is not a
non-destructive voltage-copy buffer. It may still be useful if the boosted
state is retained through the complete readout and consumed only once.

For an illustrative independently thermalized native holder and output load,
the native input-referred reset variance is kT/CA. Stacking scales its signal
and noise together. Including independent load reset noise gives

\[
\sigma^2_\mathrm{in,reset}=
\frac{kT}{C_A}\left(1+\frac{C_LN^2}{C_A}\right).
\]

Equivalently, the final output variance is kT/(Ceq+CL), divided by G² when
referred to h. This identity does **not** characterize the array's radix
switching noise, capacitor-partition covariance, or dynamic MOS noise. It
shows why passive voltage gain can suppress a subsequent comparator's
contribution without beating the original storage-noise floor.

For CA=6.98 pF at 300.15 K:

| N | CL | Ideal G | Native reset RMS | Conditional loaded input-referred reset RMS |
|---|---:|---:|---:|---:|
| 2 | 3 fF | 1.9966 | 24.37 µV | 24.39 µV |
| 4 | 3 fF | 3.9727 | 24.37 µV | 24.45 µV |
| 4 | 60 fF | 3.5164 | 24.37 µV | 25.99 µV |
| 4 | 948 fF | 1.2607 | 24.37 µV | 43.41 µV |

Rounded table values are analytical planning numbers. A large acquisition
load destroys much of the gain. The physical comparator's capacitance,
switch junctions, and interconnect must be added before choosing N. Gain
also reduces allowed h for a given headroom; it cannot be used across an
arbitrary full-scale input without clipping.

## Frozen first fixture

The initial cases are N=1,2,4 controls, a 3-fF explicit load, 3.36-µm sample
switches and 1.68-µm series/output switches. All lengths are .15 µm. Two
identical banks acquire the external signal and .9-V reference. The output
reset switches are 3.36 µm. For each MOS, the default geometry follows the
installed Sky130 nf=1 symbol template:

\[
AD=AS=W(0.29\,\mu\mathrm m),\quad
PD=PS=2(W+0.29\,\mu\mathrm m),\quad
NRD=NRS=0.29\,\mu\mathrm m/W.
\]

This is a **PDK-symbol rectangular pre-layout assumption, not PEX**. A paired
zero-diffusion control retains compatibility with earlier schematic-only
results. It does not silently replace this geometry assumption with a
layout-qualified area or leakage model.

The 320-ns first schedule is deliberately conservative: input acquisition
disconnects at 98 ns; parallel tops open at 100 ns; internal bottom resets
open at 102 ns; series links close at 104 ns. Output reset releases at
146 ns and the load joins at 148 ns. Voltage is scored at 198 ns, before an
optional comparator clock from 200 to 202 ns. Output disconnects at 230 ns,
resets at 234 ns, series links open at 236 ns, and the holder returns to
parallel at 238/240 ns. Acquisition for the next frame begins at 310 ns.
This schedule establishes an electrical mechanism, not minimal latency.

Calibration inputs −1 mV, zero, and +1 mV precede every scored input. They
provide one frozen affine output characterization. Evaluation includes
±100 µV, ±500 µV, ±25 µV and six fixed-seed random points over ±1 mV. Both
raw theoretical errors and calibrated residuals are retained. The first
declared deterministic mechanism gate is RMS input-referred residual <10 µV,
maximum <25 µV, and measured gain within 5% of the ideal explicit-capacitor
formula. Passing it does not qualify comparator noise or complete converter
resolution. A deliberately open series link must fail the gain condition.

All independent source-positive energy is integrated over complete measured
cycles, including returning to parallel, output reset and reacquisition. A
separate readout-phase number covers 98–310 ns but does not replace the total.
Warmup and full-trace energy are retained. Capacitors start from normal DC
operating points and physical acquisition; no ideal initial-condition source
installs a desired result. Ordinary ngspice transient contains no intrinsic
transistor noise.

## Results and open questions

The initial 3.36-µm acquisition switch did not settle the 6.98-pF holder in
98 ns: N2 gave 37.86-µV RMS/66.82-µV maximum calibrated residual and N4 gave
17.26/30.22 µV. Both **FAILED**. The acquired voltage retained up to about
50 µV of preceding-input history. Increasing only the acquisition switch to
13.44 µm substantially repaired that error, at an explicitly counted energy
cost. This is an external-input fixture; an integrated native holder would
need its own measured computation-settling control.

All following results use the larger acquisition switch, seed97801 and full
.29-µm diffusion geometry unless marked otherwise. Energy is per complete
two-stack frame, including the reference bank and closing operations.

| Case | Measured G | RMS/max calibrated input error, µV | Total energy, fJ | Frozen deterministic gate |
|---|---:|---:|---:|---|
| N1, TT, direct native node | .999955 | .00040/.00082 | 161.45 | VERIFIED |
| N2, TT | 1.98110 | 3.971/6.932 | 255.89 | VERIFIED |
| N4, TT | 3.78069 | .185/.315 | 383.16 | VERIFIED |
| N4, TT, zero diffusion | 3.85412 | .185/.316 | 388.59 | VERIFIED, alternate geometry |
| N4, SS85 | 3.76166 | 1.670/2.909 | 414.67 | FAILED gain loss >5% |
| N4, TT, comparator connected | 3.75855 | .189/.323 | 507.19 | FAILED gain loss >5% |
| N4, TT, first series link absent | 1.49076 | .216/.370 | 365.44 | FAILED gain |
| N4, TT, 948-fF load | 1.24964 | .147/.250 | 384.05 | VERIFIED formula; little useful gain |
| N4, SS85, .84-µm series switches, comparator | 3.78798 | 1.668/2.903 | 525.06 | VERIFIED |
| Same .84-µm switches/comparator, TT, ±50-mV span | 3.79970 | 58.45/112.43 | 701.05 | FAILED linearity |
| N1, TT, ten actual comparator reads | .999559 | .00036/.00073 | 1385.30 | VERIFIED |
| N4, TT, .84-µm series, ten reads,20-ps step | 3.803972 | .188/.321 | 1576.77 | VERIFIED |

The last two comparator-enabled completed cases resolve every requested
nonzero evaluation sign correctly, including ±25 µV. This is deterministic
sign correctness, **not noise resolution**. For the SS .84-µm case there are
12 such evaluation reads. The larger-span case includes 14 evaluation reads;
correct sign does not rescue its failed precision gate. A missing link can
also leave a very linear but much smaller gain, explaining why calibration
alone is an insufficient validation criterion.

For the ±50-mV failure, the measured external capture error itself is
55.62-µV RMS/122.75-µV maximum. A separate diagnostic fit against actual
captured state, using only the same three calibration records, leaves
7.71/11.42 µV of stack transfer residual. The official external-input gate
remains failed. This decomposition prevents attributing all of the wide-span
error to stack nonlinearity; a native array connection could bypass that
external acquisition, but has not been tested here.

The N4 ten-read experiment aborted at 4.322 µs, on a comparator-clock edge,
with ngspice timestep 1.25e−22 s and trouble at `vclk#branch`. Its incomplete
trace is excluded from success statistics. An earlier redundant zero-volt
wire alias in the N1 deck also aborted at an acquisition edge; merging the
two names of the same physical wire completed the direct-node control.
These are numerical failures, not proof of physical oscillation. Original
decks, logs and partial traces are retained.

The N4 ten-read case completed with a20-ps timestep and resolves all120
requested nonzero evaluation decisions. The largest first-to-tenth change
in pre-clock differential voltage is3.94 µV at the output; instantaneous
read disturbance reaches64.12 µV. The corresponding N1 baseline used100 ps,
so their191-fJ frame-energy difference is a preliminary comparison across
different timesteps, not a convergence-qualified energy advantage. Neither
fixture changes DAC codes between these repeated senses.

Artifacts use prefix `build/sim/imc_cap_stack_`; each completed result JSON
records exact source/deck/ngspice hashes and its artifact directory. Each
directory retains the source snapshot captured before simulation, netlist,
full log and voltage/port-power trace. The pure-stack and DAC follow-ups use
distinct result tags. No mismatch, sampled transistor-noise Monte Carlo,
PEX, or array-connected gain result is established by this table.

## Preserving the native DAC charge quantum

A fixed DAC attached directly to the boosted output is generally wrong for
the intended code interpretation. The output equivalent capacitor is CA/N²
and the transformed native charge is Q/N. An unchanged output-port charge
step would represent N times the original native charge. A potentially
useful connection instead places the original split CDAC in the **lowest
segment**, whose bottom is always VCM; the other segments are plain storage.
Its effective capacitance plus a matching capacitor equals C1=CA/N.

For the ideal equal-capacitor ladder, with each Cs=CA/N and output load CL,
let M be its capacitance matrix. Before output loading,

\[
(M_0^{-1})_{ij}=\frac{\min(i,j)}{C_s},\qquad i,j=1,\ldots,N.
\]

Adding CL to the last diagonal gives, by a rank-one inverse update,

\[
(M^{-1})_{N1}=\frac{1/C_s}{1+C_LN/C_s}
             =\frac{G}{C_A}.
\]

Physical charge conservation during stacking gives the signal output Gh.
A physical bottom-plate change that injects charge ΔQ into the lowest
segment therefore gives

\[
v_o=G h+\frac{G}{C_A}\Delta Q
   =\frac{G}{C_A}(Q_\mathrm{native}+\Delta Q).
\]

The null still means `Qnative + ΔQ = 0`. The signal and original DAC charge
receive the same gain. Global reference levels can remain .65/.9/1.15 V
because the switched DAC bottoms all belong to the grounded lowest segment.
There is no implicit floating ideal reference rail at each upper segment.
The self-check independently solves M for equal and unequal capacitors and
checks this first-node charge coefficient.

For unequal Ci, the exact first-node coefficient is
`1/[C1(1+CL/Ceq)]`, while signal gain remains `N/(1+CL/Ceq)`. Thus native
charge interpretation still requires NC1=CA; otherwise it has a static
charge/signal gain-ratio error. MOS parasitic shunts can produce a more
general discrepancy. Neither a signal-only affine fit nor the ideal matrix
identity proves the real circuit's DAC/signal ratio.

The existing 10-bit 6+4 split CDAC with u=3.75 fF presents 64u=240 fF to its
input. Its physical capacitors total `(63+16+16/15)u=300.25 fF`, including
the bridge. It fits inside one 1745-fF segment of a 6.98-pF N4 holder with a
1505-fF matching capacitor. A 12-bit 8+4 version presents 256u=960 fF and
also fits N4, but not N8 at this total capacitance: N8 would require at least
7.68 pF before parasitic allowances. Padding must be paid on both the native
array and holder if the half-radix match is to survive.

One real 10-bit CDAC needs ten three-way CMOS bottom multiplexers: 60 MOS
devices, plus a fine-node reset TG. It replaces capacitor area within the
first segment, rather than requiring N complete CDACs. The fully matched
reference control duplicates the stack and the CDAC switch network; this
adds another CA of reference storage per tested column, not a free shared
reference. Shared or simpler references remain unverified alternatives.

This is **not a claim of a new generic SAR architecture**. Closely related
primary prior art calls parallel-acquired capacitors stacked above a
grounded CDAC traditional passive gain and continues switching the lower
CDAC while upper integration capacitors retain state. See
[US patent 12,683,619, Figs.2–5](https://patents.justia.com/patent/12683619),
[2020 capacitor-stacking SAR](https://www.jstage.jst.go.jp/article/elex/17/16/17_17.20200193/_pdf),
and [2021 measured capacitor-stacking ADC](https://jiaxin.netlify.app/pdf/21_ISSCC_Jiaxin.pdf).
The present investigation concerns compatibility with the native IMC
capacitance and charge quantum; independent derivation does not establish
novelty.

The first physical stepping controls implement that split CDAC in both
lowest segments, including 30 actual bottom TGs per side, fine reset,
separate native reset, and .29-µm diffusion on every transistor. All bottoms
start at VCM. A selected signal-side bit is switched VCM→1.15 V at170 ns,
then to .65 V at190 ns, then back to VCM at210 ns, with .2-ns nonoverlap.
Output values at188/208 ns measure a full .5-V reference step. The external
MAC-state substitute is acquired through a real TG; no copied ideal state
is installed. The source-positive energy includes resetting the native and
fine nodes, their clocks and both reference rails. These are commanded
bottom steps, **not a SAR decision loop**.

The frozen additional mechanism gate is a maximum5% error between the
measured physical DAC charge response and signal response, after only the
three signal calibration samples. DAC step errors are not fitted away.

| Physical control, TT27 | Signal G | Full selected-bit output step | Charge/signal ratio error | Total energy | Result |
|---|---:|---:|---:|---:|---|
| N1, fine bit0, 3.36-µm fine reset | 1.000298 | 15.748 µV | −6.232% | 322.09 fJ | FAILED |
| N4, fine bit0, 3.36-µm fine reset | 3.826029 | 58.933 µV | −8.256% | 534.97 fJ | FAILED |
| N4, coarse bit9, 3.36-µm fine reset | 3.826030 | 32.0315 mV | −2.606% | 615.88 fJ | VERIFIED mechanism |
| N1, fine bit0, .42-µm fine reset | 1.000298 | 16.575 µV | −1.307% | 306.32 fJ | VERIFIED mechanism |
| N4, fine bit0, .42-µm fine reset | 3.826028 | 62.029 µV | −3.438% | 519.50 fJ | VERIFIED mechanism |

The coarse charge step is60 fC; the fine charge step is .1171875 fC. The
selected physical bottom spans .49999998 V for the fine tests, so insufficient
bottom settling cannot explain the fine attenuation. Its presence in N1 and
large improvement from changing only the reset transistor support a
fine-node parasitic-load explanation. Stacking adds a further charge/signal
ratio discrepancy. **A3.4% mechanism gate pass is not a10-bit ADC accuracy
pass**: bridge trim, gain-ratio calibration, code dependence and PVT still
need actual converter verification. This preserves the negative controls
and prevents an attractive signal-gain measurement from hiding wrong DAC
quantization.

## Why late gain after coarse conversion is conditional

After coarse conversion, let the original connected holder CA have residual
voltage `h = Qres/CA`. Keep every coarse bottom at its last decision voltage
during reconfiguration. Those fixed bottom-voltage terms cancel between
initial and final charge-conservation equations; returning them to VCM
would undo part of the coarse subtraction. Their capacitance does not
vanish, however.

If the entire coarse DAC remains in the lowest segment, its capacitance
must fit inside C1=CA/N to retain the exact quantum above. If instead it
makes C1 larger, signal still gets G but fine DAC charge gets G/(NC1).
The null becomes `Qres + CA*ΔQ/(NC1)=0`, not the original code equation.

Disconnecting the coarse capacitor tops and stacking only quiet/fine
capacitors of total Cselected also has a cost. Those capacitors retain h,
but only the charge `Cselected*h`; the remainder stays on disconnected
coarse capacitors. With equal selected segments, a fine charge step now
represents native charge `ΔQ*CA/Cselected`. To preserve the original native
LSB requires a physically smaller fine step by Cselected/CA, or a different
converter/code scheme with its own quantization cost. Retaining residual
voltage is not the same as retaining residual charge. This rules out the
unpaid quiet-cap-only combination, while leaving a narrower late-gain
architecture with explicit capacitance/quantum redesign for future tests.

An unequal lowest-heavy stack can deliberately exploit a different quantum.
For CA=6980 fF, C1=3840 fF (a 14-bit split CDAC's effective capacitance), and
three upper segments of 1046.667 fF, the gain is about 3.93 with CL=6 fF.
After coarse conversion, define `a=CA/(N*C1)=.454427`. The exact ideal
read equation is

\[
Q_\mathrm{native}+Q_\mathrm{coarse}+a\,\Delta Q_\mathrm{fine}=0.
\]

The native-equivalent fine step is smaller despite using the same physical
unit capacitor. Its correction range shrinks by the same factor. A simple
binary range bound therefore needs at least `ceil(log2(1/a))=2` additional
physical fine bit positions, or another explicitly designed redundant
coarse/fine search, to span the same coarse residual interval. A search can
in principle revisit nearby absolute DAC codes after stacking and reconstruct
`−a*Qfinal−(1−a)*Qcoarse`, but finite rail/code margins and overlap must be
verified. This is a **SPECULATIVE** alternate code scheme, not a validated
unchanged SAR continuation. The gain/range exchange itself is not free
precision.

Unequal segmentation also has a conditional sampled-noise cost. If branch
switches equilibrate their differential charge modes before isolation, the
charge covariance is

\[
\mathrm{Cov}(q_i,q_j)=kT\left(C_i\delta_{ij}-\frac{C_iC_j}{C_A}\right).
\]

Stacking weights each segment charge by1/Ci, producing additional
input-referred variance

\[
\sigma^2_\mathrm{redistribution}=kT\left(\frac1{N^2}\sum_i\frac1{C_i}
                                      -\frac1{C_A}\right).
\]

It vanishes for equal Ci, but is about .364kT/CA for the lowest-heavy example.
Adding that term to a separately derived2/3kT/CA radix-stage variance would
raise RMS noise about24.3%. This is an explicit conditional covariance
model, not sampled MOS-noise simulation. Actual switching order and finite
bandwidth can change the covariance; the old native common-mode noise must
not be counted a second time.

## Paid reference noise

The one-holder noise table above is not the total differential noise of the
two-stack fixture. Independently thermalizing both 6.98-pF native/reference
banks contributes about `sqrt(2)*24.37=34.47 µV` referred to the unboosted
differential input, before load and comparator noise. Counting native-array
noise elsewhere still leaves the reference bank's 24.37 µV as an additional
readout contribution. That alone exceeds a hypothetical 20-µV readout budget.
The current deterministic passing fixture therefore **does not meet that
noise requirement** on this conditional reset model.

At CA=31 pF the reference reset term would be about 11.56 µV, leaving about
16.3 µV in quadrature for other readout noise under a 20-µV allocation. A
gain of3.8 would translate that to roughly62 µV at the comparator. These
are planning bounds, not measurements. Actual switch-noise covariance,
array-stage noise, common reference sharing, differential comparator noise,
and sampled-time dynamics remain unverified. A stiff reference might remove
sampled-reference noise but must then survive the already-demonstrated
floating-versus-stiff kickback failure mechanism.

A separately proposed architecture puts two useful partial sums on the
differential inputs, with one group's sign reversed so their difference
represents the desired sum. For equal per-side storage Cs=Ctotal/2,
`Vdiff=2*Qtotal/Ctotal`; both native signal-noise contributions already belong
to useful computation, avoiding an otherwise-unused sampled reference. The
area and switching of both sides still count. This architecture is known
in related charge-domain work and is **unverified in this fixture**.
In particular, a small differential residual does not guarantee small
individual partial voltages. High-N stacking can violate common-mode
headroom even when two large partials nearly cancel. Both per-side residuals
must be bounded, or a physically implemented centering operation paid for.

## Alternating two useful differential holder banks

An ideal alternative uses every capacitor of two useful banks, with no
otherwise-unused reference state. Split each bank of capacitance Cb into
N equal capacitors Cs=Cb/N, for evenN. One output chain alternates a normal
p-bank capacitor and a reversed n-bank capacitor. The other uses the
remaining normal n-bank and reversed p-bank capacitors. Every original
capacitor is used exactly once. Swapping physical plate connections provides
the inversion; no ideal inverting voltage source creates a held state.

With initial native voltages hp and hn relative to VCM, the ideal outputs
after separate VCM-reset loads CL join are

\[
v_p=\frac{N(h_p-h_n)}{2(1+C_LN^2/C_b)},\qquad
v_n=-\frac{N(h_p-h_n)}{2(1+C_LN^2/C_b)}.
\]

Thus `Vdiff=G(hp−hn)=(G/Cb)Qsum`. The first normal capacitor in the positive
chain can host the grounded CDAC. Its incremental charge sensitivity is
`1/[Cs(1+CLN²/Cb)]=G/Cb`, preserving the original native charge quantum in
the ideal equal-capacitor network. The same host-fit constraints still apply.

Before output loading, positive-chain intermediate voltages alternate
`m(hp−hn)` and `hp+m(hp−hn)`. They avoid multiplying native common mode byN.
Loading and real parasitics must still be solved. A one-sided DAC correction
also moves output common mode: when it brings the positive output to the
negative one, both end at the negative output's level, not necessarilyVCM.
MSB trial excursions and every intermediate node therefore remain required
headroom checks in a complete ADC.

For equal capacitors and matched loads, each bank's charge-redistribution
modes cancel from the ideal differential output: that output depends on
the sum of all p-bank capacitor voltages minus the sum of all n-bank
capacitor voltages. It is inappropriate to blindly add one independent
kT/C penalty for every stack switch. Unequal capacitances, unequal loading,
switch noise during reconnection, and clock injection can break this
cancellation. The physical converter/noise proof is still outstanding.

The implemented mapping uses original p/n capacitor indices0..N/2−1
normally in their respective chains; indicesN/2..N−1 reverse orientation
in the opposite chain. Each original bank acquires its own external voltage
through actual TGs. Both native inputs in the first control have+50-mV
common-mode offset and differential test levels±1mV. The reference load
is physically disconnected/reset toVCM before joining, exactly as for the
earlier stack test.

| N4, full geometry, actual comparator | Ordinary two stacks | Alternating stacks |
|---|---:|---:|
| Output common mode | 1.082039–1.082040 V | .8949711–.8949714 V |
| Differential gain | 3.794561 | 3.772399 |
| Input-referred RMS/max residual | 2.717/4.834 µV | 2.752/4.898 µV |
| Correct nonzero decisions | 12/12 | 12/12 |
| Full two-bank frame energy | 543.70 fJ | 481.32 fJ |
| Original5% gain-loss gate | VERIFIED | FAILED:5.0415% loss |

The deterministic common-mode cancellation is **STRONGLY SUPPORTED** by
this physical control. The narrowly missed frozen gain gate stays failed;
it is not retrospectively loosened. Native-array integration, noise and
full DAC decision sequences remain unverified.

Differential passive common-mode cancellation is known. In addition to the
SAR stack references above, see the primary
[2019 RFIC capacitor readout-reuse receiver, Fig.3 and Eq.2](https://ris.utwente.nl/ws/portalfiles/portal/134648031/RFIC2019_SubmW_mixer_first_RFFE_VKPurushothaman_V11.pdf)
and [Lin et al., ISSCC2019 paper20.2, Fig.20.2.3](https://picture.iczhiku.com/resource/ieee/wHkfSWFHToTdhMVM.pdf).
Their circuit organization differs from reusing two native IMC holders,
but that distinction does not establish novelty.

## Larger-stack screen

To assess a possible raw-comparator-noise constraint, preliminary controls
increase each bank to15.5 pF. With the existing real comparator, N8 and
3.36-µm sample/.84-µm series TGs gives measuredG6.90705 versus ideal7.90212,
2.951/5.097-µV RMS/max residual and737.41 fJ perframe. It **FAILS** the
original ideal-gain gate. N16 with .84-µm sample/.42-µm series TGs gives
G10.4153 versus ideal15.2447,42.50/75.08-µV residual and518.82 fJ; it also
**FAILS**. A larger-switch N16 configuration failed DC convergence before
any transient data; initial-guess hints and more DC iterations did not
rescue that configuration. Its failure is numerical, not a demonstrated
physical instability.

The completed smaller-switch N16 case has up to66.47-µV external-capture
error. Conditioning on actual captured voltage leaves1.729/2.916 µV of
transfer residual. Output drift from180 to198 ns reaches108.58 µV, about
10.4 µV referred to its input. Longer-acquisition and crossed N16 controls
are being used to separate these causes; none establishes minimal latency.

For illustration only, a separately supplied preliminary raw comparator
sigma of444.8 µV would map to `444.8/(2G)` relative to a joined total holder
when both differential banks contain useful sums. The measured N8 and N16
gains would give32.2 and21.35 µV respectively. This conditional calculation
does not transfer that comparator's noise qualification to these geometries,
clock histories or common modes, and adds no claim of sampled-noise success.

Extending only external acquisition by200 ns repairs most N16 history:
ordinary stacking givesG10.79522, .257/.402-µV residual and519.45 fJ in a
520-ns frame. Crossed stacking with+50-mV native common mode givesG10.63133,
.942/1.675 µV,504.60 fJ, outputCM≈.885995 V, and12/12 correct requested
decisions. Its SS85 control givesG9.84548,8.421/14.987 µV,528.85 fJ and12/12
correct decisions. Both still **FAIL** the original5% ideal-gain-loss gate.
The longer acquisition cannot be imported into a native-array timing claim
without verifying the actual computation/holder connection.

The crossed N4 fine-DAC control with explicit closing nonoverlap completes
atTT27: G3.779708,3.489/6.208-µV input residual,2.253% maximum DAC/signal
ratio error and701.79 fJ total frame energy. It passes the declared narrow
mechanism gate. AtSS85, a control using abstol1e−13 A/vntol1e−8 V completes
withG3.745931,10.085/17.949 µV,1.968% DAC/signal ratio error and698.64 fJ.
That control **FAILS** both RMS and ideal-gain gates. The looser absolute
tolerances are disclosed and have not received a complete paired numerical
convergence qualification; reltol remains1e−6.

The original DAC closing sequence briefly overlapped falling acquisition
with rising native/fine reset over .2 ns. The `_rno` controls turn acquisition
off before reset begins. The earlier overlap and its energy are preserved,
not silently rewritten. Some TT andSS runs also aborted at clock breakpoints
at both100-ps and20-ps maximum steps; nonoverlap repairs one TT case but does
not establish that every abort was caused by overlap. Numerical failures
stay separate from completed physical gate failures.

The per-node voltage audit includes every native bus, capacitor plate,
fine node and output over stack formation/readout. The completed crossed
N4TT fine-step case spans .75763–.96198 V; N16TT comparator case spans
.78288–.97100 V. Their SS completed controls span .77457–.96132 V and
.77949–.96794 V respectively. These are measured small-signal/fine-step
headroom checks, not coverage of every full-scale MSB trial. Exact per-node
data are in `build/research/imc_cap_stack_campaign/cross_headroom.json` and,
for newer runs, each result's `analog_node_extrema_during_boost_and_read_V`.

## Exact guard-disconnect schedule and its failure under coarse noise

A full14-bit split DAC cannot fit inside an equal N16 segment of a15.5-pF
bank: it presents3840 fF, versus968.75 fF available. Moving those coarse
bottoms into upper series segments does not preserve their original role.
A finite noiseless alternative separates the two largest coarse capacitors
on a dedicated guard-top bus and physically rescales the fine DAC.

Let C0 be the **entire capacitance participating in parallel coarse sensing**,
including any connected receiver/filter capacitance. Let Cs be the retained
selected storage after guard and read-load isolation. With u=3.75 fF,
the two guard capacitors are512u=1920 fF and256u=960 fF. Ignoring separately
counted read loading for the numerical example, C0=15500 fF andCs=12620 fF.
Choose the physical12-bit fine DAC unit

\[
u_f=u\frac{C_s}{C_0}=3.0532258\ \mathrm{fF}.
\]

The fine DAC presents256uf=781.626 fF, fitting nominally insideCs/16=788.75 fF.
The margin is only7.124 fF, about0.90%, before real parasitics and bridge
admittance error. Matching capacitors restore the intended native C0 during
computation; shrinking the fine DAC is not allowed to change the half-radix
denominator unnoticed. If a load is included in C0 then discarded, subtract
it fromCs and use that actual ratio. The host-fit condition simplifies to
`C0 >= N*256u`, but does not prove physical feasibility near the boundary.

The exact ideal schedule is:

1. During native computation, keep selected segment tops and guard top bus
   connected in parallel. All capacitor bottoms sit atVCM. Reset the fine
   bridge node while the entire holder is reset, then release it before
   native accumulation. Include all connected loading in the array/holder
   match.
2. After computation, open the input/array transfer path while retaining
   parallel holder connections. Make two actual coarse comparisons and
   switch only the two guard bottoms between the physical high/low rails.
   All fine bottoms remainVCM. The resulting residual is
   `h=(Qnative+Qcoarse)/C0`.
3. Freeze both guard bottom references. Open the guard-top connection to
   each native bank. Isolate the comparator/load and physically reset its
   load toVCM before stacking. The selected capacitors retain voltageh;
   their retained charge isCs*h. Charge on disconnected guard/load elements
   has not been copied into the selected state.
4. Form the two crossed N16 chains, release the load reset and connect the
   comparator. Change only the grounded lowest-segment fine-DAC bottoms
   during the twelve fine comparisons.
5. Reconstruct the original charge using
   `Qnative = −Qcoarse − (C0/Cs)*Qfine`. Becauseuf=u*Cs/C0, every physical
   fine step has native significance `(u/16)Vspan`, the original LSB.
6. Consume the result. Disconnect the comparator, return to parallel with
   the holder reset asserted, and only then restore the guard bottoms and
   reconnect their top bus. Count guard isolation, reset, reference, and
   load switching energy. Guard reset while still connected would undo its
   subtraction; resetting an ideally isolated guard is algebraically safe
   but real off-switch coupling still needs verification.

Two noiseless coarse decisions produce centers at±2048 and±6144 nativeLSBs;
the twelve fine bits cover±2048 around each center. The source self-check
verifies full14-bit midpoint reconstruction and native quantum identity.
This is **VERIFIED algebra only**. There is no implemented full guard
sequence or noisy conversion proof in the current transistor fixture.

Selecting a subset of an equilibrated bank also carries a conditional
charge-redistribution cost. Per bank it adds voltage variance
`kT(1/Cs−1/C0)`. Referred to the joined equivalent of two useful banks, the
added variance is half that expression. Relative to an existing
`(2/3)kT/(2C0)` native-stage variance, this adds34.23% variance, or15.9% RMS,
for the numerical example. The independent critic confirmed these units
and covariance factors; actual dynamic switch noise remains unverified.

The noiseless schedule has **zero overlap at coarse boundaries**. The
coarse decisions are unboosted; their errors can leave a residual outside
the later fine range. A same-noise-per-decision SAR reduction factor therefore
cannot be transferred to this heteroscedastic two-stage conversion.
For uniformly distributed full14-bit inputs and coarse Gaussian sigmaσc
expressed in nativeLSBs, the small-σ/full-scale coarse-clipping asymptote is

\[
\mathrm{MSE}_{\mathrm{coarse}}\simeq
\frac{3}{16384}\frac{2}{3}\sqrt{\frac2\pi}\,\sigma_c^3.
\]

There are three coarse boundaries. Each contributes the integral of squared
distance beyond the fine range weighted by its wrong-decision probability.
With raw comparator sigma444.84 µV, C0=15.5 pF andnativeΔQ=.1171875 fC,
σc=58.8375 LSB. The asymptote predicts16.84-µV excess RMS referred to a joined
2C0 holder, before fine noise.

A2-million-input fixed-seed numerical bisection experiment confirms the
practical problem:

| Coarse/fine noise model | Equivalent excess RMS | Residual outside fine range |
|---|---:|---:|
| Two noisy coarse decisions; ideal fine ADC | 17.08 µV | .8574% |
| Same coarse noise;12 independent fine decisions atG10.6313 | 22.82 µV | .8585% |
| Same coarse noise;12 independent fine decisions atG9.8455 | 23.66 µV | .8677% |

The artifact is `build/research/imc_cap_stack_campaign/coarse_guard_noise.json`.
These are mathematical uniform-input controls, not device-noise or workload
results. They **FAIL a20-µV equivalent-noise planning target** for this
unmodified two-stage scheme. Actual workload density at the coarse
boundaries and comparator correlation can change the result.

Paid overlap remains a possible repair. The current nominal host margin
allows only about0.91% wider fine range, or18.7 nativeLSBs, versus58.84-LSB
coarse sigma. Roughly3σ overlap needs about8.6% wider fine range and
C0≥16.68 pF per bank before parasitics. It also makes the fine nativeLSB
8.6% coarser unless another conversion resource is added. Extra redundant
comparisons or a finite-range fallback are alternatives only after their
actual DAC/reference schedule is specified. The exact ideal identity is a
useful partial discovery; the full low-noise architecture remains
**SPECULATIVE** and its naive zero-overlap version has failed this control.

## Selective coarse voting: useful conditional repair, paid service cost

An exact finite-range control now repeats only the two unboosted coarse
decisions using fixed odd majority votes, K=3/5/9. Every individual decision
receives its own Gaussian draw under the independent control; the same
two coarse centers, twelve-bit fine range, clipping, and measuredG10.6313
remain in force. The implementation does not replace majority by an assumed
Gaussian noise reduction. A shared raw-voltage latent noise component gives
explicit rho=.5 andrho=1 controls, scaled by the actual gain in the fine
phase. These are declared covariance models, not measured correlations.

`tb_imc_cap_stack.py --guard-majority` freezes30,000 calibration inputs and
500,000 independent evaluation inputs. The retained artifact and exact
source/protocol are
`build/research/imc_cap_stack_campaign/guard_majority_397c2904203b.json`
and its adjacent `_source.py`/`_protocol.json` files. Added-cycle budgets
are also spent on fine votes in a separate control. A greedy allocation
is trained only at444.84µV/rho0, then transferred unchanged to the other
conditions; it is not a globally optimal allocation or a separately
optimized baseline for each noise case.

| Comparator sigma / covariance model | No extra votes | CoarseK3 | CoarseK5 | CoarseK9 | Greedy fine, sameK3 budget | Greedy fine, sameK9 budget |
|---|---:|---:|---:|---:|---:|---:|
| 444.84µV / independent | 22.804 | 17.704 | 16.584 | 15.864 | 21.529 | 19.817 |
| 444.84µV / rho=.5 | 24.866 | 22.528 | 21.926 | 21.596 | 24.319 | 23.497 |
| 444.84µV / fully shared | 26.821 | 26.821 | 26.821 | 26.821 | 26.821 | 26.821 |
| 366.72µV / independent | 17.913 | 14.337 | 13.599 | 13.091 | 16.826 | 15.246 |
| 366.72µV / rho=.5 | 19.620 | 18.143 | 17.735 | 17.392 | 19.183 | 18.425 |
| 366.72µV / fully shared | 21.298 | 21.298 | 21.298 | 21.298 | 21.298 | 21.298 |

All entries are equivalent excess RMSµV on a joined2C0 native holder,
under uniform full-range mathematical inputs. The old-sigmaK3 independent
result has approximate95% interval17.532–17.873µV. The fully shared control
produces exactly the same output for every vote plan. The noiseless-fine
coarse-clipping floor above independently shows why extra fine comparisons
cannot repair a wrong coarse interval after the fine range has saturated.

The366.72µV point is the parent's fresh288-trial component fit with explicit
diffusion geometry; its95% profile interval is292.23–470.42µV. This is a
conditional point estimate, not an established lower noise specification.
The quoted intervals overlap the uncertainty relevant to the architecture.
Neither table includes native-holder thermal noise, subset-disconnection
noise, real DAC switching noise, mismatch, or a loaded-column noise trace.

Actual repeated-read controls now connect the real comparator and receivers
to two15.5pF holders at+50mV common-mode offset, with10 successive20ns
evaluate/reset cycles. All120 held-out requested nonzero decisions are
correct in each TT27 andSS85 run. The largest first-to-last preclock
differential drift is.647µV atTT and.584µV atSS. Across cycles2–10, integration
of **every independent source's positive delivery** gives122.93fJ per added
cycle atTT and127.45fJ atSS; all closing resets remain paid in the full trace.
The matchingN4 boosted control gives120.53fJ per added cycle. See
`build/research/imc_cap_stack_campaign/read_cycle_energy.json` for exact
artifact paths and extrema.

| Extra coarse votes | Extra complete latch cycles | Added service time | Added measured TT / SS ideal-port energy |
|---|---:|---:|---:|
| K3 on each of two coarse decisions | 4 | 80ns | .492 / .510pJ |
| K5 on each | 8 | 160ns | .983 / 1.020pJ |
| K9 on each | 16 | 320ns | 1.967 / 2.039pJ |

These are measured component-cycle additions. Majority logic, full ADC
references, and extra held-node stochastic disturbance are not priced by
this deterministic fixture. The proposed next measurement is sequential
intrinsic-noise correlation with physical reset history; voting is useful
only to the extent that the actual repeated errors differ.

The N16 crossed holder also completed10 successive reads in TT: measured
gain10.63137, calibrated RMS.941µV/max1.674µV, and full-frame1.530pJ.
It retains the original **FAILED ideal-gain gate**; successful decisions
and low fitted nonlinearity do not erase its substantial parasitic gain
loss. Added read cycles average113.94fJ. A significant negative result is
the175.63µV first-to-tenth preclock differential drift, equivalent to16.52µV
at the original differential input or8.26µV on a joined2C0 holder. At
requested±25µV inputs, comparator-input magnitude falls from roughly263µV
to88µV. The zero-input calibration trace alternates between about+120 and
−140µV after successive reads. This is decision-dependent kickback feedback,
not a simple calibratable gain drift. All analog nodes remain within
.78288–.97676V in this narrow fixture. Stiff-input intrinsic-noise
correlation cannot qualify this loaded fine-voting state; the much smaller
direct-holder disturbance is a separate reason to prefer coarse voting.

The input-W7 control loads the same stack more heavily: gain10.32715
versus10.63133 atW3.5, a2.86% loss, while energy rises504.60→523.82fJ.
The parent's raw-noise point estimates366.72→346.38µV improve only5.55%,
with overlapping confidence intervals. Their combined point estimate
would improve by only about2.8%; no width optimum is established.

Selective SAR voting itself is prior art. Ahmadi andNamgoong explicitly
optimize vote count by bit under a power constraint in
[their optimized-vote SAR paper](https://picture.iczhiku.com/resource/eetop/shigjTUgJKRHQBMn.pdf).
The useful narrow hypothesis here is that a physical interstage gain/noise
boundary can reverse the usual preference for fine-bit voting because
coarse clipping becomes irrecoverable. The bounded search did not establish
novelty for that complete integration. It remains **SPECULATIVE**, supported
by exact finite-range numerical controls and deterministic repeated-read
component evidence.

### Updated component-noise and complete thermal-phase boundary

The matched64-seed-per-input full-diffusion comparator cohort supersedes the
smaller288-trial point estimates above as the current matched comparison:
parent-reported default sigma455.260µV (95% profile387.509–538.788), internal
4fF per-drain sigma328.851µV (279.912–392.048), and16fF sigma315.815µV
(268.816–376.507). These are still qualified **component hybrid** noise
measurements with stiff inputs, not a loaded converter. The4fF result offers
stronger evidence of improvement than simple input widening. The extra
16fF improvement remains uncertain while ideal-port decision energy rises
127.99→167.83fJ. The older366.72µV mathematical voting rows remain retained
conditional evaluations, not a current best comparator specification.

The sequential physical-noise study is now complete in
[LATCH_CORRELATION.md](LATCH_CORRELATION.md). It does not establish independent
votes: one small-input polarity has a positive lag-one sign correlation,
the lower flicker-cutoff control also retains correlation, and majority
improvement is not established at both tested polarities forK3. Stiff-input
sign correlation cannot resolve the separately measured loaded-stack
kickback feedback.

**Thermal correction:** the earlier2/3·kT/C stationary-holder expression
included sharing noise but omitted a fully thermalized fresh-array reset.
For equal capacitors, independent fresh reset and fully thermalized sharing,

\[
\operatorname{var}(h_{j+1})=
\tfrac14\operatorname{var}(h_j)+\tfrac14(kT/C)+\tfrac12(kT/C),
\qquad \operatorname{var}(h)_\infty=kT/C.
\]

This changes the baseline, not the absolute extra noise of a subsequently
specified disconnection. For selectedCs12.62pF fromC0=15.5pF, the conditional
extra variance of the equivalent joined-two-bank native voltage remains
\(kT(1/C_s-1/C_0)/2\). Relative to the corrected joined baseline
\(kT/(2C_0)\), its ratio is.228209 and the RMS multiplier is1.10825;
the previous.3423 ratio/15.9% increase used the incomplete2/3 baseline.
For the earlier unequal-stack example, added.364·kT/C corresponds to about
16.8% RMS increase over the correctedkT/C baseline, rather than24.3% over
2/3·kT/C. Both assume the stated thermalized covariance and omit other
switching modes; neither is a complete loaded-transient-noise result.
The old system passes using2/3 must remain labeled optimistic conditional
model results. A real two-capacitor reset/share covariance control is being
owned independently by the prior-art/device branch.

### Distributed shunts break both gain and fine-charge co-gain

ForN equal sectionsc=Cs/N, a grounded linear shuntCp at each internal node
and output loadCL produce a tridiagonal capacitance matrixM: diagonal2c+Cp,
last diagonalc+Cp+CL, adjacent off-diagonal−c. With the matched crossed
initial differential-charge assumptions used above, native differential
inputd produces endpoint chargecd. Thus

\[
G=c(M^{-1})_{NN},\qquad
R_Q=\frac{N(M^{-1})_{N1}}{(M^{-1})_{NN}}.
\]

The second expression is the ratio between the actual lowest-segment
fine-DAC significance and the ideal native-charge significance. Output
load alone cancels from this ratio. **Internal shunts do not cancel.**
For uniformCp, writing\(\alpha=\operatorname{acosh}(1+C_p/(2c))\),

\[
R_Q=N\sinh\alpha/\sinh(N\alpha)<1.
\]

An independent scalar recursion checks gain: startCeff=c+Cp, then replace
Ceff byCp+c·Ceff/(c+Ceff),N−1 times;G=c/(Ceff+CL). Its small-shunt loss
contains\(\sum j^2 C_{p,j}/C_s\), so uniform parasitic loading grows as
CpN³/(3Cs), in addition toCLN²/Cs. In the continuum approximation,

\[
G\simeq(C_s/C_p)^{1/3}\frac{\tanh z}{z^{1/3}},
\quad z=\sqrt{C_pN^3/C_s}.
\]

Maximization gives\(\sinh(2z)=6z\),z=1.419223,
Nopt=1.262895(Cs/Cp)^(1/3), andGmax=.791465(Cs/Cp)^(1/3).
At this optimum the fine-charge ratio is approximatelyz/sinhz, so maximizing
voltage gain does not preserve a fine quantum automatically. This is a
linear-ladder diagnostic derived from standard capacitor nodal analysis;
no novelty or transistor-level optimum is claimed.

The exact matrix, recurrence and hyperbolic expressions agree in
`build/research/imc_cap_stack_campaign/ladder_sizing.py` and its JSON output.
Fitting one uniformCp to the old15.5pF/N16/G10.63133 result gives5.085687fF.
This is a **surrogate fit, not a measured physical capacitance**. Transferring
it unchanged toCs12.62pF predicts:

| N | Gain | Fine-charge ratio | Margin after restoring fine unit by1/RQ |
|---:|---:|---:|---:|
| 8 | 7.29585 | .96695 | 769.16fF |
| 10 | 8.50708 | .93651 | 427.39fF |
| 12 | 9.33011 | .89348 | 176.86fF |
| 14 | 9.78200 | .83784 | −31.48fF |
| 16 | 9.92778 | .77092 | −225.14fF |

Increasing only the fine reference span by1/RQ is an alternative to enlarging
the unit cap: the surrogate requires.55961V forN12 or.64858V forN16, versus
.5V originally. It pays new references, reference energy and calibration,
and cannot repair a residual-dependent or code-dependentRQ with one scalar.
Neither remedy has passed a physical full-converter test.

### Physical selected-cap and coarse-guard tests: failures retained

The new source is
`tb_imc_guard_stack.py`.
It acquires two real15.5pF banks through TGs. Each has1920fF and960fF guard
capacitors,12.62pF selected state, and a real8+4 split12-bit fineCDAC in
its lowest section. UF=3.053225806fF makes its nominal seen capacitance
781.625806fF. All muxes, acquisition, isolation, series links, reset devices,
comparator and output receivers use explicit.29µm rectangular diffusion.
Every independent source's positive delivery, including closing reset,
is included in energy. Input acquisition is external, and correct coarse
words are supplied by an oracle. The comparator makes one final read but
does not choose the coarse words or execute all fine decisions. There is no
native MAC integration, noise, mismatch or PEX claim.

The fixed schedule, relative to each800ns frame, is acquisition10–300ns,
coarse-bottom changes312/342ns, dedicated guard-top isolation400ns,
selected-top isolation420ns, bottom isolation422ns, stacking424ns,
output-reset release466ns and output join468ns. Output is scored528ns;
one fine bit is stepped tohigh530ns andlow550ns, then returned570.2ns.
Comparator evaluation600–610ns follows; joinopens630ns, outputreset634ns,
stackopens636ns, bottomsreturn638ns, selectedtopsreturn640ns. Native and
fine resets turn on650/652ns, coarse bottoms return682ns, and guardtops
reconnect710ns. Nonoverlap edges are explicitly.2ns apart or longer.
No stored voltage is numerically copied between phases.

The first three calibration inputs surround the positive coarse center
15.483871mV by±1mV; their common coarse word is[−,+]. Frozen held-out smoke
inputs are−100µV,+100µV and−15.458871mV, testing the opposite coarse word
and a near-null residual. A larger predefined set also spans±60mV and
both sides of the other coarse boundaries; it has not yet completed.
Frozen limited-mechanism gates are10µV RMS/25µV max equivalent input error,
5% ideal-gain error, and5% fine-charge co-gain error. These gates are much
weaker than a complete14-bit ADC acceptance and do not establish one.

| Physical fixture | Gain / output-load-only ideal | Fitted RMS / max input error | Full-frame energy | Result |
|---|---:|---:|---:|---|
| N8 selected12.62pF, Ci4, single read | 7.208777 / 7.880112 | 6.673 /11.886µV | 401.611fJ | **FAILED gain** |
| N8 guard+fineCDAC, dedicated guard isolation, Ci4 smoke | 7.120354 /7.880112 | 569.764 /711.212µV | 2275.367fJ | **FAILED accuracy, gain, co-gain** |

The selected-cap primitive retains all12 correct requested nonzero
comparisons; all recorded analog nodes stay within.784573–.995163V in the
narrow test. Those partial successes do not erase its gain failure.

The guard fixture localizes its major discontinuity before stacking:

| Held-out input | Coarse word | Error before guard isolation, after own diagnostic affine | After isolation | Final frozen output equivalent error |
|---:|---:|---:|---:|---:|
| −100µV | [+,−] | −103.710µV | +743.590µV | +711.212µV |
| +100µV | [−,+] | −29.307µV | −14.771µV | −15.104µV |
| −15.458871mV | [+,−] | −132.600µV | +712.790µV | +683.991µV |

These phase-specific fits diagnose the cause; they do not replace the
frozen final-output acceptance. The dedicated guard-disconnect edge changes
differential voltage by approximately−2.345mV for[−,+] but−1.504 to−1.513mV
for[+,−]. Its cause needs transistor/terminal-charge diagnosis; attributing
this entire difference to a simple geometric gate capacitor is not yet
supported. Opening the selected-top switches already isolates the selected
state, so a matched `native_bus` control removes the redundant guard-top
switch while keeping coarse bottoms frozen. That control is running.

The fine-step amplitude also varies52.138–60.599µV across smoke cases,
with−3.150% to+12.568% co-gain error. Uniform fixed-shunt loss alone predicts
a constant reduction, so it does not explain this physical residual
dependence. Bridge/mux nonlinear parasitics, injection and unequal effective
section capacitances remain candidate causes for direct controls.

Exact successful-completion artifacts are:

- `build/sim/imc_cap_stack_n8_tt_27_ca12620p0_cl3p0_d0p29_sw0p84_jw0p42_dt100p0_s97801_cmp1_fault0_aw13p44_span1000_reads1_ophints_cross1_cm50_aextra200_cint4_timeout1800.json`
- `build/sim/imc_guard_stack_n8_tt_27_isolated_bit0_dt100_ci4_smoke1_at1e-14_vt1e-09_timeout1800.json`

The originalN16 guard smoke aborted at3.000000µs with a timestep-too-small
error naming`vclk#branch`, on the comparator clock edge; its JSON status is
**FAILED_NUMERICAL_OR_INTEGRITY** and no physical-failure conclusion follows.
The originalN16 selected12.62pF primitive reached5.93128µs of8.3205µs when
its600s wall-clock limit expired; the log has no simulator abort. This is a
runtime-limit result, not an electrical result. Separately, theN16/15.5pF
Ci4 ten-read control aborted at4.8142µs during closing reset and remains a
numerical failure. Original decks, logs and partial data are preserved.
Subsequent1800s runs change only the explicit simulator wall-time allowance.

The deeper phase audit refines the guard-disconnect diagnosis: the guard,
native bus and selected sections have not equilibrated when isolation occurs.
For the center calibration case at398ns, guard differential voltage is
6.236mV, native differential is.688mV, and the lowest selected section is
−1.208mV. The last coarse-bottom transition is342ns. Interrupting that ongoing
redistribution400ns therefore produces a large state change; calling the
entire event charge injection would be unsupported. A paid+600ns quiet
interval after coarse switching now tests whether settling is the main
cause. All subsequent physical edges and observations move together, and
the1400ns frame includes the added delay and energy. This is a diagnostic
control; no throughput improvement is claimed. The first `native_bus`
control aborted numerically at2.866µs, on output-reset release. A20ps-step,
10⁻¹²A absolute-tolerance control is running with original failure preserved.

### Initialized capacitor-plate parasitics

The intended capacitors in the transistor fixtures are ideal. Their physical
plate-to-substrate and interconnect capacitances remain unpriced. The local
Sky130 MIM model has two external terminals and an intended capacitor plus
series resistances; it does not supply a substrate port. A layout coupon
and extraction are being pursued independently. A generic textbook percentage
is not a measuredSky130 parasitic ratio.

`build/research/imc_cap_stack_campaign/plate_parasitics.py` independently
constructs all2N physical capacitors, gives every original top and bottom
plate its actual parallel-acquisition voltage, includes plate-to-ground
capacitances, and merges terminals according to the crossed switch schedule.
It conserves initial charge at every merged node and solves the resulting
capacitance matrix. No acquired capacitor voltage is copied into an ideal
post-stack source. The source and JSON check two acquisition common modes,
N=2…32 and a range of explicitly hypothetical parasitic ratios.

Let each intended section bec=Cs/N, with original top and bottom parasitics
βt·c andβb·c. In one crossed chain, normal own-bank sections alternate with
reversed opposite-bank sections. Internal odd nodes join two original top
plates, giving shunt2βt·c. Even internal nodes join two original bottom
plates, giving2βb·c. The final output is one original bottom plate, so its
shunt isβb·c plusCL. The lowest original bottom plate remains grounded.

Initial top-plate parasitic charge at an odd junction isβt·c(hp+hn) in
both chains; original bottom-plate parasitic charge iszero. The intended
capacitor charges at internal nodes are also identical between chains.
Thus the initial **differential** charge vector is exactlycd at the endpoint,
where d=hp−hn. The reduced matrix reproduces the complete initialized graph.
Its gain and fine-injection ratio follow the inverse-matrix expressions in
the previous section. Common-mode cancellation survives matched linear
plate parasitics when their initial charge is retained; zeroing all initial
parasitic voltages would produce an incorrect common-mode analysis.

For pure bottom parasitics andCL=0, the infinite periodic ladder has even-node
normalized admittanceB satisfyingB=2βb+B/(1+2B). Its positive solution is
B=βb+sqrt[βb(1+βb)]. The output has half the internal bottom shunt, yielding

\[
G_{N\to\infty}=\frac1{\sqrt{\beta_b(1+\beta_b)}}
\simeq\frac1{\sqrt{\beta_b}}.
\]

This is a conditional asymptote, not an assertion that a particular layout
has thatβ. Finite output loading only reduces the gain. Even when gain
approaches a finite ceiling, fine charge injected at the lowest segment
continues to be attenuated relative to native endpoint charge.

| Hypothetical βbottom, βtop=0 | N8 gain / fine ratio | N12 gain / fine ratio | N16 gain / fine ratio |
|---:|---:|---:|---:|
| 0 | 7.8801 /1.0000 | 11.6028 /1.0000 | 15.0822 /1.0000 |
| .005 | 7.1226 /.9518 | 9.4699 /.8925 | 10.9658 /.8177 |
| .010 | 6.5182 /.9071 | 8.0976 /.8009 | 8.8581 /.6788 |
| .020 | 5.6120 /.8266 | 6.4218 /.6538 | 6.6753 /.4845 |

The table usesCs12.62pF andCL3fF per output and excludes MOS switch loading.
It therefore cannot be added to a transistor result as an independent gain
factor without rebuilding the joint matrix. Forβtop>0, parallel acquisition
also seesCs(1+βtop). The JSON explicitly distinguishes normalization to
intendedCs from total initial top-node charge: the latter fine-charge ratio
is(1+βtop) times the former. Native compute matching and coarse-to-fine code
significance must use the actual participating capacitances.

### Finite sharing does not lower the complete stationary thermal floor

For two equal capacitors connected throughRs forTs, write
r=[1+exp(−2Ts/(RsC))]/2. With ideal fixed capacitors and white thermal resistor
noise,

\[
h'=rh+(1-r)a+\eta,\qquad
\operatorname{var}(\eta)=2r(1-r)\,kT/C.
\]

An independent fully thermalized fresh reset suppliesvar(a)=kT/C. Hence
innovation variance is[(1−r)²+2r(1−r)]kT/C=(1−r²)kT/C, and stationary
var(h)=kT/C for any.5≤r<1. Starting from an artificially noiseless holder,
B updates give(1−r^(2B))kT/C. Shorter sharing changes the radix and finite
startup approach to equilibrium; it does not improve this stationary floor.
This identity was independently audited. Finite-band MOS noise, nonlinear
terminal capacitance, incomplete reset history and the real switch schedule
still require the separate physical covariance test.

### Recovered guard controls and conductance-sized retry (2026-09-11)

The completed `native_bus` 20 ps control retains the guard capacitors on the
native bus while selected sections disconnect through their existing top
switches. It reduces held-out RMS/max error to **229.951/286.534 µV**, versus
569.764/711.212 µV with the separate guard-top switch. It still **FAILS**:
measured gain is 7.14159, maximum fine co-gain error 12.2394%, and positive
energy is 2.48388 pJ/frame. Removing the extra guard-top switch does not
alone repair the coarse-to-fine interface.

The paid +600 ns isolated control aborted at 2.466 µs on `vclk#branch`.
Its earlier completed physical phases remain diagnostic evidence. In the
first calibration frame, at local 998 ns, native, lowest section and guard
differential voltages are −1122.5474, −1122.5476 and −1122.5482 µV. The
subsequent guard-disconnect change in native voltage is only −0.1352 µV at
1018 ns. At the original local 398 ns, those nodes differed by millivolts.
Thus incomplete redistribution explains the large disconnect disturbance;
this partial trace does not establish complete converter accuracy.
The reproducible selected-column audit is
`build/research/imc_cap_stack_campaign/recovered_phase_audit.py` and JSON.

The +600 ns native-bus job left an empty log and INCOMPLETE manifest after
the earlier session ended. A separate `timeout3600_settle600` retry preserves
that artifact. No electrical conclusion is drawn from the empty log.

Sizing follows the user's gm/ID reference flow's operating-region caveat:
these sampling devices are in triode, so the required settling conductance
is compared with actual terminal gds/admittance at the intended VDS/VSB,
not a saturation gm/ID-to-bandwidth substitution. At both terminals 0.9 V,
L=0.15 µm and explicit 0.29 µm diffusion, measured TG resistance is:

| Equal N/P width | TT27 resistance | SS85 resistance |
|---:|---:|---:|
| 0.84 µm | 13.264 kΩ | 24.046 kΩ |
| 1.68 µm | 5.592 kΩ | 9.170 kΩ |
| 3.36 µm | 2.376 kΩ | 3.380 kΩ |

These are the KCL-checked `imc_switch_admittance_*_kclv2` fixtures. For a
1.5775 pF selected section, the simple R·C diagnostic falls from 20.92 to
3.75 ns TT, or 37.93 to 5.33 ns SS, when the parallel-acquisition TG grows
from 0.84 to 3.36 µm. Coupled-network settling and nonlinear large-signal
resistance still require the actual transient. The same width increase
raises terminal capacitance and can damage stack gain after isolation.
A frozen 800 ns native-bus smoke run therefore tests sample width 3.36 µm
and coarse mux width 6.72 µm, retaining all earlier error/gain gates and
metering the added clock energy. The series/join devices remain 0.42 µm.
This is an explicit speed/loading tradeoff, not an accepted improvement.

The ladder and initialized-plate mathematical checkers are now also durable
entry points at `analog/testbenches/tb_imc_stack_ladder.py` and
`analog/testbenches/tb_imc_stack_plate_parasitics.py`. Both were rerun and
print PASS; outputs go under the campaign's `durable/` build directory,
leaving original source-hashed artifacts intact.

Both recovered native-bus controls completed and **FAIL** the unchanged
mechanism gates:

| Physical control | Gain | Held-out RMS/max µV | Maximum fine co-gain error | Positive energy/frame |
|---|---:|---:|---:|---:|
| Original 800 ns frame | 7.14159 | 229.951 / 286.534 | 12.239% | 2.48388 pJ |
| Paid 1400 ns frame (+600 ns settling) | 7.14387 | 232.793 / 288.815 | 9.927% | 2.48592 pJ |
| 800 ns, sample W3.36 / guard W6.72 | 6.77681 | 236.536 / 289.905 | 15.673% | 3.13885 pJ |

Therefore the remaining native-bus held-out error is not cured by allowing
full coarse settling. Larger switches worsen gain, fine co-gain and energy.
Coarse significance, voltage-dependent capacitance and code-dependent offset
remain unresolved; another blind settling/width sweep is not justified.
The completed artifacts end in `timeout3600_settle600` and
`timeout3600_sample3.36_guard6.72`, with full decks, source snapshots and
traces preserved. No full physical 14-bit converter has passed.
