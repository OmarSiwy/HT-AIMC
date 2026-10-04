# Four-row physically connected signed grounded IMC

This test closes the programmable bank into a real floating array/holder pair.
It is deliberately small and deterministic; no full-model quality or noise
claim follows from a pass. New owned source:
`analog/testbenches/tb_imc_signed_grounded_core.py`.

Four fixed signed3-bit weights[-7,-3,2,5] use direct three-TG routes from each
bottom plate to row, complementary row, orVCM. N/P bit widths0.50/0.70um and
L0.15um match the recent bank controls. Every bit uses the actual contacted
1260nm coupon, replicated1/2/4 times: mutual4.07454fF, top/substrate0.06928fF,
bottom/substrate0.28183fF. The top plate is the array column. Inactive bits go to
VCM, so all28 installed units contribute to the column capacitance.

The holder physically contains another28 identical units, top atH and bottoms
atVCM, with their actual substrate capacitances. This is a fixed passive holder,
not a programmable replica or an assigned analog state. Equal1.68/1.68um TGs
reset array and holder; another TG with those dimensions performs sharing.
Every MOS has explicit0.29um diffusion geometry. The fixture uses78 MOS and56
installed coupon units (about132.81um² of summed isolated bottom footprints),
excluding real row/reference drivers, SRAM/decode and routed layout. Static
controls are ideal logic rails. There is no arbitrary120fF system-level floor.

## Charge equations and frozen oracles

Ignoring MOS charge but retaining all coupon substrate capacitances,
A=H=28*(4.07454+0.06928)=116.02696fF. Bottom/substrate capacitance loads the actual
row sources; with stiff settled bottom voltages it does not add to column A.
For least-significant-plane-first activation bits,

```
Q_m = 0.45*Cu*sum_i weight_i*sign(x_i)*bit_m(abs(x_i))
V_H,next = (Q_m + H*V_H,previous)/(A+H)
V_H,final = 0.45*Cu/A * dot(weight,x)/8
```

The two full-scale aligned products±119 therefore predict approximately±0.2351V
holder swing. Array acquisition can reach approximately±0.2686V before sharing.
This MIM-only oracle remains separate from the actual MOS prediction.

A separate frozen-VCM nativeAC deck extracts the complete two-port OFF-switch
capacitance matrix M for[A,H] and signed differential row coupling K. Both
clamped-port excitations and each of the four row/complement excitations are
measured through actual native TGs. No clamp exists in the transient signal path.
For A reset toVCM between planes and a constant reciprocal OFF matrix,

```
D = sum_ij Mij
beta = (M_HA + M_HH)/M_HH
r = beta*(M_AH + M_HH)/D
input coefficient_i = beta*(K_Ai + K_Hi)/D
```

This matrix prediction is frozen before reading transient products. It omits
MOS charge changes between switch states, clock injection and bias dependence,
which the transient is intended to expose rather than fit away.

For shunts a,h and OFF mutual c, M=[[a+c,-c],[-c,h+c]], the complete join/open/
array-reset cycle is

```
Vnext = h*(Q + h*Vprevious)/[(a+h)*(h+c)]
```

Thus equal shunts alone give r=h/[2(h+c)], below one half if c>0. Exact binary
r=1/2 requires h=[a+c+sqrt((a+c)^2+4ac)]/2, approximately a+2c, and then the
signal coefficient is1/(2h). The source self-check independently solves isolated,
joined and post-reset charge states for several Q/V initial conditions and
verifies this identity. It is a constant-matrix result, not a guarantee for
switching MOS capacitance. A subsequent holder-size candidate must use the
frozen zero-bias matrix, not transient-error fitting.

## Physical timing and verification

The first word begins after40ns real reset. Each of three80ns planes releases
array reset10--10.2ns, changes row voltages12--12.2ns, closes sharing34--34.2ns,
opens sharing54--54.2ns, resets the array58--58.2ns, and returns rows60--60.2ns.
Holder reset opens only at the word's first10ns boundary and closes240--240.2ns.
Word period is280ns. The final holder is read238ns, after the last array reset;
this timing is essential to the OFF-crosscap recurrence. Shared-state,
post-release and post-array-reset voltages are all recorded independently.

First two words±119 calibrate only gain and offset. Ten subsequent frozen words
include small cancellation products+1/-2, row-separated large products, single
bit-position probes and zero. No heldout fit changes matrix, holder or radix.
A zero-subtracted three-plane decay probe measures actual radix separately from
the product gain fit. Initial/closing holder reset, array reset and final2ns
share motion have explicit gates. Product gates are max0.1MAC and RMS0.05MAC;
these are bounded deterministic experiment criteria, not inferred full-system
accuracy requirements. Failure remains archived.

All positive ideal-port energy is counted for both row polarities, VDD, VCM and
complementary phase clocks. Driver implementations, mismatch, transient noise,
PVT capacitor variation and full-network PEX remain unqualified. One116fF
holder has stationary kT/C noise around189uV at27C (roughly0.096MAC here), already
larger than the deterministic RMS gate. Thermal noise is not drawn in this
fixture; a deterministic pass does not establish that noise budget.


## First connected native result: TT27

`build/campaign/signed_grounded_core/tt_top_nominal_r3/result.json` is a
**VERIFIED deterministic pass for the stated 12-word fixture**, with the first
two words calibrating gain/offset and the remaining ten receiving no fit.
Fresh-product RMS/max error is 0.028953/0.034455 MAC. Measured zero-subtracted
successive radix is 0.5000270/0.5000319. The calibrated gain is
1.910169 mV/MAC and offset is −4.534329 mV. Zero input still has +0.034253 MAC
calibrated residual; this negative finding is included in the error metric.

