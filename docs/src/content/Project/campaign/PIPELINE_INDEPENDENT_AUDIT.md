# Independent stationary-noise and native-pipeline audit

Audited `tb_imc_reset_share_stationary.py`, `tb_imc_reset_share_noise.py`, `tb_imc_native_pipeline.py`, archived stationary results and completed nine-word TT/SS results. No owned pipeline source or simulation result was modified. This review does not certify a physical readout or complete IMC architecture.

## Stationary normalization: supported

An AC 1 A test current drives node h against an ideal noiseless 1 S feedback conductance referenced to VCM. Thus Ydevice=1/V(h)−1 S. Input-referencing the output noise removes the transimpedance. The native ngspice quantity is amplitude spectral density and is squared; the VACASK quantity is output power spectral density and is divided by |gain|². The physical 1 kΩ resistor oracle gives 0.999999652 relative to 4kT Re(Y), supporting the PSD and one-sided normalization conventions.

| Device | Native TNOIMOD=1 / Nyquist at 1 MHz | Hybrid / native | Native TNOIMOD=0 / Nyquist |
|---|---:|---:|---:|
| Reset TG | .8297119604 | 1.0007758 | 1.1469473731 |
| Share TG | .8324035686 | 1.0018137 | 1.1425247125 |

The TNOIMOD=1 deficit is effectively flat from 1 kHz through 1 GHz, before the upper-frequency change. Therefore it cannot be attributed solely to a finite transient-noise integration cutoff. The noise-selector control preserves Re(Y); changing the selector overshoots unity and is not a validated repair. The hybrid is a corrected BSIM4.8 electrical implementation with legacy thermal-noise behavior, not a complete implementation of native BSIM4.5.

The DC fixture intends zero channel VDS at .908 V common mode, with NMOS gate/body 1.8/0 V and PMOS gate/body 0/1.8 V. The subsequently completed `stationary_tt908_tnoi1_optioncontrol` explicitly records V(h)−VCM=−1.94×10⁻¹⁴ V, NMOS/PMOS channel currents 6.69×10⁻¹⁸/8.46×10⁻¹⁹ A, and approximately 1.79 pA VDD-port leakage. Independent inspection of `operating.csv` and `device_op.txt` closes the earlier missing operating-point evidence; the stationary ratios are unchanged. The resistor control validates normalization, not transistor thermodynamic fidelity.

The measured factors predict an equal-capacitor recurrence coefficient (αreset+2αshare)/3≈.831506 relative to kT/C. This is a supported explanation of the supplied simulator results. It is **not** evidence that an equilibrium capacitor can physically retain less than kT/C for free; preserve the full-reset kT/C system budget unless a separate physical nonequilibrium mechanism is demonstrated.

## Pipeline topology: supported within the fixture

The alternate bank contains real holder capacitance, share TG and reset TG. Its inactive clocks are numerically checked throughout the intervening word. No ideal voltage source writes a copied answer to either holder.

The selected trim uses a real grounding NMOS with a complementary bypass TG. Enabled: bottom grounded, bypass off. Disabled: grounding device off, capacitor bottom follows its top through the bypass; residual device capacitance remains. The static complementary control sources are metered; configuration storage is absent and identified. This is one selected ideal capacitor plus physical switches, not a qualified trim DAC.

The replica uses a fully OFF TG: NMOS gate ground, PMOS gate VDD, with its remote channel terminal at fixed VCM. This reproduces an extra class of loading, but the actual inactive-bank terminal follows a stored prior result. Equal geometry does not make their voltage-dependent capacitances equal for arbitrary histories. Large-signal history validation remains necessary.

## Completed quantitative evidence

| Variant | Capture RMS/max MAC | Retained RMS/max MAC | Max one-word drift MAC |
|---|---|---|---:|
| TT selected trim | .047654 / .048471 | .047009 / .048002 | .009785 |
| SS85 selected trim | .096591 / .104586 | .108315 / .149585 | .055571 |
| TT off replica | .011084 / .013537 | .012304 / .013767 | .009792 |
| SS85 off replica | .117203 / .201591 | .112182 / .127854 | .083190 |

The same corner-specific calibration protocol is used, with parity-specific three-point affine fits. The actual calibration MAC values are [2237,−1224,−335,989,−46,373]; held-out values are only [33,66,21]. Sampled holders span approximately .8687–.9516 V across the entire original nine words. Passing these cases establishes local deterministic accuracy and retention; it does not establish full-scale linearity or frozen-TT PVT robustness. Retained accuracy initially covers two held-out words; final-word retention needs the additional physical word now included by the fresh-history fixture.

The fresh positive-history source extends real row/reset/share PWL controls, preserves all six calibration vectors and numerically verifies 128×7-bit stimulus encoding. Its intended held-outs are [+14224,−14224,+33,+14224] MAC. At audit time the matched serial and replica runs are incomplete. Their results must remain separate from the completed small-signal PASS.

Source-positive energy includes ideal clock, rail and reference port delivery; it excludes real drivers, programmable storage, ADC and converter service contention. Only column zero is duplicated. The 427 ns word timing is a core fixture cadence, not demonstrated end-to-end throughput or latency reduction.

## Completed fresh-history results: full-range accuracy FAILED

The matched extreme-history runs have now completed with the original six-word calibration unchanged. Both serial and replica architectures fail the frozen compute-accuracy gate:

| Architecture / history | Capture RMS / max error (MAC) | Held-out error vector (MAC) |
|---|---|---|
| Serial, positive first | 5.009228 / 9.756069 | [−1.846694,−9.756069,+.010942,−1.333486] |
| Replica, positive first | 4.158784 / 7.974141 | [−1.937465,−7.974141,+.016301,−1.356828] |
| Serial, negative first | 6.739491 / 9.771109 | [−9.187976,−1.337616,+.016041,−9.771109] |
| Replica, negative first | 5.448599 / 7.959865 | [−7.317933,−1.355425,+.011333,−7.959865] |

The replica's maximum one-word drift is only .062518 MAC for either ordering, passing the .25-MAC retention gate. Its large compute error therefore cannot be explained by end-of-word retention drift alone. Serial failure shows an underlying full-range compute/calibration limitation; the apparently smaller replica error does not establish a usable improvement while both fail. These tests do not isolate a unique physical cause.

The separate frozen moderate-random replica history passes: capture RMS/max .051645/.081380 MAC, retained .033634/.045002 MAC, maximum drift .009792 MAC. Thus local retention and moderate-input accuracy survive additional history testing, while full-scale compute accuracy remains FAILED. No calibration or sizing was changed to hide the extreme-history failures.
