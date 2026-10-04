# AnalogIOC analog storage integration — new-session handoff

Updated: 2026-09-09. Workspace: `/home/omare/Documents/Projects/Research`.

## User objective and authorization

Integrate analog storage/readout into the actual IMC signal path and optimize
**tokens/s and tokens/J together**, at preserved workload accuracy. The user
wants substantially better results than Mythic, a comparison with equal
resources, fast simulation iterations, and a compute-bound operating point.
They authorized architecture changes, circuit sizing, independent primary-source
research, and experiments. Proceed with implementation and verification; do not
stop at a proposal or repeatedly ask whether to continue.

Treat “optimally” as a requirement to compare viable alternatives under explicit
constraints and find the best supported throughput/energy tradeoff. Do not
claim a global optimum or a competitor victory from isolated component tests.
Do not force an analog latch or double buffering if another connection has
better measured accuracy, energy and service time.

**Current truth: the new hold test is standalone. It has not been integrated
into the array-to-ADC path. There is no demonstrated token-rate improvement
from analog storage.** The system report combines separate circuit fixtures;
it is not an integrated transistor-level measurement or hardware token run.

## Read first

1. `AGENTS.md`, then `docs/src/content/Project/CONTRACT.md`. The contract describes the
   original mini architecture and contains old migration paths. Follow current
   AGENTS paths; keep research alternatives and production acceptance distinct.
2. `docs/src/content/Project/IMC_SYSTEM_BENCHMARK.md` and
   `build/research/imc_system_benchmark/mythic_comparison.md`.
3. `docs/src/content/Project/IMC_HOLD_RETENTION.md`.
4. `docs/src/content/Project/IMC_SIZING_RESEARCH.md`, especially the current 128-row result.
5. `docs/src/content/Project/IMC_NULL_SAR.md`, including its latest seed-9953 failure;
   `IMC_NULL_SAR_REVIEW.md` for connected capacitance and noise pitfalls.
6. `docs/src/content/Project/IMC_ITERATION_SPEED.md` and `IMC_TRANSIENT_NOISE_PATH.md`.
7. Latest entries of `docs/src/content/Project/STATUS.md`; append updates, never rewrite it.

Use the user's notes before inventing a topology:

```text
~/Documents/Projects/OmarSiwy.github.io/Notes/Circuit Design/Analog Design/Analog Compute/
```

Relevant notes include `27h10` (null-balancing SAR), `27g2` (kT/C), and `27h3`
(column/converter accounting). The paper is present in that directory's
`paper/`: `main.pdf`, `sec_arch.tex`, `sec_circuits.tex`, `sec_laws.tex`,
`sec_eval.tex`, etc. The AGENTS reference to `Digital Design/paper/` was absent
at this checkpoint; use the located Analog Compute paper rather than stopping.

Leave `flows/` and external notes untouched. Schematic generators belong in
`analog/schematics/`, self-checking SPICE tests in `analog/testbenches/`,
research documentation in `docs/src/content/Project/`, generated artifacts in `build/`.
Existing work directories are scaffolded. There are many uncommitted research
files and modifications; preserve them. No simulation is active at handoff.

## Existing circuit evidence

### Array: retained significance accumulation already exists

`analog/testbenches/tb_imc_sizing_research.py:matrix_probe()` constructs the
current research array. The accepted deterministic configuration is the
`--share-settling` branch, stored under `share_settling_repair` in
`build/sim/imc_sizing_research.json`:

```python
matrix_probe(width=.42, evaluate_ns=8, replay=True, endpoint_mos=True,
             accumulate=True, accumulation_bits=7, dynamic_bits=True,
             array_reset_width=3.36, accumulator_reset_width=3.36,
             nrows=128, share_width=6.72, share_hold_ns=15.6,
             corner=corner, temp=temp)
```

- 128 rows × 8 signed W4 outputs; 4-fF unit capacitors; 1.8-V supply.
- Physical row drivers, resets and sharing switches, with ideal capacitors and
  fixed programmed weights. Memory/programming circuitry is not complete.
