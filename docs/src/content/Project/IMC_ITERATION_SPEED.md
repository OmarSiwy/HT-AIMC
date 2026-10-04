# Faster simulation iterations

Date: 2026-09-07. These are host-side research iteration improvements, not changes to predicted chip tokens/s or tokens/J.

## Implemented and measured

| Work | Before | After | Meaning |
|---|---:|---:|---|
| SmolLM2 research-model forward | 1.692 s | 0.923 s | 1.83× faster for the same workload |
| Top-five vocabulary selection | 0.270 s | 0.035 s | 7.80× in the underlying timed samples; displayed times rounded |
| Parse an existing 175-vector SPICE trace | 0.43235 s | 0.22200 s | 1.95× faster, five-run medians |
| Serialized size of that SPICE trace | 110,440,518 bytes | 56,142,179 bytes | 49.2% smaller; same 19,718 sample times and all 175 vectors |
| Full precision experiment after optimization | — | 130.4 s | All 64 cases retained |
| Quick screening experiment | — | 16.8 s | Reduced workload, **not** a same-workload speedup |

The model forward now uses batched matrix multiplication for attention instead of generic `einsum` contractions. The original summation order remains available with `Net(fast_attention=False)` for comparisons. Top-five selection uses `argpartition`, with the original full sort on boundary ties to preserve the selected set. Changes are in `scripts/compiler/metrics/depth_budget.py`.

Across all 64 original/optimized experiment cases, the largest absolute changes were **7.96e-7 in KL** and **2.087e-6 in perplexity ratio**. Argmax agreement and top-five overlap were identical. Floating-point summation order changes make this numerical equivalence, not bitwise equality. All 15 golden-model checks also passed. These timings and equivalence results were collected by the main research run; its original and optimized artifacts are `build/research/imc_precision_experiment_original.json` and `build/research/imc_precision_experiment.json`.

Both shared SPICE runners now enable ngspice's native `wr_singlescale` option. It writes the time or sweep scale once per row instead of repeating it for every vector. `load_wrdata()` accepts both the compact layout and historical scale/value pairs, preserving existing analysis dictionaries. It still parses and validates every numeric column and every row width.

This saves serialization, parsing and storage work. It does **not** claim a 1.95× speedup for the nonlinear SPICE solver: the measured 1.95× applies to parsing the existing large tile artifact. The output-format change leaves solver settings, timesteps, tolerances and sampled waveforms unchanged. Results are recorded in `build/research/spice_io_benchmark.json`.

For an external tool that requires legacy column pairs, use:

```python
run_ngspice(netlist, name, compact_output=False)
run_spice(netlist, name, timeout=9000, compact_output=False)
```

The full repository's Python consumers were checked: raw ngspice data is read through `load_wrdata`; the other `np.loadtxt` call reads generated sizing tables, not raw waveforms. Existing processes that already imported the old runner retain their existing behavior until restarted.

## Verification

`analog/testbenches/test_spice_io.py` was run against the old code and failed, then passed after the change. It runs a tiny RC fixture through both real ngspice-43 runners in legacy and compact modes and checks identical times, voltages and currents; one-vector output; single-row output; smaller serialization; and rejection of malformed rows and values. It does not run a heavy PDK simulation.

The real sky130 `tb_write_dac.py` also passed using the new default: all 16 levels monotone, error below 5 mV, worst settling 4.6 ns, and reported energy 1.208 pJ per code slot.

Run the checks inside the project's Nix environment with numpy and the pinned ngspice available:

```sh
python3 analog/testbenches/test_spice_io.py
python3 analog/testbenches/tb_write_dac.py
```

## Screening and full runs

The new `--quick` mode keeps all 30 model layers and all four protection configurations, but uses one 64-token note, one seed, Q8-dequantized weights and one noise level. Its JSON explicitly says `screening_only: true` and writes a separate filename, so it cannot overwrite the full experiment.

Inside the existing Nix numpy environment:

