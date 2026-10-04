# Native accumulator pipeline investigation

2026-09-11. Status: ideal trim, selectable trim and OFF-replica variants pass three small archived validation products at TT and SS85 after corner calibration. Fresh full-range history stress fails the computation-accuracy gate for both OFF-replica pipeline and matched serial. Retention still passes; no full-range pipeline or ADC qualification is claimed. This tests whether the actual charge-domain core can preserve one result while directly computing the next into another native accumulator. It does not copy the computed voltage to a separate analog latch. No ADC or whole-chip throughput improvement is claimed.

## Objective and controlled experiment

The existing 128-row, eight-column core uses Cu = 4 fF, seven fixed signed-magnitude activation planes, 8 ns evaluation, 15.6 ns sharing, 0.42 µm row devices, 6.72 µm share switches and 3.36 µm array/holder reset switches. The captured core produces six deterministic calibration inputs from seed 401 followed by three real stored `ffn_down` activation rows. `dynamic_bits=False` preserves seven planes for every word. Each plane occupies 61 ns; each word occupies 427 ns.

Only column zero gains another native accumulator, share transmission gate and reset transmission gate. The same physical row drivers and all eight array columns remain present. The other seven columns are controls. One bank directly receives every share operation of an entire word; the other bank is isolated. Banks alternate at whole-word boundaries. The serial reference has one bank and the same column-zero clock/interface arrangement, initial reset and final reset.

The CURRENT archived programming file produces native holder capacitances [568, 484, 304, 600, 516, 336, 444, 424] fF. Column-zero Cacc is therefore 568 fF, from 120 fF array load plus 4 fF × sum|w| with sum|w|=112. These are the actual captured values, not the larger holders used in the campaign's dense-weight branch. The archived weights span −5 to +3 across the eight columns; column zero spans −4 to +3 with 87 nonzero weights. Validation input absolute maxima are 127, 32 and 25. This is a particular stored workload sample, not a dense full-range weight stress test. Input files and the unmodified captured netlist are fingerprinted for every run.

The first pair uses three words to check initialization, bank selection, isolation and retention. It cannot establish calibrated product accuracy. Full runs require all nine words. Each physical bank uses three independent calibration words: [0,2,4] or [1,3,5]. The serial reference uses those same parity-specific subsets even though it has one physical holder. Validation uses only words [6,7,8]. Control columns use the same subsets. No validation word sets gain, offset, clock timing or capacitance.

## Timing and charge behavior

Both column-zero banks are physically clamped to VCM during the initial 16 ns, followed by a 200 ps release. Subsequent native word-reset rising edges begin 50 ps before the word boundary and are stretched to 200 ps. The entire edge is routed to the upcoming bank. A naive mask applied at the mathematical word boundary would partly reset the completed bank and would invalidate the pipeline test.

Completed voltages are read at word-end minus 0.1 ns, after the final row return and array reset, but before the upcoming holder-reset edge. The previous bank is sampled again at the next word-end minus 0.1 ns. Its share and reset gates must remain low throughout this hold interval in the actual transient. The last word has no subsequent-word retention sample. Both banks and all controls receive a final 25 ns reset, whose energy is separately recorded.

The leading ideal relation is

\[
h_{k+1}=\frac{C_hh_k+C_av_k}{C_h+C_a},\qquad
h_{word}-V_{CM}=\frac{C_u\Delta V}{C_h2^7}\,\mathrm{MAC}
\]

when effective Ch=Ca, all share operations settle and all parasitic/offset terms vanish. Adding an OFF share switch changes the array's effective capacitance and can change the radix coefficient away from one half. Its terminal capacitance may depend on the voltage held by the inactive bank. Therefore duplicating a capacitor bank is not guaranteed to preserve the original transfer function, even when its gate never turns on during the hold interval. The first controls are explicitly untrimmed.

One-word retention tests leakage, off-switch feedthrough, neighboring-bank reset kick and the next word's array switching. A quiet isolated-capacitor test would omit those mechanisms. Later physical read loading can add further error and energy. No ideal voltage source is allowed to drive either stored-state node in this fixture.

## Cost and verification boundary

