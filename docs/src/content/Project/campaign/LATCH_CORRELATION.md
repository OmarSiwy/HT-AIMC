# Sequential comparator-noise correlation

Status: **VERIFIED within the declared finite-band hybrid fixture**. This
is a component-level measurement of repeated
intrinsic comparator decisions under physical reset history. It does not
qualify a loaded holder, SAR, mismatch, or complete-column noise.

The experiment is
`analog/testbenches/tb_imc_latch_correlation.py`. It reuses the parent's
qualified native4.5 model export and corrected4.8 electrical / legacy4.5
thermal-noise hybrid. All nine devices use the explicit nf1 rectangular
diffusion assumptionAD=AS=.29W, PD=PS=2(W+.29), NRD=NRS=.29/W. InputW=3.5µm,
both output loads10fF, input common mode.9V, supply1.8V. Input sources are
stiff noiseless clamps; CMOS receivers are absent.

Each complete trajectory contains16 physical20ns clock cycles. Clock
rise begins at5+20i ns and ends at7+20i; fall occupies12–14+20i ns. Decisions
are sampled at11+20i, with actual reset checks at4+20i and24+20i. The final
stop is325ns, retaining the closing reset. No initial node voltage is
forced. Noise settings areSDE, stochastic-LTE floor30, maximum step2ps,
noise frequency parameters2MHz–2GHz andoversample6. The finite low-frequency
limit is a declared assumption, not a proof that slower flicker is absent.

The first requested qualification compared every cycle against native
ngspice at±2mV using the existing5mV maximum /1mV RMS trajectory-difference,
.1ns ready-time and.5% energy-difference gates. The positive-input startup
cycle failed:87.78mV maximum and39.06mV RMS discrepancy, predominantly the
initial device state. Every subsequent cycle passed, with maximum≤.231mV
andRMS≤16.8µV. That original failure remains in
`build/campaign/latch_correlation/tt16_fmin2m_n64/`.

The explicit follow-up retains startup as an unqualified burn-in cycle,
matching the parent's prior second-cycle-only noise qualification. Both
input polarities pass unchanged gates on all15 later cycles and all
physical output-reset checks. The first cycle still must resolve the
correct±2mV polarity and reset; only its full native/hybrid trace-difference
acceptance is excluded. This scope change is recorded rather than
silently relaxing the numerical limits. The new protocol and immutable
source are in
`build/campaign/latch_correlation/tt16_fmin2m_n64_postreset/`.

That follow-up collected64 independent complete trajectories per input at
0 and±250µV, with disjoint seeds beginning98100. The first startup cycle
is retained but excluded from the stationary statistics. The independent
unit for uncertainty is the whole seed trajectory, not each correlated
decision. Recorded outputs are:

- Positive-decision fraction for every cycle and all post-startup cycles.
- Observed sign Pearson correlations at lags1,2,4,8, with trajectory-level
  bootstrap intervals and conditional transition counts/probabilities.
- ExactK1/3/5/9 majority outcomes from the firstK post-startup decisions,
  one outcome per independent trajectory, compared with independent
  identical-Bernoulli predictions based on the observed marginal.

No transformation from sign correlation to latent Gaussian rho is assumed.
Fixed-sign thresholds, flicker modulation, nonlinear reset state, and
finite samples can all make that inference invalid. Per-cycle marginals
remain alongside pooled correlation because time-varying marginal
probabilities can themselves produce an apparent pooled correlation. A
separate frozen analysis file adds cycle-centered correlations and Wilson
intervals for vote error counts; bootstrap intervals alone can degenerate
when a64-trajectory window records zero errors.

