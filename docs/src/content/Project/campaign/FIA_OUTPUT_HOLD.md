# Direct FIA output isolation fixture

**Initial isolation coordinate FAILED the frozen pre-isolation calibration gate.** Signal retention exists, but physical switching and latch activity alter the transfer. No receiver-noise or complete fine-SAR qualification is claimed.

Source: `analog/testbenches/tb_imc_fia_output_hold.py`. Completed native TT27 fixtures are `build/campaign/fia_output_hold/tt_w3p36_r1` and its `tt_w3p36_alwayson_r1` control. Decks, source snapshots, port currents and result JSON are preserved.

Each native input holder is1 pF, matching the representative0.48–1.78 pF system range. The known short-L FIA uses Wn22/Wp44 µm, L0.18 µm, a2 pF reservoir and250 fF per output. Real TGs (Wn=Wp3.36 µm, L0.15 µm) separate amplifier drains from those existing250 fF storage capacitors; the capacitors are not duplicated. Internal drains reset to VCM at110 ns while the storage nodes remain isolated until200 ns. The existing physical latch remains attached to storage and executes one actual decision at70 ns, returning to reset at92 ns. No DAC or guessed fine reference is added.

Isolation is active from68.2 to200 ns, a132 ns observation window. The full frame is240 ns. Acquisition switches are13.44 µm; internal output reset switches3.36 µm. All ideal source-port charge and positive delivered energy are counted. Explicit capacitance totals4.520 pF: two1 pF input holders,2 pF reservoir, two250 fF storage nodes and two10 fF latch loads. Native MOS diffusion is explicit; ideal mutual capacitors are used to match the parent baseline. This is not full-network PEX or a device-area estimate.

The first−500/+500 µV samples alone establish the frozen pre-isolation gain at67.8 ns. Subsequent inputs are−20/+20/−100/+100 µV,−5/+5/−10/+10 mV and+20 µV after large-signal history. The original `acquired_native_uV` field was measured at29 ns, before acquisition release at30 ns; it is a driven-voltage reference. A separate actual post-release31 ns measurement is now explicitly available. Original failed results were not overwritten.

## Initial results

The isolated fixture has pre-isolation gain18.09670. Across the heldout cases and observation times69–199 ns, frozen-calibration error reaches98.678 µV native, RMS43.415 µV. The frozen gates are max20 µV/RMS10 µV, correct resolved signs, and storage reset<100 µV. All decisions and reset pass, but the error gate fails. Maximum storage reset residual is13.258 µV. Positive source energy is2.2034–2.2320 pJ/frame.

At±10 mV native input, the physical isolation step changes the stored result by approximately±119.8 µV native at69 ns, relative to the67.8 ns sample. The matched always-on-TG control changes by only±19.2 µV over that interval. Isolation therefore adds a substantial signal-dependent effect beyond continued integration. Later latch activity changes the stored output again; at199 ns the drift is−106.8/+100.8 µV. The+20 µV sample after large history shows approximately6.2 µV native drift. These effects cannot be dismissed as a constant offset.

The always-on-TG control has pre-isolation gain18.09785, essentially equal to the switched fixture before the isolation edge. It correctly loses its stored signal when the FIA drains reset, so it fails the retention gate by construction. This control establishes initial loading, not retention success.

Measured charge-weighted gm/ID over40–67.8 ns in the+20 µV case is21.373 V⁻¹ for NMOS and15.019 V⁻¹ for PMOS. The current-reuse effective ratio, `(∫gmN+∫gmP)/(0.5·∫(|IN|+|IP|))`, is36.402 V⁻¹; combined gm-time is15.594 pF per branch. High gm/ID alone does not establish noise efficiency or sampling accuracy.

## Separate post-isolation calibration diagnostic

`tt_w3p36_r1/independent_postcal_audit.json` uses actual31 ns post-release input measurements and only the first two calibration samples. Calibration at119 ns, after the one physical latch has returned to reset, gives gain18.06118. At that same read phase, the heldout errors are approximately−0.580/−0.822/−1.079/−0.685/−9.911/+4.310/+5.724/−12.338/+5.861 µV. Extending observation to199 ns keeps the largest error around13.4 µV. Calibration at69 ns instead leaves approximately21.1 µV error at10 mV.

