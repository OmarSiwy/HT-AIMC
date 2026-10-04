# Candidate population and falsification ledger

Initial checkpoint: 2026-09-10 23:55 UTC. See the later corrections below.
This is an evolving research population,
not a claim that a complete architecture has met the campaign objective.
An individual PASS applies only to the stated fixture and acceptance gate.

## Latest population update — 2026-09-11 15:54 UTC

- **Retain direct signed-bank routing, qualify parasitics:** four-bit direct
  three-way bottom selection passes independent timestep controls at SS85;
  the shared sign mux fails settling. The isolated MIM BOTTOM-column
  projection passes at 1 ps, TOP-column fails. Both finer controls are active.
  A diagnostic two-point gain/offset fit worsens remaining-stimulus residual
  to 0.1423% FS, so scalar calibration is not an established repair.
- **Retain bounded physical SAR, challenge thresholds/history:** all four
  fresh seven-bit conversions pass physical decision replay and frozen-code
  checks. Including warmups costs 7.76–7.79 pJ / 1080 ns. Boundary probes are
  active; no continuous 360-ns initiation interval or noise pass is established.
- **Reopen long-channel sizing after flicker analysis:** L0.30 with 3-pF
  reservoir gives conditional 52.33-µV receiver noise including old latch
  proxy, still missing 50 µV. Extra reservoir costs 31.2% event energy versus
  2 pF. The earlier white-only estimate below omits material flicker noise.
- **Reject robust group128 and group64 claims:** group128 physical-noise
  cases fail KL; group64 has perplexity failures across seeds despite KL
  passes. Grounded original-group32 tests are live with explicitly ideal
  unsigned topology and provisional receiver budget.
- **Preserve architecture alternatives:** fixed-DAC early SAR termination
  may reduce decision service without raising Vref. Weighted polarity
  modulation across digitally accumulated groups may suppress correlated
  additive receiver error. Both are known underlying techniques requiring
  costed IMC integration, not novelty claims or verified improvements.

No complete candidate meets all matched objectives. Historical updates follow.

## Population update — 2026-09-11 14:57 UTC

- **Retain sizing mechanism, reject tiny-switch generalization:** original
  five-amplitude W0.48/W0.50 SS85 controls pass, but fresh amplitudes falsify
  W0.50 with0.25254%-FS error. W0.70 passes fresh inputs and independent
  timestep agreement at0.01897%. Measured N/P port admittances select an
  asymmetric0.50/0.70 pair: initialfresh0.02864%PASS, lower width and loading;
  full-scale, finer-step and TT controls pending.
- **Retain original-group compiler alternatives:** raw32, group64 and group128
  ideal-readout controls greatly reduce requantization error. Group128 requires
  only1.733x previous partial conversions, but its first physical2kT/C+50µV
  cases FAIL KL and reused-site mismatch alone fails onecase. Raw32 initial
  physical cases pass a single-holder/noiseless-reference model only. Full
  cohorts and more practical noise/reference configurations remain active.
- **Reject free fixed-holder reuse:** actualcode-dependent capacitances cause
  large inter-phase sharing-radix distortion when a fixed maximum holder is
  used. Current quality models assume ideal matchedradix and numerator-only
  mismatch; actual padding/reconfiguration or another transfer mechanism is
  required. Grounded constant-total22-unit banks are a costed alternative,
  with larger charge-noise and capacitor costs.
- **Retain direct FIA plus isolated split DAC as a candidate:** direct N1
  wide-residue transfer is stronger than N4 at±10mV. Physical output isolation
  changes gain and requires calibration at the final read phase. The new
  split4+3 network has correct250fF nominal effective output load and passes
  fresh deterministic endpoint checks after frozenfinalphase calibration;
  actual coarse/fine radix is8.12853, not8. CompleteSAR still unqualified.
- **Reject noiseless reference substitution:** removing the second sampled
  holder exposes about−4.44mV acquisitionkick previously common-mode-cancelled.
  This is an interface failure, not proofsingle-ended FIA is impossible.
  Coupled floating-input LTV reproduces gain within0.79%; conditional FIA
  white noise40.28µV pluslatch gives~45.8µV beforeotherreceiverterms.
