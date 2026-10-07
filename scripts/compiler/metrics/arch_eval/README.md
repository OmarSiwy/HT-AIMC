# arch_eval: design -> the four ARCH_METRIC numbers

One scorer for every candidate (node researchers, the joint search, the judges).
Objective: `docs/src/content/Project/ARCH_METRIC.md`. Numpy only.

```sh
python3 scripts/compiler/metrics/arch_eval/test_arch_eval.py        # self-check, PASS/FAIL
python3 scripts/compiler/metrics/arch_eval/cli.py [design.json]     # score (default design if omitted)
python3 scripts/compiler/metrics/arch_eval/cli.py --baseline [--wbits 8]   # digital systolic baseline
python3 scripts/compiler/metrics/arch_eval/cli.py d.json --knob die_mm2=200 --json
python3 scripts/compiler/metrics/arch_eval/search.py [base.json]    # one-at-a-time stub search
```
(Outside the full shell: `nix-shell -p 'python3.withPackages(p:[p.numpy p.scipy])' --run '...'`.)

## Files

| file | concern |
|---|---|
| `workload.py` | Llama-3-8B shapes, per-request MAC/byte counts, `tiles(wl, R, C)` |
| `metric.py` | `KNOBS` (every ARCH_METRIC knob), `score(points)`, `better`, `rank`, `pareto` |
| `asap7.py` | constants: `asap7_constants.json` per key, literature fallback otherwise |
| `design.py` | design JSON: `make`, `load`, `dump`, `NODES` |
| `nodes/nX_*.py` | one module per decision node (researchers own these) |
| `nodes/default/` | frozen copies of the shipped defaults: the fallback. Do not edit |
| `model.py` | tile -> die -> system composition, operating points, `evaluate(design)` |
| `baseline_systolic.py` | digital systolic die under the same model and metric |
| `search.py`, `cli.py`, `test_arch_eval.py` | stub enumerator, scorer, self-check |

## Design JSON

```json
{"name": "my-candidate",
 "nodes":  {"n1_system": "resident", "n6_readout": "sar_27h1"},
 "params": {"rows": 256, "adc_bits": 7, "kv_bits": 8}}
```
Unlisted nodes use their module's `DEFAULT`. Params are one flat namespace: the
effective dict is (each default option's params) <- (each chosen option's params)
<- `design.params`, in node order n1..n10. Pick param names that do not collide.

## Metric (metric.py)

`KNOBS` (ARCH_METRIC defaults): `die_mm2=100`, `power_cap_W_per_mm2=1`, `hbm_Bps=819e9`,
`hbm_bytes=24e9`, `hbm_pJ_per_bit=4`, `d2d_Bps=2e12`, `d2d_pJ_per_bit=0.5`,
`stream_floor_tok_s=20`, `prompt=512`, `gen=128`, `vdd_min=0.45`, `vdd_max=0.7`.

A point = one (VDD, clock fraction, concurrency B). `score(points)`:
- **tok/s per die**: max over points that satisfy KV capacity, per-stream decode rate
  >= floor, die power <= cap, quality gate. Processed (prompt + generated) tokens of the
  system / dies used. Generated-only reported as `gen_tok_s_die`.
- **TOPS/W** at that peak point: 2 x (weight + QK^T + A.V MACs)/s per die / die power.
  CLI also prints the 27n1 bit-normalized value (x b_w x b_x).
