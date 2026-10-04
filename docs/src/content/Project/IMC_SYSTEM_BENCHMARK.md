# Executable IMC system benchmark

The [benchmark](../../../../scripts/compiler/metrics/imc_system_benchmark.py) reports **TOPS,
watts, TOPS/W and fJ/MAC**, together with **tok/s and tok/J**, from one common
work/time/energy boundary. It uses cached circuit results, so architecture and
budget iterations do not rerun transistor simulations. It is a schedule and
cost model; it does not yet execute a complete transistor-level chip or generate
tokens on simulated hardware.

Run from the repository root in the existing Nix Python environment:

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 /nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3 scripts/compiler/metrics/imc_system_benchmark.py
```

Outputs are [the report](../../../../build/research/imc_system_benchmark/results.md),
`results.json` and editable `inputs.json` in `build/research/imc_system_benchmark/`.
The same run also writes [the comparison with equal weight positions and ADC count](../../../../build/research/imc_system_benchmark/mythic_comparison.md)
and `mythic_comparison.json`. Use that report for the Mythic hardware comparison;
the original single-macro token scenario is a separate diagnostic.
Supply `--config path/to/inputs.json` to change a scenario and `--out build/research/name`
to keep separate results. JSON overrides may contain just the changed fields;
unknown keys, invalid numbers and unsupported precision are rejected.
`--self-check` runs the independent arithmetic and failure controls without artifacts.
`--require-validated` writes the report and exits **1** while full-chip evidence
is unvalidated. Default exit **0** means the benchmark ran successfully, not that
the chip passed its acceptance gates.

## What the current run tests

The default scenario is one logical **128×8 W8A8 macro**, eight ADCs, an
8B-class shape model, batch one and a 2,048-token context. It assumes two W4
coefficient banks share the ADCs and are served serially. The array measurement
itself is W4A8; W8 loading, storage and bank selection remain unmeasured. This
default is a small reproducible scenario, not a proposed final chip size.

The circuit adapter reads matching TT/27°C and SS/85°C records from:

- `build/sim/imc_sizing_research.json`: the 366 ns retained-charge array fixture.
  It checks whole-word and per-plane accuracy and verifies that the array
  contains **zero physical ADC conversions**, preventing double counting.
- `build/sim/imc_null_sar_vcm_refs2_calibrated_suite.json`: the frozen no-holder
  converter's twelve-input tests. It uses **whole-cycle** time and sums positive
  delivery across all phases. The eight-column and deliberately wrong-bridge
  controls determine development-suite acceptance.
- The four predeclared `imc_null_sar_vcm_refs2_calibrated_seed9952_{tt,ss}.json`
  and `...seed9953_{tt,ss}.json` files: incomplete or failed regression remains
  visible. Circuit configuration must match the development suite.

Each consumed artifact is fingerprinted in the output. The adapter does not
select the cheapest stimulus or replace a failed candidate with another one.
Updating a SPICE artifact and rerunning the benchmark updates the report.
Converter energy is the twelve-input cohort mean, not a worst-case conversion
bound; the two corners do not constitute a complete PVT qualification.

Work counters include all seven weight projections per layer and the full LM
head. These Llama-class shape scenarios reserve separate untied embeddings;
they are not SmolLM checkpoint measurements. Useful MACs exclude padding,
weight slices, activation planes and ADC decisions. Partial tiles still pay
full array/ADC cost. Attention MACs, full-context KV reads, one KV append per
token, and aggregate fabric leaf traffic are separately counted. Reported TOPS
uses native **weight-MAC** work; attention energy/time is added when supplied.

The schedule loads a group of tiles once, reuses those weights across the batch,
then proceeds to the next group. Matrices, array/ADC phases and memory services
are serialized. No replication or overlap is free. This is one explicit schedule,
not a universal throughput ceiling over every possible architecture.

## Acceptance and missing measurements

The four quantities follow:

```text
TOPS    = 2 × useful_MACs / elapsed_seconds / 1e12
watts   = joules / elapsed_seconds
TOPS/W  = 2 × useful_MACs / joules / 1e12
fJ/MAC  = joules × 1e15 / useful_MACs
tok/s   = completed_scenario_tokens / elapsed_seconds
tok/J   = completed_scenario_tokens / joules
```

Null inputs mean **unknown**. They are omitted only from the explicitly named
`known_cost_projection`; they never become zero-cost evidence. The separate
`validated_chip_metrics` field stays null. This matters because array and ADC
are still separate acquisition/load fixtures, and the array's three specific
B7/B6/B5 words do not characterize a complete model's activity or worst-case
A8 timing. Even supplying every budget produces a projection, not silicon data.

The editable inputs cover:

- Macro count, ADC sharing, batch, context, W4/W8, KV precision and resident/streamed weights.
- Extra macro energy/time for reconstruction, weight selection, reference and clock
  generators, regulator losses, wiring and required checksum work. Add generator
  **overhead**, not the same delivered reference energy a second time.
- Programming, external-memory and fabric bandwidth/energy; attention and nonlinear costs.
- System-wide leakage and maintenance power, startup energy/time per batch, power cap,
  weight-storage capacity and KV capacity. Resident startup must include initial
  weight programming; startup also covers calibration and cold-start energy.
- Workload-quality acceptance. Entering `true` is a scenario assertion; it cannot
  waive the independent integrated-circuit/noise/layout/token-execution gates.

The memory gate requires known external, fabric and programming service rates,
and at least **1.2×** margin against weight compute under this serialized
schedule. A resident scenario must fit both storage bytes and physical tile
count. A power cap adds an explicit throttle interval and charges leakage during
that interval. Fabric bandwidth is aggregate leaf service, not an off-chip or
network-bisection specification. These screens are necessary conditions; they
do not independently establish that the eventual chip is compute-bound.

The report includes the [Mythic M1](https://www.mythic.ai/m-1) vendor baseline
of 25 TOPS at 3–4 W, or 6.25–8.33 TOPS/W by headline arithmetic. It deliberately
withholds a victory ratio until precision, workload and power boundaries match.
The research targets remain 100 and 250 TOPS/W **with complete accounting**.

## Matching Mythic's installed resources

The documented historical **M1076** uses 76 compute tiles, 79,691,776 logical
weight positions and 19,456 ADCs. The vendor's product brief specifies 76 tiles
and the 25 TOPS / 3–4 W headline; Mythic CTO Dave Fick's
[IEEE presentation abstract](https://events.vtools.ieee.org/m/307323) specifies
79.69M 8-bit weights and 19,456 8-bit ADCs. The
[official ISSCC preliminary press kit, page 46](https://www.isscc.org/s/ISSCC2022PressKit.pdf)
lists 1,024×2,048 physical flash cells per tile and seven additional control/I/O
tiles. Logical weight positions are distinct from the physical flash-cell count.
Current M1 branding alone does not prove identical tile-level implementation.

One 1,024×1,024 logical matrix needs 8 row groups × 128 output groups of our
128×8 macros: **1,024 small macros per equivalent tile**, or **77,824 total**.
Matching weight capacity while retaining eight ADCs per small macro would use
622,592 ADCs—**32 times Mythic's count**. Matching ADC count alone would retain
only 2,490,368 logical weight positions—**1/32 of Mythic's capacity**.

The new comparison matches both counts by proposing 256 shared ADCs per
equivalent group. A W4 slice produces 8,192 partial outputs, requiring 32
conversion rounds. Two serial W4 slices reconstruct each W8 operation:

```text
group time = 2 × (366 ns array + 32 × 295 ns ADC) = 19.612 µs
useful work = 76 × 1,024 × 1,024 native MACs per group cycle
conditional throughput = 8.12684 TOPS
```

This counts repeated independent group MVMs, not generated tokens. Array/ADC
fixture energy gives 32.67/33.52 fJ per native MAC at TT/SS, but shared-mux,
retention, reconstruction, physical storage, reference/control and routing
costs remain absent. The last partial output waits **9.145 µs** before service;
its leakage, noise and sampling disturbance must be tested. Each final output
combines 16 partials, requiring at least 15 additions (15,360 per group), plus
scale/gain correction. Output accuracy has not been demonstrated for this mapping.

The 366 ns array phase is the mean of three B7/B6/B5 words. Extending its
61 ns plane schedule to eight magnitude planes, including −128, gives a
**timing-only projection of 8.027 TOPS**; no energy or accuracy measurement is
assigned to that extension. At the same ADC count, reaching 16.6 or 25 TOPS
with the current mean array phase would require ADC cycles below approximately
**138.6 or 88.2 ns**, respectively, before any added overhead. These are inverse
timing requirements, not demonstrated circuit capabilities.

The ISSCC disclosure distinguishes its 8-bit **16.6 TOPS / 3.3 full-system
TOPS/W** point from **5.2 array TOPS/W**; the implied full-system power is
5.03 W. These preliminary figures are kept separate from the product's
25 TOPS / 3–4 W headline. Equal weight and ADC counts are useful architectural
constraints, but do not establish equal area, precision, workload or full-power
boundaries. Our converter is 10-bit and the process is sky130, versus the
published 8-bit ADCs and 40 nm process. A strict one-to-one end-to-end result
remains unvalidated, including the candidate's failed reserved ADC test.

## Analog storage and shared readout

The user's analog-latch suggestion has a concrete counterpart in
[Mythic US10255205B1](https://patents.google.com/patent/US10255205B1/en): local
DACs accumulate multilevel charge. Figure 3/claim 3 uses that state to generate
network inputs; Figure 4/claim 5 places a local DAC in ADC feedback. This is
evidence for disclosed analog state storage, not proof of a shipped output
sample-and-hold circuit. A regenerative binary latch alone does not retain an
arbitrary analog result.

[Mythic US10389375B1, Figure 6](https://patents.google.com/patent/US10389375B1/en)
also discloses multiplexing column currents into a shared readout. With stable
inputs, a current-producing array could maintain the selected weighted-sum
current instead of storing every result on an output capacitor. That is a
mechanism inference, not a verified production schedule. The patent's binary
comparator/FSM states and output shift chain do not establish a multilevel
analog-result FIFO.

Our passive array already retains its accumulated result on a disconnected
capacitor. The untested part is retaining accuracy over the shared-ADC waiting
interval and sampling it without excessive disturbance. Storage can decouple
array operation from readout, but does not by itself reduce the conversion count.
The report now includes two timing-only schedule controls:

- Ideal elimination of all array/hold overhead leaves 64 ADC rounds of 295 ns
  per group, limiting this specific mapping to **8.442 TOPS**. More throughput
  requires changing the service count, ADC period, or number of ADCs.
- Preparing 32 small macros and immediately converting their 256 outputs,
  repeated 32 times per slice, takes **42.304 µs / 3.768 TOPS** under a serial
  schedule. It avoids the long interbatch analog queue, while still requiring
  acquisition, conversion-time holding, multiplexing and digital partial sums.

Neither scheduling control claims measured energy or integrated retention.
A separate [bounded sample/hold experiment](IMC_HOLD_RETENTION.md) completed
three fixed levels at TT27 and SS85 with the smallest actual programmed
accumulator capacitance, 304 fF. Subsequent deterministic drift over 9.145 µs
is at most 72.57 µV with assumed diffusion geometry, but isolation and input
return introduce 1.68–11.43 mV of sampling error. A numerical-conductance-floor
control changes the drift appreciably; ideal-capacitor and transistor leakage
model exclusions also remain. This supports investigating analog storage;
it does not qualify retention through the shared mux or repair ADC accuracy.

## Verification

Self-checks use an independently calculated work/time/energy example, exact
model totals, an edge-padded small model, W4/W8 service-count controls, ADC
sharing, batch weight reuse, invalid inputs, failed accuracy, slow memory,
insufficient resident capacity and power throttling. They assert all reciprocal
metric identities and ensure partial evidence cannot populate chip metrics.

`scripts/compiler/metrics/test_imc_system_benchmark.py` adds eight cached-artifact tests
covering corrupt suite signatures, signed-net energy substitution, invalid PVT,
changed stimulus hashes, missing reset/closing frames, changed circuit identity,
failed regressions and incomplete coverage. All eight pass in about 1.8 seconds.
Mutated evidence exists only in memory and is never written as a circuit result.

During implementation, the legacy `scripts/compiler/metrics/report.py` TOPS/W expression
was also corrected: an extra `1e-3` understated its result by 1,000×. Its older
subset/projection assumptions otherwise remain; it is not the new benchmark's
measurement source.
