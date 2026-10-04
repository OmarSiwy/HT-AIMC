# Causal seven-bit fine SAR on an isolated FIA output

This experiment closes the decision path using actual native transistor-latch results. It does not substitute an ideal ADC or copy an analog state. Digital sequencing is ideal and its implementation energy/area are unpriced; physical analog, reference and TG-clock source energy is measured in the final replay.

Source: `analog/testbenches/tb_imc_fia_fine_sar.py`. Each fresh input gets two complete physical zero warmup frames, then one active conversion frame. Frames are360 ns. A single FIA aperture begins at40 ns; output isolation opens at68.2 ns and remains open until320 ns. The internal FIA resets at110 ns and input acquisition reopens at120 ns while the output remains held. These real interfering transitions are retained rather than suppressed.

The output has the physical contacted-coupon7-bit4+3 split DAC and190 fF holding capacitor per side. Each bottom now has three actual TG paths to VCM, LOW0.5875 V, and HIGH1.2125 V. The additional off TG is real loading, so the earlier two-route bit weights are explicitly provisional calibration, not silently assumed exact.

## Decision rule and physical initialization

During amplification, bottom plates are atVCM. After isolation, all positive-side DAC bottoms physically switch LOW around72 ns. This initializes an unsigned floor search with a signed physical offset. It is not a neutral-start bipolar successive-correction algorithm. For each bit b from6 down to0:

1. Form `trial = accepted | (1 << b)`.
2. Apply HIGH to trial1 bits and LOW to trial0 bits through the real TGs. Every unprocessed bit remains LOW.
3. Clock the actual transistor latch and require both outputs to be fully resolved.
4. Retain the bit only if the latch reports nonnegative held residue.
5. Physically apply the accepted mask before the next trial.

Trials begin at80+32k ns, latch rising edges at92+32k ns, reads at104+32k ns, and accepted-mask updates at106+32k ns. Route changes use actual0.2 ns edges and break-before-make. The final rejected or accepted LSB is physically applied around298 ns and actual final bottom voltages are checked at308 ns. Only then are bottoms returned to VCM at318 ns and storage rejoined/reset at320 ns.

Let old measured positive bit weights at+0.25 V be w_i, and let L(c)=Σbit_i(c)w_i, W=Σw_i. The new references are±0.3125 V, so the frozen provisional physical threshold is

`D(c) = 2.5 L(c) − 1.25 W`.

The held residue model is `G Vin + O − D(c)`. Therefore a fully resolved nonnegative latch decision retains the trial. For an interior output code c, the frozen reconstruction is

`Vin_hat = ((D(c)+D(c+1))/2 − O)/G`.

This is bin-center reconstruction for a floor search, not nearest-level quantization. Endpoint codes are flagged rather than assigned an undeclared external coverage convention. The gain/offset come from the old physical first-pair119 ns calibration and the weights from the old169 ns seven-bit measurements; their hashes are frozen before any new heldout result. New three-TG loading, reference amplitude, read phases and repeated latch activity are allowed to disagree with that model. No heldout refit is used.

## Causal replay proof boundary

For bit k, a native transient starts again from physical initialization and the same two warmup frames, applying only previously established decisions. The actual latch at the next read supplies the new bit. Each prefix also rechecks all earlier decisions. A final complete native replay applies the resulting seven-bit sequence, requires all seven transistor decisions to match, and verifies the actual final DAC state. No analog voltage, capacitor charge or device state is transferred between simulations.

Offline replay is verification machinery, not eight physical conversions charged to a production ADC. Conversely, the two zero warmups are real phases in every certified waveform and are not assumed free in a production pipeline. The certified tested schedule costs1080 ns per independent input including warmups; the active conversion frame alone is360 ns. Continuous word-to-word service without warmups remains unverified.

Independent critic confirmed the signed-offset floor rule, latch polarity, route nonoverlap, final rejected-LSB application, prefix causality and source-energy boundaries. The latch is read12 ns after its clock starts; noise numbers from earlier clock/aperture configurations cannot automatically be inherited. No transient-noise, mismatch, PVT, all-code or SoTA qualification is implied by a deterministic causal replay.

## Completed bounded native decision tests

**VERIFIED deterministic causal decision path for four fresh inputs.** All seven latch choices in every final native replay are fully resolved, match the earlier causal prefixes, and produce the frozen-calibration oracle code. An independent certificate audit verifies every prefix choice and all28 trial DAC states; actual trial bottoms are within59.5 nV of the programmed reference levels at observation. No calibration was refitted to these heldouts.

