# sysreference: digital systolic-array baseline

This is the digital design the analog IMC tile has to beat under `docs/src/content/Project/ARCH_METRIC.md`.
It is a weight-stationary INT8 systolic array (TPU-MXU style), optimized the way a competent
digital team would do it, so the comparison is not against a strawman (note 27n9). The arch
scorer `scripts/compiler/metrics/arch_eval/baseline_systolic.py` reads `build/ppa.json`.

## How to use

Each `make` target runs in its own `nix-shell` with python3+numpy, iverilog, verilator, yosys
and openroad. If those tools are already on PATH (inside `./env.sh mixed`), pass `NIX='sh -c'`
to skip the extra shell.

```sh
cd digital/sysreference
make test                          # regression, bit-exact, prints PASS/FAIL per case
make lint                          # verilator -Wall over every configuration the PPA study uses
make ppa                           # synth + place + power + report -> build/ppa.json (hours)
python3 scripts/score.py           # score build/ppa.json with the ARCH_METRIC scorer
python3 scripts/score.py variants  # score every entry of build/ppa.json "variants"
```

### Regression

`python3 test/run_tests.py` runs every case: numpy golden, then the cycle-exact schedule
(`test/sched.py`), then iverilog. It checks each INT8 output row, each column's INT32
accumulator, and that the RTL's last-output cycle equals the scheduler's prediction. A failing
case exits non-zero. `run_tests.py real` runs only the SmolLM2 GEMM, and `run_tests.py vcd`
writes an RTL VCD of a 16x16 prefill GEMM.

When the RTL changes its pipeline depth or an issue rule, update `test/sched.py` in the same
commit (`Cfg.lat`, the issue constraints in `schedule`). Otherwise the cycle check fails.

### PPA flow

The `make` targets call `python3 scripts/ppa.py <step>`. Run them in this order, or use
`make ppa` (`ppa.py all`).

| Step | What it runs | Output |
|---|---|---|
| `make synth` | yosys -> ASAP7 RVT (asap7sc7p5t_28): every `CONFIGS` entry at TT, s8/s16 also FF/SS, 4 in parallel | `build/ppa/synth/<cfg>_<corner>.{v,json}` |
| `make place` | OpenROAD floorplan, place, CTS, repair_timing, STA: s8 at TT/FF/SS, plus every `VARIANTS` entry at TT and its utilization. Runs serially because of OpenROAD memory | `build/ppa/place/<tag>.{json,odb,timing.rpt,r2r.rpt}` |
| `make power` | the synthesized netlist simulated at gate level on RTL-checked stimuli (random dense, plus SmolLM2 real data per variant), then VCD -> OpenSTA `report_power` | `build/ppa/power/<case>/power.json` |
| `make report` | python only: the area fit, the derived 128x128 numbers, the variants, the SRAM model | `build/ppa.json` |

- `place` resumes: a run that already wrote its `.odb` and logged `Design area` is reused.
  Delete `build/ppa/place/<tag>.*` to redo it. `synth` and `power` always rerun.
- The cell library and ORFS asap7 platform files default to pinned nix store paths. Override
  them with `ASAP7_SC` (`.../asap7/libs.ref/asap7sc7p5t`) and `ASAP7_ORFS_TEST` (ORFS `test/asap7`).
- The `PERIODS` dict in `ppa.py` sets the target clock period per corner (TT 650 ps).
  `repair_timing` only works as hard as this target asks, so tighten it when fmax stops moving.
  fmax is read from STA register-to-register paths.

### Variants

`VARIANTS` in `scripts/ppa.py` maps a name to (synth config, placement utilization %):
`base`, `int4w`, `nopipe`, `int4w_u80`. Every variant is placed and power-measured at s16. The
128x128 numbers come from the s8/s16/s32 area fit plus the variant's measured s16 area delta.
`DEFAULT` (`int4w`) is the variant written to the top level of `build/ppa.json`, which is
what `baseline_systolic.py` reads. `report` also adds `DEFAULT` at 64x64 and 256x256.

To add a variant:

1. Add a `CONFIGS` entry. Its keys are `sa_top` parameters (`Rows`, `Cols`, `AccDepth`, `WW`,
   `PipeMul`) plus synth switches (`_booth=0`, `_cg=0`, `_adder="ripple"`).
2. Add the entry to `VARIANTS` with its placement utilization.
3. Rerun `make synth place power report`, then `python3 scripts/score.py variants`.

### Recording a version

Score the default configuration with `python3 scripts/score.py` and add a row to `VERSIONS.md`
with the metrics and their label (measured / derived / projected). Commit it as
`sysreference vN <config>: tok/s/die=... TOPS/W=... tok/W=... tok/J=... (<label>)`.

## Design (src/)

| Module | What it does |
|---|---|
| `sa_pe` | One MAC cell: signed `AW x WW` multiply (Booth), registered product (`PipeMul`), psum add, two weight banks. Zero and bubble operands are isolated: the activation register holds and the product is masked, so a zero costs one flag flop toggle. |
| `sa_top` | `Rows x Cols` array. Input skew, a tag that travels with each token, per-column `sa_edge`, output deskew. Double-buffered weights: each token carries the bank it was issued against, so the next tile loads one row per cycle while the current tile computes. The steady-state tile period is `max(M, Rows)`. |
| `sa_edge` | Per-column INT32 K-tile accumulator (`AccDepth` slots) and the INT8 requant from `scripts/golden/model.py`, in 8 stages. The 32-bit accumulate is split into two 16-bit halves, so the slot read-modify-write spans 3 cycles. `sa_ctrl` therefore starts tiles at least 3 cycles apart. Requant parameters are double-banked. |
| `sa_ctrl` | Tile controller, `test/sched.py` in hardware. It runs a loader, a streamer and a requant engine, and each starts its next action at the earliest legal cycle. |
| `sa_sram` / `sa_sys` | Behavioural 1R1W SRAMs with a 1-cycle read (fakeram7 timing), plus a tile with wbuf/abuf/rqbuf/obuf. Synthesis treats the SRAMs as blackboxes and charges them from the SRAM model. |