This supports a potentially calibratable phase-dependent gain, while preserving the original pre-isolation failure. The read phase was explored after seeing failures; this is a diagnostic, not independent architecture qualification. Repeated fine-SAR comparisons, DAC charge injection, common-mode changes, reset covariance and thermal noise may alter this result. One physical latch clock is not a complete SAR conversion.

An additional smaller-TG coordinate (Wn=Wp0.84 µm) tests reduced switching charge against greater resistance and settling loss. Results remain separate from the frozen3.36 µm failure.

## Smaller switch control

`tt_w0p84_r1` reduces each isolation MOS width fourfold to0.84 µm. Pre-isolation gain falls to16.85075. Frozen held error max111.595 µV/RMS26.334 µV still fails. Energy decreases only to2.1837–2.2121 pJ/frame, approximately20 fJ less. Large-range errors already exist before opening: the−10/+10 mV inputs have+53.677/−53.110 µV error under the frozen pre-isolation calibration.

Separate119 ns post-isolation calibration using the first two actual31 ns input samples leaves+40.058/−45.306 µV errors at−10/+10 mV, compared with+5.724/−12.338 µV for3.36 µm switches. Thus smaller switches reduce switching charge but their ON-state resistance/loading degrades the useful gain and wide-residue linearity. **FAILED as the better joint sizing coordinate** over the tested range. No blind width sweep was performed.

Unverified noise includes native acquisition, FIA thermal/flicker/reset noise, series-switch channel noise and the isolation partition covariance, latch kickback noise, and driver noise. An independently reset ideal250 fF capacitor would have approximately129 µV RMS single-ended at27°C, but that value cannot simply be added as a new independent term to an already simulated FIA output-noise state: the connected amplifier/storage covariance must be propagated through opening. The deterministic held node is not an ideal analog memory.

## One sampled holder and a stiff reference

`tt_w3p36_singleended_r1` uses the same3.36 µm isolation switches, timing and frozen input cases, but removes the negative-side1 pF holder and its acquisition TG. The positive input source drives VCM+Vin instead of VCM+Vin/2, while an explicit ideal reference source fixes the other FIA gate atVCM. Thus differential input amplitude is unchanged, with exactly one sampled computational holder. Explicit capacitor total falls to3.520 pF. Reference-port current and positive delivered energy are counted; reference noise, impedance and physical driver area remain unqualified.

**FAILED:** frozen pre-isolation gain25.30194, held native error max2451.43 µV/RMS1196.38 µV; several small positive input decisions have the wrong sign. Reset still passes at13.598 µV. This failure is substantially affected by acquisition and initialization, and does not establish a fundamental failure of single-ended FIA operation.

In particular, the input acquisition TG now injects an uncancelled approximately−4.44 mV shift into the signal holder. A+20 µV driven input becomes−4419.46 µV differential at31 ns after acquisition release. The two-holder circuit largely cancelled this common sampling shift. A stiff reference does not receive that shift. The first two calibration samples also have startup/history dependence; the large frozen-calibration gain and subsequent range error should not be interpreted as a stationary single-ended transfer without further controls. A digital output offset correction cannot restore lost analog headroom or repair wrong raw signs by itself; a calibrated physical reference or charge correction would need independent testing.

The ideal reference supplies4.50–5.72 fJ positive energy per frame, included in total2.1535–2.1739 pJ. At67.8 ns, across cases, input common mode spans0.893406–0.902732 V, stored-output common mode0.887355–0.890726 V, upper floating source rail1.61994–1.62712 V and lower rail0.26090–0.26869 V. These measurements show no gross rail violation at that sampled phase; they do not replace full transistor-region/headroom checks.

Independent critic confirmed the removed holder/acquisition TG, stiff reference, unchanged differential amplitude and energy boundary. `singleended_physical_audit.json` preserves detailed common modes, rails, acquisition shifts and reference energy. The original manifest's `input_holder_fF_per_side` label means per sampled side in this control; the immutable deck contains only one holder, the audit makes the count explicit, and the current generator now records holder count separately. Original failure artifacts remain unchanged.
