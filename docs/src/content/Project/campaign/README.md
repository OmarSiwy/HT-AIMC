# Analog IMC research campaign

Active research objective: derive and test the strongest area, delay, power and
throughput architecture supported by the whole repository and current primary
literature. State-of-the-art performance and novelty require evidence; they
are targets, not assumed properties of the final candidate.

The [optimization contract](OPTIMIZATION_TARGETS.md) defines area, latency and
power at matched throughput/capacity, the feasibility gates, free variables,
gm/ID workflow and evidence retention policy.

Latest comparison with the beginning of this session:
[current results and changed conclusions](SESSION_COMPARISON.md), updated
2026-09-11 around 13:35 UTC. This includes full-range pipeline failures and
the fresh comparator cohort that did not confirm the earlier sizing benefit.

Campaign started 2026-09-10 22:37:37 UTC. At 2026-09-11 01:32:38 UTC the user
extended the autonomous campaign: “Keep going. I will be back in 48 hours.
Use agents if needed to research in parallel.” The new consolidated-result
target is **2026-09-13 01:32:38 UTC** (2026-09-12 21:32:38 America/Toronto).
This supersedes the original ten-hour target of September 11 at 08:37:37 UTC.
The active goal spans context compactions and intermediate checkpoints.
Continue useful research until the new deadline; do not declare the objective
complete after one local fixture or report. Preserve progress on disk throughout.

## Initial evidence and boundaries

The starting repository HEAD is `7b8d241`; the working tree contains extensive
uncommitted research predating this campaign. Preserve that work. Research
reports go here or in `docs/src/content/Project/`; generated evidence belongs in `build/`;
physical testbenches belong in `analog/testbenches/`. Do not change `flows/`,
external notes or production behavior merely to make a research test pass.

The immediately preceding round is recorded in
[gm/ID product sizing](../IMC_GMID_PRODUCT_SIZING.md). A restricted positive
log/charge/exp scalar passes deterministic <1% screens with 600-fF state and
1.5-µs complete words, but has major area/noise/integration costs. The exact
current 128×8 normal-number charge core was freshly reproduced at TT27/SS85:
0.04277/0.10333 MAC RMS, 4.49981/4.58724 fJ/MAC ideal-interface delivery,
366-ns mean over the existing three-word cohort. Neither result qualifies
an integrated chip or competitor victory.

## Work streams

| Stream | First concrete deliverable | Purpose |
|---|---|---|
| Circuit archive | [CIRCUIT_EVIDENCE.md](CIRCUIT_EVIDENCE.md) | Trace successes and failures to physical mechanisms and exact tests |
| Workload/system archive | [SYSTEM_EVIDENCE.md](SYSTEM_EVIDENCE.md) | Identify accepted quality, capacity, converter and service constraints |
| Fresh primary literature | [SOTA_EVIDENCE.md](SOTA_EVIDENCE.md) | Compare strongest measured architectures and search useful gaps |
| Root integration | Experiments, population and campaign synthesis | Combine compatible mechanisms and test complete signal paths |

The first evidence map should cover all project design reports and follow
their relevant code, results and history. A failed report is not sufficient
grounds to reject a mechanism: distinguish fundamental limits, topology,
sizing, numerical failure, stale assumptions and incorrect accounting.

## Acceptance and search discipline

1. Compare candidates at an explicit workload, format, physical work count,
   weight capacity, converter count, accuracy, process and energy boundary.
   Keep native MAC/operation conventions visible.
2. Trace row inputs through the real computation and receiver. A replayed
   ideal voltage or separate passing ADC is not integrated evidence.
3. Derive sizing through actual-bias gm/ID data, pole/settling and noise
   budgets, then validate switches, device regions and complete transients.
4. Preserve at least three materially distinct architectural mechanisms
   until physical/system evidence rejects or combines them. Log multiplication
   is one candidate, not a required architecture.
5. Freeze calibration before new validation inputs. Report failed corners,
   solver aborts, timing controls, energy sources, parasitics and missing noise.
6. Give an independent critic the surviving circuit and its exact evidence.
   Resolve objections quantitatively. Record useful intermediate discoveries.
7. Recombine only compatible mechanisms: state, signal scale, impedance,
   resource occupancy and noise covariance must remain consistent.
8. Produce a final architecture, derivations, reproducible tests, strongest
   matched baseline comparison, prior-art assessment and unverified items.
   Use VERIFIED / STRONGLY SUPPORTED / SPECULATIVE / FAILED labels by claim.

## Time allocation

The first hour prioritizes whole-archive evidence and objective formalization.
The next phase screens diverse mechanisms with cheap analytical and small
transistor tests. Most of the remaining time goes to connected signal paths,
gm/ID sizing, corner/history/noise checks and independent criticism. Reserve
the final portion for fresh validation, honest matched comparison and a
self-contained evidence-backed report. Reallocate time when an experiment
reveals a stronger mechanism; do not spend the deadline polishing a weak one.

## Running record

- 22:37 UTC: goal created; three parallel archive/SoTA investigations started.
  Root preserving the completed log-sizing round and examining paths toward
  integrated normal-number and alternative IMC architectures.
- 23:55 UTC: whole-repository circuit/system maps and current SoTA comparison
  are available. [Candidate population](POPULATION.md) records retained and
  failed mechanisms. Connected core/SAR tests now include actual computed
  charge and paid final reset; first conversion controls fail, and balanced
  receivers are under test. Dense W8 fixtures replace sparse-load assumptions.
  An unclipped diagnostic isolates a strong range-extension opportunity on
  two model passages; finite hardware/noise remains under investigation.
  Explicit junction geometry and endpoint coverage have rejected several
  previously optimistic component conclusions. Campaign remains active.
- 01:30 UTC: finite Cu8 charge-range policies now pass both exposed model
  passages and all declared seeds with 20-µV final-conversion Gaussian read
  noise; every 50-µV case fails. Optimized separate-converter baselines reduce
  the apparent pooling area advantage, so mixed-depth quality comparisons
  remain active. Dense balanced low-digit sizing reaches 48.423 fJ/MAC and
  477 ns within the provisional deterministic charge-error allocation;
  matched original sizing, high digits and additional corners are running.
  Raw comparator noise is hundreds of µV, and repeated loaded fine reads
  reveal nonlinear kickback. Native-holder pipelining and current/PWM
  alternatives continue; no integrated SoTA or novelty claim is established.
- 01:32 UTC: user extends the campaign by 48 hours. All three parallel streams
  continue with their current frozen tests. The additional validation time is
  allocated to complete physical signal paths, programmable weight storage,
  mismatch/PVT, physical area and fresh workloads; the original acceptance
  gates and retained failures remain unchanged.