- **Retain extracted-unit evidence with limits:**1260/1580/1840nm contact
  coupons passDRC/matrix audits; smallunitbottomparasitics are5–7%, far above
  largecoupon1% assumptions. Banklinearprojection tests now include these;
  fullarrayPEX, distributedresistance and capacitorcorners remain unverified.

No complete candidate has passed matched quality/area/delay/power objectives.
Earlier entries below are historical, including their then-pending statuses.

## Population update — 2026-09-11 13:35 UTC

This update supersedes pending statuses and preliminary claims below;
historical entries remain available for provenance.

- **Retain conditionally:** balanced-digit dense sizing passes the frozen
  physical charge allocation at 48.423 fJ/low-slice-MAC and 477 ns. Original
  digits at matched small widths fail both physical/raw gates. Neither is
  a complete programmable W8/ADC measurement.
- **Retain retention mechanism, reject full-range accuracy claim:** OFF-replica
  native pipeline passes moderate random products and TT/SS retention. Both
  it and matched serial fail extreme arithmetic. Independently measured
  static C(V) correction worsens the error. Complete-cycle charge injection
  is the next physical target.
- **Reject claimed comparator sizing win:** fresh 256-seed/input cohorts
  give 403/396/387-µV noise for baseline/Ci4/Ci16; paired confidence intervals
  do not demonstrate improvement. Capacitance adds energy and delay.
- **Retain physical programmable-bank control only:** the unsigned clamped
  bank passes its charge gate and independent timestep check at TT. Measured
  inactive loading is substantial. Nominal system representation controls
  pass some settings; PDK fixed mismatch defeats robust two-die qualification
  so far. Offset and rank-one correction are separately costed experiments.
- **New readout branch:** a physically switched floating-inverter amplifier
  resolves deterministic signs but exposes acquisition, input attenuation,
  gain compression and reset errors. Actual gm/ID and both branch currents
  are measured. Noise and complete ADC operation are not qualified.
- **New area evidence:** eight Substrate2 MIM coupons pass full DRC and
  terminal-matrix electrical audits. Contact-only top metal reduces extracted
  top loading; bottom loading remains material, especially for small units.
  These are isolated coupons, not complete macro area/PEX.
- **Corrected noise model:** complete reset/share noise is stationary kT/C.
  Native/hybrid switch models' approximately .83 Nyquist ratio is a compact
  model limitation verified against a resistor oracle, not a physical benefit.

See [session comparison](SESSION_COMPARISON.md) for initial-versus-current
numbers and [FIA characterization](FIA_CHARACTERIZATION.md) for the new branch.

## Engineering objective

Minimize complete-system energy per useful W8 activation MAC, resident-weight
area, initiation interval and first-result latency subject to measured model
quality. Retain the joint development gates KL ≤ 0.01 and perplexity ratio
≤ 1.01 on each declared passage/seed; do not replace them with a favorable
average. Keep converter, row-drive, reference, reset, memory, calibration,
digital accumulation and data movement boundaries explicit. Report both
native operations and normalized TOPS conventions for competitors.

The user prioritizes appropriate gm/ID sizing and product error/delay. Use
actual device bias for gm/ID, current density and capacitance. For pass
switches, additionally use actual triode conductance: saturation gm/ID alone
does not determine settling. No positive circuit result below includes PEX,
full transient noise, a complete weight-memory implementation or chip power.

## Population