The MIM-only ±119-MAC oracle is ±235.066 mV; adding the frozen native OFF
matrix gives ±227.221 mV. Actual outputs are +222.776 and −231.844 mV.
Thus the matrix improves loading prediction but does not predict clock-induced
offset. In the zero word, sharing release moves the holder from approximately
+2 µV to −4.469 mV. Static capacitance analysis cannot explain away that step.

The measured OFF diagonal capacitances are 120.032292 and 120.032610 fF.
Off-diagonal entries are −0.00000615 and +0.00000435 fF, with reciprocity error
0.00001049 fF; their sign and scale do not support a resolved physical mutual
capacitance. The resulting static radix is 0.50000066. No negative or sub-layout
holder trim is fabricated from this numerical residual. The constant-matrix
compensation identity remains a verified algebraic partial discovery, while this
particular nominal geometry provides no meaningful static trim target.

Runs r1/r2 failed native AC operating-point convergence and remain archived.
Bottom-node `.nodeset` hints alone did not fix the tight-tolerance OP. The r3
AC uses established programmable-bank tolerances (reltol1e−6, abstol1e−13,
vntol1e−9); nodeset is an OP guess, not an initial-state copy. Physical transient
uses 20 ps maximum timestep. Matched 10 ps and frozen-TT-calibration SS85
controls are running separately. Noise, mismatch, layout routing, physical row
and reference drivers, weight storage, and larger row count remain unverified.

The 12 complete word frames consume 0.05011–0.35834 pJ per word (mean
0.15998 pJ), counting positive ideal-source energy. Their fixed period is 280 ns;
this is not a minimized delay or implemented clock/driver power claim. Maximum
last-2-ns sharing motion is 0.01485 µV. Closing holder reset is below 0.000015 µV
in this deterministic simulation. These small numerical reset values do not
represent thermal reset uncertainty. All 56 installed MIM units occupy summed
coupon bottom footprints of 132.8096 µm² before routing/spacing/transistors.


## SS85 calibration boundary

`ss85_top_nominal_r1` completes with unchanged geometry and timing. Fitting only
its own first two calibration words gives RMS/max 0.013142/0.016809 MAC and
radix 0.50001096/0.50001450: deterministic per-corner **PASS**. Applying the
original frozen TT27 calibration instead gives RMS/max 0.228690/0.286050 MAC
on the same ten fresh words: **FAILED**. SS85 gain is 0.9968078 times TT gain;
offset shifts +502.203 µV. Recalibration cannot be treated as free or silently
used to erase this PVT failure. Capacitor mismatch is still absent.

The initial fixture has asymmetric fresh products (minimum −2, maximum +49);
±119 are calibration endpoints. A separate frozen 34-word extension retains
the original twelve words, then adds exact sign reversals of the nine nonzero
fresh probes, six independently seeded mixed-extreme vectors each immediately
followed by its opposite, and a final zero. Seed91637 and the full chronological
word list are frozen in source/manifest before simulation. This extends coverage
without changing calibration, topology, geometry, or copying any internal state.


The independent 10 ps maximum-step control completes **PASS**. With the original
20 ps calibration retained, fresh RMS/max are 0.02894974/0.03446402 MAC; maximum
raw output difference over all twelve words is 0.287865 µV. Gain changes by
0.804 ppm. This supports the numerical stability of the nominal deterministic
result. `build/campaign/signed_grounded_core/controls_r1.json` records immutable
result hashes and separates frozen-TT from per-corner calibration. Under frozen
TT calibration the SS85 all-twelve-word maximum error is 0.642781 MAC, including
the original endpoint inputs; its fresh-only maximum remains 0.286050 MAC.


## Bounded timing candidate and numerical extension status

Native equal-terminal ON-TG AC conductance across nineteen biases 0.45–1.35 V
(`on_conductance_r2/result.json`) gives sampled minima 95.230 µS for the phase
TG and 42.009 µS for the bit TG, both around 1.0 V. The phase differential-mode
capacitance is approximately 120fF/2, giving local settling tau≈0.630 ns;
150 fF per-side loading would give ≈0.788 ns. A four-unit bit bottom has about
17.43 fF mutual-plus-bottom-substrate loading before MOS terms, giving ≈0.415 ns
with the sampled worst bit resistance. These are local scalar estimates, not
proven worst-case large-VDS or nonlinear full-network poles.

The `--fast` candidate keeps every 0.2 ns edge and uses a 40 ns plane:
reset release6, row change8, share ON18/OFF28, array reset32, row return34 ns.
Three planes plus 40 ns closing reset give 160 ns per word. Geometry and all
calibration inputs are unchanged. The default generated deck remains byte-for-
byte identical to the original nominal deck after this timing parameterization.
Both own-firstpair and original-frozen-TT calibration must be reported.

The 34-word 20 ps extension aborted numerically at8.45µs before its9.56µs stop,
with an ngspice timestep2.5e−23 failure at vshb. This is **INCOMPLETE**, not a
physical accuracy pass or fail. Its complete partial trace is losslessly gzip-
archived with decompressed SHA verification in failure.json. A matching 10 ps
retry preserves all chronological stimuli without copying simulation state.
