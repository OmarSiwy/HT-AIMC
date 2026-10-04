# FIA native-noise assessment at measured gm/ID trajectories

**VERIFIED as a conditional current-observation calculation:** archived native PSD and gm trajectories give **33.342 µV RMS** for an ideal independent-white-current observer. This observer omits capacitive feedthrough and dynamic-charge signal paths and has not reproduced the complete FIA signal transfer. It therefore does **not** yet establish a lower bound on physical FIA noise or prove that the circuit cannot meet 20 µV. Reset, reservoir, switches, flicker and latch noise also remain unqualified.

## Evidence and method

The immutable source trajectory is `build/campaign/fia/tt_measured_stiff_r1/trace.csv`, using its +20 µV input word and local 40–69 ns pre-latch aperture. Sixteen time coordinates preserve all four actual drain/gate/source/body biases. Native Sky130 stationary noise uses the same W/L and .29 µm drawn diffusion. Each drain has a noiseless 1000 S measurement load; input-current referencing removes its transimpedance. Bias sources are instruments, not proposed free circuitry.

All 64 device snapshot transconductances match the archived trajectory within .238%. The initial sparse-time quadrature overestimated the transconductance integral by about 2.2%; the final calculation interpolates noise coefficients onto the original dense gm trajectory and recovers Γ=15.7898 pF.

`tb_imc_fia_noise_audit.py` preserves full 1 Hz–100 GHz total spectra. `tb_imc_fia_noise_components.py` requests native per-source contributions, separates the reported 1/f component from total PSD, and checks the algebraic consistency of subtraction and reconstruction. This is not an independent sum of all individual noise mechanisms. No foundry noise selector or model coefficient is changed. The remaining white-current PSD varies by at most .0114% between 1 kHz and 10 MHz, supporting a quasi-static white decomposition without relying on a high-frequency asymptote beyond device fT.

| Local time | NMOS gm/ID | PMOS gm/ID | NMOS white γ | PMOS white γ | Sum gm / sum gds |
|---|---:|---:|---:|---:|---:|
| 40.2 ns | 17.794 | 14.874 | 1.4665 | .8403 | 30.50 |
| 42 ns | 20.301 | 14.627 | 1.3346 | .8633 | 26.19 |
| 45 ns | 21.854 | 15.709 | 1.2560 | .7223 | 24.96 |
| 52 ns | 23.301 | 15.899 | 1.2267 | .5874 | 23.78 |
| 69 ns | 24.503 | 15.631 | 1.2410 | .5050 | 22.80 |

Here γ=Swhite/(4kT gm) is measured from the native terminal-current spectrum, not assigned from a textbook long-channel constant. Lower PMOS gm/ID does not imply poorer noise per current; its smaller measured γ matters too. Neither transistor can be sized by gm/ID alone.

## Bound and normalization

For differential input ±v/2, let G(t) equal half the sum of all four gm values, and let SΔ(t) be the sum of the four independent one-sided current-noise PSDs. An arbitrary linear current observation with weight w has

σ² = [∫w² SΔ dt / 2] / [∫w G dt]².

Cauchy–Schwarz gives the optimal observation bound

σ² ≥ 1 / [2∫G²/SΔ dt].

For two matched complementary branches with constant γ this reduces to 4kTγ/Γ, confirming the differential and one-sided factors. The numerical result is 33.3416 µV; a uniform ideal current integrator gives 33.4863 µV. The equivalent integrated γ is about 1.059, so assigning γ=2 would have been materially pessimistic for this coordinate. The observed amplifier is not the ideal observer. Its capacitive and time-varying charge signal paths must be qualified before this oracle can be related to a physical noise lower bound.

The previously measured gain is approximately 21.49. A separately independent 403.43 µV latch would contribute approximately 18.77 µV at that gain, giving approximately 38.26 µV in the illustrative quadrature combination of the conditional observer and latch models. Actual latch/preamp coupling and reset correlations still require a physical stochastic test; the quadrature illustration is conditional.

At unchanged coefficients, reducing only the FIA white bound from 33.34 to 20 µV requires approximately 2.78 times the useful gm-time. That does not meet a 20 µV combined receiver budget because the latch consumes much of it. Uniform width/capacitance scaling also preserves gain while increasing input loading and area. Late intrinsic gain around 22.8 explains why a longer aperture alone cannot be assumed to suppress the latch adequately. Longer L or another gain mechanism needs actual gm/gds, gate loading and noise characterization.

## Flicker and physical-model limits

Using total stationary PSD as a fictitious white spectrum gives information-bound sensitivities of 78.07 µV at 1 MHz, 44.96 µV at 10 MHz, 35.40 µV at 100 MHz and 33.39 µV at 1 GHz. These are **not** switched flicker-noise predictions: colored-noise temporal covariance cannot be replaced by one selected frequency. Early NMOS flicker is substantial, and late PMOS fT falls below 300 MHz. This is why the direct component decomposition was necessary.

The separate reset/share equilibrium audit found native TNOIMOD=1 near .83 times Nyquist and TNOIMOD=0 near 1.14 times Nyquist. No universal .83 correction is applied to these biased FIA devices: the discrepancy is bias/model dependent. Agreement with native stationary noise qualifies model reproduction, not silicon noise fidelity. The system continues to count full-reset kT/C separately.

