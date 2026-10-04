# Physical reset/share covariance check

Status: statistical characterization in progress; no full-core noise qualification.

The analytic stationary holder variance is kT/Ch when each array reset and subsequent share fully thermalize. For r=Ch/(Ca+Ch),

`Var(h_new) = r² Var(h_old) + (1-r)² kT/Ca + kT Ca/[Ch(Ca+Ch)]`

`= r² Var(h_old) + (1-r²) kT/Ch`.

For equal capacitors, fresh array reset contributes kT/(4C) and the share switch contributes kT/(2C). Omitting reset gives the optimistic stationary 2kT/(3C). Including it gives kT/C. This is a linear equilibrium identity, not proof of finite-duration MOS noise behavior.

The physical test uses two 568 fF capacitors, 3.36µm reset transmission gates and 6.72µm share gates, all L = 0.15µm and explicit 0.29µm junction geometry. Array reset runs 16 ns, share 15.8 ns, with 0.2 ns edges and 60 ns cycle. Native Sky130 4.5 deterministic simulation qualifies the corrected 4.8 electrical/legacy 4.5 thermal-noise VACASK hybrid. The hybrid is not a complete native 4.5 implementation. Ideal capacitor dielectric noise, row/reference fluctuations, array covariance, ADC and layout are absent.

Every cycle samples array and holder before sharing and holder after sharing. Sixteen initial cycles are excluded. The covariance matrix and raw per-cycle samples are retained, allowing independent recalculation. The share residual is h_after−(a_before+h_before)/2. Correlated cycles mean ordinary IID confidence intervals cannot be assumed.

The 64-cycle zero-noise control passes unchanged trace gates: r = 0.49999982855, recurrence-fit residual 0.000766µV RMS, and post-burn-in holder-after range 0.08461µV, compared with sqrt(kT/C)=85.4155µV. Therefore large stochastic variance is not merely deterministic startup drift.

One preliminary 128-cycle noise run at 2 GHz upper cutoff and 10 ps maximum timestep completed. Normalized variances were array-before 1.03682, holder-before 0.77937, holder-after 0.79258; share residual 0.37743, with holder lag-one correlation 0.43552. These estimates remain statistically and numerically unqualified. Finite noise bandwidth can suppress the expected equilibrium variance; fresh 512-cycle seeds and paired 5 ps/2 GHz versus 5 ps/8 GHz controls are in progress. No lower-capacitance sizing claim uses this preliminary reduction.

Generator: [tb_imc_reset_share_noise.py](../../../../../analog/testbenches/tb_imc_reset_share_noise.py). Evidence: `build/campaign/reset_share_noise/`. Every new configuration uses a fresh directory, source snapshot and qualified model export. Failed and interrupted earlier runs are retained.


## Completed finite-bandwidth controls

All values below are variances normalized by kT/568 fF. Each 512-cycle run discards 16 startup cycles; no row/reference noise is present.

| Seed / max step / upper noise cutoff | Array before share | Holder after share | Share residual | Holder lag-one correlation |
|---|---:|---:|---:|---:|
|1234 /10 ps /2 GHz|0.81949|0.79825|0.38658|0.48809|
|1235 /10 ps /2 GHz|0.75959|0.84358|0.45566|0.46947|
|1234 /5 ps /2 GHz|0.73092|0.83419|0.45936|0.46449|
|1234 /5 ps /8 GHz|0.85851|0.88709|0.43537|0.52202|

The two independent 10 ps/2 GHz trajectories give pooled holder variance 0.82009 with circular 16-cycle block-bootstrap 95% interval [0.73430,0.91113], and share residual 0.42069[0.38509,0.45791]. Each trajectory is centered independently before pooling; 5000 replicates use frozen seed 47012. Source and results are archived as `bootstrap_resume.py` and `resume_2GHz_bootstrap.json`. Same noise seed with a different maximum step does not imply identical random increments or a pathwise comparison.

Increasing cutoff to 8 GHz while holding 5 ps maximum step gives a higher holder point estimate but a lower share-residual estimate. Sampling uncertainty, finite bandwidth and switching/model details remain inseparable with this small cohort. These controls do not establish that the actual switched MOS network reaches ideal equilibrium, or demonstrate a useful reduction in required capacitance. The equilibrium identity remains the conservative analytical screen pending broader physical qualification. All simulation results remain explicitly UNQUALIFIED for final device-noise acceptance.


## Native compact-model thermal deficit identified

The independent stationary checker measures current-noise PSD divided by 4kT Re(Y) for an ON transmission gate at 0.908 V common mode and essentially zero VDS. A noiseless 1 S feedback load enables measurement; input referencing removes its transimpedance. A separate physical 1 kΩ resistor is the oracle. At 1 MHz:

| Device | Native noise /4kT Re(Y) | Hybrid /native PSD |
|---|---:|---:|
|1 kΩ resistor|0.999999652|Not applicable|
|3.36µm reset TG|0.829711960|1.000775814|
|6.72µm share TG|0.832403569|1.001813721|

The approximately 17% deficit is already present in the native Sky130 BSIM4.5 TNOIMOD=1 result. It is not explained solely by hybrid implementation or finite transient-noise bandwidth. Using the measured factors αR and αS in the equal-capacitor recurrence predicts stationary holder variance (αR+2αS)/3=0.831506 kT/C and share residual αS/2=0.416202 kT/C. Those predictions agree with the finite-bandwidth transient estimates within their reported uncertainty. This is a quantitatively supported explanation of the simulator output, not evidence of a physically free reduction below equilibrium capacitor noise.

The passive equilibrium fluctuation-dissipation check must remain separate from fidelity to the provided compact model. Gate bias is static, both channel ends have equal DC voltage, and no useful non-equilibrium noise-squeezing mechanism has been demonstrated here. Treat the deficit as a model/physics limitation pending further investigation; continue using kT/C in the conservative system budget. Neither smaller capacitors nor an architecture advantage is justified from the 0.83 factor.

Reproduce with `analog/testbenches/tb_imc_reset_share_stationary.py`. The successful immutable artifact is `stationary_tt908_resume_v5/`; earlier generator/reader syntax failures are preserved. The resistor oracle is asserted numerically. MOS spectra and model-to-model ratios are characterization results and remain visible, including negative findings.


The TNOIMOD=0 option-control changes only that noise-model selector in the frozen native model cards. Re(Y) matches the TNOIMOD=1 result exactly at all 81 sampled frequencies. At 1 MHz the noise/4kT Re(Y) ratios become 1.146947 for reset and 1.142525 for share. This overshoots unity; it is **not a validated repair**. No campaign model was replaced. The original deficit is almost frequency-independent from 1 kHz through 1 GHz, so a simple high-frequency cutoff cannot explain it. Both channel terminals are at 0.908 V DC, NMOS gate/body at 1.8/0 V and PMOS gate/body at 0/1.8 V. There is no intended channel DC power at zero VDS; tiny junction leakage remains in the supplied model. PSDs are one-sided current PSDs after dividing output PSD by squared input-current-to-output-voltage gain. The stationary measurement load is an ideal noiseless instrument, not a proposed power-free circuit block.


This equilibrium expectation also appears in the primary [UC Berkeley BSIM4.8.0 manual, §10.2, printed pp.90–92](https://ngspice.sourceforge.io/external-documents/models/BSIM480_Manual.pdf): its newer TNOIMOD=2 formulation approaches normalized channel-noise factor unity at low VDS. That is a reference check, not validation of a substituted model for these Sky1304.5 cards. The campaign retains its original model and exposes this limitation.
