# Small passive stack with a measured FIA: conditional architecture screen

**SPECULATIVE circuit candidate, verified linear graph calculations.** An N4 crossed stack with the short-L FIA and approximately6pF native capacitance is worth a bounded physical test. The long-L N2 combinations have poor conditional margins. No hybrid receiver has passed noise, DAC linearity or throughput validation.

The noise numbers below use the previously defined gm-current observation oracle and an independent403.43µV latch estimate. They are **not physical FIA lower bounds**: full dynamic-charge signal transfer remains under independent qualification. Their purpose is to compare prospective loading and resource costs before another SPICE architecture sweep.

## Long-L N2 comparison

Native L.50/Wn44/Wp88 stationary decomposition is complete. Its conditional white-current observer gives39.3376µV, with Γ12.563pF; its stiff gain is32.6438. The analogous L.30 result is36.3052µV with gain30.5843. Combining the observer and latch gives41.2332/38.6272µV, respectively.

An ideal unloaded two-section gain of2 would give20.6166µV for L.50 and19.3136µV for L.30. The latter leaves little room for physical loading. Effective input-load proxies inferred from stiff/floating gain are415.58/330.93fF; endpoint droop gives641.58/474.16fF. These are sensitivities, not measured constant capacitors. With the contact-coupon parasitics and a hypothetical5fF switch shunt per node, L.30 atCa2.4/6pF has loaded gain1.264/1.606 and conditional noise30.57/24.06µV. The no-switch-parasitic model needs approximately89.3pF native C to reach20µV with the smaller input-load proxy. This is an unattractive area tradeoff, not a physical impossibility proof.

## Actual initialized odd/even capacitor graph

Each of two banks has N distinct Cs=Ca/N capacitors, initially acquired in parallel. Each series chain alternates orientation and bank ownership. For odd N, a chain uses ceil(N/2) capacitors from its own bank and floor(N/2) from the opposite bank. Index allocation is checked so no physical capacitor appears twice. The previously used even-N helper's floor-based indexing must not be reused unchanged for N3.

After ideal reconnection, the reduced matrix has diagonal2Cs except the finalCs; adjacent off-diagonal entries are−Cs. Internal node shunts alternate2βtopCs and2βbottomCs. The endpoint shunt is βtopCs for odd N and βbottomCs for even N. Uniform switch shunts and the FIA input-load proxy are then added. The retained initial plate charges give differential endpoint signal charge Cs(1+βtop)d for odd N and Cs d for even N. Direct full-graph charge conservation reproduces this reduced matrix numerically.

Consequently N3's output retains one copy of an input common-mode error, whereas even N cancels the matched stored common-mode component. The absolute chain anchor must place the FIA input near its required common mode; that reference and its switching are paid circuitry.

The contact-coupon model uses grounded substrate and the actual20µm contacted coupon: βtop=.000036664 and βbottom=.0103433 relative to813.338fF mutual capacitance. Repeating that coupon is a sensitivity model for larger sections; surrounding routes, switch wells, matching and the complete network are not extracted.

## Short-L candidate comparison

The short-L FIA input-load proxies are169.40fF from gain loss and186.40fF from endpoint droop. The former combines the initial stiff reset coordinate with the improved-reset floating coordinate and is therefore approximate. With the smaller proxy and5fF hypothetical switch shunts:

| Native C | N | Loaded passive gain | Conditional native observer+latch RMS | Fine/native co-gain |
|---|---:|---:|---:|---:|
| 4pF | 3 | 2.104 | 18.18µV | .98144 |
| 4pF | 4 | 2.252 | 16.99µV | .96764 |
| 6pF | 3 | 2.320 | 16.49µV | .98306 |
| 6pF | 4 | 2.600 | 14.71µV | .97161 |
| 13.692pF | 3 | 2.623 | 14.59µV | .98489 |
| 13.692pF | 4 | 3.148 | 12.15µV | .97610 |

The larger proxy and all small-capacitance cases remain in the machine-readable artifact. This is a reason to test a moderate stack with the smaller short-L input pair; multiplying unloaded gain by a long-L FIA gain hides the unfavorable loading.