- **tok/W** at the peak point: tok/s per die / (die power + that die's HBM access power).
- **tok/J**: max of the same ratio over every point feasible on KV, power and quality
  (floor not applied). Same boundary as tok/W, so tok/J >= tok/W.
- `better(a, b)`: strict lexicographic (tok/s, TOPS/W, tok/W, tok/J). `pareto(scores)`: 4-D front.

Die power = arrays, converters, drivers, digital rail, SRAM buffer, PHY energy, die-to-die,
leakage. External = HBM device access energy (`hbm_pJ_per_bit`), excluded from TOPS/W.
Weight programming in resident mode is one-time and not charged (27n2); streaming mode
charges every rewrite.

## System model (model.py)

Lockstep waves of B requests: prefill (B x 512 tokens, GEMM: one tile load serves all of
them) then 128 decode steps (GEMV, B vectors per load). Each phase time = max of
`compute` (tile occupancy; streaming = loads x max(t_load, vectors x t_pass) when double
buffered), `hbm` (streamed weights + KV write/read, 16-bit KV unless `kv_bits`),
`attention` (digital rail MAC rate), `d2d`, `latency` ((4L+1) x (t_stage + hop) + one
stream's attention). The max is reported as the `binding` resource; `concurrency` says
what stopped B (KV capacity, per-stream floor, power cap, or saturation).
Resident: dies = ceil(tiles per weight copy / tiles per die), one HBM per die for KV.
Streaming: one die = one full replica with its own HBM (weights + KV share it).

## Node contract

Every node module exposes `OPTIONS = {name: {"params": {...}, "provenance": str}}`,
`DEFAULT` (a key of OPTIONS), `SWEEP = {param: [values]}` and the functions below.
`p` is the merged flat params dict. Use `from arch_eval import asap7 as k` for constants
(`k.get(key)`, `k.get(key, vdd=V)` for the @V tables). Units in names (`_fJ`, `_ns`, `_um2`).
Return extra keys freely; the listed ones are required. A module that fails to import,
lacks a function, or raises is replaced by `nodes/default/<same file>`; the CLI prints
`NODE FALLBACK: ...` and `evaluate()["errors"]` lists it.

| node | function | returns (required keys) |
|---|---|---|
| n1_system | `plan(p, wl, tile, die, knobs)` | `mode` ("resident"/"streaming"), `dies` (int) |
| n2_domain | `array(p, vdd, fmt, cell, rows)` | `e_mac_fJ` (per crosspoint per input word, one weight slice), `t_word_ns`, `v_exc_V`, `c_col_fF` |
| n3_cell | `cell(p, vdd, fmt)` | `area_um2_per_weight` (all slices, one bank), `c_weight_fF` (per slice on its column), `e_write_fJ_per_bit`, `t_write_row_ns`, `leak_nW_per_weight` (at VDD_nom) |
| n4_formats | `fmt(p)` | `wbits`, `abits`, `slices`, `input_planes`, `kv_bits` |
| n5_array | `geometry(p)` | `rows`, `cols` (logical outputs), `adc_share` (columns per ADC), `checksum` |
| n5_array | `v_range(p, geo, arr)` | float: converter input range Vc (V) |
| n5_array | `accuracy(p, vdd, geo, arr, adc, fmt)` | `snr_db`, `parts_db` (dict) |
| n6_readout | `adc(p, vdd, v_fs_V)` | `bits`, `e_conv_fJ`, `t_conv_ns`, `area_um2`, `e_digital_fJ` (per conversion) |
| n7_dataflow | `rail(p, vdd, op, knobs)` | `area_mm2` (dict, fixed die area), `att_mac_per_s`, `e_att_mac_J`, `e_exp_J`, `e_elem_J`, `e_buf_J_per_byte`, `phy_J_per_bit`, `hop_s`, `leak_W`, `tile_util`, `pingpong` |
| n8_quality | `gate(p, acc, fmt)` | `passed` (bool), `target_db`, `margin_db` |
| n9_circuits | `op(p, vdd, clk_frac)` | `vdd`, `clk_frac`, `e_scale`, `delay_scale`, `leak_scale`, `clk_GHz`; `SWEEP["vdd"]`, `SWEEP["clk_frac"]` set the operating-point grid |
| n10_wildcards | `apply(p, tile)` | the tile dict (may rewrite any key); `CANDIDATES = {name: design}` |

The composed **tile dict** (`model.tile`, what n10 sees and what `baseline_systolic.tile`
mimics): `rows, cols, slices, phys_cols, macs_per_pass, t_pass_s, t_load_s, [t_stage_s],
e_pass_J, e_pass_J_parts, area_um2, area_um2_parts, wbits, write_bits_per_load,
e_write_J_per_bit, leak_W, snr_db, quality, fmt, op, rail`.
Per pass (one input vector through one tile): energy = array (rows x phys_cols x e_mac)
+ converters + digital recombination + activation buffer bytes; time = max(t_word,
rounds x t_conv) with ping-pong, else the sum.

## Labels

Every output number is **projected** until every input is measured: the defaults
combine measured sky130 anchors (METRICS.md, IMC_SIZING_RESEARCH.md), measured ASAP7
gm/Id (analog/docs/asap7/results.json) and literature constants. `asap7.report()` and
the CLI say which constants came from `asap7_constants.json` and which fell back.
Node `provenance` strings must say measured / derived / projected and cite the source
(repo doc, note id like 27h1, or paper).

## Shipped defaults (2026-10-05) and what they say

Default = resident, charge-domain passive 128x64 W4A8 port of the sky130 macro, 8-bit
SAR per 8 columns (27h1 law). It **loses to the systolic baseline on all four metrics**
(projected): the 27h1 thermal term (VDD/Vc)^2 4^B on a +-4 sigma passive column swing
makes the converters ~97 % of die energy (~430 fJ/MAC). `adc_bits=7` nearly closes
TOPS/W; the ported sky130 integrator readout triples TOPS/W but is ~16x slower.
Run the CLI for the current numbers.

## Condition sets

`metric.CONDITIONS` holds the condition sets every design is scored under:
`arch` (ARCH_METRIC) and `sohu` (Llama-3-70B, FP8 weights + KV, 2048/128, fixed batch 1000,
8-die tensor-parallel group, 4.8 TB/s + 144 GB HBM per die). `metric.knobs_for(name, **over)` (under `sohu` the die is iso-area with the calibrated Sohu-equivalent, `metric.sohu_area()`, unless `die_mm2` is given)
returns the knobs. New knobs: `model` (`8B-class` | `70B-class`), `batch` (0 = free
concurrency), `kv_bits` (0 = the design's own), `system_dies` (ideal tensor-parallel group, no
d2d cost). Scores also carry `tok_s_mm2` and `tok_s_mm2_W` (reported, not ranked).

    python3 scripts/compiler/metrics/arch_eval/cli.py [design.json] --conditions sohu
    python3 scripts/compiler/metrics/arch_eval/cli.py --baseline --conditions sohu    # FP8 weights
    python3 scripts/compiler/metrics/arch_eval/cli.py --sohu-target   # systolic die sized to 62,500 tok/s/chip