Artifacts are `build/campaign/fia_fine_sar/tt_{p377,m377,p911,m911}_r1/`, with per-bit prefix decks/results and each complete `final_replay/`. `four_case_certificate_r1.json` records result and prefix hashes, actual trial-voltage checks and pre-latch signal margins.

| Driven native input, µV | Actual post-release native, µV | Physical code | Frozen reconstructed native, µV | Error vs actual native, µV | Active-frame positive port energy, pJ |
|---|---:|---:|---:|---:|---:|
|+377|+381.115378|69|+373.658784|-7.456594|3.170006|
|-377|-381.115378|57|-375.371971|+5.743407|3.159467|
|+911|+920.944591|78|+939.217632|+18.273041|3.158998|
|-911|-920.944591|48|-940.930819|-19.986228|3.183896|

The four-point reconstruction RMS is14.335 µV. This is descriptive deterministic quantization/calibration error for four inputs, not a noise measurement, statistical accuracy guarantee or complete-code INL result. The distinction between driven input and the physically sampled native state remains explicit.

Each certified input also costs two warmup frames with2.302788 and2.302445 pJ positive source-port work, in addition to its360 ns active conversion frame. The total certified waveform therefore occupies1080 ns and roughly7.76–7.79 pJ per independent test input. Offline prefix replays are not physical conversion energy; they establish causality. Conversely, warmups are actual waveform operations and cannot be removed from a throughput claim without a continuous-history test.

The minimum settled pre-latch residual magnitude across each seven-decision sequence is417.28/417.31/237.06/237.03 µV output in table order. These values are sampled before the latch clock, not after its kickback. They are signal margins only: no stochastic decision-error probability is qualified for this timing. The earlier comparator-noise result used a different observation window and cannot simply be attached to this conversion.

The measured energy is positive work at ideal analog/reference/clock-source ports. Native capacitor charging and actual TG/latch currents are included. Digital sequencing, clock/reference driver loss, calibration storage, routing, a preceding coarse converter and the computational core remain unpriced. It is not a complete IMC energy figure.

Remaining tests include continuous word histories without zero warmups, actual noise and reset/partition covariance, dense code/threshold coverage, endpoint behavior, mismatch/PVT, physical controller timing, reference generation and integration with the system's single computational-holder noise boundary. Four matched codes do not establish any of those claims.

## Frozen boundary stress selection

The next four inputs were selected before their new simulations, using only the original calibration pair and measured bit weights. They target ±1 µV around two predicted native thresholds: code64 (the first MSB decision) at37.721334 µV and code57 (an odd-code final-bit decision) at−405.911742 µV. The original first-pair acquisition map is `native31 = 1.0109195813903238 × driven − 0.00168872982263224 µV`; inversion gives driven inputs36.3263545964,38.3047513322,−402.5147604201 and−400.5363636843 µV. No earlier heldout result enters this selection or a calibration refit.

These are frozen-model threshold estimates, not measured thresholds of the new three-route DAC. The distinction is deliberate: disagreement can falsify transfer of the old calibration even when the physical decision path is repeatable. Every test retains the same two360 ns physical zero warmups plus360 ns active frame, causal prefix runs, and final full replay. Selection is preserved in `build/campaign/fia_fine_sar/boundary_selection_r1.json`; results use `tt_boundary{64,57}_{minus,plus}_r1`.

### Completed boundary quartet: two calibration failures preserved

**VERIFIED:** all28 physical decisions resolve and reproduce their causal prefixes in the final full traces. Actual trial and final DAC states, interior-code and held-reset gates pass in all four cases. **FAILED:** transfer of the frozen old calibration at both selected positive-side boundary points. These failures remain in their result JSON and the testbench exits nonzero; no calibration was changed.

| Target threshold / side | Actual native31, µV | Actual / frozen-oracle code | Frozen reconstruction error, µV | Minimum pre-latch residual magnitude, µV output | Active-frame positive port energy, pJ |
|---|---:|---:|---:|---:|---:|
|64 / minus|36.722543|63 /63|−37.579137|38.650757|3.131680|
|64 / plus|38.722130|63 /64|−39.578724|2.441948|3.141534|
|57 / minus|−406.907896|56 /56|−29.543649|48.530697|3.173322|
|57 / plus|−404.908303|56 /57|−31.543243|12.414912|3.174568|

