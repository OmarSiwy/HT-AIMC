# Quiet virtual-column feasibility against the passive core

**STRONGLY SUPPORTED negative feasibility result for the existing OTA, not a
proof against all active architectures.** Reinstating the repository's legacy
telescopic virtual-ground integrator is physically meaningful, but it does not
currently offer a demonstrated area, delay, power or fullrange-error improvement.
No new OTA was designed in this round.

## What a quiet column actually changes

With feedback capacitor Cf, column shunt capacitance Ca and OTA gain A, an
injected charge Q obeys

(Ca+Cf) vx−Cf vo=Q,  vo=−A vx,

so vo=−(Q/Cf)/[1+(1+Ca/Cf)/A]. The column excursion is reduced, and the intended
charge resides on the feedback capacitor. Clamping the existing passive column
to VCM without preserving this feedback charge simply removes the computed
signal; it is not a drop-in linearity repair. The current seven-plane passive
binary recurrence must also be implemented physically in the active alternative.
A continuous unweighted integrator does not reproduce that recurrence.

Constant-voltage switching reduces signal-dependent switch charge only at the
nodes actually held quiet. Output sampling, feedback reset, finite OTA gain and
input-referred noise remain. Output-dependent A produces charge-transfer
curvature after one affine calibration. This is the established switched-
capacitor integrator principle, rather than a new architecture; Razavi's
[switched-capacitor integrator tutorial](https://seas.ucla.edu/brweb/papers/Journals/BRWinter17SwCap.pdf)
explicitly treats finite gain, noise, and settling design.

## Native characterization of the existing gm/ID-sized OTA

The frozen `analog/schematics/library/ota.py` and installed Sky130 sizing entries
were characterized atTT27 without resizing or bias adjustment. Native drawn
source/drain geometry uses the campaign's explicit0.29µm extension. Evidence is
`build/campaign/legacy_ota_audit_r1/result.json` with exact decks/logs, device
operating points and input-referred stationary noise spectra.

- Supply current8.17936µA; power14.72285µW at1.8V.
- Input devices: ID≈4.09µA, gm≈48.55µS, gm/ID≈11.87V⁻¹, L=.30µm.
- Tail: gm/ID17.48V⁻¹, but |VDS|−|VDSAT| is only14.84mV atVCM. The large
  saturation margin suggested by old comments is not present at this device.
- Output-dependent approximate open-loop gain from input gm divided by the
  native clamped-output DC conductance is216 at.55V,664 at.65V,1053 at.75V,
 1420 at.9V,1589 at1.05V,1558 at1.15V and1077 at1.25V. This diagnostic uses
  input-device gm; exact complete-loop transfer still needs measurement.

At Cf=Ca, beta=.5. A raw relative charge-gain error below0.25/14224≈17.6ppm
would require A beta>~56895, far beyond this amplifier. That requirement is a
sufficient uncalibrated gain-error condition, not necessary after calibration.
However, the measured several-fold variation in A over output swing means a
constant affine correction cannot simply be assumed to remove finite-gain
curvature. The passive baseline's fullrange failure cannot be declared repaired
by swapping in this OTA.

## Energy and timing screen

Even an idealized schedule that wakes the OTA for only the seven15.6ns share
intervals costs1.60774pJ per column, or12.8619pJ for eight columns, at its measured
quiescent current. Keeping it on throughout427ns costs6.2867pJ per column.
These figures omit wakeup, bias/reference generation and switched-capacitor
energy; the short awake schedule has not been validated. The original small-
input passive8-column core consumes about5.06pJ per word from all ideal source
ports, so this old OTA cannot be advertised as a power improvement on that
comparison. Different precision and functionality still require a complete
matched architecture comparison.

For a one-pole capacitive-feedback approximation,

beta=Cf/(Cf+Ca), Ceff=Co+Ca Cf/(Ca+Cf), tau≈Ceff/(beta gm).

At Cf=Ca=568fF and the measured gm, even Co=0 gives tau≈11.70ns. Reaching a
17.6ppm relative settling band from a full step takes about10.95tau≈128ns,
before self-loading, slew, internal poles or clock overhead. This is a
conditional single-pole screen, not measured closed-loop delay. It shows that
15.6ns cannot be imported from the passive TG schedule. Uniformly raising gm
by bias/width pays current and adds capacitance; no free speed scaling follows.

Archived `tb_swing_tau_svt` gives tau22.743ns in its older200fF feedback,
700fF column/137.844fF output-filter fixture. Other archived filter-load points
give15.478/25.507/35.542/54.936ns at0/100/200/400fF. Their dimensions/bias differ
from today's library (including a.705V tail bias), so they are historical
controls, not a matched transient measurement of the fresh operating point.
They document the same loading bottleneck already explored in the repository.

## Noise and honest remaining options

The fresh clamped-output native OTA input-referred total noise is about
2823nV/√Hz at1kHz,160nV/√Hz at1MHz and49.4nV/√Hz at100MHz. These are stationary
total spectra, not a switched-noise result or a legitimate single-frequency
white floor. Flicker, mirror dynamics and changing feedback transfer prevent
integrating one quoted value indiscriminately. A virtual column still needs
reset/acquisition covariance and an active-noise budget; it does not erase the
native kT/C mode.

A different dynamic or gain-boosted regulated-column architecture remains
possible, but must physically preserve the arithmetic charge state, provide
required loop gain across swing, acquire/reset quietly, and pay its actual
gm/ID, input capacitance, noise and startup energy. The old OTA branch supplies
useful mechanisms and falsifiers. Merely restoring it would return to an
already documented baseline with substantial costs, rather than demonstrate
an improved analog IMC frontier.

One established alternative worth retaining is correlated level shifting (CLS):
[Gregoire and Moon, ISSCC2008](https://web.engr.oregonstate.edu/~moon/research/files/isscc08.pdf)
store an estimate and then return the amplifier toward mid-supply while retaining
an output at a high-impedance charge node. Their two-phase loop gains multiply,
reducing finite-gain/swing sensitivity. Thus the single-phase A beta requirement
above is not fundamental to all active charge-domain architectures. CLS is prior
art, distinct from offset/flicker-canceling correlated double sampling. A native
holder could conceivably participate in an estimate/refinement architecture,
but the extra state capacitor, clock phases, charge transfer and total settling
must be paid. No noise or power benefit from that paper is imported into Sky130
or the current core, and no CLS implementation was made in this bounded round.

A fresh568fF/568fF small-charge transient attempt with1TΩ DC feedback aborted
at the initial timepoint (`legacy_ota_tau_r1/failure.json`). Its OP-only trace
is not a measured pole or settling result. No fitted time constant is claimed
from it; the analytical screen and separately identified archived fixtures
above remain the relevant timing evidence.