| Mechanism | Quantitative finding | Present status | Next falsifier |
|---|---|---|---|
| Normal-number native radix charge core | Fresh legacy sparse 128×8 TT/SS: 0.04277/0.10333 MAC RMS; 4.49981/4.58724 fJ/MAC at ideal ports; 366-ns mean before ADC | VERIFIED deterministic baseline in its original scope | Dense W8, explicit junction geometry, real connected conversion |
| Fixed-charge SAR on the native holder | Fixed 3.75-fF DAC unit plus parallel holder capacitance removes column-capacitance dependence from ideal charge LSB; real 1.68-µm bottom switches retain local core RMS 0.0253/0.0689 MAC TT/SS without comparator | STRONGLY SUPPORTED loading mechanism; full converter unresolved | Real decision loop, calibration, comparator kickback, noise, range |
| Charge pooling with common activation scale | Common A10 supports ideal pooled reduction on two development passages; threefold fewer final conversions including padding | STRONGLY SUPPORTED format mechanism | Noise, tails, physical pooling and resource scheduling |
| Rare range extension | At unchanged charge quantum, removing only clipping changes pooled Exception KL 0.025716→0.005006; FIFO 0.025501→0.004998 | VERIFIED diagnostic model; finite circuit SPECULATIVE | Bounded coarse correction with paid capacitance/noise and per-MVM stall counts |
| Balanced comparator receivers plus matched floating reference | Standalone 24 fresh nonzero decisions including ±25 µV pass TT/SS; 131.6/134.9 fJ/trial; 1% reference mismatch produces ~39.7-µV differential kick | STRONGLY SUPPORTED deterministic cancellation | Actual SAR history, large input swing, junctions, transient noise/mismatch |
| Dynamic differential preamplifier | Warm-tail/100-fF decoupling raises gain but disturbs held input; BSIM noise estimate ~410/461 µV for 4-ns box window | FAILED proposed 100-µV noise/power target | Preserve actual-bias gm/ID and correlated-kickback lessons |
| Native capacitor parallel-to-series boost | Full-geometry 6.98-pF N4 fixture after acquisition repair: gain 3.7807, calibrated 0.185-µV RMS/0.315-µV max, ~383 fJ/full cycle | STRONGLY SUPPORTED standalone deterministic mechanism | SS, comparator load, noise, integration and fixed-charge DAC compatibility |
| Source-modulated 2T1C current weight cell | Shared one-dimensional row map reduces nonseparability; fixed endpoint tests fail combined product-error budget even where random samples pass | FAILED current domain-wide accuracy gate | Wide-range current-fed row; converged programming, actual noise, retention |
| Replica MOSCAP storage | Small-signal capacitance covariance flattens source feedthrough; full transients abort and one-finger diffusion area erases a presumed area advantage | SPECULATIVE partial mechanism | Numerically complete physical programming and folded layout cost |
| Restricted log/charge/exp multiplication | Narrow positive mantissas pass <1% deterministic error with 600-fF state, 1.5-µs full word, ~2.77 pJ | VERIFIED restricted scalar; not an IMC winner | Wide-range signed mapping, array-scale noise/area/service |
| Two-bank analog pipeline | Prior fixture reduces initiation interval 395→295 ns but leaves first latency 395 ns and fails 1-mV analog accuracy | FAILED original handoff gate | Reuse native state or cancellation without copying attenuation |
| Current-fed row normalization | KCL can implement normalized weight currents without a voltage log-input driver | SPECULATIVE | Finite source/headroom, full 1/511…1 range, source noise and normalization cost |

## Preserved cross-branch insights

1. **Fixed charge quantum and variable native capacitance can coexist.**
   A fixed split-CDAC unit plus parallel capacitance gives
   `ΔQ = u ΔV / 16`, while its comparator voltage quantum is `ΔQ / CA`.
   This removes a gain-normalization problem, but larger CA still magnifies
   comparator voltage noise when referred to charge. Native compute matching
   must include every physically connected load.
2. **Rare events can dominate model quality.** About 22 ppm clipped pooled
   conversions on one passage produce a large KL penalty. Count boundary
   events by tile/MVM and worst correction depth; a shared resource may stall
   many ordinary columns behind one exceptional column.
3. **Symmetric loading is cheaper than extra gain in one tested comparator.**
   Equal output receiver loads and matched floating input holders suppress
   deterministic differential kick. A low-noise preamp is not automatically
   an energy improvement; actual BSIM noise exceeded an ideal γ=2/3 estimate.
4. **Passive voltage gain preserves the native thermal-noise burden.**
   For N equal parallel-acquired sections, `Cout=CA/N²` and unloaded gain N.
   With load CL, `G=N/(1+CL N²/CA)`. The maximum ideal gain is
   `0.5 sqrt(CA/CL)`. Quantizer charge scaling and reference switching must be
   rederived after stacking; a voltage gain is not a free precision gain.
5. **Current sharing does not remove all device noise.** Under an ideal fixed
   row current, the covariance is proportional to
   `diag(I)−I Iᵀ/ΣI`; noise cancels only in the conserved total. A matching
   noisy row source restores the independent-current covariance. Do not infer
   universal SNR improvement from correlated column noise.