The actual native samples differ from the calibration-only selection prediction by at most0.004 µV, much less than the intended1 µV boundary offsets. The selected MSB residuals at90 ns are−38.650757 and−2.441948 µV output; final-bit residuals at282 ns are−48.530697 and−12.414912 µV. Thus all four actual pre-clock signals remain below their physical trial thresholds. The positive MSB point has a positive5.833 µV held residual **after** its latch decision at104 ns; this does not reverse the already resolved negative decision and demonstrates why post-kickback residuals cannot substitute for pre-clock signal margins.

`boundary_certificate_r1.json` independently checks prefix causality, source-result hashes, all trial states and final matches. The two zero warmups again cost2.302788+2.302445 pJ per tested input, so the paid1080 ns trajectory costs7.736913–7.779801 pJ. Maximum held-reset error is8.844280 µV. No unresolved decision, replay inconsistency or numerical failure occurred in this quartet.

This is evidence that small calibration-transfer shifts become visible near code boundaries, despite the earlier four exact-code passes. It does not measure the actual threshold positions, prove noisy decision reliability at2.44 µV output margin, or invalidate calibrated conversion in general. A physically matched new calibration would require separate calibration stimuli and fresh validation; the current old-calibration failures must remain part of that comparison. These four intentionally selected boundary points are not a random accuracy cohort.

The earlier28 raw prefix CSVs have been archived losslessly after independent audit completion; every decompressed SHA256 was checked before removing the duplicate CSV. `prior_four_prefix_archive_r1.json` records the archives and hashes, saving474,068,795 bytes. All final traces, decks, result JSON, calibration and source snapshots remain intact. The new boundary traces remain uncompressed for independent review.

## Consecutive-word history control: frozen schedule

The next bounded fixture is `tb_imc_fia_fine_sar_history.py`, reusing the same physical generator with multiple active words. It tests +3000 µV followed immediately by the earlier lower MSB-boundary input, and −3000 µV followed immediately by the upper input. Two360 ns zero frames occur only at initial startup. The two active360 ns frames then run consecutively, with no zero frame inserted between them: total1440 ns per certified history. Existing physical reset, DAC return-to-CM, input acquisition and isolation events remain present and paid in every frame.

A flat14-decision causal prefix retains every established decision from both words. Each simulation starts from physical startup; no analog state is copied or reinitialized between active words. The final1440 ns replay checks all14 decisions, both words' trial/final DAC states and held resets, and all four frame energies. The independently initialized `tt_boundary64_minus_r1` and `tt_boundary64_plus_r1` are frozen controls for the respective second words. Physical replay, history-induced code change, and old-calibration agreement are reported separately. In particular, the already demonstrated upper-boundary calibration failure is not repaired or relabeled by a successful history comparison.

Generalization was checked against the immutable prior generator: the original lower-boundary prefix0, prefix6 and full-replay SPICE decks are byte-for-byte unchanged. The new tests are `build/campaign/fia_fine_sar_history/tt_positive_to_boundarybelow_r1` and `tt_negative_to_boundaryabove_r1`, each with frozen calibration, selection, source snapshots and all causal prefixes. This tests two specific transitions; it does not establish arbitrary continuous-stream throughput or stochastic reliability.

### Completed consecutive histories: repeatable path, failed history invariance

**VERIFIED:** both complete1440 ns histories reproduce all14 resolved transistor decisions; all physical trial/final DAC states and both held resets pass. The preceding +3000/−3000 µV words produce codes111/15, matching their frozen oracles, with reconstruction errors−6.571098/+4.857911 µV. **FAILED:** both following boundary words change from independently initialized code63 to history code64.

| Consecutive active inputs | Second-word physical / oracle code | Error vs actual native, µV | Change from independent-control reconstruction, µV | Active energies, pJ |
|---|---:|---:|---:|---:|
|+3000 → lower boundary|64 /63|+31.538587|+69.117724|3.123071 /3.207116|
|−3000 → upper boundary|64 /64|+29.539022|+69.117746|3.146027 /3.199248|

The upper-boundary history's agreement with the old calibration is not a repair: it disagrees with its independently initialized physical control. Separate calibration and history gates preserve that distinction. Both full testbench runs exit FAIL. The actual sampled native31 changes by only+0.00000791 and−0.00001390 µV versus controls, excluding input acquisition error as the explanation at this scale.

