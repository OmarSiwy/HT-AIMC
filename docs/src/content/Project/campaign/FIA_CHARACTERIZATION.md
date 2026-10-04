# Floating-inverter readout: physical characterization

Status: **STRONGLY SUPPORTED deterministic interface only**; noise, complete
ADC and integrated IMC operation remain unverified. Initial sizing is a
reference point, not an optimum or a reproduction of published performance.

The topology follows [Tang et al., VLSI 2019](https://www.xtang.me/pubs/files/2019_VLSI_Tang.pdf):
a reservoir capacitor is precharged between supplies while disconnected from
both inverter source rails. Two physical SPDTs then connect its plates to
those rails after supply disconnection. Two inverters amplify a differential
input before a separate latch. A fixed aperture replaces the paper's
decision-dependent termination. Global body connections, ideal capacitors,
ideal clock/reference sources and explicit one-finger junction geometry are
declared in each deck. No paper energy or noise is inherited by this circuit.

Initial Sky130 TT27 dimensions: Wn=22 µm, Wp=44 µm, L=.18 µm;
reservoir=2 pF, output=250 fF per side, input holder=2.4 pF per side,
VDD=1.8 V, nominal common mode=.9 V. Eight sequential differential inputs
are −2 mV, +2 mV, −250 µV, +250 µV, −20 µV, +20 µV, −100 mV, +100 mV.
All eight deterministic decisions resolve with correct signs; this is a
sign gate, not an accuracy or noise specification.

## Actual gm/ID and loading

The −20-µV small-signal frame gives charge-weighted gm/ID of approximately
21.40 V⁻¹ for N and 15.01 V⁻¹ for P. Their summed integrated gm is
15.79 pF per branch before latch release. Dividing summed integrated gm by
the mean of N/P integrated absolute channel currents gives an explicitly
defined branch proxy of 36.42 V⁻¹. N/P currents differ while the output
charges; all individual integrals and both branches are retained.

Stiff-input small-signal gain is about 21.49. Floating-input gain referred
to the actual acquired differential voltage is about 20.12. At 100 mV,
gain compresses to approximately 13.3. The 3.36-µm sampling TG does not
fully acquire the 2.4-pF holder in the available interval: the −250-µV
frame acquires −231.54 µV after its preceding +2-mV frame. During
amplification it changes further to −214.74 µV. Correct signs hide these
material acquisition and loading errors.

## Conductance controls

Increasing only acquisition width to 13.44 µm removes most history-dependent
settling but adds signal-dependent switch injection: ±250 µV is acquired
as approximately ±251.18 µV, and ±20 µV as ±20.0946 µV. The subsequent
amplification still attenuates the held differential by approximately 7.2%.
This is a measured transfer effect requiring calibration or redesign, not
a lossless readout. Small-signal complete-frame positive port energy rises
from about 2.10 to 2.18 pJ.

Increasing output-reset width separately from .84 to 3.36 µm reduces the
closing output deviation from the .9-V reset target: approximately 243→39 µV
on small inputs and 1.75 mV→185 µV on ±100-mV inputs. Energy rises to
about 2.20 pJ for small inputs. Closing reset remains a diagnostic; it does
not yet meet a declared converter-reset error budget.

These measurements include positive energy delivered by all independent
source ports over the complete 140-ns frame. They do not include transistor
clock drivers, SRAM, physical references or a multi-decision ADC. The
amplifier remains enabled after the nominal integration instant, so this
schedule is deliberately not an energy optimum.

Source: `analog/testbenches/tb_imc_fia.py`. Evidence:
`build/campaign/fia/tt_measured_stiff_r1`, `tt_measured_floating_r1`,
`tt_acq13p44_only`, `tt_acq13p44_reset3p36`. Every run retains source,
deck and trace hashes. Fresh SS85 and doubled-PMOS-width controls are
pending. Independent native device-noise analysis is pending; no assumed
constant gamma is being used to claim a noise pass.

## Corner and gm/ID sizing controls

The SS85 control at the same widths resolves all eight signs. Its small-input
actual-acquired gain is about21.85 and complete-frame delivery about2.515pJ,
versus20.07 and2.202pJ atTT. Effective charge-weighted gm/ID falls from36.42
to31.02V⁻¹. Correct signs therefore do not establish constant gain or energy
across PVT.

Doubling only PMOS width44→88µm raises its charge-weighted gm/ID only
15.01→15.50V⁻¹, and effective branch gm/ID36.42→36.66V⁻¹. It reduces loaded
gain20.07→19.41, shifts output common mode to~.875V and raises small-input
energy2.202→2.352pJ. This is not a supported sizing improvement; any noise
benefit would require separate verification. The NMOS-width control remains
pending because native bias noise shows substantially larger N-device flicker.

Independent native PSD analysis finds a conditional white-current observation
bound of33.34µV for the initial trajectory, excluding flicker, switches, reset,
reservoir and latch noise. This rejects20µV within that reduced observation
model. An independent critic identified that capacitive signal feedthrough,
terminal-charge dynamics and source-rail coupling must first be included or
bounded before treating it as a lower bound on the actual physical FIA.
That transfer qualification remains pending. The fresh403.43µV latch divided by stiff gain21.49
contributes18.77µV; an independent-noise quadrature bound is already38.26µV.
This is a compact-model-conditional analytical check, not a measured physical
noise floor. Subtracting the native reported flicker spectrum from its total
and checking a flat positive remainder supports the white decomposition;
adding that remainder back is an algebraic check, not an independent sum of
every physical noise source. Source and thermal/flicker component audit are in
`build/campaign/fia_noise/native_components_r1/result.json`.
