# Connected native stack and FIA fixture

2026-09-12 research round. **N1 direct control VERIFIED for the bounded deterministic gates; N4 hybrid FAILED reset and fine-DAC co-gain gates.** Neither is a noise-qualified converter or integrated IMC result.

Source: `analog/testbenches/tb_imc_fia_stack.py`. Immutable decks, manifests, source snapshots and completed traces: `build/campaign/fia_stack/n1_tt_r1/` and `n4_tt_r1/`. Initial result serialization failed on a NumPy Boolean; completed unchanged transient traces were reanalyzed after converting gate values to Python bool. Results preserve original deck/source hashes and record analysis recovery/source hash. No circuit rerun or data substitution was used.

## Frozen circuit and boundaries

Each of two computational native holders has 6000 fF nominal effective capacitance. Real TGs sample stiff initialization sources; these sources stand in for native core initialization only. There is no ideal buffer, voltage copy, or dependent source between stored charge, reconfigured stack, and FIA. N1 and N4 use the same short-L FIA (NMOS22/PMOS44 µm, L0.18 µm, reservoir2 pF, outputs250 fF each), actual two-SPDT reservoir switching and an actual NMOS latch. Acquisition/reset/reference clocks and voltage-source port charge/energy are recorded.

The crossed N4 chain allocates each of the eight native capacitor sections exactly once. Each bank's section0 contains an explicit 12-bit split host: 255Cu coarse, Cu dummy plus 15Cu fine, bridge16Cu/15; Cu=3.75 fF. Its ideal effective host capacitance is256Cu=960 fF. Real DAC bottom-plate TGs, their parasitics, bridge and fine reset load are present. Fine-bit0 steps physically from VCM to VCM±0.5 V after stacking. Its ideal native equivalent is19.53125 µV; measured actual bottom-plate step is used in co-gain analysis.

Capacitors use grounded-substrate parasitics interpolated from actual contacted Substrate2 MIM coupons, with parallel tiles no larger than the measured813.338 fF coupon. Real native MOS models include explicit0.29 µm diffusion geometry. This is not complete network PEX. Both fixtures contain14.6405 pF explicit mutual capacitance; N1 has35 and N4 has41 capacitor elements including two latch loads, excluding separate parasitic capacitors. No area reduction is claimed from these counts.

The240 ns frame explicitly adds100 ns of initialization/reconfiguration to the140 ns demonstrated FIA service. Frozen calibration uses only the first native −500/+500 µV cases. Heldouts are −100/+100/−20/+20 µV. Three additional cases exercise negative, zero and positive fine steps. Fine gain is never independently recalibrated to hide disagreement with native gain. This is a small-residue fixture, not a full-range ADC.

## Native TT27 results

| Metric | N1 direct | N4 connected |
|---|---:|---:|
| Output/native acquired differential gain |20.20053|47.28874|
| Native heldout errors, µV |−0.6963,−0.4641,−0.6037,−0.5574|−0.5281,−0.3514,−0.4584,−0.4231|
| Fine/native co-gain |0.975647|0.925910|
| Maximum native reset residual, µV |0.25859|27.97259|
| Maximum FIA output reset residual, µV |33.99737|35.33884|
| Positive delivered source energy/frame, pJ |2.3976–2.4557|2.6539–2.7169|
| All eight nonzero decision signs |PASS|PASS|
| Frozen combined gates |PASS|FAIL|

Gates were native reset<10 µV; FIA reset<100 µV; native heldout RMS<5 µV and max<10 µV; fine/native co-gain within5%; all nonzero signs correct. N4 violates two gates. Its increased gain does not override these failures.

Actual differential input slopes at119/139/169 ns are0.99237/0.99239/0.96186 for N1 and3.11815/3.11886/2.23680 for N4. The FIA is enabled at140 ns. Dynamic connected loading therefore substantially reduces the initially established N4 gain; multiplying an unloaded passive gain by a stiff FIA gain would misrepresent this result.

N4 reset failure is still settling: in the first frame, p_t2 residual decreases from−218.98 µV at220 ns to−71.18 µV at230 ns and−26.68 µV at239 ns. Additional reset time is a falsifiable paid control, not yet tested. The isolated native sampling bus experiences approximately−98 mV clock-feedthrough after partition disconnection; its off-device coupling is present in this simulation. Fine co-gain error is a separate7.409% failure, compared with2.435% for the direct host. One native affine calibration cannot remove it.

## Noise and architectural limits

Both sampled holders are computational states. Their acquisition noise belongs to the upstream holder budget: at6000 fF and27°C, fresh equilibrium sampling gives approximately26.28 µV per side or37.17 µV differential. Neither holder is a noiseless reference. The stated20 µV receiver target, where used, is additional noise only.

Separately resetting the FIA gate to VCM before joining adds another thermalized state. In the simplified constant-capacitance model Ce=Ca/N², with independent receiver input reset capacitance CL, its native-referred variance per side is kT·CL·N²/Ca². AtN4/Ca6 pF, CL60 fF implies approximately14.9 µV differential; CL160 fF implies24.3 µV. Actual MOS charge-matrix covariance, correlations with rails/output resets, and transient noise are not yet qualified. A trajectory-derived effective input loading capacitance cannot automatically replace CL in this thermal calculation.

Independent critic confirmed physical chain allocation, split-host arithmetic, source boundaries and clock ordering; no topology/conservation blocker was found. Signal sampling is measured at97 ns before acquisition release at98 ns, so results include subsequent release/loading errors but do not establish absolute acquisition accuracy. No mismatch, PVT sweep, transient receiver noise, reference/clock-driver energy, routed extraction, full SAR sequence or integration with core computation has passed here.