The added column-zero bank contains 568 fF and four MOS transistors: one 6.72 µm NMOS/PMOS share pair and one 3.36 µm NMOS/PMOS reset pair, all L=0.15µm. Its summed transistor gate area is 3.024 µm², excluding contacts, wells and routing. At the nominal 2 fF/µm² MIM density, the added capacitor alone corresponds to 284 µm² before layout. That is an incremental estimate, not a complete IMC cell/macro area. Nominal capacitor density is documented in the [SkyWater device details](https://skywater-pdk.readthedocs.io/en/main/rules/device-details.html).

The extra holder is 15.45% of the eight original native holders' summed capacitance. Extending ping-pong operation to all eight columns would double holder capacitance; this single-column probe does not hide that eventual cost. Programmable weight storage, clock-mask logic, clock/reference generation, ADC and routing remain outside the simulated boundary.

All MOS definitions receive explicit one-finger source/drain area, perimeter and sheet squares using the installed Sky130 xschem 0.29 µm extension. This includes the added switches and the original core. It is schematic geometry, not PEX. Initial conditions come from a physical reset-state DC operating point; energy required to establish that pre-simulation state is not measured. Ideal capacitors have no intrinsic dielectric leakage or noise in deterministic transient analysis.

Every external voltage source contributes measured net and positive delivery. Sources are grouped into rails, references, original core clocks and bank clocks. Per-word and final-reset energies are reported separately. Positive delivery is summed per source before integration, so recovered energy from one ideal port cannot cancel consumption from another. Physical clock/reference generators still need implementation and can consume more energy.

The legacy deterministic column-zero accuracy criterion is RMS < 0.25 MAC and maximum < 1 MAC on the three actual validation words. A separate frozen retention gate requires maximum one-word drift < 0.25 MAC. The retained validation values for words 6 and 7 must meet the same RMS/max accuracy limits using the unchanged capture-time calibration; no hold-phase refit is permitted. Word 8 has no following compute interval in this fixture and is explicitly untested for retention. Calibration input spans and gain signs are checked and recorded. Completion, inactive-bank gate isolation and closing reset are separate checks. Passing these does not establish sampled noise, random mismatch, real receiver performance or a pipeline initiation interval with an ADC.

## Reproducibility

Generator: tb_imc_native_pipeline.py. It uses `connected_sar.capture` to obtain the real core, the same waveform-closing helper, and the shared physical-diffusion annotation. Exactly flat PWL vertices are removed only after checking voltage-waveform equivalence. Original and modified decks, imported source snapshots, frozen input hashes, solver settings and output hashes are retained under `build/campaign/native_pipeline/`. Choose new names for reruns.

```sh
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_native_pipeline.py --name tt_serial_3_untrimmed --banks 1 --max-words 3
/nix/store/lmam35qlyl43gaw4x19128gqhymcgkgr-python3-3.13.13-env/bin/python3 analog/testbenches/tb_imc_native_pipeline.py --name tt_pingpong_3_untrimmed --banks 2 --max-words 3
```

The initial numerical settings preserve the core's Gear integration, reltol 1e−5, abstol 1e−14 A and vntol 1e−8 V, with an explicit maximum timestep 0.1 ns. No accuracy claim is based on an incomplete transient. Source capture is read-only and does not modify the shared core generator.

## First physical controls: completed, untrimmed

Both fresh three-word TT 27 °C simulations completed the entire 1306 ns trajectory, with inactive clocks low and the paid closing reset successful. The first three inputs are calibration inputs only. These runs establish a working physical bank schedule, not calibrated MAC accuracy.

| Calibration word | Serial capture (V) | Ping-pong capture (V) | Capture change (µV) | Drift while next word computes (µV) |
|---|---:|---:|---:|---:|
| 0 | 0.952275877 | 0.951652660 | −623.217 | −0.152417 |
| 1 | 0.868319458 | 0.868524279 | +204.821 | +0.091836 |
| 2 | 0.889883123 | 0.889973598 | +90.476 | Not exercised |

The unchanged seven control columns differ by at most 0.168 µV between these runs. This does not provide a formal numerical uncertainty bound; a tighter-timestep comparison remains necessary for small residual claims. The added switch changes the computed value much more than the subsequent one-word retention drift.

| Positive ideal-port delivery | Serial | Ping-pong |
|---|---:|---:|
| Word 0, all eight columns | 8.59452 pJ | 8.60482 pJ |
| Word 1, all eight columns | 9.23396 pJ | 9.25983 pJ |
| Word 2, all eight columns | 8.77958 pJ | 8.77969 pJ |
| Closing 25 ns reset | 0.07679 pJ | 0.09896 pJ |

The small total energy increment does not establish clock-driver cost or benefit from ADC overlap. The final reset errors are below 0.0017 µV in both deterministic simulations. The DC-initialized starting state is not a measured startup-energy event.

A diagnostic fit uses completed plane values, including subsequent row return and array reset:

\[
h_k=r h_{k-1}+b S_k+o.
\]

Only calibration words are used; each word's first plane is excluded because it follows holder reset. The serial fit gives r = 0.50002495, while the ping-pong banks give 0.49671788 and 0.49673128. Fit residuals are respectively 0.389, 0.192 and 0.160 µV RMS. Under a constant effective-capacitance model, changing holder capacitance by ΔC = Ch(1/r − 2) would restore r = 1/2. Substituting nominal Ch = 568 fF proposes +7.506 and +7.475 fF. This is a sizing hypothesis, not a verified correction: voltage-dependent parasitics and history can invalidate a constant ratio. A fit taken only across the sharing interval is deliberately avoided because it omits later charge injection and state movement.

Artifacts are `tt_serial_3_untrimmed/`, `tt_pingpong_3_untrimmed/` and their `complete_cycle_fit.json` files under the build directory above. Every run retains its own original generator snapshot. The complete-cycle postprocessor fingerprints itself and the exact trace. Full nine-word runs preserve zero trim and the frozen accuracy criteria.


## System boundary and conditional noise screen

The captured serial deck contains 2716 fF of weight capacitors, 960 fF of array load, and 3676 fF of native holders: 7352 fF total explicit capacitance. Providing a second native holder to every column would add 3676 fF, increasing that sum by 50%. This is a capacitor inventory, not a layout-area ratio: device area, capacitor overlap, programmable storage and routing remain separate.

Two banks can overlap computation and conversion only if the prior word's ADC service completes before its bank is reused. For a fixed column group, the ideal period is at least max(Tcompute, Tservice), with Tcompute = 427 ns in this fixture. For illustration, fourteen 20 ns decisions require 280 ns per column. A fixed ADC group can then serve only one complete column per compute interval, before mux/setup costs. Eight such fixed groups would require eight converters. An aggregate arithmetic bound gives six converters, but reaching that bound would require additional scheduling and interconnect capable of migrating unfinished conversions; it is not established by adding two holders. These examples are schedules, not measured converter configurations. The machine-readable inventory and examples are in `schedule_and_area_screen.json`.

At 27 °C, sqrt(kT/568 fF) = 85.42 µV. Dividing by the calibration-cycle gain estimate of 24.258 µV/MAC gives 3.52 MAC. Thus the deterministic 0.25 MAC accuracy gate cannot be presented as sampled-noise accuracy. As one conditional ensemble screen, independent uniformly distributed integer inputs from −127 to 127 and this column's sum(w²) = 174 give an ideal signal RMS of 23.55 mV, or 48.81 dB relative to that capacitor-noise value alone. That uniform-input result is not representative of the three actual validation outputs: their exact column-zero MACs are 33, 66 and 21, giving only 1.0745 mV RMS signal and approximately 21.99 dB against the same capacitor-noise estimate. Neither calculation is an inference-quality result. Both exclude all converter, reference, row-drive, leakage and mismatch terms. The actual switching covariance and sampled-noise budget require a physical noise study.


The corresponding ideal thermal model can be derived without treating all sharing events as independent output noise. For constant grounded effective array capacitance Ca and holder capacitance Ch, let r = Ch/(Ca+Ch). A fresh array reset contributes variance kT/Ca. The conserved common voltage has variance r² Var(hold)+(1−r)² kT/Ca. A fully settled share resistor contributes differential-mode variance kT(Ca+Ch)/(Ca Ch), of which the holder receives the squared factor [Ca/(Ca+Ch)]². Therefore

\[
\operatorname{Var}(h_{new})=r^2\operatorname{Var}(h_{old})+
(1-r)^2\frac{kT}{C_a}+\frac{kT C_a}{C_h(C_a+C_h)}
=r^2\operatorname{Var}(h_{old})+(1-r^2)\frac{kT}{C_h}.
\]

Its stationary marginal is kT/Ch, including unequal capacitors. If the holder begins with reset variance kT/Ch, every subsequent fully thermalized cycle preserves that marginal. For equal capacitors, the fresh reset and sharing terms are kT/(4C) and kT/(2C). An independent critic confirmed this derivation under the stated assumptions. Four exact rational matched/unequal-capacitance identities are recorded in `reset_share_noise_identity.json`. A sharing-only model that omits the fresh reset term gives a different, optimistic result and must remain separately labeled. This identity does not establish that the actual finite-duration Sky130 core reaches every assumed equilibrium.


## Full nine-word result: untrimmed architecture fails accuracy

Both fresh TT 27 °C runs completed the full 3868 ns trajectory, including the 25 ns closing reset. The six calibration inputs are disjoint from the three actual validation words. Input spans are nonzero and all fitted gains have the expected sign.

| Metric | Matched serial reference | Untrimmed ping-pong |
|---|---:|---:|
| Validation column-zero RMS error | 0.009815 MAC | 1.525007 MAC |
| Validation column-zero maximum error | 0.010966 MAC | 1.897052 MAC |
| Frozen capture accuracy gate | PASS | **FAILED** |
| Seven control columns, RMS / max | 0.044220 / 0.095696 MAC | 0.043455 / 0.096460 MAC |
| Maximum one-word drift | Not applicable | 0.006355 MAC |
| Frozen drift gate, < 0.25 MAC | Not applicable | PASS |
| Retained validation words 6/7, RMS / max | Not exercised | 1.604633 / 1.897072 MAC, **FAILED** |
| Mean validation-word positive ideal-port delivery, whole eight-column core | 5.059884 pJ | 5.060392 pJ |
| Closing reset positive delivery | 0.075404 pJ | 0.083892 pJ |

The per-word energy includes the selected bank's reset and physical input/reference/clock port delivery. The closing reset is separate. Mean validation energy corresponds to 4.94129 and 4.94179 fJ per 128×8 arithmetic term for this sparse, hard-programmed sample, before programmable memory, clock/reference generators or conversion. These values are not a useful complete-system energy comparison because the untrimmed pipeline fails accuracy and the actual ADC is absent. Boundary energy of the third word differs between the three-word and nine-word fixtures because only the latter proceeds into another computation at that boundary.

The ratio explanation survived a prospective test. Before validation began, the first three calibration-word traces predicted ping-pong errors [−1.241718, −1.858125, −1.347043] MAC using a constant-r recurrence and the frozen parity calibration. Actual errors were [−1.245338, −1.897052, −1.351764] MAC. Maximum prediction disagreement is 0.03893 MAC. Six-calibration-word fits then gave r = 0.49671621 and 0.49671107, consistent with the earlier estimates. These results support capacitor imbalance as the dominant deterministic error mechanism; they do not eliminate smaller history-dependent terms.

A +7.5 fF addition to each holder was frozen at 02:02 UTC from the rounded first-three-word calibration proposals, before the full validation results were available. The subsequent full transient keeps the same gain/offset calibration subsets and the same accuracy/drift gates. The exact timestamp, configuration and source fit hash are in `frozen_trim_candidate.json`. The extra capacitor is ideal in this trial; no claim is made for a physical trimming network or achievable mismatch.

A negative numerical result is preserved: the otherwise unchanged 50 ps maximum-timestep three-word control aborted at 502.042 ns with a 6.25e−23 s attempted timestep and `vpipe_reset1b#branch` reported as the trouble branch. ngspice returned zero, but the completion assertion rejected the trace. It is not convergence evidence. One unchanged-circuit 25 ps control is in progress. Consequently the sub-microvolt drift is not yet qualified against timestep sensitivity.

Full-run artifact directories are `tt_serial_9_untrimmed/` and `tt_pingpong_9_untrimmed/`. Their manifests and results contain exact source snapshots, deck hashes, input hashes, simulator hash, output hashes and solver settings. The 50 ps failure directory retains its incomplete trace, log and explicit failure record.


## Resume audit, 2026-09-11

The 25 ps untrimmed control also failed numerical completion: ngspice stopped at 558.925 ns on `vpipe_reset1b#branch`, attempting 3.125e-23 s. Its failure record and original trace are preserved. Neither tighter control establishes timestep convergence. Earlier +7.5 fF and separate row-clock-energy jobs stopped before completion and remain incomplete evidence. A fresh full-nine-word +7.5 fF run retains the frozen calibration, validation, geometry and accuracy gates; it does not reuse an interrupted trajectory. The physical reset/share noise study has native-versus-hybrid and zero-noise controls, but no statistically qualified result yet.


## Frozen +7.5 fF correction: held-out deterministic PASS

The fresh full-nine-word `tt_pingpong_9_trim7p5_resume` run completed 3868 ns. Both holders use 575.5 fF, retaining the trim frozen before earlier validation. Column-zero held-out RMS/max error fell from 1.525007/1.897052 MAC untrimmed to **0.061411/0.086652 MAC**, passing the unchanged 0.25 RMS / 1 maximum gates. The serial reference remains more accurate at 0.009815/0.010966 MAC. Retained words 6/7 pass using the same capture-time calibration: 0.067588/0.086630 MAC RMS/max. Maximum one-word drift is 0.006295 MAC. Word 8 retention is still untested.

Mean positive ideal-port energy of validation words, for the entire eight-column core, is 5.060885 pJ: rail 1.050935, references 1.913399, row clocks 0.653013, core clocks 1.320471 and bank clocks 0.123067 pJ. Closing reset adds 0.083903 pJ. The matched serial reference was 5.059884 pJ, but this tiny 0.001001 pJ difference is not yet numerically qualified and excludes physical clock-generation and ADC costs. The added holder increases capacitance and thus implemented area even when ideal-port dynamic-energy change is small.

Calibration-only complete-cycle fits give r = 0.499897766 and 0.499892836, with 0.176/0.226µV RMS residual. The remaining ratio error predicts another 0.235/0.247 fF correction under the constant-capacitance approximation. These are hypotheses; the successful +7.5 fF result is retained as the frozen candidate. No validation data selected it. The postprocessor now uses actual trimmed holder capacitance when computing an additional trim proposal.

This verifies a deterministic native-state retention mechanism in the specified sparse archived array. It is not sampled-noise accuracy, physical trim-network qualification, PVT robustness, full ADC overlap, or a complete throughput/area improvement. The existing 100 ps transient completed; tighter controls have numerical failures, so paired 100 ps/50 ps controls at an explicit 1 pA current tolerance are underway. The frozen +7.5 fF candidate is also being tested at SS85 with unchanged capacitor values; per-corner gain/offset calibration is still allowed by the existing protocol and will be labeled separately from frozen-TT calibration.


The paired 100 ps / 50 ps controls at 1 pA current tolerance both completed all three calibration words. Column-zero capture differences (50 ps minus 100 ps) are [−0.00216,+0.02271,−0.06229] µV; the maximum across all eight columns is 0.19151 µV. The two retention-drift changes are +0.00623/+0.00650 µV. Changing only current tolerance at 100 ps from 10 fA to 1 pA changes column-zero captures by at most 0.08844 µV. Thus the earlier timestep aborts are numerical failures, while completed independent solver settings support the small retention drift in this limited three-word fixture. Full-nine-word trimmed and corner-specific numerical qualification remains separate. Exact comparisons are retained in `resume_timestep_control.json`.

A physically selected trim experiment retains the 7.5 fF value but adds three minimum-width MOS per bank: an NMOS grounds the capacitor bottom when enabled; a transmission gate bypasses bottom to holder when disabled. Both use 0.42/0.15 µm geometry. Off-switch parasitics, finite on-resistance and bottom-node motion are now included. The two static complementary configuration voltages are metered; one configuration storage bit per bank is explicitly absent. This is one selectable capacitor, not a demonstrated fine-resolution trim DAC. Full-nine-word enabled and three-word disabled controls are underway, with unchanged accuracy gates. The NMOS grounding switch operates near ground in deep triode; its sizing must use actual on-conductance and terminal capacitance, not a saturation-only gm/ID number.


Actual TT27 switch-port characterization supports the minimum-width trim choice. At 0 V drain bias, the selected grounding NMOS has port conductance 533.82µS (Ron 1.873kΩ); its 7.5 fF RC is 14.05 ps. At 10 mV VDS, ID=5.2896µA and gm=2.91189µS, so gm/ID=.5505 V⁻¹ and VDSAT=.40556V: this is deliberately deep triode. Applying a saturation gm/ID target here would mischaracterize the switching function. The bypass TG at 0.9 V common mode has Ron 30.831kΩ, giving 231.24 ps with 7.5 fF. The disabled ground NMOS at 0.9 V contributes 0.31339 fF terminal capacitance. These are terminal measurements with explicit junctions; the complete selected capacitor includes further bypass-device parasitics. The deck, operating-point audit and AC results are retained in `trim_switch_dc_ac/`.


## SS85: fixed capacitor trim passes after corner calibration

The frozen 575.5 fF holder values completed the full SS85 nine-word test. With the existing independent per-corner gain/offset calibration, column-zero capture RMS/max is **0.169702/0.206319 MAC**, retained validation RMS/max **0.187852/0.243459 MAC**, and maximum drift **0.050080 MAC**. All frozen gates pass. Mean validation-word ideal-port delivery is 5.190229 pJ for the eight-column core. Geometry, timing and trim values were unchanged.

Using the TT gain/offset coefficients instead gives errors [5.721060,5.606887,5.753330] MAC, RMS 5.694106 and maximum 5.753330: **FAILED**. Thus this is not calibration-free PVT robustness. Constant capacitor trim plus refreshed affine calibration survives the tested TT/SS85 endpoints. No process Monte Carlo, temperature continuum, supply sweep, physical trim network at SS85 or full-converter noise qualification is implied. Frozen-TT audit coefficients and results are in `ss85_frozen_tt_calibration.json`.

A conditional ratio-error sensitivity screen perturbs both holder capacitors while refitting gain/offset on calibration words only. The calibrated constant-r model predicts RMS errors 0.2498 MAC for −1 fF, 0.4509 for −2 fF, and 0.3541 for +2 fF, around the current frozen ideal trim. These are not Monte Carlo results and assign no physical mismatch distribution. They show why approximately 1 fF ratio accuracy can matter even when the unperturbed deterministic test passes. The model omits history-dependent transistor capacitance; actual perturbation sweeps remain necessary.


## Selectable capacitor: TT deterministic PASS with physical switches

The frozen 7.5 fF selected trim completed all nine TT words. Column-zero RMS/max error is **0.047654/0.048471 MAC**; retained validation RMS/max **0.047009/0.048002 MAC**; maximum drift **0.009785 MAC**. All unchanged gates pass. The slightly smaller error than direct ideal trim was not tuned on validation; the added device capacitance shifts the effective ratio. The trim-bottom nodes span only −1.193 to +1.327 mV, so the selected NMOS stays close to its characterized ground operating point.

Mean validation-word ideal-port energy is 5.059658 pJ, closing reset 0.083872 pJ. Its tiny difference from the serial/ideal trim figures is below the established system-comparison boundary and is not an energy improvement claim. Relative to the original single-holder column, this one-column pipeline now adds 583 fF explicit capacitance and ten MOS: four for the second share/reset bank, six for the two selected trims. Two configuration storage bits and physical control-generation are still excluded. The 7.5 fF values remain ideal capacitors rather than extracted MIM cells.

The disabled control completes three calibration words, with r = 0.49764449/.49765542 and drift −1.01143/−0.46070µV. Disabling therefore does not reproduce a zero-capacitance state: the conducting bypass devices and disabled grounding device remain physical loads. This control does not establish disabled-state full-word compute accuracy. SS85 selected-trim testing remains underway.

The full-nine-word direct-ideal trim numerical control at 50 ps/1 pA also passes: capture RMS/max 0.061780/0.085764 MAC and retained 0.067211/0.085482 MAC. This agrees with the original 100 ps/10 fA result at the accuracy-gate scale, though timestep and current tolerance both differ; separate three-word controls isolate those settings. No failed narrower-timestep trace was accepted.


## Always-OFF replica TG: TT deterministic PASS without added trim capacitor

Each holder now receives one always-OFF replica of the 6.72 µm share transmission gate, connected to VCM at its other channel terminal. Its gate/body voltages are static 0/1.8 V as appropriate. This mirrors the otherwise unmatched inactive-bank loading on the array. The geometry was frozen from the actual share switch, with zero ideal MIM trim and no validation-based width fit. Unlike the actual inactive bank, the replica peer is fixed at VCM; voltage-history mismatch remains a possible failure mechanism.

The full-nine-word TT test passes: column-zero capture RMS/max **0.011084/0.013537 MAC**, retained validation **0.012304/0.013767 MAC**, and maximum drift **0.009792 MAC**. The original serial reference was 0.009815/0.010966 MAC. The added replica brings nominal deterministic accuracy close to serial while retaining the other word physically. It does not reduce the previously documented sampled-noise floor.

Relative to original serial, the one-column probe adds 568 fF native holder capacitance and eight MOS: four share/reset-bank devices plus four replica devices. No trim configuration bits or extra trim MIM are used. Device area, wells, junction capacitance, leakage and fixed VCM-reference loading remain physical costs. This is generic dummy-parasitic compensation applied to this native pipeline; no novelty claim is made. The same frozen geometry is under SS85 test, and independent critique is requested before broader claims.


A separate completed-trace audit measured maximum holder excursion anywhere during the following physical computation, not only at its end. Maxima are 0.4255µV (0.01777MAC) for direct ideal trim TT, 0.5011µV (0.02094MAC) for selected trim TT, 0.5002µV (0.02090MAC) for the OFF-replica TT, and 1.4349µV (0.06015MAC) for selected trim SS85. These results cover the existing calibration/small-validation trajectories; they do not imply that an actual connected ADC is unaffected. Each run now has `hold_excursion_audit.json` with worst time and word.

Fresh history stress preserves the original six calibration vectors and all device geometry. Four physical validation words use [+14224MAC,−14224MAC,33MAC,+14224MAC] for column zero: sign-aligned maximum, sign-opposed maximum, the original small input, then an actual repetition of the first stress input. All row/reset/share control waveforms are extended for the fourth word; no voltage is copied onto a state node. The final repetition exercises retention of the small output. Matched serial and OFF-replica runs are in progress. Reverse-polarity and frozen seed 88321 random histories are distinct planned controls. They will use the same calibration and accuracy gates rather than tuning to the new validation data.


## Fresh full-range stress: both replica and serial FAIL the frozen accuracy gate

Both ten-word circuits completed 4295 ns, all physical control checks and closing reset. The exact four validation products were [+14224,−14224,33,+14224] MAC. The original six calibration words were unchanged, and 26,880 actual row-control samples were independently checked against all 70 signed activation planes.

| Architecture | Four validation errors (MAC) | RMS / maximum (MAC) |
|---|---|---:|
|Serial|−1.846694,−9.756069,+0.010942,−1.333486|5.009228 /9.756069, FAILED|
|OFF-replica pipeline|−1.937465,−7.974141,+0.016301,−1.356828|4.158784 /7.974141, FAILED|

The replica's maximum one-word drift remains 0.062518 MAC, passing the drift gate, and the small output following an extreme remains accurate. Its retained-output accuracy gate nevertheless fails because the large computed products were already inaccurate. This separates retention from computation accuracy. Maximum error corresponds to 0.06859% (serial) or 0.05606% (replica) of the one-sided 14224 MAC range; these percentages do not replace the frozen absolute-MAC gate or establish an ENOB/INL specification. The failure is largely a pre-existing full-range core/affine-transfer limitation, rather than a new failure caused solely by the pipeline. Reverse-polarity and independently frozen random histories remain in progress.

A calibration-only constant-r recurrence predicts replica errors [+0.186,−0.572,+0.011,+0.580] MAC, much smaller than the observed extreme errors. Thus small residual fixed-ratio error alone does not explain the full-range failure.

One candidate analytical repair was independently characterized and rejected. If array and holder have identical nonlinear charge functions Q(V) and sharing conserves just those charges, then 2Q(Vnew)=Q(Vold)+Qreset+CuΣwΔV. This suggests integrating actual holder terminal C(V) and performing affine calibration in charge instead of voltage. A separate static off-state Sky130 fixture measured C(V) from 0.45 to 1.35 V at 5 mV spacing, with an asserted 568 fF ideal-capacitor oracle. No nonlinear coefficient was fitted to any compute-validation output.

Applying this static holding-state charge coordinate worsened maximum full-range error: serial 9.756→11.742 MAC, replica 7.974→11.180 MAC. **FAILED** as a repair. The off-state terminal charge is evidently insufficient to represent the complete clocked recurrence; clock injection, channel charge during sharing, and intermediate state movement cannot be omitted. The C(V) data remain useful device-loading evidence. Generator: `tb_imc_holder_charge_coordinate.py`; characterization artifact `holder_cv_tt27_step5mV/`; each stress run retains `static_charge_coordinate.json`.


The same frozen OFF-replica geometry also completed SS85: capture RMS/max 0.117203/0.201591 MAC, retained 0.112182/0.127854 MAC and maximum drift 0.083190 MAC. It passes the original small-validation gates after corner affine calibration, but does not dominate the selected-capacitor variant's SS85 error/drift. Wider OFF replica devices create additional leakage. Selected trim at SS85 completed with capture 0.096591/0.104586, retained 0.108315/0.149585, and maximum drift 0.055571 MAC. Neither result repairs the subsequent full-range stress failure.


Reverse-polarity history confirms the full-range failure: replica RMS/max 5.448599/7.959865 MAC, matched serial 6.739491/9.771109 MAC. The small 33 MAC product remains accurate after the opposite extreme. A fresh seed 88321 random history passes the replica gates: capture RMS/max 0.051645/0.081380 MAC, retained 0.033634/0.045002 MAC. This one random sequence does not establish a statistical yield or full-input-domain guarantee. All cases retained the original six calibration vectors and device geometry; failed full-range cases remain part of the result.

### Full-range phase diagnosis and frozen dummy control (2026-09-11)

The complete serial and replica positive/negative stress traces now have
`phase_diagnosis.json`, generated by
`build/campaign/native_pipeline/phase_diagnosis.py`. All stage-local affine fits
use only the original six calibration words, omitting each first reset plane.
Per-plane sample offsets are 25.7 ns (before sharing), 39.5 and 41.5 ns (late
sharing), 42 ns (after release), 44 ns (after row return), 45 ns (after array
reset), and 60.9 ns (completed plane). The final 2 ns of sharing moves the holder
by at most 0.0207 µV; the holder and array differ by at most 0.00321 µV at 41.5 ns.
These observations strongly reject incomplete late settling as the dominant
~200 µV full-range error at this timing. They do not validate shorter timing.

For serial positive and negative fullscale words, the stage residuals weighted
by the nominal remaining binary recurrence are respectively +317.8/−1154.9 µV
at settled sharing and −353.9/+890.1 µV at release. The combined sharing-plus-
release affine-map residual is −37.8/−271.3 µV. Array pre-share residuals are
−17.1/+98.2 µV and enter the ideal sharing map with about half weight. Subsequent
row return, reset and recovery residuals are each below 0.04 µV in this serial
sequence. Replica combined-sharing residuals are −28.7/−220.0 µV for its first
positive/negative pair. These are diagnostic local residuals, not an exact
additive proof of final calibrated MAC error: independent local regressions,
parity fits, nonlinear propagation and first-plane extrapolation matter.

The useful finding is that switch-on/ON-state charge and switch-release effects
are individually much larger than their net error and oppose one another.
A release-only correction could therefore worsen the result. A frozen physical
control adds complementary-clock N/P dummies with source and drain tied to each
charge node, W=3.36 µm and L=.15 µm (half the real share width), symmetrically to
array column zero and every native holder. Their turn-off coincides with real
share turn-on and vice versa. This is a conventional charge-injection hypothesis,
not a novelty claim or an optimized size. Serial pays four additional MOS;
two-bank replica pays six, with real terminal geometry and measured ideal-source
clock energy. The unchanged original calibration and fullrange stress protocol
will decide whether this hypothesis survives. Results are pending; no accuracy
claim is made for the added dummy devices.

A separate native switch bias audit (`share_bias_audit/result.json`) measures the
frozen 6.72/6.72 µm share TG at 10 mV channel drop and common voltages 0.55, 0.90,
and 1.25 V. N-device gds is 5.280, 0.8204, and 0.000153 mS; P-device gds is
0.000179, 0.07069, and 0.9484 mS. The corresponding gm/ID coordinates are N:
2.008, 10.673, 32.145 V⁻¹ and P: 16.577, 13.129, 2.802 V⁻¹. These are actual
bias trajectory characterizations, not saturation sizing targets: channel drop
is 10 mV and both contributions exchange dominance over signal range. Equal
geometric widths do not imply equal conductance or charge. Raw simulator terminal
charges are retained but their polarity/sign conventions must be respected before
using them for cancellation. Any subsequent unequal N/P width experiment must
also recheck holder/array loading symmetry and device-model bins.

Independent reviewer `stack_resume` inspected the dummy topology before results:
tied source/drain and complementary clocks are consistent; inactive-bank dummies
remain static. The half-width hypothesis is strongest at release, when the main
TG endpoints have equalized. It is not exact at turn-on with unequal endpoints,
voltage-dependent capacitances and finite gate edges. The dummies also add ON-state
channel capacitance during hold. This limitation must survive in interpretation
of both successful and failed results. A zero-dummy regeneration was byte-identical
to the archived serial stress deck, isolating the source change.

**FAILED: frozen half-width dummy control.** Both complete 10-word simulations
pass clock isolation and closing reset but fail unchanged MAC accuracy gates.
Serial RMS/max error is 14.427589/28.364180 MAC, versus 5.009228/9.756069 without
dummies. Replica RMS/max is 13.359882/26.274634, versus 4.158784/7.974141. Replica
retention drift remains below 0.101928 MAC and peak excursion below 0.127216 MAC;
the failure is computation. Mean positive ideal-source energy over the four
stress words rises from 9.341967 to 9.431320 pJ serial and from 9.381658 to
9.469794 pJ replica. These stress energies are not the ~5 pJ original small-input
workload energy and must not be substituted for one another.

Preserved result paths are `tt_serial_dummy3p36_stress_positive` and
`tt_replica6p72_dummy3p36_stress_positive`. Stage diagnosis explains why a useful
local cancellation failed globally: negative-fullscale serial combined-share
residual improves modestly from −271 to −225 µV, but the array pre-share residual
changes from +98 to −918 µV. Dummy ON-channel capacitance loads the input charge
state nonlinearly. The individual turn-on/release residuals become much smaller,
yet the complete circuit becomes less linear. Final sharing motion remains below
0.0185 µV. This is a concrete counterexample to using improved local clock-charge
cancellation as evidence of improved product accuracy.

A second frozen control uses Wn=4.48 µm/Wp=8.96 µm at unchanged total share width
13.44 µm, no dummy. Only column zero changes; the other seven controls retain the
original share devices. Replica N/P geometry follows the new real share geometry.
A width-linear extrapolation of the independently measured bias sweep predicts
worst-case Ron improving only from 2.490 to 2.348 kΩ, so this is primarily a
charge-curvature hypothesis, not a claimed large delay gain. Device bins and
terminal geometry are reevaluated by the actual native simulation. No width fit
uses the stress results. Matched serial and replica fullrange runs are pending.

**FAILED strict gates; partial sizing tradeoff:** the fixed-total-width
4.48N/8.96P controls completed. Serial RMS/max becomes 3.880711/6.738254 MAC
(original 5.009228/9.756069), with fresh errors
[−2.658011, −6.738254, +0.011971, −2.787552]. The maximum improves but positive
fullscale worsens; mean positive ideal-port stress energy changes
9.341967→9.347717 pJ. Replica RMS/max becomes 5.087650/7.423759 MAC
(original 4.158784/7.974141), errors
[−4.704823, −7.423759, +0.021931, −5.127251]. Thus its RMS gets worse despite a
slightly improved maximum. Replica retained RMS/max is 5.062849/7.360663 MAC;
end drift max 0.063096 and peak excursion max 0.093797 MAC still pass. Its mean
stress energy changes 9.381658→9.389834 pJ. No PVT validation is warranted for a
candidate failing the nominal gate.

These results reside at `tt_serial_ratio4p48_8p96_stress_positive` and
`tt_replica_ratio4p48_8p96_stress_positive`. Calibration-only complete-cycle
radix fits are 0.500003894 serial and 0.500003338/0.500009324 replica, closer to
one-half than the previous equal-width control, yet fullrange error persists.
Late sharing movement stays below 0.0229 µV and holder–array difference below
0.00553 µV. The nonlinear combined-share residual decreases for negative
fullscale, but array pre-share curvature and bank-dependent history remain.
Neither more exact small-signal radix nor lower estimated worst-case Ron is
sufficient for fullrange accuracy. This round therefore retains the native-hold
mechanism and bias-characterization data, and rejects both tested modifications
as complete accuracy solutions. Neither is claimed novel.
