# Shared arithmetic: calibration access and paid scheduling

**SPECULATIVE architecture; VERIFIED coefficient and covariance calculations.**
Sharing a physical capacitor reduces the number of independent mismatch
parameters. It does not reduce their amplitude, and their repeated use creates
correlated errors. A correction must act before unrelated site contributions
merge, or each site's partial sum must remain separately observable.

## A schedule compatible with the existing magnitude banks

Divide each logical 256-row block into S temporal phases, for S=1,4,8,16.
There are 256/S physical sites per output column. A site stores S W8 weights in
SRAM and reuses two programmable magnitude banks. Each phase selects one weight
per site, executes the ten magnitude planes of common A11, converts both bank sums,
and digitally adds the phase result. The original signed radix8 reconstruction
is retained. Two bank ADCs per column are assumed to operate in parallel.

The weights are local, but their selection/read, programming gates and decoded
signs still consume energy. There are 2048 payload bits per logical 256-row
column per MVM, independent of S, unless vector reuse amortizes those reads.
This counts payload, not a claim that all bits traverse a global bus.
The number of active site-plane events stays approximately constant because
S times as many slots operate on 1/S as many sites. Core capacitor switching
energy therefore does not automatically grow by S. Fixed column reset, ADC,
clock and programming overhead need their own activity counts.

| S | Physical sites/column | Activation-plane slots/block | Bank conversions/column | Minimal magnitude C per stored weight | Measured two-4bit-fixture C per stored weight |
|---:|---:|---:|---:|---:|---:|
| 1 | 256 | 10 | 2 | 88fF | 120fF |
| 4 | 64 | 40 | 8 | 22fF | 30fF |
| 8 | 32 | 80 | 16 | 11fF | 15fF |
| 16 | 16 | 160 | 32 | 5.5fF | 7.5fF |

These are installed magnitude capacitor counts, excluding holders and converter
capacitors. SRAM, signs, selectors, reference switches, clock buffers and routing
remain. Sharing does not divide their entire area by S. A first initiation-time
expression without overlap is S(10t_plane+t_ADC+t_program+t_reset). Real scheduling
must establish which phases overlap. Ping-pong holders require extra state and
cannot be credited with a complete ADC pipeline that has not been built.

There is also a new radix problem: programming different weights changes the
measured C(code), so a holder matched to one phase is generally unmatched in the
next. This architecture needs paid programmable holder matching, a sufficiently
accurate regulated charge integrator, or an explicitly verified varying-radix
reconstruction. The current coefficient screen grants ideal normalization and
does not establish any of these implementations.

## A calibration that can legally precede the sum

During dedicated calibration, isolate one physical site and one capacitor bit
and measure its response through the column receiver. Eight measured bit
coefficients per site describe the two four-bit fixtures. The low bank's unused
upper bit can be omitted in a separately validated three-bit implementation.
Calibration access, isolation loading, ADC normalization and measurement noise
need physical validation; knowing a simulator's capacitor value is not such a
measurement.

For each stored integer q, choose between the two legal exact representations
q=L+8H, |L|≤7 and |H|≤15. Predict each representation's error using those measured
physical bit coefficients, then store the preferred code. This corrects the
programming before the analog sum. It uses no per-weight physical-error oracle
at inference and applies no illegal gain division after mixed-site sums. One
extra choice bit per W8 weight is charged when the original weight plus choice
is retained; a direct encoded-memory implementation requires its own bit count.
The offline programmer needs eight calibration coefficients per physical site,
or 2048/S coefficients per logical column. They need not all remain on-chip
after programming, but obtaining and retaining the programming result is not
free. Two-polarity measurement with m repeats costs at least 16m conversions
per site, before reference calibration and state restore.

The [screen](../../../../../scripts/compiler/metrics/imc_shared_cap_calibration.py) samples a
256×256 matrix from the exact 106M-weight histogram. Physical bit errors and
measurement errors are fixed and reused across all S weights, both candidate
codes, and repeated MVMs. This is not the actual layer ordering or a full-model
quality evaluation. At 0.5% relative capacitor-measurement RMS error:

