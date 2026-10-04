# Readout alternatives after the split-CDAC nulling prototype

Research follow-up, 2026-09-09. **The next distinct topology worth testing is a six-bit coarse CDAC with four-bit bidirectional charge injection directly onto the retained node.** It removes the split DAC's fine node and confines the charge-injection circuit to a small residual range. It does not remove the ten comparator decisions. A capacitor-biased preamplifier is a separate, promising experiment for making those decisions accurate without standing bias. Neither proposal has a demonstrated complete-service energy or noise advantage in Sky130.

This follows the user's [27h10 null-balancing note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27h10 A Null-Balancing SAR Readout Pays for Precision with Matching Instead of Standing Bias.md>), the converter discussion in the [contract](CONTRACT.md), and the [Mythic review](IMC_MYTHIC_NULLING.md). The existing charge-domain accumulator has already removed the compute OTA. A derived null-versus-TIA bias saving cannot be multiplied into its measured energy again. Patents establish disclosed mechanisms; they do not identify every detail of a shipped Mythic chip.

The split 6+4 implementation remains the immediate control to repair and integrate. Its separate voltage-acquisition fixture does not yet prove conversion of the passive IMC result. Avoid changing ADC topology solely to discard an unfavorable diagnostic result.

## What the primary circuits actually contribute

**CAP-RAM: direct conversion of already-held charge.** Its seven-bit differential ciSAR replaces a sampling capacitor DAC with long-channel MOS charge-injection cells. Figure 10 includes selected transfer paths, bias devices, a channel-charge reservoir and reset. Sixteen unary cells serve the binary search; the largest step reuses all sixteen twice. The cells only remove charge, so the comparator steers removal between differential nodes. Its 6.85 ENOB is a transient-noise simulation. These are useful interface and reference-loading ideas, but neither ten-bit operation nor 100-µV input noise follows from that result. The public paper's Figure 10 was inspected directly. [CAP-RAM, §III-B and Figures 10–11](https://arxiv.org/pdf/2107.02388).

The original ciSAR paper clarifies **interrupted settling**: transfer current decays as the reservoir rises, and switches terminate the packet before the next decision. The taper reduces timing sensitivity; high output impedance limits dependence on the held voltage. Reusing the same cell also avoids allocating a separate device to every DAC weight. The measured 40-nm design is six bits, 1 GS/s and 1.26 mW, hence **1.26 pJ/conversion**; each integration capacitor is 200 fF. Its common mode is near supply for transfer-device headroom. It does not demonstrate the same behavior at AnalogIOC's 0.9-V center. [Choo, Bell and Flynn, ISSCC 2016](https://www.mpflynngroup.com/uploads/7/3/4/9/73490609/07418106.pdf).

**A coarse/fine hybrid is grounded in a higher-resolution implementation.** Choo et al.'s image-sensor ADC uses coarse/fine charge paths, capacitor division, cascodes and per-path calibration. The tapering packet improves timing tolerance; the cascode addresses voltage-dependent charge transfer. A dummy path makes reference loading independent of the decision, but its charge and clock energy still count. The measured **104-µV** readout uses multiple sampling; the **63.6-pJ/pixel** energy point excludes the programmable controller and is not the energy of that lowest-noise setting. This supports the mechanism, not a sub-pJ solution. [2019 JSSC author manuscript, §§II–V](https://blaauw.engin.umich.edu/wp-content/uploads/sites/342/2020/06/Energy-Efficient-Motion-Triggered-IoT-CMOS-Image-Sensor-With-Capacitor-Array-Assisted-Charge-Injection-SAR-ADC.pdf).

