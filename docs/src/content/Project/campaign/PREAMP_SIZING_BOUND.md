# Integrating preamp: noise, headroom and gm/ID sizing bound

Status: **VERIFIED conditional analytical identities**, supported by archived
stationary PDK characterization; **SPECULATIVE** new implementation. The
purpose is to prevent repeating the earlier small, fast preamp failure.

## Conventions and factor of two

Consider a matched NMOS pair. Each device carries I and has transconductance
gm; the differential input is applied as ±vid/2. The differential signal
current is gm·vid. Assume independent device white noise with one-sided PSD
4kTγgm per branch, constant gm and γ, ideal integration for T, and fixed equal
output capacitors C. The differential noise PSD is 8kTγgm. Since the squared
boxcar integrates to T/2 over positive frequencies,

    σin² = 4kTγ/(gm T)
    A = gm T/C
    Ecore = 2 I T VDD = 2 VDD gm T / (gm/I)

The factor two in energy is necessary: gm/I above is the efficiency of one
input transistor, while supply current feeds both branches. A claimed
2.5 pJ for gmT≈28 pF, VDD1.8 V and device gm/I20/V omits one branch.
At300 K and γ2/3, achieving20 µV input RMS requires gmT27.61 pF and
**4.97 pJ core energy**, before bias reference, reset, clocks and regeneration.

For time-varying gm and independent white channel noise, the exact ideal
integrator expression is

    σin² = 4kT ∫γ(t)gm(t)dt / [∫gm(t)dt]².

This remains conditional on fixed output capacitance, no output conductance,
no tail-noise conversion and no input loading/correlation. Actual finite-gds
weighting must be included when the integrator leaks.

Independent output-reset noise adds differential variance2kT/C, giving
input-referred variance2kT/[A·gmT]. Comparator noise adds σcmp²/A² under an
independent-noise approximation. Correlated reset/cancellation cannot be
assumed without the physical switching schedule.

## Native PDK evidence invalidates the optimistic gamma

The archived `imc_dynamic_preamp_dc_tt_27_1p35_0p3_4p0_550p0.json`
operating point has W1.35 µm/L0.3 µm, I2.13051 µA, gm39.2772 µS,
actual gm/I18.4356/V, source voltage0.18517 V and input-port capacitance
1.85835 fF. SS85 has I2.93292 µA, gm43.8568 µS and efficiency14.9533/V.
These actual body/drain biases supersede a table lookup at grounded source.

The companion stationary-noise fixture, with ideal conductance loads used
only as characterization instruments, reports effective γ from
`Svin·gm/(8kT)`:

| Frequency | TT27 effective γ | SS85 effective γ |
|---:|---:|---:|
| 1 MHz | 13.9791 | 13.9743 |
| 100 MHz | 1.85148 | 2.13015 |
| 1 GHz | 1.59666 | 1.88153 |

The low-frequency rise cannot be discarded when lengthening integration.
Even freezing the TT1GHz value as an optimistic white floor gives gmT≈66 pF
and about12.9 pJ core energy for20 µV, before all other noise and overhead.
These stationary figures are diagnostics, not a dynamic-noise qualification.

## Headroom and candidate sizing

With precharged drains and equal branch currents, common-mode fall is
ΔVCM=IT/C=A/(gm/I). Thus gain is bounded by permitted common-mode travel,
not increased freely by choosing a smaller output capacitor. At efficiency20/V
and allowed fall0.6 V, A≤12. At A12 the329 µV comparator contributes27.4 µV
input RMS before the preamp's own noise. The system's20 µV final-code noise
assumption therefore needs a quantitatively justified SAR-noise mapping or
more gain; it is not a20 µV comparator specification.

A17 at the archived TT efficiency requires0.922 V common-mode fall:
precharge1.8 V ends near0.878 V. Fine residuals may fit, while large coarse
inputs can drive one branch into triode before integration completes.
Correct sign under overload and recovery from the preceding decision must
be verified, with full-range stimulus and a real retained native input.

Scaling the old TT pair and its complete tail/bias path by8.79 would suggest
Winput≈11.86 µm, T80 ns, gm≈345 µS and gmT≈27.6 pF. It is only a starting
coordinate: body effect, drain motion, finite tail compliance and geometry
must be re-characterized. A17 would require C≈1.62 pF per drain, plus device
and routing capacitance. The previous noise evidence rules out labeling
this starting coordinate20 µV. Scaling width alone also increases gate and
Miller loading on the1.3–3.4 pF native holders.