| S | Die1 uncalibrated → programmed coefficient RMS | Die2 uncalibrated → programmed coefficient RMS |
|---:|---:|---:|
| 1 | .26033 → .22243 | .26115 → .22358 |
| 4 | .26140 → .22401 | .25932 → .22245 |
| 8 | .26247 → .22485 | .25924 → .22179 |
| 16 | .26364 → .22553 | .25910 → .22159 |

The approximately 14–15% reduction agrees with the earlier independent-site
redundant programming result. Sharing saves calibration parameter count but
does not itself reduce coefficient RMS. Around 30% of codes change and active
capacitance rises. A noiseless calibration is also retained as an optimistic
bound. No calibration accuracy, PVT margin, yield or inference-quality pass is
claimed. [Complete fixed-die results](../../../../../build/campaign/shared_cap_calibration/result.json).

For common site gain error e_g, the output error is
δy=Σ_g e_g Σ_{i∈g}x_iw_i. Independent site gains give
Var(δy)=σ_e²Σ_g(Σ_{i∈g}x_iw_i)², not σ_e²Σ_i(x_iw_i)².
Aligned equal contributions increase variance by S; balanced signed
contributions within a site can cancel it. Both counterexamples are checked.
Actual workload correlations and mapping therefore matter.

## More conversions can reduce read noise while increasing quantization error

Consider equal phases with C_phase=C0/S+Cf, fixed native charge quantum ΔQ,
the same activation exponent, and independent reset/read samples. In the
reconstructed summed-charge domain:

- Thermal variance is kT(C0+S Cf).
- Read variance is σ_v²(C0²/S+2C0Cf+S Cf²).
- Independent uniform quantization variance is S ΔQ²/12.

The last relation is a statistical approximation; deterministic quantization
errors can correlate and the worst-case absolute sum bound grows as S ΔQ/2.
With no fixed floor, thermal error is unchanged, read error falls with S, and
quantization error grows. For C0=3000fF and Cf=120fF, variance relative to S1 is:

| S | Thermal | Read | Independent uniform quantization |
|---:|---:|---:|---:|
| 1 | 1 | 1 | 1 |
| 4 | 1.1154 | .3110 | 4 |
| 8 | 1.2692 | .2014 | 8 |
| 16 | 1.5769 | .1554 | 16 |

This is a useful tradeoff, not an unconditional precision gain. ADC padding,
range selection, input-dependent active capacitance and holder-radix errors
must enter a full implementation. [Arithmetic and count audit](../../../../../build/campaign/shared_cap_calibration/counts_and_noise_audit.json).
The initial count file uses nine planes, corresponding to A10; the matched A11 schedule above needs ten magnitude planes. [A11 count correction](../../../../../build/campaign/shared_cap_calibration/a11_count_audit.json).
That audit also corrects a naming error in the first result file: its
`conservative_matched_holder_fF_per_weight` field is an ideal 22-unit count plus
column floors, not a conservative physical bound. The audit uses measured
unsigned code7+code15 loading instead, still excluding sign and extracted wiring.

## Why isolated per-site gain correction is more expensive

An alternative is to retain every site's partial sum, digitize it separately,
divide by one calibrated gain, then merge digitally. One equal arithmetic cap
can process S weights serially, but multibit weights require bit-plane results
or another validated multiplication mechanism. With eight weight planes,
separate site observation costs 8N/S conversions per output column, plus the
site accumulators and ADC multiplexing. A switched-capacitor integrator that
holds S worst-case same-sign packets at equal input/output swing requires
H≥S Cu. Thus holder capacitance per stored weight does not shrink with S.
Its OTA, reset and packet-transfer noise are additional costs. A passive
accumulator instead has exponentially weighted history and cannot silently be
treated as an equal-weight sum. This alternative remains a paid analytical
bound, not a recommended physical design.

