# Physical output DAC weights and held-code carries

This bounded experiment measures all seven output-DAC weights and physical7→8 and63→64 transitions. It tests whether individual bit responses predict multibit behavior. It is not a complete SAR search, a full code-coverage test or a receiver-noise qualification.

Source: `analog/testbenches/tb_imc_fia_dac_weights.py`, with frozen imported output-DAC and output-hold source snapshots. The physical circuit uses the contacted-coupon7-bit4+3 DAC from `FIA_OUTPUT_DAC.md`, actual per-bit bottom-plate SPDTs,1 pF differential input holders, and3.36 µm output-isolation TGs. No signal state is copied or assigned ideally.

The64-frame sequence occupies15.36 µs at240 ns/frame. Two explicit zero-input warmup frames precede each stimulus. This is paid characterization overhead; zeroing between words is not assumed free in a production pipeline. Seven bits are each exercised with negative and positive0.25 V reference steps. Static codes7,8,63 and64 are measured separately. Carry frames establish code7 or63 at80 ns, then physically switch the corresponding DAC TGs to code8 or64 around140 ns while the output remains isolated. Nonoverlap opens old routes at139.4–139.6 ns and closes new routes at140–140.2 ns.

Responses are measured at119,139 and169 ns. Each level is referenced to its immediately preceding second zero-warmup frame. Individual positive and negative responses, odd/even components and actual bottom voltages are recorded. For each carry, the observed139→169 ns output change is corrected by the measured static-start-code drift over the same interval. This separates code-change response from held-node leakage and ongoing reset coupling. The final carry level is also compared with a separately initialized static target code.

The positive-bit superposition prediction for code n is the sum of independently measured positive weights whose bits are set. It is compared against static7/63 levels and against drift-corrected carry gaps. These comparisons expose code-dependent loading and switching effects that a two-bit radix ratio alone cannot identify.

The independent critic's `SPLIT_DAC_CODE_CRITIC.md` already demonstrates that radix8.2593 alone does not reject the architecture: under binary sub-array and state-independent-weight assumptions, calibrated bin-center reconstruction increases uniform-input quantization variance only about2.2% at matched coverage. The present experiment measures some of those assumptions physically rather than treating DNL as an automatic failure criterion.

## Numerical failure and recovery boundary

`tt_coupon_allbits_carries_r1` aborted at6.0302 µs during a zero warmup, with ngspice reporting an excessively small timestep and a constant complementary-clock source branch. Partial trace, source, deck, log and `failure.json` are preserved. It did not pass the requested sequence and is not interpreted as an architecture failure.

The r2 deck removes10852 redundant vertices on exactly constant segments of48 voltage-source PWLs using the existing `simplify_flat_pwl` helper. The helper asserts voltage equivalence at the union of original vertices and preserves every original literal at retained vertices. No physical voltage edge, geometry or initial-state assignment changes. Original r1 metadata inherited an unused13-case DAC-step field; `weight_cases` was the authoritative64-frame schedule. R2 removes those obsolete inherited fields. Results below require the complete r2 transient, not extrapolation from the partial first run.

The r2 monolithic sequence also aborted numerically at7.8782 µs during a zero warmup; its `failure.json` and partial trace remain preserved. Exact PWL pruning did not resolve the long-run numerical problem. The reported source-branch name is a failure location, not proof of its root cause.

The next controls use four independent native cohorts: bits0–2, bits3–4, bits5–6, and static/carry measurements. Each performs physical initialization, the same first calibration/check samples and two actual zero warmups per stimulus. No saved node voltage or charge state is copied between cohorts. The four complete cohorts total76 paid frames rather than64 because the initial calibration/check sequence repeats. Combining their weights assumes those physically initialized states are sufficiently reproducible; repeated calibration and zero-state measurements must be checked. The original monolithic sequence remains numerically unverified even if individual cohorts complete.

## Completed physical cohorts

The low/mid/high/carry r3 cohorts all completed their native transients and basic signal/reset checks. Source hashes and independently initialized measurement combinations are recorded in `build/campaign/fia_dac_weights/combined_r3.json`. All four first-pair calibration gains are18.0387566635, and the largest second-warmup residual is0.01158 µV output. Thus the initialized states are closely reproducible over the measured conditions. The original uninterrupted64-frame sequence remains numerically unverified.

At169 ns, measured positive bit weights are:

| Bit | Output weight for+0.25 V bottom step, µV | Relative to bit0 |
|---|---:|---:|
|0|440.720073|1.000000000|
|1|881.439665|1.999998909|
|2|1762.877694|3.999994106|
|3|3640.071540|8.259373156|
|4|7280.177552|16.518824531|
|5|14560.567872|33.038131834|
|6|29122.572681|66.079524100|

The largest even component of the positive/negative bit response is0.44717 µV output for bit6. The low sub-array is extremely close to1:2:4; higher weights have small measured departures from exact binary multiples. These are actual single-bit observations, not substituted ideal values.

| Carry | Raw observed gap, µV | Matched hold drift, µV | Corrected gap, µV | Individual-bit prediction, µV | Residual, fine LSB |
|---|---:|---:|---:|---:|---:|
|7→8|555.861947|0.340758|555.521189|555.034108|+0.001105|
|63→64|558.903802|3.228316|555.675486|556.718285|-0.002366|

The carry endpoints differ from separately measured static8/64 levels by only0.45219/0.51663 µV output. Static-code63 differs from the sum of its independently measured positive weights by1.53731 µV output. The largest drift-corrected carry residual is1.04280 µV output, below0.0024 measured fine LSB. This supports superposition and a compact calibrated-weight model for these particular states and transitions. It does not prove all128 codes, all carry directions, arbitrary previous histories or reference spans behave identically.

The four cohorts cost76 frames,18.24 µs and173.229 pJ total in this diagnostic schedule. Individual frame positive source energy spans2.22447–2.43516 pJ. All native reference/clock ports are included; driver implementations and routing are not. Two zero warmups per stimulus remain explicit overhead. No claim is made that a production pipeline can reset between decisions or words for free.

**VERIFIED bounded physical measurements:** seven weights, polarity asymmetry, two static-to-static carry comparisons and two actual held-code transitions at native TT with contacted-coupon parasitic sensitivity. **STRONGLY SUPPORTED within this tested subset:** the earlier compact bit-weight model is a reasonable description despite radix differing from8. **UNVERIFIED:** full search logic and code coverage, calibrated full-converter quantization error, thermal/flicker/partition noise, comparator decision statistics, PVT/mismatch, actual reference drivers, integration with a computational holder and continuous service timing.

The two incomplete monolithic traces are losslessly stored as `trace.csv.gz`; `failed_trace_archive_index.json` records original SHA256 and sizes. Every decompressed archive was hash-verified before removing its uncompressed duplicate, saving approximately0.878 GiB. Their failure logs, sources and decks remain unchanged. Completed r3 cohort CSV traces remain available for independent review.
