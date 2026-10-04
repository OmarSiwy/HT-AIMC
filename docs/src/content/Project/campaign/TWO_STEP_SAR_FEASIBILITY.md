# Native coarse SAR followed by one FIA residue conversion

Status: **SPECULATIVE architecture; bounded deterministic component evidence**.
This is a feasibility study, not a complete converter, noise qualification,
or novelty claim. It targets the original Q8_0 group32 path being calibrated in
`scripts/compiler/metrics/imc_raw32_precision.py`. Its 40 uV read-noise knob is additional
to stationary reset/share kT/C; quantization is modeled separately.

## Actual source and charge units

For one bank and 32-row group, using fF and fC,

```
Q = Cu * 0.45 * sum(qx * digit) / 2^B
deltaQ = (3.75 * Cu/4)/16 * Vspan
deltaV = deltaQ / Cnative
F_native = 2^bits * deltaV = Chost/Cnative * Vspan
Chost = 2^(bits-4) * (3.75 * Cu/4)
```

Vspan is a DAC reference swing, not necessarily the native voltage span.
The original FP16 weight scale and input scale multiply each group's result
before digital summation. The second bank has digital radix eight. Neither bank
may be merged across unequal group scales without accounting for those scales.

Across all 210 matrices, actual unpadded Cu4 code loading plus 120 fF column floor
is 583.31/791.89/1021.01 fF min/median/max for the low bank and
481.65/961.76/1775.73 fF for the high bank. The ADC host floors at 10/11/12 bits
are 240/480/960 fF. These statistics establish loading, not the selected precision
or signal range. Frozen calibration is still required before selecting bit split
and reference levels.

## Proposed physical sequence

1. Preserve the native group result while a coarse SAR subtracts its selected
   charge code. Bound actual signal disturbance from comparator kickback.
2. Connect one short-L FIA to the resulting physical residue and amplify once.
3. Open real transmission gates between the FIA drains and its existing output
   storage capacitors. Perform fine SAR decisions on those isolated capacitors.
4. Combine coarse and fine codes with measured gain, offset and DAC radix;
   reset and acquire the next result with all charge and clock costs counted.

The output hold should be the existing nominal 250 fF per-side output capacitor,
not a fresh equally sized capacitor attached after amplification: the latter
would halve the voltage by charge sharing. A fine CDAC must be included in the
250 fF load during amplification. At Cu=3.75 fF, a binary five-bit array including
dummy uses 120 fF; six bits uses 240 fF; seven bits uses 480 fF and therefore
cannot inherit the existing 250 fF gain result. Smaller units require separate
PDK/layout and matching justification. Device and MIM parasitics add load.

Isolation is not noiseless. Its TG resistance, channel-charge partition,
feedthrough, thermal mode, leakage and fine-comparator kickback need simulation.
FIA input noise is sampled once and is common to all fine decisions; fine-bit
count does not average it down.

## Coarse uncertainty, redundancy and information loss

Let native span be F, target spacing delta, coarse count bc, and
Delta_c=F/2^bc. If each decision perturbation is bounded by D and the coarse DAC
is otherwise exact, the interval invariant permits a residue magnitude

```
R >= Delta_c/2 + D
bf >= ceil(log2((Delta_c + 2D)/delta))
```

Additional DAC and gain errors require additional guard. A Gaussian comparator
with RMS sigma is not bounded; using D=k*sigma gives a union-tail estimate
2*bc*Q(k), before correlation or non-Gaussian qualifications. For seven coarse
decisions this is about 1.9% at k=3, 443 ppm at k=4, and 4 ppm at k=5.

Illustration only, **not a selected group32 target**: 12 bits, Vspan=0.25 V and
Cnative=1 pF give delta=58.594 uV and F=0.24 V. Seven coarse bits give
Delta_c=1.875 mV. With the earlier conditional comparator RMS of 403 uV,
five-sigma guard requires 5.905 mV fine full range, about 101 target levels,
and therefore seven fine bits. Even three-sigma guard requires seven. A fixed
seven-plus-five choice is consequently unjustified before the actual range and
decision noise are known.

Redundancy can correct a wrong coarse *decision* when the selected DAC code is
subtracted faithfully. It cannot reconstruct unknown charge deposited on the
native signal by comparator kickback. Decision uncertainty and persistent native
charge disturbance must be measured independently.

## Native evidence and limits

Unchanged `tb_imc_fia.py`, TT27, Wn/Wp=22/44 um, L=0.18 um,
Cres=2 pF, Cout=250 fF, acquisition TG13.44 um and output-reset TG3.36 um:

| Evidence | Result | Scope |
| --- | --- | --- |
| 1 pF holder, +20 uV fixture | acquired20.21852 uV; pre-latch17.10723 uV; acquired-input gain18.50865; 2.20179 pJ | Deterministic single comparator cycle, ideal clock/reference ports |
| Same 1 pF run, eight inputs including +/-100 mV | all signs PASS | Sign correctness does not establish linearity/noise |
| Earlier 2.4 pF improved-reset fixture | acquired-input gain about20.077 | Larger holder reduces FIA gate-loading effect |
| Connected N1 6 pF source, frozen +/-500 uV calibration, +/-5 and +/-10 mV validation | maximum error4.6753 uV | Actual residue transfer at6 pF, not qualification at1 pF |
| Connected N4 6 pF source, same range | maximum error45.8398 uV; reset19.94 uV | FAILED range/reset gates |

The 1 pF source loses about15.4% of its acquired differential voltage during
amplification. This is not automatically a product error after calibration, but
it invalidates importing stiff-source gain or noise without a coupled model.
The first -2 mV word has acquired-input gain18.41676 versus18.50787 on the
following positive word, so startup/history must remain visible.

Raw evidence: `build/campaign/fia/tt_raw32_holder1p0_acq13p44_reset3p36_r1/`
contains immutable source, deck, manifest, trace and result. Connected range
results are in `build/campaign/fia_stack/n1_tt_reset20_residue10m_r1/` and
`n4_tt_reset20_residue10m_r1/`.

The independently qualified reduced stiff-source charge/gm/gds model predicts
37.838 uV final-sample FIA white noise for short L. With 403 uV comparator noise
divided by stiff gain21.4936, quadrature read noise is about42.24 uV before hold
isolation. This is conditional, omits several noise modes, and is already above
40 uV. A50 uV budget would leave about26.8 uV quadrature for remaining read terms
under those same assumptions. **Do not count quantization inside that read-noise
knob or reuse this stiff-source result as a verified1 pF noise prediction.**

## Gain/radix and service cost

A fractional gain error epsilon contributes approximately R*epsilon input error.
Gain and offset must be calibrated without fitting validation inputs. Actual
coarse-step/fine-step ratio must be measured independently of native distributed
input gain. The N4 connected fixture measured16.28995 rather than nominal16.
If its low four bits were ideal binary levels0...15, the coarse-boundary gap
would be1.28995 fine LSB (DNL +0.28995). Digital gain labels do not fill physical
level gaps; all weights and carries still need evaluation.

Using a20 ns comparator cycle and30 ns amplification gives a provisional
270 ns for7 coarse +5 fine decisions, before required acquisition/reset overhead.
This is not a measured converter latency. Likewise one2.2 pJ FIA event plus
eleven additional114.25 fJ latch events is about3.46 pJ of incomplete component
arithmetic; DAC references, clocks, storage, logic, calibration and service
schedule remain unpaid. Seven fine bits would increase both costs and loading.
No working every-decision-FIA ADC exists here as a measured baseline, so no
claimed speedup over that hypothetical architecture is appropriate.

## Prior art and next falsification