**A more useful low-noise comparator lead than a complete high-resolution ADC.** The 180-nm/1-V c-ciSAR paper reports a simulated capacitor-biased preamplifier at **87 µV RMS and 150 fJ**, plus a **60-fJ latch**. Its capacitor tail progressively moves the input pair into weak inversion; high source/drain reset helps decorrelate trapping. Figure 27.2.3 shows a 1-pF tail and 400-fF output capacitors. The measured full ADC instead uses two 8-pF CDACs, mismatch correction and fifteen repeated LSB decisions. Its **0.468 µW / 6 kS/s = 78 pJ/conversion**; **4.32 fJ is a Walden FoM**, not conversion energy. Thus copy the dynamic-bias idea into a sizing experiment, not its numerical energy/noise point into our chip budget. The comparator figures are simulation and do not measure total readout noise. [Choo et al., ISSCC 2021, Figures 27.2.3–6](https://blaauw.engin.umich.edu/wp-content/uploads/sites/342/2022/09/184.pdf).

**PICO-RAM: one precision crossing can replace repeated fine decisions.** Its VTC discharges the existing arithmetic capacitance; an auto-zeroed low-power detector enables the accurate detector and time latches shortly before crossing. The reported **55.8% local ADC energy reduction** excludes interpreting the shared free-running oscillator as free. Its folding TDC uses oscillator phase and a coarse counter, with synchronized stopping. Measured output noise averages **0.4 LSB** over eight groups; a standalone 100-µV converter result is not supplied. The table pairs **40.2 TOPS/W with 0.65 V and 3.8 GOPS**, while 50.3 GOPS occurs at 1.2 V. These are W4A4 macro points, not our W8A8 readout budget. [PICO-RAM, §§IV–V and Table I](https://arxiv.org/html/2407.12829v1).

## Proposed six-plus-four retained-charge nuller

This is our proposed combination, not a reproduction of one paper. Let the actual connected hold capacitance be `C_H`, the intended total ADC span be `V_S = 0.5 V`, and `delta = V_S/1024 = 488.28125 µV`.

Replace the split network by a coarse bank with weights `32,16,8,4,2,1` and one dummy, ideally in units `C_H/64`. During arithmetic, its bottoms remain at their specified reference so that the bank serves as the accumulator. During conversion, those six bottom-plate controls provide the coarse trials. **The total capacitance, including CI ports, comparator input and parasitics, must still equal the effective array capacitance required by the accumulation recurrence.** This is an integration requirement, not something achieved by selecting nominal ideal capacitors.

In a real implementation, distinguish the switchable bank `C_D` from `C_H = C_D + C_parasitic`. Its coarse unit is `C_D/64`, and its full voltage range is `V_reference_span*C_D/C_H`. Recovering the chosen 0.5-V range requires correspondingly larger reference swing, or accepting and calibrating a smaller range. The tables below are ideal sizing examples before that correction; adding the existing filter capacitor on top of them is not free. A common reference cannot independently repair different per-column ratios without additional range/gain handling.

After an ordinary six-bit search, the coarse trial lies below the input by less than `16 delta`. Keep that coarse state and use signed CI packets for the final search:

1. Add `8 C_H delta` to the residue and compare.
2. Add or remove `4 C_H delta` according to the actual comparator decision; compare again.
3. Repeat with signed two-unit and one-unit packets.
4. The final sign selects the trial code or the preceding code.

All **1,024 interior input codes** passed an ideal charge-arithmetic enumeration with an input at one quarter LSB inside each code. The identity error was zero at the tested numerical precision. The diagnostic record is imc_hybrid_null_sar_ideal.json. This checks a ten-comparison search, with at most fifteen unit-packet activations in the fine phase; it contains no device, timing, energy or noise model.

**Both packet signs are necessary.** CAP-RAM's down-only cell cannot implement this single-ended sequence. Use complementary source/sink cells, or explicitly add and price a second held node with differential steering. A golden-precomputed packet sequence is not a closed converter. Likewise, connecting a precharged capacitor to a floating node performs charge sharing, not an ideal additive packet; the transfer device and its finite output impedance must appear in the netlist.

| Sizing quantity | 768-fF diagnostic hold | 3.628-pF illustrative W8 low-slice hold |
|---|---:|---:|
| Coarse unit, `C_H/64` | 12 fF | 56.69 fF |
| Fine unit charge, `C_H delta` | 0.375 fC | 1.771 fC |
| Largest fine packet, eight units | 3.000 fC | 14.172 fC |
| Maximum fine search range | 7.8125 mV | 7.8125 mV |
| Maximum independent unit-packet RMS for a 60-µV fine-DAC allocation, fifteen activations | 0.01190 fC | 0.05620 fC |

The last row follows `sigma_V = sqrt(15) sigma_Q/C_H`. It is a diagnostic allocation, not a measured stochastic model; correlated reference noise adds differently. The proposed fine path needs roughly percent-level aggregate packet accuracy to keep systematic error near 100 µV over its small range. A full-range CI path would demand much tighter voltage independence. Constant gain calibration cannot remove output-voltage-dependent packet error, polarity asymmetry or sequence-dependent injection.

For the 768-fF ideal case, replacing the existing 960.8-fF physical split-capacitor sum with 768 fF removes **20.1% of those ideal capacitors** before adding CI circuitry. It does not predict a 20.1% energy saving: coarse reference charging remains, packet cells and gates add load, and ten latch decisions still occur. The energy comparison must include reset and acquisition as well as conversion.

The cheapest first falsification is a **single up/down CI pair**, before constructing another complete ADC. Sweep the held voltage over the actual fine residual interval and then across the earlier coarse range as a negative stress case. Measure charge removed/added after switch-off, pulse-duration sensitivity, residual settling, polarity mismatch, all-port energy and PVT. Select pulse timing on a flat portion of the charge-versus-duration curve. If no adequate window or output independence exists, a bigger SAR FSM will not fix the cell.

## Why the other options remain conditional

| Option | Potential saving | Cost that can erase it | Decision |
|---|---|---|---|
| Integrated split-CDAC accumulator | No second full sampling bank; passive reference steps | Fine-node parasitics, reset injection, retained-state disturbance | Continue the existing circuit control and its full integration |
| Unsplit ten-bit accumulator/CDAC | Removes the bridge and fine-node ratio sensitivity | Larger capacitance or coefficient-dependent bank sizing | Test only as a controlled loaded low-slice alternative |
| Six-bit coarse CDAC plus four-bit CI | Removes fine split node; CI covers only a small range | Both packet signs, calibration, CI noise; still ten decisions | Best distinct next nulling experiment |
| Full-range direct CI or local mirror accumulator | Avoids a new sampling CDAC; can share precision bias | Output dependence, full-range charge, headroom, reference and reset noise | Require packet characterization before committing to a complete ADC |
| Gated VTC/TDC | One precision crossing, potentially fewer latch kicks | Precision detector on-time, ramp noise, oscillator/counter energy, timing linearity | Next alternative if repeated comparisons dominate after the nuller closes |

The unsplit option deserves a precise caveat. A 4.096-pF ten-bit bank has 4-fF units, physically more plausible than the sub-fF units implied by a 0.5-pF bank. However, the [actual alpha-0.5 W8 distributions](IMC_SMOOTH_RADIX.md) have median low/high loads of 3.628/0.612 pF. Forcing both to 4.096 pF increases those capacitances by **12.9% / 569%**. The array side must change too to retain the equal-capacitance radix. Programmable ballast, per-column sizing or changed range is real hardware; one cannot assume a constant bank preserves the computation. The low and high slices need different measured comparisons.

Finally, the readout budget depends on the **number of actual services per useful MAC**. Two W8 magnitude slices need two services today. A single sign-routed four-magnitude-bit bank supports `-15…15`: that is **five logical signed bits**, not native W4, and still potentially one service. The subsequent [W5–W7 format screens](IMC_GROUPED_WEIGHTS.md) now test this route: none closes the joint A8 quality gate. W6/W7 also require larger five/six-magnitude-bit capacitor banks. Counting only one W8 slice remains invalid. Logical weight precision is separate from the ADC's ten-bit output width.

## Follow-up: comparison energy must change too

In the repaired twelve-input TT development fixture, comparator, receiver
and timing-port delivery together are about **0.986 pJ/conversion**, before
DAC references, mux control, acquisition and state-drive energy. Holding that
measured decision-stage energy fixed already exceeds the optimistic
0.704-pJ W8 service allowance. A changed DAC schedule can also change comparator
residues and activity, so 0.986 pJ is a budget diagnostic, not an invariant
floor for every circuit using the same transistor sizes. Both decision-stage
and DAC energy need measurement under the replacement schedule.

One candidate is unequal comparator precision across the search. Ahmadi and
Namgoong's analysis optimizes comparison power by bit step; its simulations
find two comparator classes approach the many-comparator optimum. It is a
reason to investigate a small fast stage plus selectively used quieter stage,
not evidence of a percentage saving in AnalogIOC. Offset between stages,
redundancy/correction, input loading and timing must be included. A late quiet
decision cannot automatically repair an earlier wrong interval selection.
[Primary paper record and abstract](https://researchconnect.suny.edu/en/publications/comparator-power-minimization-analysis-for-sar-adc-using-multiple/).

A newer device-level lead is Wu et al.'s CICC 2024 stacked floating
preamplifier. Its publisher abstract describes fourfold current reuse without
another reservoir capacitor or input-bias generator, cross-coupled gain
enhancement, and reports **27.3 µV at 0.25 pJ per comparison** in 180 nm.
The full circuit paper was not accessible through the available tools, so its
measurement method, sizing, complete power boundary and transferability are
not verified here. Ten such reported decisions alone would be 2.5 pJ;
the lead is the topology and possible precision allocation, not a completed
sub-pJ ADC or a justified inverse-noise scaling law.
[Wu et al., DOI 10.1109/CICC60959.2024.10529044](https://ieeexplore.ieee.org/document/10529044/).

## Three-level reference loading: a fast sizing screen

The physical three-level candidate now passes twelve TT/SS development inputs
at 1.455/1.483 pJ per conversion, with eight-column history checks pending.
It follows the user's
[23v1 midpoint-error note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/SAR ADCs/23v1 An Error in the Half-Reference Voltage Produces Nonlinearity.md>)
and [23v2 reference-load note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/SAR ADCs/23v2 The Half-Reference Generator Sees Its Smallest Load Only in Cycle One.md>).
The midpoint becomes a DAC rail, so sharing its precision source must include
both static accuracy and the larger load after the first decision.

The new reference-load screen
enumerates all **1,023 precomparison prefix states** in about 0.06 s. It retains
the physical 756-fF coarse bank, 192-fF fine bank, 12.8-fF bridge and merged
24-fF midpoint dummy. Its 60-fF input filter is treated as settled. With
floating-top capacitance matrix `T` and top-to-reference coupling `A`,
the exact reduced rail matrix is `Crail = diag(sum(A)) − Aᵀ T⁻¹ A`.
Independent full-node charge and stored-energy identities pass at every state.
This is a quasistatic network calculation with ideal switches, not a closed
ADC simulation.

The midpoint's load with the other rails ideal grows from **55.65 fF** at
the first comparison to **205.91 fF**. If all three sources instead have the
same resistance, the largest rail-capacitance eigenvalue across valid states
is **460.54 fF** per column. Coherent switching of N identical columns
multiplies those values by N; sharing a source does not make its load constant.

For a deliberately stated allocation of an excited mode decaying from 250 mV
to 100 µV in 12 ns, the time constant must be at most 1.534 ns. The midpoint-only
case then allows about **931 Ω for eight coherent columns**, assuming ideal
end rails and switches. An unbuffered equal-resistor divider across the 0.5-V
end-rail span dissipates `P = span²/(4 Rout)`: about **67.1 µW**, or **2.48 pJ
net per 295-ns column service**. With the converter's ground-referenced
0.65/1.15-V sources, the high source delivers `1.15*I` while the low source
absorbs `0.65*I`. The corresponding **positive port delivery is 5.69 pJ per
service**, matching the converter headline's accounting convention; no
recovery of returned energy is assumed. Increasing the number of synchronously served columns
does not amortize this particular divider's energy per conversion, because
its required conductance grows with their load. It already costs more than
the ideal-source converter result under this allocation.

This is **not a universal reference-energy bound** or a demonstrated SAR
settling error. Actual switched initial conditions, mode amplitudes and
comparator sensitivity still matter. Decoupling, an active or switched buffer,
phase staggering, different timing and a different reference topology can
change the trade. Local switch resistance, the filter's 8-kΩ dynamic response,
MOS/parasitic loading, reference noise and reset distribution are omitted.
The result rejects treating a low-impedance passive divider as free; the next
reference implementation needs its own transient, noise and all-port energy
check. Artifact: imc_reference_load.json.

## Next finite-reference experiment for the VCM-start circuit

The smallest useful next test is a **shared finite midpoint source feeding the
actual CDAC, reset switches and comparator-threshold distribution**. Replacing
only the CDAC's midpoint while retaining ideal reset and threshold voltages
would miss both load and coupling paths. Start with the existing closed
one-column circuit and its frozen difficult histories, then a coherent
eight-column control. Preserve acquisition, physical warmup, closing reset,
fixed trim, trial timing and receiver gates. This is a proposed experiment;
no finite-source transistor result is claimed here.

First separate three energy quantities. The existing 12-ns/250-mV/100-µV
allocation gives **2.475 pJ of divider resistor loss**, but **5.693 pJ of
positive endpoint-source delivery** per column per 295-ns service. These are
different accounting boundaries. The high and low references are themselves
ideal in that divider screen. A full passive resistor string generating all
three levels directly from 1.8 V would cost still more; it is a useful negative
control, not an attractive architecture. Neither number is a lower bound for
a bidirectional active buffer or a switched reference.

The charge that actually needs correction is a more useful starting point
than maintaining maximum conductance for the entire service. In the screen's
ideal, settled network, the first 384-fF MSB capacitor moves by ±0.25 V. With
`T` equal to the testbench's top-node matrix and `A_after` its coupling matrix
after that switch,

```
delta_top = inverse(T) * [384 fF * 0.25 V, 0]
delta_Q_mid = -transpose(A_after[:, midpoint]) * delta_top
```

This gives top-node movements **115.942/7.246 mV** and midpoint charge
**44.522 fC per column**, with opposite sign for the opposite decision.
Applying the same calculation to the nine monotonic updates gives
**74.128 fC total absolute midpoint charge**, or **66.715 fJ of midpoint
|V·Q| at 0.9 V**. These are conversion-only ideal charge calculations: they
exclude acquisition, reset, finite filters, switch injection and buffer
supply/control energy. They are not a reference-energy prediction. They do
explain why a buffer that supplies or absorbs charge briefly could improve
substantially on an always-conducting divider.

A decap-only solution is unattractive at the strictest interpretation. Holding
that first event below 100 µV **instantaneously with no source correction**
requires about **445 pF per column**, or **3.56 nF for eight coherent columns**.
Actual decision-time error can permit less capacitance and some recovery;
the number is not a hardware lower bound. A modest local reservoir may help
with peak current, but a large capacitor behind a weak source can preserve a
data-dependent droop into subsequent decisions. The user's
[reference-bypass note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Bandgap and References/10j1 Bypass Capacitance Trades Disturbance Rejection For Recovery Time.md>)
and [frequency-dependent output-impedance note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Bandgap and References/10j Reference Output Impedance Rises Back To Its Open-Loop Value.md>)
describe this recovery/stability trade.

Use the following finite passive control before sizing an active replacement:

1. Feed the real `vlo` and `vhi` buses through explicit series resistances,
   with their upstream ideal DC sources retained and counted. Derive `vcm`
   with two equal resistors between these **local** endpoints, with a selectable
   local decap. This first control characterizes finite distribution; it does
   not implement the endpoint generators.
2. Split the distribution into named CDAC, reset and quiet-threshold branches,
   each with explicit branch resistance and any intended capacitance. The
   threshold's existing −1.9-mV trim should be a series offset relative to the
   finite quiet branch, not another ideal voltage to ground. Keep the trim
   source visible in energy accounting until its physical implementation exists.
3. First measure the direct shared-branch connection, then only one optional
   quiet RC branch. Record individual rail and branch currents, signed and
   absolute charge per reset/update, minimum/maximum local voltages, and
   `vinp-vinn` immediately before each real decision. Check final codes,
   receiver feedback, baseline error gates, inter-cycle recovery and capacitor
   energy at both service boundaries.
4. Use both polarities of coherent first-bit transitions, the fine-bank
   transition, alternating extreme inputs across frames, and the existing
   difficult SS history. Only after a one-column control passes add eight
   coherent columns and one quiet victim during an aggressor's update.

Midpoint error is not generally common-mode rejection or one removable offset.
During a held conversion, the incremental top-node response is the current
row of `inverse(T) * A`; a shared threshold subtracts the quiet-branch response.
The reset/acquisition history adds another stored-charge term. These weights
change with each decision. The user's
[half-reference error note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/SAR ADCs/23v1 An Error in the Half-Reference Voltage Produces Nonlinearity.md>)
therefore matters as much as the load note: preserving DC midpoint or fitting
one offset does not establish low INL under dynamic reference movement.

The preferred active follow-up is a **low-quiescent bidirectional buffer with
a modest local reservoir**, driven by a quiet, lightly loaded midpoint
setpoint. It must both source and sink the measured charge. Size peak current
from measured `Q/t`, then use gm/ID and the actual closed-loop poles to close
small-error settling; do not replace a MOS output stage with an ideal voltage
follower for the energy result. For scale, 44.522 fC corrected in 2 ns needs
22.26 µA per coherent column during that event. Conversely, a continuously
biased one-pole `gm/C` buffer meeting the screen's 1.534-ns time constant on
205.9 fF requires about 134 µS per column. At an illustrative gm/ID=20 V⁻¹,
its **6.71-µA, 1.8-V continuous bias alone is 3.56 pJ/service**. This is a
topology-specific sizing warning, not a lower bound: class-AB peak drive or
decision-dependent bias is the mechanism worth testing.

| Alternative | Useful mechanism | Cost the finite test must retain |
|---|---|---|
| Modest decap plus bidirectional buffer | Local charge during fast switching, active recovery afterward | Reservoir recovery, stability, supply and bias currents, reference noise |
| Two-level or decision-dependent buffer bias | High drive for reset/coarse transitions, reduced idle/fine bias | Wake-up settling, bias/clock switching, quiet-threshold behavior |
| Two phase groups of columns | Reduces coherent peak load | Unchanged total charge, phase-control energy and service schedule, aggressor activity during another column's decision |
| Switched-capacitor midpoint | Replaces static divider conduction with scheduled charge transfer | Both transfer phases, finite source resistance, ripple, kT/C, switch/clock energy and replenishment |

Sharing alone does not reduce the coherent divider's energy per conversion;
staggering reduces peak demand, not total charge. A switched midpoint is a
larger next experiment because a low effective source resistance can demand
substantial capacitor area and clock activity. CAP-RAM's charge-injection SAR
remains the separate architectural escape from a strongly driven CDAC
reference, with the packet accuracy and complete-energy gates discussed above.
[CAP-RAM](https://arxiv.org/pdf/2107.02388)

For every implementation, count each independent upstream supply once.
After replacing an ideal reference port with a physical generator, its output
power is an internal transfer and must not be added again to its supply power.
Report positive delivery and signed net delivery separately, including clock,
bias, trim and reset support; identify any energy returned to a rail whose
generator cannot recover it. Include startup separately or demonstrate
periodic steady state and charge recovery over complete services. These
deterministic tests still do not validate a 50/100-µV temporal-noise claim.

The immediate success criterion is a complete comparator-directed conversion at the same input error and actual load, with lower total service energy or shorter service time. The current 100/250-TOPS/W targets leave very limited energy for all omitted work; the [existing budget](IMC_CIRCUIT_CONVERGENCE.md) must be updated with measured native-precision compute and ADC costs together. No reviewed circuit establishes that an approximately 100-µV, sub-pJ Sky130 service already exists, and the current full-model quality study does not establish 100 µV as a universal sufficient limit.

## Physical reference-side matching after the VCM history failure

The 768-fF floating negative holder is a justified first control: with ideal
stiff bottom references, the positive split bank presents
`756 + 12.8×192/(12.8+192) = 768 fF` before the 60-fF filter. It replaces a
stiff negative source with a nominally comparable charge reservoir and pays
for its reset TG. It does **not** yet match the real positive driving
impedance. This follows the user's
[19g4 source-impedance explanation](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Comparators/19g4 Comparator Switching Kicks Transient Current Back Into Its Inputs.md>)
and [19j5 StrongARM coupling analysis](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Comparators/19j5 StrongArm Kickback Couples From the Falling Tail Nodes Through CGD.md>).

For a frozen linearized state with currents injected into the two input ports,
`δvd = (Zp−Zn) icm + (Zp+Zn) idm/2`, where `idm=ip−in`.
Matching impedances suppresses conversion of common-mode kick into differential
error; it does not cancel an inherently differential kick. During evaluation,
MOS capacitances and internal node voltages change, so one scalar capacitance
or one DC impedance is insufficient. Razavi identifies both source/tail
coupling and differential drain coupling; the latter grows when the input
devices enter triode. His alternative drain-clocked topology trades lower
kickback against gain and dynamic-offset problems, rather than providing a
free replacement. [Razavi, 2015, Figure 7 and “Kickback and Supply Transients”](https://www.eecis.udel.edu/~vsaxena/courses/ece517/Handouts/BR_Magzine_StrongARM_Latch.pdf).

Three physical quantities need separate checks:

- **Port impedance over the decision interval.** The positive bank includes
  the bridge/fine-node pole, rail-dependent TG on-resistance, off-switch and
  wiring capacitance, and finite shared reference impedance. Its effective
  capacitance changes when bottom plates cease to be stiff on the kick's
  timescale. The negative capacitor to ground lacks those paths. A recent
  primary study specifically identifies unequal DAC-switch resistances as a
  mechanism converting clock kickback into an early differential error; its
  publisher abstract is accessible, but its reported low-voltage result is
  not a quantitative Sky130 prediction. [Yuan, MWSCAS 2024](https://ieeexplore.ieee.org/document/10658857/).
- **Stored charge and reset history.** Equal TG geometry does not imply equal
  injected charge when terminal voltages and surrounding networks differ.
  Positive coarse/fine tops also experience acquisition and bottom switching;
  the negative holder is reset directly to the trimmed threshold. Compare
  both reset-release and later evaluation disturbances. The user's
  [23l1 top-plate injection note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/SAR ADCs/23l1 Top-Plate Switch Mismatch Is the Main Source of DAC Offset.md>)
  describes the differential charge error; this deterministic history
  asymmetry must be checked even before random mismatch.
- **Common mode and dynamic trip point.** A floating negative holder can make
  the two gates move together, changing input-pair charge and the available
  gain before regeneration. Its calibrated offset can therefore differ from
  the stiff-reference circuit. A fixed trim does not prove the trip point is
  constant across bit states, histories and corners. The user's
  [23o1 common-mode offset note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/SAR ADCs/23o1 Comparator Offset Drifts With the Input Common-Mode Level.md>)
  also cautions that the trend need not be monotonic.

If the calibrated holder fails the frozen SS history, use this bounded
discriminator before sweeping capacitance or changing the ADC architecture:

1. **Locate the first error in time.** Preserve the exact failing input and
   prefix. Record both holder/filter voltages, their common mode, the
   comparator's internal input-drain difference, both output polarities and
   receiver readiness. Integrate each input current separately over reset
   release, clock turn-on and regeneration. With only the known filter at a
   gate, its delivered comparator charge can also be reconstructed as
   `integral[(Vholder−Vgate)/8kΩ dt] − 60fF×ΔVgate`.
   The observed −13.5-µV pre-evaluation and −2.301-mV post-latch residuals do
   not alone establish causality: a late kick can be the consequence of a
   decision already made. Retain the original calibration-only trim rule.
2. **Compare scalar and replicated impedances in one frozen state.** Make an
   isolated comparator test with the actual troublesome bottom state fixed;
   physically precharge both inputs to the measured common mode plus a small
   differential and release them identically. Compare the scalar negative
   holder with a copy of the full split bank and its selected TG/reference
   network. Keep the real rail levels and make no bottom updates during this
   decision. This is a loading diagnostic, not a functioning SAR or a chip
   energy result. Identical live DAC updates on both sides would cancel the
   desired differential trial. Tying all replica rails to the threshold is
   a cheaper approximation, but changes the TG voltage-dependent resistance.
3. **Separate common-mode error from differential kick.** Repeat the isolated
   decision with input polarity reversed, then at the lowest/highest common
   modes actually recorded in the failure history, with the same reset and
   small differential. A replica that removes the early error implicates the
   unmatched network; a changing trip point under matched loading implicates
   common-mode/reset dependence. A surviving polarity-dependent input kick
   motivates isolation or cancellation at the comparator. Return any proposed
   remedy to the unchanged closed-loop history and strict suite afterward.

A concrete later alternative is an opposite-phase input replica that exchanges
charge with the input device, reducing the charge taken from the hold node.
Shahpari et al. describe this mechanism and plot the cancelling gate currents
in their ISCAS 2022 paper, Figures 5–7. Their comparator result is simulated
at 0.18 µm, 0.8-V common mode and 1-mV differential input, consuming about
0.98 pJ per comparison. It supports a charge-cancellation experiment, not our
energy target. [Primary conference paper, §III-B](https://confcats-event-sessions.s3.amazonaws.com/iscas22/papers/1139.pdf).
Alternatively, a preamplifier can absorb regeneration kickback, as discussed
above, but its bias, reset, input charge and gain variation must be priced.
Any physical replica adds loading and clock/reset/reference energy; none of
these deterministic matching controls establishes temporal-noise performance.


## Reset-noise cost of the matched floating holder

The scalar negative-holder experiment adds a real sampled thermal state.
`tb_imc_holder_noise.py`
checks a restricted passive model: CH to ground resets through a thermal
switch; a thermal R connects CH to the comparator-side CF. After an
explicitly assumed equilibrium reset opens, total charge is conserved.
Its filter-voltage covariance has a constant term `kT/(CH+CF)` and a decaying
term `kT CH/[CF(CH+CF)] exp(-|t|/tau)`, where
`tau=R CH CF/(CH+CF)`. The constant term survives averaging. This follows
the user's [sampled-noise derivation](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Sampling Circuits/18q Sampled Noise Power Is kT Over C Independent Of The Switch Resistance.md>)
and [compute-capacitor noise note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/27g2 kT Over C Noise Sets the Minimum Capacitor Size in a Charge-Domain Column Exactly as It Does in an ADC.md>);
the two-node covariance and sizing here are our derivation.

Referring through the positive path's ideal settled gain `g=CH/(CH+CF)`
gives a negative-branch reset contribution `kT(CH+CF)/CH²`. For CH=768 fF,
CF=60 fF and R=8 kΩ, this is **76.27 µV at 27°C / 83.32 µV at 85°C**.
If both sides were independent identical passive reset networks, the
combined reset-only values would be **107.86 / 117.83 µV**. The actual
positive split-CDAC has extra fine-node/reset/reference states, so the latter
is a symmetric model hypothesis, not its computed full noise. A hypothetical
16-ns boxcar leaves the negative branch alone at 99.23 / 108.39 µV including
its resistor noise; that boxcar is not a measured StrongARM aperture.

The check verifies equilibrium through the continuous Lyapunov identity and
then integrates physical branch-current Langevin noise in 16,384 independent
trajectories. The 16-ns variance agrees within 0.734%, the conserved-mode
variance within 1.162%, and maximum charge drift is 1.04e-30 C. Runtime is
about 0.5 seconds. Euler stepping at tau/64 introduces a small fast-mode bias (about 0.79% in its stationary variance); the 5% stochastic gate is a sanity check, not subpercent numerical validation. Results and reset-only sizing sweep.

This identifies a real cost of holding the negative input: deterministic
kickback matching does not provide noise cancellation. Larger matched
capacitance or an implemented correlated-reset cancellation method may help,
but their signal gain, area, reference energy and extra phases must be paid.
Finite reset, switch nonlinearity, comparator time weighting, correlation
between branches and intrinsic device/reference noise still need the clocked
model. These submodel minima cannot certify an ADC or override its quality gate.

## A redundant 6-coarse + 5-fine arithmetic candidate

**Six coarse decisions followed by five quiet decisions can reconstruct a
10-bit input despite bounded coarse errors.** This is a new algorithmic
candidate, distinct from the earlier nonredundant 6+4 charge-injection proposal
and from the current physical split-CDAC. The proof assumes exact coarse
weights, a preserved input residue and an exact fine converter. It establishes
neither comparator noise nor an energy improvement.

Unequal comparator precision has primary precedent: Ahmadi and Namgoong
optimize comparison power separately by SAR step and report that two
comparator classes approach their many-comparator simulation optimum.
[University-hosted paper abstract, 2015](https://researchconnect.suny.edu/en/publications/comparator-power-minimization-analysis-for-sar-adc-using-multiple/).
Wang's dissertation explicitly combines coarse/fine comparators, nonbinary
redundancy and comparator-offset calibration; its reported ADC is simulated
in 28 nm, not a measured SKY130 result.
[Primary dissertation abstract, 2018](https://scholar.smu.edu/engineering_electrical_etds/9/).
Okazaki et al. define a strict per-step error tolerance and show why extra
decisions trade against reduced DAC settling time. Their timing parameters
are assumed examples; an extra bit is not automatically a faster converter.
[Primary full paper, §§2–5, 2014](https://www.jstage.jst.go.jp/article/elex/advpub/0/advpub_11.20140218/_pdf/-char/ja).
The following interval proof and numerical results are our derivation, not
numbers taken from those papers.

### Bounded-error proof and the endpoint qualification

Measure `x` in final 10-bit LSBs, with `0 <= x < 1024`. The six coarse trial
weights are `512,256,128,64,32,16`. A comparator accepts trial `t` iff
`x >= t + e`, with independently adversarial `|e| <= eps`; equality accepts
in this mathematical convention. Thus acceptance is possible only when
`x-t >= -eps`, while rejection is possible only when `x-t < eps`.

Before a step of weight `w`, let the retained coarse code be `c` and assume
`x-c in [-eps,2w+eps)`. Acceptance replaces `c` by `c+w`; the acceptance
condition bounds the new residue below by `-eps`, and the old interval bounds
it above by `w+eps`. Rejection leaves `c` unchanged and directly imposes the
same upper bound. Induction therefore gives, after all six decisions,
**`r=x-c in [-eps,16+eps)`**. More precisely, each of the 64 possible final
coarse codes has the reachable input interval
`[max(0,c-eps), min(1024,c+16+eps))`.

At `eps=8`, form `u=r+8 in [0,32)`. Five ideal binary decisions produce
`q=floor(u)` from 0 through 31. The final code is the arithmetic sum
**`clip(c+q-8,0,1023)=floor(x)`**. This needs carry/borrow across coarse bins;
concatenating six coarse bits and five fine bits is incorrect. The signed
fine correction spans −8 through +23. An unsigned implementation can use
the 11-bit sum `s=c+q`, return zero for `s<8`, return 1023 for `s>1031`, and
otherwise return `s-8`. Do not allow a negative correction to wrap around.

The exact inclusive ±8-LSB claim depends on the stated tie convention.
A physical zero-differential comparison can resolve either way: at `x=24`,
rejecting coarse trial 16 with `e=+8` leaves `c=0,r=24`, outside the fine
half-open range. Its largest correction is 23, so it returns 23 instead of
24. A physical design therefore needs reserved range margin, for example
**`eps_coarse + delta_handoff + eta_fine < 8 LSB`**, with each term a bounded
input-referred magnitude. This condition protects range; it does not remove
the fine converter's own quantization, noise or gain/offset error. An
unbounded Gaussian noise distribution needs a declared tail probability;
eight LSB is not an allowed noise standard deviation.

[`imc_redundant_sar.py`](../../../../scripts/compiler/metrics/imc_redundant_sar.py) checks all
**262,144 inputs** (every 10-bit code and all fractions `k/256`) and all
**520,192 allowed coarse paths**, with zero reconstruction error under the
ideal-fine/tie assumptions. Exact interval intersection separately verifies
all 64 coarse paths for continuous real inputs. Required negative controls
retain the one-LSB tie failure and the two-LSB failure when coarse error is
±10 LSB. The old nonredundant four-bit fine range produces up to eight LSB
error under the same ±8-LSB coarse model.

A separate enumeration reserves 7.5 LSB for coarse error, ±0.125 LSB for
handoff and ±0.25 LSB for each fine decision. Across 1,512,192 complete
adversarial paths, the output can still differ by one code. Handoff is checked
at both endpoints; the residual bound covers intermediate perturbations.
This explicitly rejects the claim that overlap corrects fine-comparator noise.
The user's [back-end offset note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Pipelined ADCs/24w Overlap Cannot Correct the SAR Comparator Offset.md>)
makes the same essential distinction. In this particular ideal linear model,
a constant fine-input offset `h` gives `floor(x+h)` if range clipping is
absent: the script verifies `h=0.25 LSB`. Periodic boundary DNL requires an
additional coarse-dependent transfer, clipping or handoff effect; it does
not follow from a global additive fine offset alone.

### What a physical realization must add

The fine converter must cover **32 LSB, twice the earlier fine range**, and
make signed corrections. One ideal direct-charge schedule starts at a
correction trial of +8 LSB, then moves by `±8, ±4, ±2, ±1 LSB` according to
the previous decisions. The last sign selects the last trial or one code
below it. Enumerating all 32 fine outputs verifies 23 absolute unit-charge
movements versus 15 for the nonredundant four-decision schedule; the largest
packet remains eight units. A physical final-DAC update, if required after
the last decision, is additional and is excluded from that count.

For illustration only, a 0.5-V full span makes one LSB 488.28125 µV and the
fine input interval `[-3.90625,+11.71875) mV`. An ideal 768-fF hold gives
`Qunit=C*Vspan/1024=0.375 fC`, with an eight-unit packet of 3 fC. An actual
3.628-pF column would need 1.771484 fC per unit before further loading. These
are charge identities, not joule estimates. The connected capacitance,
reference impedance, fine packet mismatch and positive/negative current
sources need a physical implementation and measurement.

Switching from the cheap comparator to a quiet comparator must preserve the
same sample and calibrated residue gain. Added input capacitance, sampling
time mismatch, offset, switch injection and reference settling consume
handoff/range or final-accuracy budget. The user's
[sampling-path note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/SAR ADCs/23s8 Equalizing Sampling Time Constants Keeps Flash and SAR Samples Consistent.md>)
and [delay-mismatch note](</home/omare/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Pipelined ADCs/24u Sampling Path Delay Mismatch Acts as an Extra Comparator Offset.md>)
identify precisely this coarse/fine sample-consistency requirement. Those
costs cannot be hidden inside ideal error correction or an unpriced gain
switch.

Against ten quiet decisions, a simplified necessary savings condition is
`6*Echeap + Eadded < 5*Equiet`, where `Eadded` includes the change in DAC,
handoff, reset, reference and control energy relative to that baseline.
The analogous latency condition is `6*Tcheap + Tadded < 5*Tquiet`.
Neither quantity has been physically priced here. The next experiment should
first implement and validate the signed fine range and handoff, then measure
the two comparator modes under the same actual loading and noise model.

Reproduce with `python3 scripts/compiler/metrics/imc_redundant_sar.py` (stdlib only).
The cached Nix Python used here completes the full check in **8.43 s** and
prints PASS; generated results
preserve every continuous coarse interval, all fine charge paths and the
deliberate failing controls. No current circuit or SPICE result was changed.
