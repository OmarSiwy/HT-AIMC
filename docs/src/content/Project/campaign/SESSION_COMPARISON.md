# Initial session results versus current evidence

Checkpoint: 2026-09-11, approximately 13:35 UTC. Research continues.
**No complete architecture has demonstrated superiority to Mythic or SoTA.**

| Question | Beginning of campaign | Current evidence |
|---|---|---|
| Legacy sparse core | 128×8 fixture: TT RMS .04277 MAC, 366 ns, 4.49981 fJ/MAC; SS RMS .10333 | Remains a narrow deterministic reference, without ADC, programmable memory or PEX. Its low energy cannot be transferred to dense W8 loading. |
| Dense arithmetic sizing | Sparse results did not establish dense operation | Original dense low slice: 85.951 fJ/slice-MAC, 549 ns. Balanced digits plus smaller switches: 48.423 fJ, 477 ns, passing the provisional physical charge allocation but failing the older raw-MAC gate. Matched original digits at those smaller widths fail both gates. |
| Analog pipeline | Additional bank switching disturbed arithmetic | OFF-replica compensation achieves .0111-MAC RMS on small TT heldouts; TT/SS retention passes with corner calibration. Fresh extreme arithmetic fails: maximum 7.97 MAC versus matched serial 9.77. Moderate random history passes. No overlapped physical ADC or complete throughput measurement. |
| Comparator sizing | Earlier limited samples suggested substantial benefit from internal capacitance | Fresh 256-seed/input cohorts give baseline 403.43 µV, +4 fF 395.93 µV, +16 fF 386.80 µV. Independent paired confidence intervals include zero improvement; energy and delay increase. Earlier apparent benefit is not confirmed. |
| Reset/share noise | An optimistic 2kT/(3C) estimate appeared in system models | Correct complete reset/share recurrence gives stationary kT/C. Native switch model yields about .83× Nyquist near equilibrium; resistor control passes. This model deficit is not a physical noise advantage. |
| Programmable weights | Compiled ideal capacitances hid installed inactive components | Physical unsigned switched-bank product test passes a frozen .1%-FS gate with independent timestep control. Inactive loading materially worsens system precision and must be included; sign/SRAM/full-array operation remain unverified. |
| System quality | Ideal active geometry understated several costs | Fresh nominal loading-aware formats have some passing configurations. Actual PDK fixed-cap mismatch defeats robust two-die qualification so far; constant-offset calibration alone is insufficient. Rank-one correction is being tested, with its storage and compute cost counted. |
| Area | Active capacitance was an incomplete proxy | Resident binary banks, holders, SRAM and converter costs are now separated. Eight Substrate2 MIM coupons pass DRC and electrical matrix checks. Small capacitors incur much larger fractional bottom-plate loading. No placed complete macro area exists. |

The dense energy reduction is about **44%**, and its word latency reduction
about **13%**, relative to the stated dense baseline. It is not a comparison
against the initial sparse 4.5-fJ result or against Mythic. Low/high slices,
memory, ADC, reference generation and real drivers must be assembled before
a system energy or throughput claim.

The strongest partial findings are load-aware digit recoding and sizing,
physically compensated pipeline retention, and identification of previously
hidden loading/noise/mismatch costs. None is established as novel prior art.
Failed candidates and numerical failures remain in the experiment records.

Ongoing work tests signal-dependent switching error, a physical floating-inverter
readout, programmable representation under fixed mismatch, and modest calibrated
correction using the existing sidecar concept. The first FIA resolves eight
deterministic signs but exposes input acquisition error and has no noise pass.

Details: [dense core](DENSE_CORE.md), [pipeline](NATIVE_PIPELINE.md),
[independent pipeline audit](PIPELINE_INDEPENDENT_AUDIT.md),
[comparator noise](DECISION_NOISE.md), [capacitor layout](CAPACITOR_LAYOUT.md),
[storage sharing](STORAGE_SHARING.md), [reset noise](RESET_SHARE_NOISE.md).

## Continuation checkpoint — 2026-09-11 14:36 UTC

The original table remains a dated snapshot. Subsequent results sharpen its
limitations and identify a different architecture branch:

- **STRONGLY SUPPORTED, ideal readout only:** preserving the original Q8_0
  scales for each 32-weight group reduces first-passage perplexity ratio from
  1.007563 (existing smoothed column requantization) to 1.000644 (unsmoothed
  original groups with A11). Second passage is 0.999069. These are exposed
  diagnostic passages, not independent model validation. Hardware needs
  6,635,520 partial conversions/token, 6.4 times the prior organization, plus
  original group-scale storage and digital rescaling. Physical Cu4/read40-µV
  calibration is running; there is no hardware quality pass yet.