Once-per-residue FIA amplification in pipelined SAR is established prior art.
Park et al. implement a cyclically charged FIA as an open-loop residue amplifier
and adjust its operating region and gm/ID through switched reservoir reuse.
Their65 nm measured prototype is a technology-specific comparison, not a number
to import into Sky130. [KAIST primary publication record, JSSC2024,
DOI10.1109/JSSC.2024.3419759](https://pure.kaist.ac.kr/en/publications/a-high-resolution-pipelined-sar-adc-using-cyclically-charged-floa/).

The next physical test is a matched1 pF input, actual output-isolation TG and
existing storage load, frozen calibration, extended hold/reset and large-to-small
residue history. It is owned by the stack branch. A complete SAR follows only if
the actual calibrated group32 range/spacing, guard-bit loading and noise budget
survive that test. PVT, mismatch, stochastic transient noise, DAC code coverage,
PEX, supply/reference noise and full service scheduling remain unverified.

## Frozen raw32 target update

`build/campaign/raw32_precision/calibration_summary.json` now selects11/12 bits,
predominantly11 bits with reference spans0.25/0.5 V and12 bits with0.25 V.
Native spacing spans30.38--244.14 uV; native coverage spans0.0622--1 V across
the selected capacitance extrema. Maximum observed calibration signal is
0.16568 V, not a worst-input guarantee. The model has6.636 million bank
conversions and76.129 million decisions per token. Calibration includes clips;
end-to-end quality is not implied by these selections.

Applying the conditional403 uV coarse comparator RMS and five-sigma guard to
seven coarse bits requires6--8 fine bits across those extrema, with required
native residue half-range2.258--5.921 mV. Typical12-bit,0.25 V reference,
960 fF native loading gives61.035 uV spacing and requires seven fine bits.
Actual coarse comparator noise and kickback at these loads remain unqualified.

The new floating-input two-state native-port model predicts gain within0.8%
and input retention within0.4% of the1 pF trajectory. Its conditional added
FIA white noise is40.275 uV; with the earlier latch noise divided by measured
gain, about45.8 uV before remaining receiver modes. See
`FIA_INDEPENDENT_AUDIT.md` for the equations and important interface difference:
two independent1 pF differential holders have91.04 uV native noise, whereas the
raw32 scalar1 pF model has64.37 uV relative to an ideal reference. A complete
physical architecture must resolve that difference rather than silently
counting one native holder while simulating two.

## Split fine DAC: avoiding the unsplit loading penalty

The480 fF seven-bit figure above applies to an **unsplit** binary array. A known
split4+3 array can preserve the250 fF ideal electrical output load. Let Cu=3.75 fF,
Cm=15Cu main array, Cl=8Cu lower array including dummy, Cb=8Cu/7 bridge, and
Chold=190 fF directly at the main node. The two node charge equations are

```
(Chold+Cm+Cb) vm - Cb vl = Qm + sum(Cmain_i Vbottom_i)
-Cb vm + (Cl+Cb) vl = Ql + sum(Clow_i Vbottom_i)
```

Eliminating vl gives main capacitance
Chold+Cm+Cb*Cl/(Cb+Cl)=190+56.25+3.75=250 fF and low-array attenuation
Cb/(Cb+Cl)=1/8. Its smallest output voltage step is
(Cu/8)/250*Vref=0.001875*Vref. Main and lower effective weights consequently form
the intended seven-bit binary progression in this ideal charge graph.

Physical array capacitance is(15+8+8/7)Cu=90.5357 fF, and total including the
190 fF hold is280.5357 fF per side,12.2% more than the original250 fF. Electrical
loading and physical capacitor area are distinct. Routing, substrate and MOS
parasitics have not been included in the250 fF figure.

At illustrative gain18.1, exact matching to the calibrated native30.38--244.14 uV
spacing requires Vref=delta_native*18.1*250/(Cu/8), or0.293--2.357 V. The upper
end exceeds the1.8 V rails, but that alone does not reject the architecture:
a finer fine-stage spacing can still provide adequate residue coverage. The
actual feasibility condition is

```
(Delta_c+2D)/2^bf <= delta_fine <= min(delta_target, delta_hardware_max)
```

with endpoint/sign-code conventions and further guard evaluated in the real
ADC. Seven bits still do not satisfy the tightest calibrated spacing with the
conditional five-sigma guard. A split4+4 eight-bit array uses Cl=16Cu,
Cb=16Cu/15, retains16Cu main-equivalent load, and physically uses120.25 fF
before the190 fF hold. Its lowest weight is Cu/16. This is an optional sizing
alternative, not a validated implementation.

The low-node parasitic is especially consequential. With Cp at that node,
the main-unit/low-unit radix is R=1+(Cl+Cp)/Cb. For split4+3,1 fF unmodeled Cp
increases R by0.2333 fine LSB, producing conditional coarse-boundary DNL+0.2333
when the lower three bits are ideal binary. A1.034% parasitic on the30 fF lower
array alone would contribute0.3102 fF and DNL+0.0724 if its substrate plate
coupling lands at that node. Actual capacitor orientation, bridge parasitics,
reset TGs, bottom-switch capacitance and voltage dependence must be extracted.
Direct main-node loading alters gain but does not by itself alter this radix.
The previously measured N4 radix failure demonstrates why nominal split
arithmetic is not physical validation.

Lower-node initialization adds a charge state and potentially an independent
reset-noise mode. It must be initialized through actual switches; a noiseless
initial charge is not implicit in the equations. The complete reset/isolation
covariance, references, fine switching energy, leakage, mismatch and all carry
transitions remain required checks. Generic split CDACs are established prior
art; the proposal is a bounded loading remedy, not a novel circuit claim.