- Three saved FFN-down words use seven/six/five magnitude planes. Each plane
  costs 61 ns; mean array word time is 366 ns. An eight-plane timing extension
  is 488 ns, with no corresponding full-range energy/accuracy measurement.
- TT27/SS85 array positive delivery: 4.4998/4.5872 fJ per native W4A8 MAC.
  Whole-word and per-plane deterministic gates pass; zero ADCs are instantiated.
- Weights and activations come from `scripts/compiler/out/programming/ffn_down.npz`
  and `scripts/compiler/out/acts/ffn_down.npz`; preserve their hashes and calibration split.
- Actual accumulator values are **568, 484, 304, 600, 516, 336, 444, 424 fF**.
  The rule is `Cacc = 120 fF + 4 fF * sum(abs(column_weights))`.
- The research generator has **one `out{col}` and one `acc{col}` per signed
  output**. Weight sign selects positive/negative row buses. It does not already
  provide a free pair of differential stored outputs. A differential redesign
  must explicitly construct and account for its second node and circuitry.

### SAR: actual decisions, separate voltage acquisition, failed reserved case

`analog/testbenches/tb_imc_null_sar.py:probe()` constructs a ten-decision
comparator-directed split-CDAC SAR. Physical receivers drive decision storage
and DAC selection; Python must never substitute ideal decisions. Some decision
storage/control is behavioral XSPICE, so complete realizable control energy is
still missing.

Current fixed candidate and evidence:

```text
build/sim/imc_null_sar_vcm_refs2_calibrated_plan.json
build/sim/imc_null_sar_vcm_refs2_calibrated_suite.json
build/sim/imc_null_sar_vcm_refs2_calibrated_seed9952_tt.json
build/sim/imc_null_sar_vcm_refs2_calibrated_seed9952_ss.json
build/sim/imc_null_sar_vcm_refs2_calibrated_seed9953_tt.json
build/sim/imc_null_sar_vcm_refs2_calibrated_seed9953_ss.json
```

Read the suite's `config` rather than using the CLI defaults. It uses VCM-start,
RC-graded reference switches scaled by 2, full acquisition switches, no extra
negative holder, 2.25-µm latch PMOS, 3.36-µm reset, a physical startup pulse,
23-ns trials, 12-ns settling, 2-ns resolution and edges, and frozen −1900-µV
reference trim. Complete paid service is **295 ns**, not just ten trial windows.
The twelve-input TT/SS energy is **1.514672/1.558079 pJ per conversion**.

Development suite and both 9952 corners pass. Reserved 9953 TT passes, but
**9953 SS fails**: input 1017.98088 code units returns 1019 versus ideal floor
1017, exceeding the one-code gate. The suite remains unqualified. These seeds
are now exposed; future confirmation must use new inputs frozen before tuning.
Preserve the failure, input history, calibration and exact trial decisions.

`build/sim/imc_null_sar_fresh_failure_trace.json` records the early diagnosis:
small weighted bottom-plate error (~31 µV) does not explain this case. Similar
comparator input charge entering a floating positive node and a stiff negative
reference can create unequal voltage disturbance. This is a candidate mechanism,
not a demonstrated repair; blanket switch widening is not justified.

### Standalone hold test: retention passes an illustrative gate, capture does not

`analog/testbenches/tb_imc_hold_retention.py` and
`build/sim/imc_hold_retention.json` use a 304-fF ideal capacitor and the array's
6.72-µm sample/isolation and 3.36-µm reset TGs, all L=0.15 µm.

- Fixed levels: 0.65, 0.90 and 1.15 V, TT27 and SS85.
- Hold interval: **9.145 µs**, from 220 ns after acquisition to 9365 ns.
- Maximum drift: 30.91 µV with native geometry; 72.57 µV with assumed nonzero
  diffusion geometry; 44.22 µV in the SS lower-gmin numerical control.
- **Isolation and input return shift the sample by 1.68–11.43 mV.** Holding an
  already shifted sample is not accurate analog capture. No offset was fitted.