```sh
OPENBLAS_NUM_THREADS=2 python3 scripts/compiler/metrics/imc_precision_experiment.py --quick
OPENBLAS_NUM_THREADS=2 python3 scripts/compiler/metrics/imc_precision_experiment.py
```

Use the first command to catch errors and reject weak candidates quickly. Use the second for the existing two-note, two-seed, two-precision, two-SNR comparison. Neither is a substitute for held-out language-model quality validation with the true tokenizer and physical error distributions.

Outputs are `build/research/imc_precision_experiment_quick.json` and `build/research/imc_precision_experiment.json`. Keep one Nix shell alive across iterations; repeatedly entering the full environment adds setup work that the simulator runners themselves do not require.

## Findings that did not justify a change

An attempted selected-column parser reduced raw parsing from 0.432 s to 0.301 s, but validating every row before skipping duplicate columns raised total time to 0.512 s. First-row-only validation would miss malformed later rows. That approach was rejected; native compact output preserves normal whole-file validation while removing the redundant columns at their source.

No general simulation-result cache was added. Correct invalidation must include referenced models and files, startup configuration, simulator version/options and random controls, while outputs can be large. This audit did not demonstrate sufficient repeated identical work to justify that machinery.

Some older heavy testbenches, including tile MVM decks, omit explicit `save` vectors, potentially retaining many internal nodes beyond the checked signals. **General automatic vector pruning is not implemented.** A useful next experiment is to add explicit `save` lists to individual decks, preserving all vectors required by measurements and expressions, then compare their numerical outputs and peak memory. The new charge-average research probe already uses a targeted save list; that is not a blanket change to the older suites.

Do not globally enlarge timesteps or relax tolerances. The charge-average experiment separately demonstrated that a coarser step can be acceptable for a settled diagnostic while changing an unsettled circuit's error enough to fail its numerical-equivalence gate. Those circuit-specific results are in `docs/src/content/Project/IMC_CHARGE_AVERAGE_EXPERIMENT.md`.

### Matrix solver comparison