- **FAILED robust qualification:** the apparent Cu8 success on initial noise
  seeds does not survive eight-seed testing. Extra ADC precision also fails
  to repair the first passage reliably. Rank-one correction has no complete
  two-die quality winner.
- **VERIFIED within deterministic fixture:** direct N1 floating-inverter
  readout at a 6-pF native holder passes fresh ±5/±10-mV endpoint controls
  using frozen ±500-µV calibration; maximum native-referred error is 4.68 µV.
  This is neither a noise pass nor full-range INL. Raw32 native capacitances
  are smaller, about 0.48–1.78 pF, so new loading controls are required.
- **FAILED:** N4 stacking has actual coarse/fine radix 16.289955 rather than
  16, and ±10-mV errors reach 45.84 µV with a reset failure. Its gain does not
  establish a better ADC. Separate fine-gain fitting cannot prove no code gaps.
- **VERIFIED within clamped unsigned bank fixture:** Wn=Wp=0.50 µm passes
  the 0.1%-of-per-weight-full-scale charge gate at SS/85°C with 8-ns settling
  and an independent finer timestep. Worst bypass error is 0.05627%.
  W=0.46 fails marginally (0.10174%); W=0.48 passes at 1 ps (0.07470%) and
  its finer-timestep control is running. This brackets a local sizing choice,
  not a global optimum or full signed-array qualification.

Dense timing above uses A10 (nine magnitude planes); the system A11 model
uses ten. The sparse pipeline uses seven. Their frame times must not be
compared as equal-precision system throughput.

Continuation now tests original-group physical accuracy, a once-per-word
FIA residue readout with real output isolation, and gm/ID/admittance-informed
bank sizing. These are candidates undergoing falsification, not established
novel architectures. See FIA_CONNECTED_STACK.md and
PROGRAMMABLE_CAP_CHARACTERIZATION.md for immutable experiment paths.

## Continuation checkpoint — 2026-09-11 15:48 UTC

No complete Mythic or SoTA improvement is demonstrated. The matched dense
44% energy / 13% latency improvement above remains a component result;
the initial sparse 4.50 fJ/MAC reference excludes complete storage/readout.

- **VERIFIED, bounded deterministic circuit:** four fresh seven-bit fine-SAR
  conversions use actual transistor latch decisions, physical DAC states and
  complete causal replay. All 28 decisions reproduce. Reconstruction errors
  are −7.46, +5.74, +18.27 and −19.99 µV (RMS 14.33 µV over four points only).
  Active-frame positive ideal-port energy is 3.159–3.184 pJ, plus two paid
  warmups totaling 4.605 pJ. This is not a continuous ADC noise/INL pass.
  See [physical fine SAR](FIA_FINE_SAR.md).
- **VERIFIED, bounded clamped-bank fixture:** asymmetric Wn/Wp = 0.50/0.70 µm
  passes fresh unsigned SS/85°C charge tests with independent timesteps.
  Equal 0.50 µm sizing, which passed earlier stimuli, fails fresh amplitudes;
  the earlier checkpoint must not be read as broad qualification.
- **VERIFIED, bounded signed fixture:** direct three-way selection per bit
  passes the four-bit negative-polarity SS/85°C test at 1 and 0.5 ps. A shared
  sign mux fails. Actual isolated MIM-coupon projection changes the outcome:
  column connected to TOP gives 0.10744% worst error (FAIL), BOTTOM gives
  0.08530% (PASS at 1 ps), against a 0.1% gate. Independent finer coupon runs
  are active. The TT capacitor extraction with SS MOS is a projection,
  not capacitor-corner or complete-array PEX qualification.
- **STRONGLY SUPPORTED, conditional noise model:** L = 0.30 µm FIA with a
  3-pF reservoir estimates 36.09 µV white and 34.66 µV flicker noise.
  Including the earlier latch proxy gives 52.33 µV, still above the 50-µV
  target. Reservoir growth costs 31.2% event energy for about 5.9% reduction
  in that combined estimate. No full stochastic receiver pass is claimed.
- **FAILED robust system qualification:** all 16 group-128 physical-noise
  diagnostic cases fail KL; group-64 cases pass KL but some fail perplexity.
  Original group-32 scales improve ideal-readout fidelity but require 6.4×
  conversions versus the previous organization. Grounded group-32 quality
  is now running with two-holder thermal noise and a provisional 50-µV read
  budget; unsigned topology and ideal matched sharing remain assumptions.

Next tests challenge physical SAR decision boundaries and independently
check capacitor orientation. The current optimization frontier remains
conditional on precision, storage, noise, sign routing and conversion cost.