Formats: signed INT8 x INT8 -> INT32 (the default), and INT8 x INT4 (`WW=4`). **FP8 was not built.** The
analog candidates are scored with INT weights, and an FP8 datapath needs an exponent
aligner per PE. Add it if a candidate is scored in FP8.

## Verification (measured)

- 15 `sa_top` cases and 7 `sa_sys` cases. They cover random GEMM and GEMV (M=1), padding,
  K chunking, sparse X, INT8 min/max saturation, mixed rounding, back-to-back jobs, 4x8 / 4x16 /
  8x8 / 32x32 shapes, INT4 weights, and a real SmolLM2-135M blk.0 attn_q GEMM (cosine 0.9996
  against float). Each case is bit-exact against numpy, and the RTL cycle count matches the scheduler.
- **Gate-level:** the synthesized s16 netlist is simulated on the power stimuli and passes
  against the golden. This check caught a yosys 0.62 front-end bug: `-N'(x)` evaluates to `+x`,
  so every output of the netlist saturated to -128 while RTL simulation passed. `sa_edge`
  now writes the bound as `~OutMax`. The netlist from before the fix had wrong area and power, and
  every PPA number below comes from the fixed netlist.

## PPA, ASAP7 RVT, TT 0.7 V 25 C (`build/ppa.json`)

These are the v1 numbers: base INT8 PE, 7-stage edge, 800 ps TT target. `VERSIONS.md` scores
each version.

The flow is yosys (Booth, Kogge-Stone adders, ICG clock gating), then OpenROAD placement, CTS and
repair_timing. Parasitics are placement RC from the ORFS asap7 `setRC`; there is no detailed route.
Power comes from a gate-level VCD at 99.9 % array utilization through OpenSTA.

| Quantity | Value | Label |
|---|---|---|
| PE cell area, 16x16 (mult + 2 weight banks + psum + product regs) | 65.3 µm² | measured |
| Array cell area, 8 / 16 / 32 square | 8 063 / 27 229 / 97 719 µm² | measured |
| Area per PE at 128x128 (incl. edge, skew, deskew), cell / at 70 % util | 86.7 / 123.9 µm² | derived (3-point quadratic fit) |
| fmax reg-to-reg, s16 TT / s8 TT / s8 FF / s8 SS | 1150 / 1163 / 1516 / 715 MHz | measured (critical path: the requant pipeline in `sa_edge`, not the PE) |
| fmax with ports constrained, s16 TT | 1031 MHz | measured (the port paths see the full clock insertion delay against an ideal external clock) |
| Dynamic energy per MAC, s16, SmolLM2 real INT8 data | 300 fJ (PE 181, edge 55, clock tree 41, other 24) | measured |
| Dynamic energy per MAC, s16, uniform random INT8 | 371 fJ | measured |
| Energy per MAC at 128x128, real / random data | 252 / 321 fJ | derived (edge amortized over 128 rows instead of 16) |
| Leakage, s16 / per PE at 128x128 | 23.8 µW / 76 nW | measured / derived |
| 128x128 array: peak, power at fmax, TOPS/W, TOPS/mm² | 37.7 TOPS, 4.75 W, 7.9, 18.6 | derived; excludes SRAM, HBM, PHY |
| SRAM (fakeram7), area / read energy | 0.043 µm²/bit, 84 fJ/bit | projected, an uncalibrated placeholder macro |

Ablations at 16x16, measured synth area: no Booth +8 %, no clock gating +13 %, INT4 weights
-24 %, product register removed -7 % (fmax with it removed not measured).

## Caveats

- **The power density cap binds.** 4.75 W on 2.03 mm² is 2.3 W/mm², over the 1 W/mm² cap
  in ARCH_METRIC. At peak clock the die is thermally limited, so the scorer must
  lower clock or VDD (`baseline_systolic.tile` does this through its op-point sweep).
- **This energy is an open-source-flow number.** yosys/abc does no power-aware sizing, and
  parasitics come from placement only. The arch_eval literature placeholder was 100 fJ/MAC. The
  measured 252 fJ is 2.5x that, partly because the flow is open source and partly because it counts
  edge, skew and clock overheads that a bare-MAC figure leaves out. A commercial flow would likely
  narrow the gap. Treat 252 fJ as an upper bound, not a floor.
- Arrays of 64x64 and 128x128 were not synthesized: s128 took more than 45 min in yosys. Their numbers are derived
  from the s8/s16/s32 fit. The 128-fanout weight-write broadcast is not timed, and one extra
  pipeline stage is projected to cover it.
- The SRAM numbers come from fakeram7, a CACTI-style placeholder. 84 fJ/bit is high for a 7 nm
  macro, so a scorer that charges activation reads from it penalizes the baseline. With N=128
  the activation read costs about 5 fJ/MAC.