- Illustrative 100-µV drift allowance corresponds to 3.324 pA. An injected
  100-pA discharge correctly fails; integrated current agrees with `C*deltaV`.
- Complete reset/acquisition/hold positive delivery is 40.68–138.25 fJ in this
  fixture. Hold-only energy is not the cost of a complete storage service.
- Native wrappers omit diffusion areas/perimeters; sensitivity geometry is
  assumed, not extracted. Direct gate-tunneling model options are disabled.
  Capacitor dielectric leakage, noise, mismatch, ADC, mux, read disturbance,
  neighboring activity and real clock/reference generators are absent.
- Five tiny runs took **21.12 s**; deterministic drift is numerically sensitive.

Do not transplant its ideal voltage input into an “integrated” benchmark and
call the result a real IMC-to-ADC connection.

## Architectural comparison and output cadence

Historical M1076 anchor: 76 compute tiles, 79,691,776 logical weight positions,
19,456 ADCs (256/tile). Logical tiles are 1024×1024; physical flash arrays are
1024×2048. Published ADCs are 8-bit at 40 nm; our current converter is 10-bit
at sky130. Equal counts do not establish equal area, quality or power boundary.

Matching weights alone with eight ADCs per small macro would give us **32×**
Mythic's ADC count. The joint-count mapping instead uses 1024 small 128×8
macros per group behind 256 ADCs. Eight row partitions and two serial W4
banks produce 16,384 scalar partial conversions per W8 group: 64 ADC rounds.
Final reconstruction needs at least 15 additions/output, plus scale correction.

| Schedule | Group cycle | Vector cadence per group | Conditional native TOPS, 76 groups |
|---|---:|---:|---:|
| Current separate-fixture composition | 19.612 µs | 50.989 k vectors/s | 8.12684 |
| Eight-plane A8 timing extension | 19.856 µs | 50.363 k vectors/s | 8.02697 |
| Ideal elimination of array/hold overhead | 18.880 µs | 52.966 k vectors/s | 8.44193 |
| Serial just-in-time small groups | 42.304 µs | 23.638 k vectors/s | 3.76758 |

The first row is `2 * (366 ns + 32 * 295 ns)`. Reconstruction latency and the
real mux remain unpaid. A vector has 1024 output components; vector cadence is
not a scalar sample rate, clock frequency, or token rate. A single standalone
ADC's configured service rate is 3.390 MS/s. Do not confuse these quantities.

**Storage-only overlap has at most 3.88% throughput headroom in this fixed
mapping**, even granting perfect buffering. It cannot reach 25 TOPS here.
Reaching 16.6/25 TOPS with unchanged service counts and mean array phase requires
ADC cycles no longer than about 138.6/88.2 ns before added overhead. Alternatively
reduce service count, or explicitly pay for more converters/resources.

The fixture-only TT/SS projections are 61.225/59.667 TOPS/W, 32.666/33.520
fJ/MAC, and 0.13274/0.13620 W at the first-row cadence. They exclude major
integrated costs and fail the reserved ADC gate; they are **not chip results**.
Keep M1076's 25-TOPS/3–4-W product headline separate from the preliminary ISSCC
8-bit 16.6-TOPS/3.3-full-system-TOPS/W disclosure (5.2 is array-only TOPS/W).

## Integration sequence

1. **Freeze a reproducible before case.** Snapshot source/config/model/program
   hashes and existing results under a new `build/research/` experiment path.
   Keep current artifacts intact. Define native signed W8/A8 work, output range,
   quantizer convention, calibration inputs and untouched confirmation inputs.
   Inspect the actual bank format; do not assume all W4 encodings combine the
   same way. Retain identical workload, batch, context, capacity and resources
   for every before/after result.