Unverified contributions include reset-switch noise and its history, reservoir noise and asymmetric parasitics, source-rail response, actual input-holder loading/kick, flicker covariance, finite-gds noise transfer, mismatch, supply/temperature corners and extracted layout. The next useful test is a native/hybrid qualification of a complete FIA stochastic model at these same biases and reset phases, or a linear time-varying transfer calculation that first reproduces the measured signal gain. A new width sweep without those constraints is not justified.

## Artifacts and checks

- `analog/testbenches/tb_imc_fia_noise_audit.py`: PASS positive spectra and snapshot collection.
- `analog/testbenches/tb_imc_fia_noise_components.py`: PASS native component sum and positive white PSD.
- `build/campaign/fia_noise/native_snapshot_r1/result.json`: biases, original spectra and fingerprints.
- `build/campaign/fia_noise/native_components_r1/result.json`: decomposition, dense-trajectory bound and fingerprints.
- `build/sim/imc_fia_native_snapshot_r1/` and `imc_fia_native_components_r1/`: exact native decks, logs and numerical spectra.

All noise results are conditional characterization. No 20 µV FIA receiver or system-quality rescue is claimed.

## Bounded length comparison

Root generated independent native FIA trajectories with improved acquisition/reset switches. Keeping W/L constant from L=.18 to .30 µm gives Wn36.6667/Wp73.3333 µm. The proposed constant-W/L L=.50 coordinate exceeds the installed model's valid PMOS width bin and did not simulate; its failure is preserved. A separate legal L=.50, Wn44/Wp88 coordinate is not a constant-W/L comparison.

| Floating-input coordinate | Effective gm/ID | Γ, left complementary branch | Intrinsic gm/gds at69ns | Peak intrinsic input Cgg, one branch | Gain relative to acquired input | Ideal-port energy at+20µV |
|---|---:|---:|---:|---:|---:|---:|
| L.18, Wn22/Wp44 | 36.427/V | ~15.788pF | 22.79 | 62.06fF | 20.077 | 2.202pJ |
| L.30, Wn36.6667/Wp73.3333 | 38.508/V | 14.328pF | 50.59 | 161.76fF | 26.878 | 1.994pJ |
| L.50, Wn44/Wp88 | 39.102/V | 12.561pF | 113.72 | 309.88fF | 27.826 | 1.826pJ |

All three floating-input rows use the improved acquisition/reset settings. Their approximately20.094µV acquired signal falls to18.646,16.779 and15.855µV before latching, respectively. Increasing intrinsic gain therefore also increases input loading. Intrinsic Cgg is only a diagnostic; overlap, switch and Miller contributions still matter.

The separately completed L.30 stiff-input trajectory has gain30.584 and Γ14.331pF. Native white-component decomposition gives an optimistic information bound **36.305µV**, versus33.342µV at the original L.18 coordinate. The white PSD is flat within.0157% across1kHz–10MHz. The maximum snapshot-gm discrepancy is.641%, mainly around the sharp clock edge where separately interpolated biases and gm differ. These numerical differences do not close the more important unqualified-signal-transfer gap. The uniform ideal current-integrator estimate is36.548µV.

At42ns, native γN/γP changes from1.335/.863 for L.18 to1.578/.782 for L.30. Higher effective gm/ID does not offset the larger weighted noise factor and smaller gm-time. Total-spectrum sensitivities also indicate less low-frequency flicker for L.30, but no switched flicker variance has been established.

Thus L.30 improves intrinsic gain and the observed gain/energy tradeoff but does not provide a demonstrated direct20µV readout. At the time of that comparison L.50 noise was not yet measured; its larger input loading and smaller gm-time prevent assigning a noise benefit from its higher intrinsic gain alone. No width or length is promoted to an optimum.

Parameterized audit sources now read geometry, temperature and bias trajectory from immutable result manifests. L.30 evidence is under `native_snapshot_l030_r1/` and `native_components_l030_r1/` in `build/campaign/fia_noise/`. Original r1 generator snapshots remain preserved.


### Adversarial correction: signal transfer remains unqualified

The current-observation Cauchy–Schwarz inequality is mathematically correct
for signal current G(t)v and independent white current noise. The physical FIA
also has input/output capacitance and time-varying stored-charge terms, which
can carry signal. Therefore the calculated33–39µV numbers are conditional
observer benchmarks, not established physical lower bounds. A proposed hybrid
that fails those benchmarks is an unattractive conditional screen; this alone
is not a proof of physical impossibility. A native transient signal-transfer
comparison or full tangent model is required before stronger statements.

The source's historical `PASS_NATIVE_COMPONENT_SUM_AND_POSITIVE_WHITE_PSD`
label verifies positivity and an algebraic subtraction identity. It does not
independently validate every thermal-noise contribution. Archived data and
labels are preserved; subsequent source labels make this distinction explicit.


### L.50 and independent signal-transfer update

The legal L.50/Wn44/Wp88 stiff coordinate now has a completed native
component screen: current-observer estimate39.3376µV, Γ12.5631pF and
stiff gain32.6438. White PSD varies by at most.0173% across1kHz–10MHz.
The same current-observer limitations apply.

An independent full-port admittance extraction subsequently included total
Cdd/Cdg in a charge-form LTV model. Its predicted gains21.5724/31.0097
compare with native21.4936/30.5843 for L.18/L.30, respectively, errors
.367%/1.391%. Conditional final-sample white estimates are37.838/36.643µV,
which differ from the ideal-current oracle. This materially improves transfer
support but still excludes explicit latch/reset/rail and gate-noise paths.
See the pipeline agent's `independent_ports_r1/result.json` and
`independent_port_ltv_r1/result.json` under the FIA audit artifacts.