The cached ngspice 43 binary includes KLU, but the research logs confirmed Sparse 1.3 was active. The official manual describes KLU as a potentially faster alternative, with circuit-dependent results. [ngspice 43 manual, Sections 11.1.1 and 12.6](https://ngspice.sourceforge.io/docs/ngspice-43-manual.pdf).

The new [solver experiment](../../../../analog/testbenches/tb_imc_solver_speed.py) runs the same 16×8 signed physical accumulator with each solver, preserving devices, tolerances, phases and analysis. One execution took **18.10 s with Sparse versus 17.46 s with KLU: 1.036×**, too small a single-run difference to claim a material improvement. Reconstructed outputs differ by at most **2.73e−6 MAC**, delivered energy by **0.00129%**, and both deterministic gates and word time agree. No global solver setting changed. The result is in `build/research/imc_solver_speed_r16_tt.json`.

```sh
python3 analog/testbenches/tb_imc_solver_speed.py --rows 16
```

The existing model and waveform-I/O speedups remain the measured iteration improvements. A larger-array KLU comparison is supported by `--rows 128 --corner ss`, but has not been run; its benefit cannot be inferred from the manual or this smaller case.

### Closed null SAR comparison, 2026-09-09

The [closed SAR benchmark](../../../../analog/testbenches/tb_imc_null_solver_speed.py)
compares explicit Sparse and KLU selection on the same eight-column TT27
fixture. It measures one frame, including physical warmup and the closing
reset, over 591 ns. Settings are frozen: full-width acquisition switches,
capacitance-graded reference switches, 2.25 µm latch PMOS, 3.36 µm reset
switches, 23 ns trials, 12 ns settling, 2 ns clock edges, 2 ns resolution and
−1900 µV reference trim. The source and original/configured decks were
snapshotted; original deck hashes match across runs.

This is a **TT numerical benchmark**, not a qualified circuit configuration:
this candidate failed fresh eight-column SS input histories. It also does not
measure noise, complete reference generation or FSM energy.

| Setting | Probe wall time | ngspice analysis time | Trace rows | Total iterations |
|---|---:|---:|---:|---:|
| Sparse, requested 50 ps | 179.98 s | 118.008 s | 21,398 | 68,801 |
| KLU, requested 50 ps | 269.65 s | 202.789 s | 21,496 | 74,494 |
| Sparse, requested 100 ps | 226.72 s | 117.004 s | 16,597 | 60,379 |

All three runs produced exactly the same eight final codes, 80 receiver
decisions and trial-state histories; raw code error was zero on this row.
Relative to Sparse50, all-source delivered energy differed by 0.002670% for
KLU50 and 0.002868% for Sparse100. The largest signed net-energy difference was
0.003916%. All accuracy, feedback and 0.5% energy-equivalence gates passed.

Neither alternative produced an observed wall-time improvement in these
single, ordered runs. They do **not** establish an intrinsic slowdown: the
identical circuit's reported subcircuit/parameter expansion time varied from
56.30 s to 61.07 s to 100.04 s. The requested transient step cannot explain
that setup-work change; host/timing variability is material. Sparse100 reduced
rows by 22.44% and iterations by 12.24%, while its reported analysis time was
nearly unchanged. No solver or timestep default changed.

The profile identifies more useful work to investigate. The deck expands to
462,697 lines and 6,445 equations. Sparse50 reports 68.09 s loading the matrix,
17.91 s factoring it and 12.23 s solving it, plus 56.30 s of subcircuit/parameter
expansion. KLU reduced solve time to 7.01 s but did not improve total time.
These profiler categories overlap and must not be summed as disjoint phases.
Python parsing and analysis after the runner took only 0.22–0.32 s. Reducing
repeated PDK setup/model work while preserving the exact model equations is a
better next investigation than further parser optimization.

The JSON contains raw and parsed `rusage all`, energy boundaries, source/deck
hashes, complete decisions, runner/probe timings and trace row counts:
`build/research/imc_null_solver_speed_tt.json`. Reproduce inside the cached
NumPy/ngspice environment:

```sh
python3 analog/testbenches/tb_imc_null_solver_speed.py --selfcheck
python3 analog/testbenches/tb_imc_null_solver_speed.py --coarse-if-needed
```

The first command starts no simulator. The second runs each solver once at
50 ps, then adds one Sparse100 case only if KLU fails equivalence or its
observed wall speedup is below 1.10×. The wrapper changes only the local deck
and restores the imported runner in `finally`.

### HSA compatibility setting rejected at the model-identity gate

The proposed per-run `-D ngbehavior=hsa` optimization changes selected device
models in this circuit. A small compiled-model audit extracted the 12 unique
NFET/PFET geometries from the frozen Sparse50 deck, retained the full TT PDK
and model checks, and compared native and HSA operation. All instance geometry
fields matched, including `nf=m=1`; **7 of 12 selected model bins differed**.
All lengths below are 0.15 µm:

| Width | NFET native → HSA bin | PFET native → HSA bin |
|---|---|---|
| 0.42 µm | 170 → 161 | 107 → 107, unchanged |
| 0.84 µm | 80 → 71 | 89 → 80 |
| 1.00 µm | 71 → 62 | 80 → 71 |
| 1.68 µm | 53 → 44 | 53 → 44 |

This confirms the source-level distinction: native final selection accepts
geometry endpoints within 1 nm and takes the first matching entry from its
reversed model list; HSA's earlier pruning uses strict floating-point bin
bounds. Consequently, `nf=1` alone does not establish model equivalence.
[ngspice 43 native bin selection](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/parser/inpgmod.c),
[HSA subcircuit preprocessing](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/frontend/subckt.c)

The command-line definition is early enough: ngspice 43 processes `-D`
before circuit loading, and the HSA log confirms `hs a` compatibility modes.
No global initialization file or PDK file was edited.
[ngspice 43 startup source](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/main.c)

The tiny audit's expanded model-card count fell from 1,728 to 12; reported
deck lines fell from 20,568 to 18,852. Native/HSA wall times were 3.990/3.903 s,
with about 3.87 s spent loading the full PDK in each. These are small DC
model-selection controls, not SAR speed measurements. Since model identity
failed, the full HSA SAR waveform/code/energy comparison was not run and HSA
was not adopted. Faithful reduction of unused PDK families, retaining all
native bins, remains a separate candidate to evaluate.

Reproduce the failing equivalence check after creating the baseline artifact:

```sh
python3 analog/testbenches/tb_imc_null_solver_speed.py --hsa-bin-audit
```

It writes `build/research/imc_null_hsa_bin_audit.json` and exits with status 1
when bins differ. The JSON preserves exact commands; the two
`build/sim/imc_null_model_bins_{native,hsa}/` directories preserve decks, logs
and compiled model information.
Use `device_audit.txt` for complete selected model names and `model_audit.txt`
for numeric bounds/parameters. Ngspice truncates long lines in the expanded
listing; that listing establishes model-card counts, not complete model
fingerprints.

### Native-bin pruning: measured 1.49× on the frozen TT8 control

An isolated, opt-in ngspice 43 patch reduces repeated model expansion while
preserving native model selection. In the same-binary Sparse50ps comparison,
wall time fell from **216.566 s to 145.147 s**: an observed **1.492×** speedup,
or 32.98% less wall time. The complete parsed trace arrays were **exactly
identical**, including all saved voltages and power vectors. All eight final
codes, 80 receiver/trial decisions, both integrated energy metrics, 21,398
trace rows and 68,801 iterations also matched exactly. This remains the frozen
TT numerical control above; its physical circuit was not qualified across
corners by this experiment.

| ngspice `rusage` item | Pruning off | Pruning on |
|---|---:|---:|
| Expanded deck lines | 462,697 | 221,961 |
| Netlist loading | 4.596 s | 4.575 s |
| Subcircuit/parameter expansion | 74.071 s | 2.147 s |
| Netlist parsing | 26.321 s | 1.065 s |
| Total analysis | 136.592 s | 137.328 s |
| Reported maximum program size | 1,461.086 MB | 346.055 MB |
| Circuit equations | 6,445 | 6,445 |

Profiler categories overlap; do not add them as disjoint phases. Reported
program size is the simulator's metric, not a measured resident-memory peak.
One execution per setting was measured, with the other research compilation
paused and `OMP_NUM_THREADS=1` in both runs. This establishes the observed
benefit for this control, not a universal or median speedup. The practically
useful change is removing repeated model expansion; the circuit's transient
work and timestep sequence did not change.

The patch retains the union of every native-admissible bin for all proven
literal geometries in each audited NFET/PFET wrapper, in original card order.
Final selection still runs through ngspice's original double-precision
endpoint-tolerant matcher. Geometry conversion follows numparam's literal
parse and 15-digit scientific serialization before native parsing. No HSA
compatibility mode, model coefficients, PDK files, solver or timestep changes
are involved. The pass scans the reordered deck head, including global
parameters moved by ngspice preprocessing.
[Native matcher](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/parser/inpgmod.c),
[numparam conversion](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/frontend/numparam/xpressn.c)

This first implementation supports valid, nominal, audited SKY130 01v8
wrappers with direct `l={l}`, `w={w}`, `nf={nf}` bindings and literal positive
geometry. Global MC switches must be unshadowed zero. Every scale declaration
must be a proven positive SPICE literal with exactly the same native double
value: the full PDK declares `1.0u`, while the fixture also declares `1e-6`.
Unsupported geometry, multiplicity, scaling, active randomness, compatibility
modes or control mutations cause conservative fallback. Statistical model
expressions are accepted only by a constrained grammar that independently
proves their MC multiplier is zero. This is not a general optimization for
arbitrary PDKs or malformed model expressions.

Before timing, **35 acceptance gates passed**. An 18-geometry audit includes
the newer 0.735, 1.26 and 6.72 µm widths, at L=0.15 µm. TT and SS retain exactly
the pinned simulator's selected model names, geometry and readable model
coefficients. The union contains 10/180 NFET and 10/108 PFET bins for this
expanded geometry set. Symbolic widths, `nf=2`, enabled MC, a stochastic
voltage source and conflicting scale declarations all fall back. Out-of-range
geometry preserves the native model-selection failure.

Ten BSIM4.5 fields cannot be fingerprinted through `showmod`: `lintnoi`,
`llambda`, `lvtl`, `lxn`, `wlambda`, `wvtl`, `wxn`, `plambda`, `pvtl`, `pxn`.
The exact release's parameter table exposes them, but its model-query switch
has no corresponding getter cases, so `showmod` prints an uninitialized
value after `E_BADPARM`. They **do** have model setters. The audit excludes
only these unreadable output fields; the patch preserves their raw model
cards and does not claim these parameters are absent or inactive.
[BSIM4.5 model query](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/devices/bsim4v5/b4v5mask.c),
[model setters](https://sourceforge.net/p/ngspice/ngspice/ci/ngspice-43/tree/src/spicelib/devices/bsim4v5/b4v5mpar.c)

The archived physical wrong-bridge control was also replayed with pruning off
and on. Both retain codes **27/512** for target codes **31/511**, preserving
the **4 LSB failure** and both archived energy metrics. Faster preprocessing
does not turn that incorrect circuit into a passing result.

Source and reproduction:

- [ngspice patch](../../../../analog/testbenches/ngspice43_native_bin_prune.patch), against
  official `ngspice-43` commit `2af390f0b12ec460f29464d7325cf3ab5b02d98b`.
  `git apply --check` passes against the unmodified checkout.
- [Model/fallback and failure tests](../../../../analog/testbenches/tb_imc_native_bin_prune.py).
- [Frozen SAR benchmark](../../../../analog/testbenches/tb_imc_null_solver_speed.py).
- Artifacts: `build/research/ngspice43_native_prune/{build_manifest,audit_results,failure_replay}.json`
  and `build/research/imc_null_native_prune_tt.json`.

The isolated stock and patched builds use cached Nix GCC/autotools, with
`CFLAGS='-O2 -std=gnu17'`, `--with-x=no --with-readline=no --with-fftw3=no`,
and `--enable-xspice --enable-cider --enable-osdi --enable-klu --enable-openmp`.
They were built at two jobs under `build/research/ngspice43_native_prune/`;
the stock build's compiled devices/coefficients and the patched flag-off full
trace were checked against the pinned simulator. Build logs, recipes, compiler
closure, startup-file hashes and binary hashes are in that artifact directory.
No installed simulator, global configuration or flow file was changed.

```sh
python3 analog/testbenches/tb_imc_native_bin_prune.py --prepare  # no simulator
python3 analog/testbenches/tb_imc_native_bin_prune.py
python3 analog/testbenches/tb_imc_null_solver_speed.py --native-prune-benchmark
python3 analog/testbenches/tb_imc_native_bin_prune.py --failure-replay
```

The full benchmark requires the saved frozen baseline artifact. To use the
qualified local build for subsequent nominal circuit experiments, select the
wrapper only for that invocation:

```sh
NGSPICE="$PWD/build/research/ngspice43_native_prune/ngspice-native-prune" \
OMP_NUM_THREADS=1 python3 analog/testbenches/tb_imc_null_sar.py --validate
```

Check the two `nativebinprune: ... kept ...` log messages before attributing a
new run's speed to pruning. Fallback is intentional and preserves the original
deck. This simulator validation does not qualify a new circuit topology or
establish intrinsic transient-noise accuracy.