2. **Solve the connected charge and range equations before sizing.** The SAR's
   effective coarse-node capacitance is 768 fF, but voltage acquisition loads
   the source with **948 fF**, plus filter/device/mux capacitance. A simplistic
   neutral passive sample from 304 fF retains only `304/(304+948) ≈ 0.243` of
   its initial signal; derive the actual switched transfer and offsets instead
   of applying that ratio as a circuit result. Reusing the CDAC as the accumulator
   also changes `h_next=(Cacc*h+Carr*partial)/(Cacc+Carr)`: the current radix-half
   recurrence requires matched capacitances. Track whether the split DAC's fine
   node is floating or clamped in each phase; that changes the load. Direct
   positive held-residue sensing also changes the existing voltage-sampling
   decode polarity. Include comparator/filter loading, actual voltage range,
   gain, mismatch sensitivity and kT/C in this decision. Calibration cannot
   restore input-referred noise margin lost to passive attenuation.

3. **Build the smallest real connected experiment.** Use actual row-driven
   accumulation, retention, selector and comparator-controlled conversion in
   one netlist, initially one useful column and then two independently driven
   stored outputs sharing a converter. First attach the physical ADC acquisition
   network with the comparator inactive to isolate loading from kickback, then
   enable closed conversion. Reuse/refactor the existing generators
   minimally; freeze the old behavior as the baseline. No ideal unity buffer,
   waveform replay source replacing the loaded accumulator, or Python-selected
   SAR bits in the accepted signal path. Include a zero-wait control and the
   9.145-µs wait, worst input histories, and real reset/acquisition cycles.
   A reduced prototype must not claim full 32-way mux fan-in qualification.

4. **Compare storage connections before choosing one.** Start with retaining
   the existing accumulator, direct charge-domain conversion using a correctly
   matched CDAC, and an explicit transfer/sample stage where needed. Investigate
   differential sensing and sampling-sequence cancellation if they address the
   measured disturbance; the present array has no free second stored output.
   Add a second storage bank only when a schedule demonstrates useful overlap.
   Switching noise, mismatch, settling, kickback and clock/buffer energy all
   belong in the comparison. Preserve exposed failing cases as regressions.

5. **Explore conversion-count reductions for substantial throughput gains.**
   Combining eight row-partials before readout could reduce 16,384 services to
   2,048/group, but an 8× sum range requires three more bits at fixed absolute
   LSB, or equivalent precision loss after normalization. Weight-dependent
   capacitances preclude simply joining nodes. Combining W8 banks requires the
   exact signed high/low coefficient weighting, scaling and noise transfer.
   Neither operation is free or already proven. Keep ordinary W8 as the quality
   reference: earlier W4–W7 format screens did not establish an equal-quality
   single-bank replacement on the checkpoint.

6. **Qualify the best candidates in stages.** Separate sampling error, hold
   drift, read disturb, conversion error and reconstructed MAC error. Use frozen
   calibration, input order, TT27/SS85, near-threshold/rail/zero transitions,
   repeated history, earliest/latest mux slots and simultaneous-neighbor
   activity. The existing ADC one-code gate is a floor, not an end-to-end MAC
   accuracy guarantee. Preserve the array's RMS <0.25 MAC and maximum <1 MAC
   gates and the existing model quality gates; do not loosen them to accept
   integration. Then test relevant additional PVT, geometry,
   mismatch/noise and reference impedance on finalists. A deterministic PASS
   cannot become an ENOB/yield claim. A full physical noise path remains open.

7. **Propagate integrated evidence into the system and token benchmark.**
   Extend `scripts/compiler/metrics/imc_system_benchmark.py` and its evidence tests to
   consume integrated service time/energy once; do not add the old standalone
   ADC/array costs again. Count all physical partials/banks, warmup, reset,
   mux/control/reference generation, reconstruction and bank maintenance.
   Report pipeline initiation interval separately from first-result latency;
   charge leakage during queues and amortize programming/calibration explicitly.
   Use a real checkpoint/prompt and exact mapping to compare tok/s and tok/J at
   equal quality. Clearly distinguish measured circuit timing, counted workload
   schedules, software token execution and any actually simulated token path.
   A single 79.7M-weight device cannot hold the default 8B-class model. Choose
   a capacity-feasible workload or explicitly account for identical streaming
   or multiple chips. Demonstrate external/fabric/programming service margin;
   the user's compute-bound requirement is an acceptance condition, not a free
   assumption. Keep unknown chip/token metrics null.