Next bounded tests are reset-settling control and physical fine-host/radix correction, followed by a shared native-acquisition FIA-gate control if its actual covariance and added native loading are paid. A separate coarse-SAR/one-FIA/fine-SAR architecture could amortize FIA service, but requires full residue headroom/linearity, interstage hold noise and actual timing verification. These are known primitive combinations; no novelty or superiority claim is made.

## Paid reset control

`n4_tt_reset20_r1` extends only the end-of-frame reset dwell by20 ns, making the frame260 ns. Native reset error drops to3.35543 µV and FIA reset to22.07354 µV; both pass. Gain47.28742, native heldout errors−0.51183/−0.34031/−0.44403/−0.40970 µV, and fine/native co-gain0.925874. Energy2.6556–2.7180 pJ/frame. **Overall still FAILED** due to fine co-gain. This isolates a paid settling repair without changing geometry or concealing the separate capacitor-transfer failure.

The independent completed-trace audit finds N4 fine/native co-gain0.922464 before FIA enable (native gain3.118861, fine gain2.877036 at139 ns). The amplifier is therefore not the primary origin of the7.4% mismatch. N1 preamplifier-input co-gain is0.974377. Fine-reset release also creates a roughly−1.824 mV internal fine-node kick and common section0 disturbance before acquisition release; the actual segmented state differs slightly from the observed native bus. Differential cancellation is demonstrated only over the frozen small-signal cases.

## Fine-amplitude and quiet-bus controls

`n4_tt_reset20_finelinearity_r1` calibrates a separate fine slope using real ±0.25 V bottom steps (±half of the original fine quantum), then evaluates ±0.5 V steps in subsequent frames. Fine gain43.782039 gives equivalent native amplitude errors−0.000397 and−0.000152 µV at the two validation endpoints. The endpoints were observed in the earlier uncalibrated experiment, so this is an amplitude-linearity control, not a blind architecture validation. The nominal native/fine co-gain remains0.925871 and the original combined fixture gate remains **FAILED**. The small tested range supports a stable separate fine gain, but does not establish complete SAR code coverage, INL or calibration robustness. In particular, actual coarse-LSB/fine-LSB radix must be measured before claiming a fine calibration repairs a split ADC; it cannot be inferred by equating coarse charge injection to distributed native sampling.

`n4_tt_reset20_quietbus_r1` reuses the real native-reset TG to clamp the isolated sampling bus to VCM from101.2 to197 ns, after top partition disconnection. No ideal clamp is inserted and its added clock/reference charge is counted. Gain47.287397 and fine/native co-gain0.9258742 are essentially unchanged from the floating-bus control. Energy rises to2.7576–2.8199 pJ/frame, approximately0.102 pJ extra. Native reset still passes at3.38353 µV. **FAILED as an accuracy repair**; keeping a quiet bus does not address the measured fine-transfer mismatch here.

## Actual coarse/fine radix and wider residue controls

`n4_tt_reset20_coarsebit4_r1` moves the selected real bottom-plate mux from fine bit0 to coarse bit4, retaining unitCu geometry and recording the actual coarse bottom swing. Compared with `n4_tt_reset20_r1`, the measured output response per actual bottom volt has coarse/fine ratio **16.289955**, and the ratio before FIA enable is16.290049. Thus physical coarse/fine radix differs from nominal16 by1.812%; this is distinct from the7.4% mismatch between fine injection and distributed native initialization.

If all four lower fine weights remain binary, an adjacent coarse transition has an illustrative level spacing `(16.289955−15)·LSBfine = 1.289955·LSBfine`, or DNL+0.289955. Digital gain calibration can label these levels but does not create missing analog thresholds. This is not a measured maximum DNL: all fine weights and coarse carries still need actual verification.

The system model confirms that reference span is bottom-plate swing. With this fixture's Cu3.75 fF/Ca6000 fF and0.5 V reference swing, nominal native quantum is19.53125 µV and4096 quanta cover80 mV total native span, not0.5 V. Half of that coverage is available per polarity in the signed interpretation. The present fixture does not exercise the complete ADC span.

Both wider-residue controls preserve the original ±500 µV native calibration and replace native validation points with−5/+5/−10/+10 mV. Geometry and260 ns timing are unchanged.

| Metric | N1 direct | N4 connected |
|---|---:|---:|
| Frozen small-signal gain |20.19986|47.28742|
| Native errors at−5/+5 mV, µV |−4.6753/+3.6030|+2.1884/−2.6740|
| Native errors at−10/+10 mV, µV |+0.4382/−1.0571|+45.8398/−44.8213|
| Differential output magnitude at5/10 mV, V |0.1011/0.2020|0.2363/0.4707|
| Maximum native reset residual, µV |0.01905|19.93952|
| Maximum FIA reset residual, µV |21.52304|below100 gate|
| Frozen combined gates |PASS|FAIL|

Artifacts: `n1_tt_reset20_residue10m_r1` and `n4_tt_reset20_residue10m_r1`. All nonzero decision signs pass. N4 fails native linearity, native reset, and nominal fine co-gain. N1 passes this sparse endpoint experiment, but its nonmonotonic endpoint errors do not prove continuous-range INL. N1 positive source energy remains2.3987–2.4570 pJ/frame. A direct FIA is therefore a stronger candidate for a once-per-word residue amplifier when its separate noise budget allows it. N4 remains a higher-gain alternative for smaller residues, with unresolved receiver reset noise and ADC-radix correction costs.

Completed stack `trace.csv` files are losslessly archived as `trace.csv.gz` to limit build storage. `build/campaign/fia_stack/trace_archive_index.json` records original SHA256 and sizes; every archive was decompressed and hash-verified before removing its uncompressed duplicate. Results, source/deck manifests and logs remain untouched. Restore a CSV from its gzip archive before invoking an analyzer that expects the original filename.