## Fine-DAC geometry is a hard architectural constraint

For the existing split-CDAC assumptions, its lowest-section coarse host requires.960/1.920/3.840pF for12/13/14bits. Native capacitance must therefore be at least:

| N | 12bit | 13bit | 14bit |
|---|---:|---:|---:|
| 2 | 1.920pF | 3.840pF | 7.680pF |
| 3 | 2.880pF | 5.760pF | 11.520pF |
| 4 | 3.840pF | 7.680pF | 15.360pF |

An N4/6pF bank fits that12bit host but needs1.680pF additional capacitance for13bit and9.360pF for14bit. N3/13.692pF fits14bit; N4 still needs1.668pF. A different distributed DAC could change this constraint, but requires a concrete separate architecture.

For fine charge injected into the first series node, the response is proportional to inverse-matrix element[N,1], while native signal uses[N,N] and the retained initial-charge factor. Their ratio is not automatically one. In the N4/6pF case the2.84% deficit corresponds to roughly.45 of a16-step fine interval's LSB across the fine range. Native affine gain calibration does not remove this coarse/fine weight mismatch. A real bridge-ratio correction, nonbinary decision protocol with measured weights, or different injection geometry must be provided; it cannot be treated as ideal cancellation.

## Poles, energy and service cost

A separate unmerged-plate RC descriptor model uses finite resistors between neighboring plates and between the endpoint and an initially reset input load. Its nonzero eigenvalues give redistribution poles. For N4/6pF and the smaller input-load proxy, the slowest time constant is1.170ns at2.376kΩ per switch and1.664ns at3.380kΩ. These Ron values come from the prior real-TG characterization at.9V; the matrix uses ideal linear capacitors and constant Ron. A conservative13ln(2) settling interval is approximately15ns for that SS resistance. Actual edge injection, coarse input headroom, nonlinear Ron and amplifier timing still need SPICE verification.

The FIA's measured ideal-port energy is approximately2.1pJ per demonstrated decision frame before adding a stack/DAC implementation. No free clock/reference driver or reset is assumed. At the demonstrated140ns fixture cadence,12–14 decisions require1.68–1.96µs plus reconfiguration. Two holders alone cannot hide that against a427ns core word cadence. Faster reset/decision timing or additional conversion/holding resources must be demonstrated and priced; these timings are fixture observations, not a full-system latency estimate.

The stack should only be enabled after a coarse decision phase leaves a suitably small residue. Applying the fine gain to a full-span signal can violate FIA input/headroom constraints and creates a different kickback regime. Coarse-to-fine transition, SAR redundancy and real charge delivery are part of the proposed test.

## Next bounded test

After the FIA signal/noise transfer is qualified, use an N4 short-L FIA at approximately6pF native capacitance with the real12bit host. Freeze one physical bridge/injection solution before held-out validation. Verify a complete coarse-to-fine conversion, actual input loading, reset/sample covariance, native kick and the entire read/reset service interval. N3 at larger native C is a separate14bit-tail option, with its common-mode behavior explicitly tested. Neither is currently a verified improvement.

Sources and results: `tb_imc_fia_stack2_bound.py`, `tb_imc_fia_stack34_bound.py`; `build/campaign/fia_noise/stack2_bound_r1/result.json` and `stack34_bound_r1/result.json`. Both self-check ideal gain identities; the latter independently checks unique physical capacitor allocation, initialized odd/even graph agreement and finite-R pole count. These checks establish their mathematical models, not a physical ADC.


### Stronger conditional LTV noise sensitivity

The independent port-admittance LTV model subsequently predicts short-L FIA
gain within.367% and conditional final-sample white noise37.838µV. Replacing
the33.342µV ideal-current observer with this stronger transfer model gives
approximately42.24µV including the separately independent latch. The
N4/6pF screen therefore becomes approximately16.24µV native, and the
N4/4pF screen approximately18.76µV. This preserves the preference for the
6pF candidate while narrowing its margin. Missing reset/rail/gate noise and
a real stack's time-varying input admittance remain unresolved. The input-C
proxies are not proven upper/lower bounds on that admittance.