Before the changed MSB decision, held residuals at90 ns are−46.643680/−12.248886 µV output versus control−38.650757/−2.441948 µV. Despite negative pre-clock residual, both history cases resolve to keep MSB1. External output reset alone does not establish zero internal latch state: the present latch has no explicit dp/dn internal reset devices. Independent source review found no obvious word-index, timing or state-copy bug. Retained internal charge/dynamic offset is a candidate mechanism; it is not yet proven, and timestep sensitivity remains necessary near these small decision margins.

`history_certificate_r1.json` independently verifies all14 prefixes per history and compares phase traces with the frozen controls. Total positive port work is10.935420/10.950509 pJ for the paid1440 ns waveforms, including the initial4.605234 pJ of zero warmups. The360 ns active-frame spacing is physically exercised for these two transitions, but the history failures prevent claiming an accurate continuous converter at that interval. No interword zero conversions were silently inserted.

Unchanged-deck internal-node observation and timestep controls use `tb_imc_fia_sar_state_audit.py`. They retain frozen DAC decisions; if a numerical control changes an earlier latch decision, later forced states are explicitly diagnostic and cease to be a causal certificate. Any eventual reset remedy must be a separate paid transistor topology and must re-establish causal decisions without calibration refitting.

### Unchanged internal-state observation

All four20 ps instrumented replays (two controls and two histories) reproduce the original decisions exactly. Only save/output vectors were added; no transistor, clock, capacitor or source changed. At31 ns of the boundary word, the independent control has dp/dn≈1.269302 V and tail≈0.548746 V, with only0.007 µV internal differential voltage. The positive history instead has dp1.231181/dn1.231576 V and tail0.514482 V (−394.418 µV differential); the negative history has dp1.228450/dn1.228053 V and tail0.510461 V (+396.916 µV differential).

After DAC initialization/trial activity, at90 ns the control dp−dn is−2.503 mV, versus−5.210/−5.282 mV in the histories; their tail voltages remain roughly26–29 mV below control. External op/on both nearVDD therefore conceal substantial internal charge differences. This supports retained latch state as a mechanism but does not establish that one node alone causes the decision change. Explicit dp/dn reset can alter input kickback and tail charging, so it requires a fresh paid comparison. Grounding the tail while pulling dp/dn high would also create an unwanted reset current path through the input pair; it is not treated as a free fix.

Artifacts: `build/campaign/fia_sar_state/tt_{control_below,control_above,history_positive,history_negative}_20p_r1`. The corresponding10 ps history controls are a separate numerical sensitivity check, not a topology modification.

### Numerical check and bounded reset sizing

Both history replays at10 ps reproduce all14 decisions from20 ps. Their boundary MSB pre-clock residuals change by only−0.002025/−0.000455 µV output, and active energy changes by less than0.00088 pJ. This supports the observed history failure against this timestep refinement; it is not a proof against every numerical/model issue.

The paid reset candidate adds two native PMOS devices, eachW0.42/L0.15 µm, fromVDD to dp/dn, gated by the same latch clock. No shared-tail ground clamp is added. `tb_imc_latch_reset_sizing.py` measures a local driving-point capacitance and reset-device operating points with actual native models/diffusion. At dp1.25/1.79/1.799 V with other terminals frozen, the largest measured local capacitance is3.416 fF, and reset small-signal resistance spans7.54–16.03 kΩ. Native reset gm/Id is0.65–0.96 V⁻¹, appropriate to a strongly inverted reset switch; the FIA amplifier retains its earlier measured gm/Id sizing.

The screening estimate uses a5× local-capacitance allowance and `t = Rmax × (5 Cmax) × ln(0.6 V /1 µV) =3.644 ns`, versus the14 ns low-clock interval between SAR decisions. The5× allowance is an explicit engineering margin, not a proven bound on the dynamic multi-node capacitance or tail charging. Added channel area is0.126 µm²; total layout area and clock-driver implementation remain unqualified. The full transient must still falsify reset settling, kickback, added energy and calibration shift.

Sizing artifacts are `build/campaign/latch_reset_sizing/tt_minimum_r1`. Matched independent controls are `tt_boundary64_{minus,plus}_ir042_r1`; after those complete, corresponding consecutive histories use the same reset topology. Frozen old calibration is retained. Default-width-zero generation remains byte-for-byte unchanged for checked single-word and two-word decks.