6. **A programming error and a multiplication error are different.** Timestep
   refinement in the source-cell branch moves absolute programmed current more
   than within-weight normalized transfer. Preserve both metrics; neither
   substitutes for complete physical product accuracy.

## Evidence links

- [Whole circuit archive](CIRCUIT_EVIDENCE.md)
- [Workload and system archive](SYSTEM_EVIDENCE.md)
- [Measured prior-art comparison](SOTA_EVIDENCE.md)
- [Scale alignment experiments](SCALE_ALIGNMENT.md)
- [Native core and converter loading](CONNECTED_CHARGE_CORE.md)
- [Comparator and preamplifier branch](DYNAMIC_PREAMP.md)
- [Compact current-cell branch](COMPACT_WEIGHT_CELLS.md)

Novelty remains unresolved for all surviving combinations. Generic capacitor
reuse, series stacking, mixed logarithmic/linear formats, analog pipelining,
current splitting and coarse/fine conversion have prior art. The campaign must
demonstrate a new, useful combined behavior and compare the strongest fair
baseline before making a narrower novelty claim.

## Later findings and corrections, 2026-09-11

- The user extended the campaign to48hours from01:32UTC and reaffirmed
  gm/ID sizing and minimal area/delay/power. The
  [optimization contract](OPTIMIZATION_TARGETS.md) now defines the fields,
  matched capacity/throughput boundaries and feasibility gates.
- Balanced radix16 and radix9 preserve exact W8 values but trade connected
  low/high capacitance, reconstructed noise and storage/decoder cost.
  [Dense low-slice sizing](DENSE_CORE.md) reaches48.423fJ/MAC at477ns within
  the provisional deterministic charge allocation, while failing the older
  raw-MAC gate. High-slice, matched original sizing and PVT results remain
  separate. Compiled active-C area is not programmable installed area.
- Finite Cu8 guard policies pass both exposed passages and every declared
  seed at20µV final Gaussian read noise;50µV fails. Optimizing separate ADC
  depths removes much of pooling's earlier area advantage. These are
  conditional model results, not actual comparator/ADC validation.
- **Noise correction:** the earlier system grids include sharing-only
  thermal noise. For a fresh, fully thermalized equal-C array reset followed
  by sharing, `Var(hnew)=Var(hold)/4+3kT/(4C)`, giving stationary`kT/C`.
  The sharing-only stationary value`2kT/(3C)` omits the array-reset term.
  Corrected model controls and physical switched-noise verification are
  required. No earlier conditional pass is relabeled as a physical pass.
- [Comparator noise](DECISION_NOISE.md) is hundreds ofµV at its input.
  Full-diffusion matched576-trace estimates are455.26µV default,328.85µV
  with4-fF internal caps and315.82µV with16-fF caps, with explicit intervals.
  Passive gain must include actual loading, fine-DAC significance and
  decision-dependent kickback; standalone gain is insufficient.
- Distributed ladder shunts impose an additional passive-gain penalty and
  can reduce the grounded fine-DAC transfer relative to native signal gain.
  This undermines an assumed universal co-gain cancellation. Guard coverage
  and capacitor-host margins must be recomputed after physical measurement.
- [Sequential latch tests](LATCH_CORRELATION.md) resolve modest correlation
  in one finite lower-flicker-cutoff control. K3 voting does not improve both
  polarities in the64-seed sample. Loaded N16 repeat reads separately exhibit
  large decision-dependent drift, despite correct deterministic signs.
- A native two-bank pipeline preserves old charge during real next-word
  computation in its first3-word test, but the extra off switch changes the
  arithmetic retention ratio. Full calibrated and retained-product tests
  remain pending. [Current/PWM experiments](UNIT_CURRENT_DIVIDER.md) retain
  an alternative mechanism, including sparse/PVT and complete-time failures.
- Programmable capacitor cells are now being tested physically. A bypassed
  disabled capacitor can preserve ideal active-C arithmetic, but its switches,
  junctions, SRAM control impedance, noise and all installed area must be paid.

The candidate population remains open. None of these points establishes a
complete-chip advantage over the strongest matched prior art.
