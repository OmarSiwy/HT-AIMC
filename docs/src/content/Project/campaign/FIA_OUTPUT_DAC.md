# Physical FIA output split-DAC fixture

**VERIFIED for frozen deterministic final-read loading/step tests only.** No complete SAR, receiver-noise, ADC-reference or IMC-system qualification is claimed. The earlier failure with pre-isolation calibration remains preserved; this experiment explicitly freezes calibration at119 ns before running new residue amplitudes.

Source: `analog/testbenches/tb_imc_fia_output_dac.py`, importing the preserved output-hold generator. Both sources and their hashes accompany each native deck in `build/campaign/fia_output_dac/`.

## Circuit and measurement boundary

The input remains two differential computational1 pF holders. FIA geometry is Wn22/Wp44 µm,L0.18 µm,2 pF reservoir,3.36 µm output-isolation TGs. Each previous250 fF output capacitor is replaced by190 fF hold plus a physical7-bit4+3 split DAC: main weights1/2/4/8Cu, low weights1/2/4Cu plus dummyCu, and bridge8Cu/7; Cu=3.75 fF. The ideal effective load is190+15Cu+Cu=250 fF, while actual mutual capacitance is280.535714 fF per side. Complete explicit mutual capacitance is4.581071 pF, excluding transistor and optional grounded-substrate parasitics.

Every DAC bottom has actual1.68 µm TG paths to VCM and a diagnostic reference. A0.42 µm TG resets each fine node, opens at38.2 ns before FIA precharge releases, and remains off until200 ns. Thus the FIA internal reset at110 ns does not secretly reset the fine DAC. Output isolation opens at68.2 ns. Selected DAC bottom switching uses actual nonoverlapping TG clocks around80 ns, after isolation. All reference/clock source charge and positive delivered energy are counted.

The final-read phase is frozen at119 ns. Calibration uses only the first−500/+500 µV cases, referenced to actual post-acquisition31 ns native differential voltage. New validation amplitudes are−137/+137 µV,−1.7/+1.7 mV and−7.3/+7.3 mV. They were not the previous ±5/10 mV validation points. Frozen final gates are native maximum error<20 µV and RMS<10 µV, correct native decision signs, and storage reset<100 µV. These tests use fixed DAC code during native-amplitude validation; they do not verify all code-dependent gains.

Initial fixed-bottom experiment `tt_fixed_r1` also measures three zero-input samples after+7.3 mV history: their output values at119 ns are91.5035,0.05917 and0.000574 µV. Step-ratio experiments therefore include two explicit zero warmup frames before the negative/zero/positive DAC injections. Those diagnostic warmup cycles are paid and do not establish a production converter initiation interval. The step amplitude is±0.25 V on an actual bottom node, explicitly a diagnostic reference, not a selected system ADC reference.

## Ideal mutual capacitors with real MOS loading

| Fixture | Final gain | Maximum fresh native error, µV | Result |
|---|---:|---:|---|
| Fixed bottoms, `tt_fixed_r1` |18.044531|7.25775|PASS final gates|
| Fine bit0, `tt_bit0_r2` |18.044530|7.25825|PASS final gates|
| Coarse bit3, `tt_bit3_r2` |18.044535|7.25640|PASS final gates|

Fixed-bottom native errors are−0.85537/−0.62087/−4.69592/+1.93108/−7.25775/+0.45866 µV in validation order. Energy is2.2126–2.3129 pJ/frame; storage reset12.125 µV.

The real fine-bit output slope is−1793.409794 µV per actual bottom volt; coarse-bit slope−14577.791746 µV/V. Their measured ratio is **8.1285336**, not ideal8, a1.607% radix discrepancy despite ideal mutual capacitors. Actual MOS loading and fine-reset off-capacitance remain present. Symmetric-step center residual is−0.26876 µV output for fine and−2.19545 µV for coarse. This checks only one fine and one coarse bit. Assuming all remaining fine weights are binary, the corresponding illustrative coarse-boundary DNL would be+0.12853 fine LSB; actual carry errors require multibit testing.

## Contacted MIM parasitic sensitivity

The optional `--parasitics` mode preserves intended mutual values and adds grounded-substrate parasitics log-interpolated from the actual contacted Substrate2 MIM coupon table, recording its hash. It applies only to the new output hold/DAC capacitors; input/reservoir capacitors remain the parent baseline model. This is a sensitivity model, not complete network PEX. Low-array top plates connect to the fine node, so their small top-to-substrate coupling loads that node; bottom-to-substrate terms primarily load the real reference ports. The bridge bottom-to-substrate term does load the fine node. Reversing every plate would give a different circuit.

Fixed-bottom coupon fixture `tt_fixed_coupon_r2` passes frozen final gates: gain18.038757, maximum new native error7.22332 µV, reset12.12539 µV and energy2.2126–2.3139 pJ/frame. Actual fine/coarse step sensitivity is evaluated separately below; the bridge is not assumed ideal merely because gain is similar.

Independent critic confirmed physical weights, bridge arithmetic, reset timing, nonoverlap, plate orientation and absence of ideal signal copying. Remaining work includes all bit weights/carries, an actual SAR decision schedule, system-derived reference span, repetition/history without diagnostic warmups, receiver noise/covariance, mismatch/PVT, driver implementations and layout extraction. The raw32 converter budget includes settings that require more than7 fine bits under conservative coarse-decision guard assumptions, so this7-bit fixture is not a universal architecture selection.

The completed coupon step fixtures `tt_bit0_coupon_r2` and `tt_bit3_coupon_r2` both pass the frozen final native gates, with gains18.038755/18.038760 and maximum fresh error below7.225 µV. Fine output slope is−1762.430539 µV/V bottom and coarse slope−14556.441970 µV/V. The resulting actual radix is **8.2592997**, a3.241% discrepancy from8. Fine/coarse symmetric-step center residuals are−0.26376/−2.18939 µV output. `radix_audit.json` records source hashes and both measured ratios.

Thus contacted unit parasitics barely change amplifier gain but approximately double the radix discrepancy relative to the real-MOS/ideal-mutual control. Under the explicitly conditional binary-other-weight assumption, illustrative coarse-boundary DNL rises from+0.12853 to+0.25930 fine LSB. This remains a single-bit response measurement, not a measured maximum converter DNL. Physical bit-weight calibration, bridge sizing/trim or redundancy must be evaluated in an actual search sequence before selecting a repair.