## Fast iteration and commands

Use the installed Nix Python and pinned simulator; avoid rebuilding the full
environment for each run. From the repo root:

```sh
IMC_PYTHON=/nix/store/qk5sl1xvg05cmqh03mn1srdggj39dg7p-python3-3.12.13-env/bin/python3
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export NGSPICE="$PWD/build/ngspice43/bin/ngspice"

# Cached-artifact arithmetic and evidence checks; no new transistor sweeps.
"$IMC_PYTHON" scripts/compiler/metrics/imc_system_benchmark.py --self-check
"$IMC_PYTHON" scripts/compiler/metrics/test_imc_system_benchmark.py
"$IMC_PYTHON" scripts/compiler/metrics/imc_system_benchmark.py --out build/research/imc_handoff_baseline

# Optional, qualified native-bin pruning build for faster local experiments.
export NGSPICE="$PWD/build/research/ngspice43_native_prune/ngspice-native-prune"
"$IMC_PYTHON" analog/testbenches/tb_imc_hold_retention.py
```

The hold command regenerates its existing artifact; snapshot it first if used
for a new comparison. The current array's `--share-settling` command also writes
the baseline JSON; do not launch it casually as a read-only check. Use new
output names for changed candidates. Obtain the SAR candidate reproduction
command from the end of `IMC_NULL_SAR.md`; plain CLI defaults are a different
configuration. PDK: `~/.volare/sky130A`.

Eight benchmark evidence tests pass in about 1.8 s; the benchmark refreshes in
well under a second. The optional native-pruning simulator preserved complete
TT8 traces exactly and showed 1.49× wall speedup in one controlled run. Its
benefit is circuit-dependent; preserve provenance and confirm a selected
integrated case against stock ngspice. HSA compatibility mode changed model
bins and was rejected. KLU did not demonstrate a useful speedup. Do not globally
relax timesteps/tolerances, swap BSIM revisions, or equate model DC agreement
with transient-noise equivalence. Use compact saved vectors and one heavy SPICE
lane while other agents handle equations, code/trace review and documentation.

## Deliverable for the next session

Deliver a reusable connected circuit and self-checking testbench, a documented
selection among storage/readout alternatives, preserved failures and fresh
confirmation, and a reproducible before/after table containing:

- Useful result cadence, first-result latency and ADC service count.
- TOPS, complete accounted watts, TOPS/W and fJ/native MAC.
- Tok/s and tok/J for the same feasible workload, with measurement/projection
  boundaries, output quality, capacity and memory-service margin stated.
- Resource counts and costs added for storage, muxes, converters and references.

If no tested design improves both objectives at accepted quality, report that
explicitly and identify the measured limit. A working standalone hold, a passing
development-only ADC or a higher analytical TOPS number does not finish this task.

## Primary research anchors already checked

- [Mythic M1076 product brief](https://mythic.ai/wp-content/uploads/2022/03/M1076-AMP-Product-Brief-v1.0-1.pdf): historical product headline and tile count.
- [Mythic CTO IEEE talk](https://events.vtools.ieee.org/m/307323): weight and ADC counts.
- [Official preliminary ISSCC 2022 press kit](https://www.isscc.org/s/ISSCC2022PressKit.pdf), printed page 46: paper 15.8, full-system versus array results.
- [US10255205B1](https://patents.google.com/patent/US10255205B1/en), Figures 3/4 and claims 3/5: multilevel charge state for network-input DACs and ADC cancellation references.
- [US10389375B1](https://patents.google.com/patent/US10389375B1/en), Figures 6/8: column-current mux and binary comparator/FSM decisions. Stable-input current regeneration is a plausible mechanism inference, not a verified production schedule.

Neither patent proves a shipped lossless multilevel output latch. Do not assume
the current M1 product has identical internals to the documented historical
M1076. Check primary sources when extending the research; cite any new claims.
