# Native-holder readout: falsification and FIA baseline

Status: analytical bounds verified where stated; no new physical receiver yet passes 20 µV. This round complements `CAP_STACK.md` and `PREAMP_SIZING_BOUND.md`.

The objective is additive final native-holder read noise ≤20 µV RMS, with native sampling kT/C counted separately. Minimize physical capacitance/area, total port energy, and service time at matched held-out product error. Current programmed-capacitance system settings are 340×12b, 53×13b, 27×14b (420 banks); the earlier 372×12b setting count preceded measured programming-capacitance accounting. Native holders around 1.3–3.4 pF are representative, not a maximum. A complete architecture must serve the higher precision cases too.

## Three distinct mechanisms

| Candidate | Benefit | Paid cost and failure condition |
|---|---|---|
| Moderate passive stack with repeated decisions | Raises differential voltage without static bias; repeated independent noise can average | Native/N² source capacitance makes input loading critical; each vote costs a latch reset and settling, and early SAR errors require redundancy, not merely final-bit voting. Correlated noise and holder kick do not average away. |
| CDS or chopped dynamic preamplifier | Rejects offset and low frequency device noise; current reuse can improve gm per current | CDS pays reference time and reset/sample noise. Chopping requires input and output modulation, real switches, and settling. A plain precharged pair needs large output capacitors at low gain. |
| Incremental integration receiver | Quantizer error can be suppressed by accumulating residue across cycles | Each independent IMC word needs its own reset/terminal-state accounting. Front-end thermal noise falls only as inverse square root of integration time; held input kT/C, static gain error, and DAC error persist. |

For independent near-threshold Gaussian decisions, majority-vote equivalent variance is approximately πσ²/(2K), rather than σ²/K. With an equicorrelated latent Gaussian component ρ, the local threshold-estimation approximation is σ²[π/(2K)+(K−1)asin(ρ)/K]; its floor is nonzero. This is a local small-signal estimator result, not a guarantee for a full SAR search.

For incremental state s[k+1]=s[k]+a x−q d[k]+n[k], summation gives x=qΣd/(aM)+(s[M]−s[0]−Σn)/(aM). Quantization boundary error can fall as 1/M if state is bounded, but accumulated independent analog noise falls as 1/√M. Continuous-stream noise shaping cannot be assigned to unrelated MVM words without paying the corresponding reset and decoding protocol.

## Polarity swap does not generally cancel kickback

Let a measurement with polarity s be m_s=sx+o+k(sx)+n. Demodulating and averaging opposite polarities yields x+[k(x)−k(−x)]/2: fixed offset and even kick terms cancel, while odd signal-dependent errors remain.

For a physical holder, a read can instead change its state by Δx=sκ(sx). Expanding κ(u)=c0+c1u+c2u²+… gives Δx=s c0+c1x+s c2x²+c3x³+…. Odd terms accumulate under reversal. Even an exactly cancelling final-state kick pair does not imply an unbiased two-read estimate: if each read observes the pre-kick state, the second observes x0+c0 and their average is x0+c0/2. The ideal four-read +−−+ ordering cancels this constant-kick history to first order, but not the odd term. Actual switch charge and state dependence must be measured before proposing chopping as a remedy.

## Self-consistent hybrid bound

`analog/testbenches/tb_imc_readout_bounds.py` integrates archived actual-bias pair PSD and solves the stack matrix with its loaded output. It verifies the ideal-stack and white-noise integration identities. Results are in `build/research/imc_readout_bounds/results.json`.

The model uses Ce=1/(M⁻¹)[N,N], Gloaded=G0/[1+(Cfixed+Cg)/Ce], actual screen input capacitance with conditional width scaling, and total native variance [σpre²+(329 µV/Aactive)²]/Gloaded². Assumptions include hypothetical 5 fF switch shunts, matched plate ratios .0034/.01, ideal chopping, constant operating-point PSD, 1/W noise scaling and W capacitance scaling. It excludes tail/reset/chopper noise, clipping, DAC realization, mismatch and layout. It chooses minimum noise over width, not minimum energy meeting a noise specification.

At Ca=2.4 pF, 80 ns integration and doubled input-capacitance sensitivity, the best low-gain cases are:

| Active gain | Stack N | Loaded passive gain | Native RMS | Pair energy | Output C per side |
|---|---:|---:|---:|---:|---:|
| 3 | 8 | 3.992 | 33.816 µV | 1.748 pJ | 3.237 pF |
| 5 | 6 | 3.501 | 24.849 µV | 3.342 pJ | 3.713 pF |
| 8 | 6 | 3.189 | 19.617 µV | 4.874 pJ | 3.385 pF |
| 12 | 6 | 2.916 | 16.881 µV | 6.475 pJ | 2.998 pF |

The 1.3 pF holder still reaches only 21.867 µV in the best gain-12 case. Therefore gain-3–5 hybrids fail this conditional bound, and the nominally passing larger-gain examples already pay substantial area before omitted errors. Furthermore the current 12b split-DAC host requires 960 fF; a 2.4 pF/N4 section provides only 600 fF. A distributed DAC or additional paid capacitance is required. Multiplying unloaded gains would hide both problems.

## Fully specified known primitive: floating inverter amplifier

The author-hosted [Tang VLSI 2019 paper](https://www.xtang.me/pubs/files/2019_VLSI_Tang.pdf) provides a full schematic and measured comparator results: 180 nm, 1.2 V supply, 0.6 V common mode, 46 µV input noise and 0.98 pJ per comparison. Its noise figure is a measured decision-CDF result; the short paper does not establish a stationary noise integration bandwidth. This comparator is not chopped.

The expanded journal reference is [Tang et al., JSSC 2020, DOI 10.1109/JSSC.2019.2960485](https://ieeexplore.ieee.org/document/8947992/). Exact journal full text was not obtained. The inventors' [public patent, Fig. 1 and Table 1](https://patents.google.com/patent/US20210384874A1/en), inspected as a PDF, independently specifies Wp=44 µm, Wn=22 µm, L=.18 µm, reservoir 2 pF and output capacitance 250 fF per side including parasitics. It reports an off-chip VCM regulator and symmetric reservoir MoM construction. These dimensions are characterization coordinates, not Sky130 gm/ID sizing.

Closed connections from the primary schematic:

- Two complementary inverters share upper floating rail VS+ and lower floating rail VS−. Left PMOS/NMOS gates connect VI+, common drains VX−; right gates VI−, drains VX+.
- CRES connects reservoir plates RP/RN. Each plate has its own SPDT. Reset connects RP to VDD and RN to ground while disconnecting both FIA rails. Amplify connects RP to VS+ and RN to VS− while disconnecting the precharge supplies.
- Both output capacitors connect to ground; individual reset switches restore outputs to VCM during global reset.
- The published PMOS-input latch resets its outputs low and terminates amplification using NOR(clkbar, DO+, DO−). The repo NMOS-input latch resets high, requiring different completion logic. A fixed aperture is an explicit experimental simplification.
- Bulk connections are not specified by the drawing. Sky130 NMOS bodies at ground and PMOS bodies at VDD are implementation assumptions requiring actual body-effect and junction checks.

A stronger [CICC 2024 current-reuse comparator](https://ieeexplore.ieee.org/document/10529044/) advertises 0.25 pJ/comparison, 27.3 µV and stacked floating preamplification with cross-coupled feedback. The [official conference program](https://www.ieee-cicc.org/wp-content/uploads/2024/04/CICC-2024-Program-4-16-24pdf.pdf) confirms its identity. Full schematic, timing, measurement bandwidth and power boundary remain unavailable from the primary sources retrieved. Its connections must not be reconstructed from the title or abstract.

## First-principles FIA sizing and bounded next tests

For equal inverter branch current I, define Gm=gm_n+gm_p, ηeff=Gm/I and Γ=∫Gm dt. With independent transistor white noise, γeff=(γn gm_n+γp gm_p)/Gm. For constant ratios and negligible output conductance:

σ²in=4kT γeff/Γ; A=Γ/Cout; Ecore=2VDD Γ/ηeff; ΔVres=2Γ/(ηeff CRES).

For time-varying operation the noise numerator is 4kT∫γeff Gm dt, divided by Γ². Finite output conductance replaces uniform integration with an impulse-response weighting; stationary snapshots alone do not prove the transient noise. Output reset noise adds 2kT Cout/Γ² under independent full reset. Reservoir differential reset noise, device mismatch and asymmetrical reservoir parasitics can modulate bias and gain. Total gate load includes BOTH n and p devices, Cgd feedback, and all input switches.

At 300 K, ηeff=40/V and γeff=2, Γ=9.2 pF gives roughly 60 µV FIA noise, 0.828 pJ core recharge, and requires CRES≥1.15 pF to limit reservoir droop to .4 V. A=8 implies Cout≈1.15 pF/side. If an independently verified loaded passive gain 4 existed, this would yield about 18.2 µV native noise including a 329 µV latch, before omitted noise and physical kick. This is a falsifiable hybrid coordinate, not a verified architecture. A direct FIA allocating 17 µV to its own noise instead needs Γ≈115 pF and ~10.3 pJ at these same assumed parameters.

Two bounded tests survive:

1. Characterize the fully specified FIA at the paper-sized coordinate in Sky130. Measure actual gm/ID trajectories, both floating rails, output common mode, output conductance-limited gain, input port charge, reservoir recharge energy and latch kick across input sign/common mode. Reject if signal-dependent native kick exceeds the budget even after a frozen calibration.
2. Only after that, combine a moderate physically loaded stack with the measured FIA input capacitance and noise weighting. Require a real DAC placement and coarse-to-fine transition. Test the smallest native holder first; it already invalidates the plain-pair hybrid bound.

Neither mechanism is novel by itself. Any contribution would have to lie in a verified IMC integration or scheduling improvement over these known primitives, with paid area, reset resources and service time.

### CICC 2024 evidence update

After the initial search, a [publicly readable copy of the primary paper](https://www.scribd.com/document/949394059/A-0-25pJ-Comparison-27-3V-Input-Noise-Dynamic-Comparator-Exploiting-Stacked-Floating-Preamplifier-With-Cross-Coupled-Feedback-Inverters-in-180nm-CMOS) exposed its actual text, distinct from the host's AI summary. It reports measured 180 nm silicon: 3550 µm², 27.3 µV CDF noise from 10^6 comparisons, 100 MHz clock, 1.1 V supply, .55 V common mode, and 2.06 ns delay at 100 µV differential input. Reset equalizes both internal stacked-node pairs, as well as resetting the main output and reservoir. Feedback devices MX1/2 use W/L=8/.18 µm versus 20/.18 µm for M1–4, with approximately 3:1 main-to-feedback current. It does not establish a separate noise integration band. The complete graphical connections remain uninspected, so this updates measurement status without authorizing a reconstructed netlist.

Independent implication: the equalization switches introduce additional reset noise and history-sensitive internal states; positive-feedback gain enhancement needs finite-time sensitivity/noise analysis, not multiplication of an unloaded DC gain by a current-reuse factor. These concerns define the implementation audit once the graphical schematic is available.

### Independent first FIA testbench review

The initial `tb_imc_fia.py` connection review agrees with the primary two-SPDT topology and complementary input device orientation. Its precharge-to-amplification dead time and amplification-to-precharge dead time prevent ideal clock overlap. Swapping the FIA outputs into the existing NMOS latch restores the expected input sign. Source-positive energy includes VDD, VCM, input and clock ports, through closing reset; this is a conservative delivered-energy boundary, not merely reservoir energy.

Before interpreting its trajectory as a sizing result, export individual port currents; distinguish nominal-source gain from gain relative to the actual acquired holder differential; record both branches when using large differential inputs; and separate amplification kick from latch kick with pre-latch and post-latch checkpoints. The initial gm/ID range rejects samples with gm below 10% of its peak, which censors late weak inversion. Full-aperture transconductance integral and charge-weighted effective gm/ID are needed alongside that range. A sign PASS alone establishes neither noise nor reset accuracy.

### Fresh comparator-noise correction

The independently audited fresh 256-seed-per-input cohort now gives 395.927 µV for the 4-fF latch, with approximate 95% profile interval 365.280–429.145 µV. The historical 329 µV assumption in this report's hybrid bound is therefore optimistic and must not be treated as the current noise estimate. Default/16-fF results are 403.432/386.802 µV; paired comparisons do not demonstrate a significant capacitance benefit. Existing hybrid bound results above remain historical conditional calculations and do not establish a passing receiver under the stronger fresh estimate. See `DECISION_NOISE.md` and `LATCH_GMID.md`.