PICO-RAM is the stronger existing architectural baseline: it reuses local
capacitors across DAC, MAC, analog shift/add and ADC functions, and explicitly
analyzes the conversion/precision cost of weight-bit-serial and fully bit-serial
operation. Its measured 65nm macro does not validate our sky130 schedule or W8
quality. [Author manuscript](https://arxiv.org/html/2407.12829v1).
The repository's prior redundant-cap calibration and current carry-selection
experiments already establish related programming mechanisms. No new topology
or calibration principle is claimed here.

## Paired larger-capacitor control

The [Cu8 runner](../../../../../scripts/compiler/metrics/imc_cu8_mismatch_control.py) retains
signed8 A11 separate and byte-identical Cu4 ADC bit/span selections. It uses
the same physical Gaussian draws with the larger-capacitor PDK mismatch law,
the actual Cu8 unsigned AC loading, stationary kT/C, and 20µV read noise.
Both fixed dies and both existing passages are frozen before evaluation.
ADC charge quantum and installed capacitance scale with Cu; additional settling
time is required because the Cu8 fixture fails the 8ns dynamic charge gate.
This control cannot be called a hardware pass even if its quality passes.

Both six-case Cu8 runs completed with unchanged source fingerprints. **VERIFIED initial two-seed result, rejected as a robust candidate by the extension below:** all four kT/C +20µV +fixed-mismatch cases pass on each die. Each die still fails one mismatch-only diagnostic, so no six-case blanket pass is claimed. The stochastic quality response is not monotonic in added noise; the noiseless diagnostic and physical noisy cases are reported separately.

| Die | Cu | Case type | Passes | Worst KL | Worst PPL ratio |
|---:|---:|---|---:|---:|---:|
| 1 | 4fF | fixed_mismatch_only | 1/2 | 0.0068419 | 1.0144365 |
| 1 | 4fF | fixed_mismatch_read20 | 1/4 | 0.0109800 | 1.0120066 |
| 1 | 8fF | fixed_mismatch_only | 1/2 | 0.0058187 | 1.0132460 |
| 1 | 8fF | fixed_mismatch_read20 | 4/4 | 0.0074476 | 1.0089168 |
| 2 | 4fF | fixed_mismatch_only | 1/2 | 0.0068110 | 1.0137057 |
| 2 | 4fF | fixed_mismatch_read20 | 1/4 | 0.0107547 | 1.0102923 |
| 2 | 8fF | fixed_mismatch_only | 1/2 | 0.0058114 | 1.0121398 |
| 2 | 8fF | fixed_mismatch_read20 | 4/4 | 0.0075913 | 1.0081706 |

The active connected capacitance, installed-cap cost and conversion counts are retained in the [paired summary](../../../../../build/campaign/cu8_mismatch_control/summary.json). This is a paid brute-force sizing control; its initial two-seed improvement must be considered together with the later eight-seed failures. Sharing should be compared with matched complete controls rather than a selected favorable subset. Two dies and two exposed passages are not a yield or unseen-workload qualification.

## Frozen capacitance and noise-seed extension

The follow-up protocol tests Cu6 with the same two noise seeds and mismatch-only diagnostics, and Cu8 with declared seeds60001–60008 on both existing passages and fixed dies. Cu6 uses an explicit midpoint interpolation of measured Cu4/Cu8 code-dependent loading. The Cu8 endpoint differs from Cu4+4·code by less than1.01e−8fF at1kHz, supporting that interpolation for this AC fixture only. Dynamic Cu6 timing remains unverified. All ADC settings and physical standard-normal draws are held fixed. [Runner](../../../../../scripts/compiler/metrics/imc_capacitance_robustness.py).

The exact weight-histogram numerator-error RMS is .26021/.20909/.17936 weight units at Cu4/6/8. Without column-floor and ADC padding, the weighted thermal-variance ratios are1/.56337/.38380; a dense-column mean-loading approximation gives read-variance ratios1/.71447/.58969. Larger Cu also amortizes switch loading, so the fixed-voltage read error is not Cu-independent in this physical loading model. [Static scaling details](../../../../../build/campaign/capacitance_robustness/static_scaling.json).

Eight noise seeds improve the falsification test but cannot establish rare-failure reliability. Even zero failures in eight independent draws for one fixed die/passage permits a one-sided95% binomial upper failure probability of1−.05^(1/8)=31.2%. Outcomes across passages and fixed dies are not silently pooled into an identically distributed silicon-yield sample. The unchanged ideal quantization control already has PPL ratio1.008374 on the first passage, leaving limited margin to the1.01 gate before additional analog errors.

The earlier CAP-RAM is an especially direct storage-sharing baseline: eight6T SRAM cells share one MAC circuit. Its silicon calibration fits per-slice gain/offset and then optionally a shared nonlinear correction curve. That corrects observable slice transfer behavior; it does not establish arbitrary per-weight mismatch removal. Its reported peak throughput is for4-bit inputs with binary/ternary weights, and its CIFAR-10 experiment uses quantization-aware training. Those precisions and workload adaptations must remain explicit in comparisons with this unmodified W8 transformer. [Author paper, Sections IV-A and IV-C](https://arxiv.org/pdf/2107.02388).

The Cu6 midpoint runs completed with unchanged sources. Die1 passes3/4 noisy cases and die2 passes4/4; each passes1/2 mismatch-only diagnostics. Cu6 therefore fails the original two-die physical-noise gate. Active connected C is10.79496µF versus13.33161µF for Cu8, with unchanged ADC settings. [Cu6 result summary](../../../../../build/campaign/capacitance_robustness/Cu6/summary.json). The expanded Cu8 run has already produced additional-seed failures; the original two-seed Cu8 result is not a robustness qualification. Final eight-seed statistics remain pending.

## Completed Cu8 eight-seed robustness and ideal-ADC ceiling

**FAILED broader frozen acceptance.** All32 cases completed and source hashes pass. All eight overlaps with the original Cu8 campaign exactly reproduce every field except runtime. The first passage fails many newly declared noise seeds; the initial two-seed pass cannot support a robust sizing choice.

| Die | Passage | Passes | Worst KL | Mean PPL ratio | Sample SD | Worst PPL ratio |
|---:|---|---:|---:|---:|---:|---:|
| 1 | Floating-Point Exception Handling.md | 3/8 | 0.0074476 | 1.0110154 | 0.0038192 | 1.0173972 |
| 1 | Dual-Clock Asynchronous FIFO.md | 8/8 | 0.0072089 | 0.9971938 | 0.0021572 | 0.9996519 |
| 2 | Floating-Point Exception Handling.md | 4/8 | 0.0072934 | 1.0105496 | 0.0035476 | 1.0171362 |
| 2 | Dual-Clock Asynchronous FIFO.md | 8/8 | 0.0075913 | 1.0013516 | 0.0020788 | 1.0044116 |

[Complete robustness summary](../../../../../build/campaign/capacitance_robustness/Cu8/summary.json). No minimal robust Cu follows from these tested points.

The exact-ADC diagnostic retains W8 and common A11 but removes all ADC rounding/clipping, mismatch, thermal/read noise and hardware loading. It gives KL.00478016/PPL1.00756344 on passage1 and KL.00473169/PPL.99620885 on passage2. Finite clean ADC values are .00486290/1.00837435 and .00494363/.99755070. Thus the clean ADC penalty is small compared with the combined weight/input quantization floor, and the critical passage retains little hardware margin even with mathematically exact readout. This diagnostic claims no implementable converter or PPA. [Frozen diagnostic](../../../../../build/campaign/ideal_adc_ceiling/result.json).

The paid extra-ADC-bit control also completed. The actual engine defines charge quantum by span, so +1bit alone would only increase range; this experiment uses +1bit and span/2 to halve quantum at unchanged range. All source hashes pass. **FAILED robust acceptance:** die1 and die2 still fail multiple first-passage noise seeds. [Full result and paid costs](../../../../../build/campaign/extra_adc_precision/summary.json). More ADC precision does not remove the dominant W8 recompilation floor.