A matching64-seed zero-input control lowers the nominal flicker limit to
200kHz. This is a sensitivity check, not a physical low-frequency-noise
closure. Switched-bias noise measurements show that trap capture/emission
rates and bias history affect flicker, with process- and device-dependent
reductions; restored circuit voltages do not prove independent trap states.
See [Klumperink et al.'s primary overview](https://icejive.el.utwente.nl/home/erick/Klumperink-Reduction%20of%201%20over%20f%20Noise%20by%20Switched%20Biasing-An%20Overview-ProRisc2005.pdf).
The current BSIM spectral-noise source and simulator generation are not an
explicit trap-occupancy model. Noise below the selected limit may act as a
shared threshold over a320ns burst and remains unverified.

The architecture motivation is the selective coarse-voting control in
[CAP_STACK.md](CAP_STACK.md). Its fine-range clipping cannot be repaired
after a wrong coarse interval, so spending votes before passive gain can
be more useful than spending the same number afterward. That numerical
benefit remains conditional on physical noise correlation.

A separate loaded-state negative result must remain distinct: the N16
crossed stack with an actual comparator shows up to175.6µV preclock
differential drift over10 reads and alternating zero-input kickback.
The stiff-input experiment here cannot reproduce or waive that feedback.
The actual direct15.5pF coarse-holder control has less than.65µV drift,
but its stochastic sampled-state noise is still unverified.

## Completed measurements

All192 nominal and64 lower-cutoff trajectories completed, reset and resolved
every sampled decision:4,096 noisy physical cycles in total. Both±2mV
deterministic controls passed each post-startup cycle with maximum native/
hybrid disagreement.231mV, maximum RMS16.8µV, zero1ps-grid ready-time
difference, and relative energy difference below.0046%. These numerical
gates establish the reused component port's trajectory agreement under
the stated conditions, not physical trap-memory or full-column accuracy.

| Input / lower noise parameter | Positive fraction, all15 retained cycles | Lag1 observed sign Pearson,95% trajectory-bootstrap interval | Lag1 after centering each cycle,95% interval |
|---|---:|---:|---:|
| −250µV /2MHz | .2667 | .0585 [−.0119,.1199] | .0600 [−.0119,.1276] |
| 0 /2MHz | .4927 | .0491 [−.0213,.1164] | .0545 [−.0153,.1221] |
| +250µV /2MHz | .7115 | .0681 [.0011,.1308] | .0736 [.0075,.1397] |
| 0 /200kHz | .5240 | .0871 [.0182,.1538] | .0946 [.0274,.1643] |

At zero input and2MHz, pooled lag2/4/8 estimates are.0360/−.0391/.0536;
all corresponding intervals include zero. At200kHz, lag4 is.0977 with
interval[.0240,.1733], while lag2 andlag8 remain consistent with zero.
These are pointwise intervals across several tested lags and inputs;
they are not corrected simultaneous statements. The two cutoff controls'
intervals overlap. The lower-cutoff experiment detects modest positive
correlation at selected lags; it does not establish the magnitude of the
change caused by lowering the cutoff, nor support strict independence.

For example, at0/2MHz the observed transition probabilities are
P(next+|previous−)=.4754 andP(next+|previous+)=.5245. At0/200kHz they
are.4825 and.5696. Per-cycle positive fractions are also retained: the
zero-input nominal values span.3906–.6875 across64 trajectories per cycle.
Their finite-sample fluctuation and possible temporal variation are why
both pooled and cycle-centered summaries are reported.

The vote windows use the firstK post-startup cycles of each independent
trajectory. Their wrong-sign counts are:

| Input | K1 | K3 | K5 | K9 |
|---|---:|---:|---:|---:|
| −250µV | 15/64 | 16/64 | 13/64 | 7/64 |
| +250µV | 20/64 | 13/64 | 13/64 | 8/64 |

At−250µV theK3 error probability is.250 with Wilson95% interval
[.160,.368], versusK1=.234 [.147,.351]. Its paired error change is
+.0156 with trajectory-bootstrap interval[−.0781,.1250]: **no improvement
has been established** at this polarity. At+250µV,K3=.203 [.123,.317]
versusK1=.313 [.212,.434]; paired change−.1094 [−.2031,−.0313] favors
voting for this particular finite-band input/control.

K9 reduces both point estimates, to.109 [.054,.209] and.125 [.065,.228].
The negative-input paired improvement interval reaches zero; the positive
one excludes it. The independent-Bernoulli prediction is a comparator,
not a fit imposed on the observations. These limited input points cannot
establish a full noisy coarse-transfer curve or guarantee the modeled
20µV architecture target. In particular, the attractiveK3 system-level
prediction remains **SPECULATIVE** pending broader input/corner/noise and
actual coarse-DAC integration evidence.

Exact sources, exported device models, decks, traces and statistics are
under the two result directories named above and
`build/campaign/latch_correlation/tt16_fmin200k_zero64_postreset/`.
The separate analysis source
`build/campaign/latch_correlation/analyze.py` records its own hash and the
complete simulation-result hash in each `cluster_analysis.json`.
It adds Wilson intervals and paired vote-error differences without
changing any simulator evidence. An independent agent checked cycle
mapping, closing-reset coverage, whole-trajectory bootstrapping and
explicit handling of unresolved traces.

Reproduction uses the repository's cached Nix Python and pinned simulator
paths through the reused helpers. A new unique `--name` is required; the
testbench refuses to overwrite existing evidence:

```sh
python3 analog/testbenches/tb_imc_latch_correlation.py --name new_tt16 --workers 3
python3 analog/testbenches/tb_imc_latch_correlation.py --name new_lowcut --inputs-uv 0 --fmin-hz 200000 --workers 2
```

The useful retained mechanism is **coarse repeated sensing on a large
native holder**, where deterministic disturbance is much smaller than on
the boosted fine holder. Correlated slow noise, finite-range coarse
clipping, actual held-node noise, reference disturbance and PVT still
bound its value. No novelty or Mythic comparison is established by this
component experiment.