The next useful screen is actual-bias gm/I and stationary PSD across
L0.3/0.5/1 µm at efficiencies around20–25/V, with native source/body voltages,
output0.85–1.8 V, and a paid tail/reference circuit. Then integrate the PSD
with the actual sensitivity kernel, preserving the low-frequency cutoff
and any autozero assumptions. Choose a candidate only after noise, area,
reset time and complete energy beat the measured passive-stack alternative.
A final transient must include loaded kickback, common-mode discharge,
overload recovery, output reset noise, mismatch and PVT. No new low-noise
preamp has yet been demonstrated.

## Completed actual-body-bias input-pair screen

`analog/testbenches/tb_imc_preamp_gmid_screen.py` now characterizes each
L0.3/0.5/1 µm with input gates fixed0.9 V and drain voltages0.85/1.2/1.6 V.
A source-voltage sweep solves actual device gm/I20 or25/V; the resulting
source/body voltage is retained in each noise fixture. W is10 µm, with
explicit0.29 µm diffusion. TT27 completes18 points. SS85 completes9 points:
all nine requested25/V coordinates are outside the reachable efficiency
range and are recorded as unreachable, not silently clamped to a table edge.
This does not prove the same geometry fails at SS with a different efficiency.

Outputs are `build/sim/imc_preamp_gmid_screen_tt_27_v2.json` and the matching
`ss_85_v2.json`. Full1 Hz–1 GHz stationary spectra and source sweeps are
preserved. Ideal source clamps exclude tail/reference noise. No physical
noise cancellation or lower-frequency rejection is assumed.

The first analysis exposed a useful error in applying a familiar noise
formula: at η25/L1, apparent input-referred γ falls to0.011 at1 GHz, but fT
is only32 MHz. Capacitive feedthrough increases the AC signal gain used by
SPICE's input-noise referral. That tiny ratio is not a channel-noise benefit.
The v2 analysis retains it as a diagnostic, adds AC-gain/DC-gm and fT/10
validity flags, and computes current-noise γ from the voltage PSD across
the noiseless1 S output loads. Their finite-gds correction is negligible
for these devices but the load remains a characterization instrument.
Boxcar projections use output-current PSD/DC-gm², not the misleading
high-frequency input-gain normalization. Original v1 evidence is preserved.

At TT27 and drain1.2 V:

| L µm | η /V | Actual VSB V | fT proxy MHz | Input C fF at W10 | Effective current-noise γ at10 MHz |
|---:|---:|---:|---:|---:|---:|
| .3 | 20 | .19551 | 4065 | 19.23 | 3.533 |
| .3 | 25 | .30847 | 281.3 | 16.13 | 1.440 |
| .5 | 20 | .21851 | 1351.9 | 28.42 | 2.407 |
| .5 | 25 | .32934 | 104.1 | 22.97 | 1.351 |
| 1 | 20 | .23674 | 351.2 | 52.76 | 2.042 |
| 1 | 25 | .33856 | 32.33 | 43.32 | 1.396 |

The η25/L1 point is already outside fT/10 at10 MHz; it is not a fast-stage
recommendation. High efficiency reduces current density much more than
input capacitance per width. Choosing η alone therefore misses the area and
loading cost.

For a conditional first sizing comparison, assume current/gm/capacitance
scale with width s and the stationary input-referred PSD scales1/s at fixed
bias. Then required s=(σW10/20µV)². The following **unverified scaling
projections** target20 µV preamp RMS at80 ns, exclude comparator/reset/tail
noise, and integrate the explicit1 Hz–1 GHz band:

| L / η | Required width µm | Pair core energy pJ | Input-port C fF |
|---|---:|---:|---:|
| .3 /20 | 239 | 125.7 | 460 |
| .3 /25 | 582 | 13.27 | 939 |
| .5 /20 | 200 | 57.60 | 570 |
| .5 /25 | 743 | 10.09 | 1705 |
| 1 /20 | 177 | 26.95 | 935 |
| 1 /25 | 1013 | 9.10 | 4387 |

For comparison only, discarding all noise below2 MHz lowers the projected
L.3/η25 point to W277 µm,6.31 pJ and447 fF input loading. There is currently
no physical filter/autozero schedule justifying that cutoff. Conversely,
using a1 Hz stationary floor is not a prediction of independently renewed
noise every SAR decision: slow noise will correlate with calibration and
across decisions. Both distinctions must remain explicit.

These projections make a simple low-noise integrating pair less attractive
than the initial1–3 pJ estimate. On a1.3–3.4 pF native holder, hundreds of fF
to several pF of input capacitance changes the compute radix, kickback and
noise. The next architecture needs a physically verified cancellation,
calibration or gain mechanism; a larger copy of the failed preamp is not
an established improvement.
