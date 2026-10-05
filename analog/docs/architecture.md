# AnalogIOC — system analog architecture

Stage 1 of `analog-design-flow` for the whole chip: what the system is, which block
does what, the system-level specs and where each comes from, how those specs are
split across blocks, how a PDK swap re-derives them, and what is still open. Each
block's own `analog/<block>/docs/architecture.md` implements its row of §4.

Sources are cited inline. `docs/src/content/Project/` paths are relative to this repo; "AnalogIOC
source" means `~/Documents/Projects/Research/analog/schematics/` (read-only, the
migration origin, see `analog/docs/MIGRATION.md`). Status labels follow AnalogIOC's
own convention (`docs/src/content/Project/METRICS.md`):

| Label | Meaning |
|---|---|
| measured | SPICE testbench result recorded in a AnalogIOC doc |
| counted | exact compiler / yosys count |
| derived | `analog/docs/specs.py` law evaluated on measured parameters |
| projected | law-scaled or projection-PDK number, no silicon or SPICE behind it |
| target | a requirement or paper design point, not a result |

## 1. What AnalogIOC is

AnalogIOC is an analog in-memory-compute transformer accelerator on sky130
(`docs/src/content/Project/CONTRACT.md`). Weights sit as 4-bit differential capacitor codes in
charge-domain crossbar tiles. INT8 activations arrive as two 4-bit PWM nibbles
(1:16 duration ratio) and are integrated as charge on per-column virtual-ground
integrators. Each column converts with an event-rate coarse loop (reference-charge
packets on threshold crossings, early termination on the first no-cross) followed by
a 4-bit SAR on the residue. A rank-1 LoRA sidecar, its A/B weights held in 2T gain
cells, adds `B·(A·x)` in charge onto the same column integrators for on-chip training.
Attention runs as Q/K/V/O projections on the tiles; the KV cache, qKᵀ scores, softmax
and A·V run on the digital rail (`docs/src/content/Project/APPLICATION_ATTENTION.md`). The digital rail
(`docs/src/content/Project/INTERFACES.md`), the GGUF compiler and the bit-true golden model sit
outside `analog/`. Timing is self-timed, with no global analog clock (GALS).

Mini-chip dimensions (the SPICE-tractable scale everything below is sized for):
`specs.N_ROWS` × `specs.N_COLS` tile (16 data columns + 1 ABFT checksum column), rank-1
LoRA over 16. Simulation runs on a `specs.TQ_SIM` PWM grid; the real-silicon grid is
`specs.t_q_floor()` (CONTRACT: "t_q = 10 ns for simulation (real target 200 ps)").

### Signal chain

MVM path (assembled by `analogioc`; AnalogIOC source `top/analogioc_top.py`):

```
 digital rail / compiler (outside analog/)
   | INT8 act -> two 4b PWM nibbles (xin_p_r*, xin_n_r*)          ^ col_code 8b, done
   v                                                              |
 async_ctrl ---- t_q taps, phases -----+                          |
 (tq_chain + Muller-C sequencer)       |                          |
                                       v                          |
                          pwm_driver x16 --outa/outb--> weight_tile 16 x 17 --col<j>--> integrator_conv x17
                                                        (C+/C- 4b cap banks,           (ota + C_int integrate,
                                                         cmos_switch steering)          event-rate coarse loop,
                                                                  ^                     4b SAR, strongarm x2,
                                                                  |                     packet bank = pwm_driver)
     lora_sidecar -------------- colb<j> (charge sum) ------------+                         ^
     (A,B gain cells + ota integrator + write_dac x2 + ramp V->T)                           | thr_p/thr_n,
                                                                                            | sar_p/sar_n
                                                                                   rstring_ladder x4
```

Parallel super-tile (`chip_supertile`; AnalogIOC source `top/chip_supertile.py`): K
tile windows, each on its own `integrator_conv` C_int, each converted to INT8 by its
own converter and summed on the digital fabric. The shared charge-bus variant was
measured lossy (§6.3).

### Hierarchy (from `MIGRATION.md` DEPENDS)

```
analogioc        async_ctrl integrator_conv lora_sidecar ota rstring_ladder weight_tile
chip_supertile   integrator_conv
integrator_conv  cmos_switch ota pwm_driver strongarm
lora_sidecar     cmos_switch gain_cell_array ota write_dac
weight_tile      cmos_switch pwm_driver
gain_cell_array  cmos_switch
write_dac        cmos_switch
rstring_ladder   cmos_switch
leaves           ota strongarm cmos_switch pwm_driver async_ctrl
```

## 2. Blocks

Ports are the AnalogIOC `.subckt` port lists in order (AnalogIOC source, `generate()` of
each file). Stage 2 requires the `.va` module and the migrated `.subckt` to carry the
block name and these ports.

| Block | Role | DEPENDS | Ports (AnalogIOC `.subckt`) | Used by |
|---|---|---|---|---|
| ota | Telescopic-cascode OTA, NMOS input, single-ended. Column integrator amplifier. | — | `inp inn out vb_nc vb_pc vb_tail vdd vss` | integrator_conv, lora_sidecar; analogioc (sidecar bias) |
| strongarm | Clocked latch comparator for the coarse loop and SAR trials | — | `vinp vinn outp outn clk vdd vss` | integrator_conv → analogioc, chip_supertile |
| cmos_switch | Transmission gate. Crossbar steering, resets, ladder and DAC tap mux | — | `in_ out ctrl ctrl_b vdd vss` | weight_tile, integrator_conv, gain_cell_array, write_dac, rstring_ladder, lora_sidecar → all tops |
| pwm_driver | Chops the PWM envelope onto the two-phase SC grid (one C·VDD transfer per chop cycle) | — | `inp inn phi1 phi1e outa outb vdd vss` | weight_tile (row drive), integrator_conv (packet bank) → analogioc, chip_supertile |
| async_ctrl | Self-timed sequencer plus `tq_chain` t_q tap line | — | `go adc_done xbar_rst adc_go latch_out done vdd vss`; `tq_chain`: `in tap1..tap4 vdd vss` | analogioc |
| gain_cell_array | 8×8 2T all-NMOS gain cells, 30 fF store, column write, PWM row read. LoRA A/B weight storage | cmos_switch | `wdata0..7 wsel0..7 rd0..7 col0..7 vss` | lora_sidecar |
| write_dac | 4b R-string DAC plus 4:16 decoder and TG mux. Programs gain cells | cmos_switch | `b0 b1 b2 b3 out vref vdd vss` | lora_sidecar |
| rstring_ladder | 4b R-string between two external rails plus tap mux. Converter thresholds and SAR span | cmos_switch | `b0 b1 b2 b3 out vrn vrp vdd vss` | analogioc |
| weight_tile | 16×(16+1) charge-domain crossbar, differential 4b cap banks, rail ballast. Programmable (INTERFACE §7): every bit cap's bottom plate on a selector driven by a write-only 6T bit, written a row at a time | cmos_switch pwm_driver | `xin_p_r0 xin_n_r0 .. xin_p_r15 xin_n_r15 col0..col16 wwl0..wwl15 wd0..wd135 phi1 phi1e phi2 vcm vdd vss` (`wd<8j+k>`: column j, k = 0..3 Cp, 4..7 Cn) | analogioc; chip_supertile (K windows) |
| integrator_conv | Column converter: integrator, event-rate coarse loop, 4b SAR, OTA bias parking | cmos_switch ota pwm_driver strongarm | `vg out rst phi1 phi1e phi2 go clk_c clk_cs fire_win acq clk_f clk_fs tr3 tr2 tr1 tr0 tl3 tl2 tl1 tl0 thr_p thr_n sar_p sar_n vcm vdd_ota vdd_cmp vdd_pkt vdd vss` | analogioc, chip_supertile |
| lora_sidecar | Rank-1 LoRA: A·x integrate, V→T ramp, B drive summing onto tile columns | cmos_switch gain_cell_array ota write_dac | `xrd0..15 colb0..15 wa_sel0..15 wb_sel0..15 da0..3 db0..3 rst ramp_en vax vcm vb_ramp vb_nc vb_pc vb_tail vdd vss` | analogioc |
| chip_supertile | Parallel super-tile assembly plus charge-bus loss probe | integrator_conv | probe only | top |
| analogioc | Flat assembly (tile + 17 converters + sidecar + ladders + timebase) | see §1 hierarchy | flat, `STIM_NODES` in `top/analogioc_top.py` | top |

Naming note: AnalogIOC's converter subckt defaults to `int_conv`
(`integrator_conv.generate(name="int_conv")`). The flow requires the subckt, `.va`
module and block name to match, so the migrated deck must be named `integrator_conv`.

## 3. System specs

Where a value is derived in `specs.py` or read from `pdk_specs.py`, the table cites
the function or constant. Run `python3 analog/docs/specs.py` for the current numbers.
It needs numpy; under the nix shell, or
`nix-shell -p "python3.withPackages(p: [p.numpy])"`.

### 3.1 Architecture constants and derived operating point

| Metric | Target / value | Unit | Source | Status |
|---|---|---|---|---|
| Supply | `pdk_specs.get_pdk().vdd` | V | pdk_specs.py | process fact |
| Column virtual ground / common mode | `specs.VCM_FRAC` × vdd | V | specs.py | target |
| Converter output bits | `specs.B_Y` | bit | specs.py (law:bout) | target |
| Nominal code ceiling (±4σ) | `specs.CODE_MAX` | code | specs.py (law:bout) | target |
| OTA compression ceiling | `specs.MAC_MAX` | code | specs.py | measured |
| Integrator usable single-sided swing | `specs.V_SWING` | V | specs.py | target |
| Integration cap | `specs.c_int()` = max(kT/C law at `B_Y`, layout floor `c_int_col`) | F | specs.py (law:esnr) | derived |
| Crosspoint unit cap | `specs.c_u()` | F | specs.py (law:esnr) | derived |
| Charge-transfer efficiency (single crosspoint) | `specs.k_cal()` | — | specs.py `_CAL` (A7, `tb_weight_tile`) | measured |
| Charge per code unit | `specs.q_unit()` | C | specs.py | derived |
| Volts per code unit (calibrated) | `specs.u_cal()` | V | specs.py (law:adc) | derived |
| Coarse packet cap (1 packet = 16 code units) | `specs.c_pkt(D)` | F | specs.py (law:adc) | derived |
| Multi-bank transfer efficiency | `specs.multibank_efficiency(n)`, floor `specs.MB_EFF_FLOOR` | — | specs.py (A9, `diag_multibank`) | measured fit, first order |
| Fine SAR reference trim | `specs.fine_ref_trim()` | — | specs.py `_CAL` (Task A, `diag_fine15`) | measured |
| OTA bias per input side | `specs.I_SIDE`; sizing `specs.ota()` from `specs.OTA_COORDS` | A | specs.py, gmid.py | derived |
| Integrator packet-absorb τ | `specs.tau_absorb()` | s | specs.py | derived (anchored to measured 26 ns at the A1 point) |
| Coarse decision cadence | `specs.coarse_cadence()` = `K_SETTLE`·τ snapped to `TQ_SIM` | s | specs.py (law:adc) | derived; falsifier `tb_integrator_conv` |
| Kick-filter R, C | `specs.kick_filter()` | Ω, F | specs.py | derived |
| Coarse slots per conversion | `specs.N_COARSE` = `COARSE_CAP` + `COARSE_MARGIN` | slot | specs.py | derived (cap proved lossless; margin measured) |
| SAR time | `specs.sar_time()` | s | specs.py | target (sim-grid constants) |
| Conversion time | `specs.conv_time()` | s | specs.py (eq:E_conv) | derived |
| Ladder segment R | `specs.r_seg()` from `P_LADDER_BUDGET` | Ω | specs.py | derived; falsifier `tb_rstring` |
| Ladder tap decap | `specs.c_tap()` from `V_TAP_TOL` | F | specs.py | derived |
| Simulation t_q | `specs.TQ_SIM` | s | specs.py, CONTRACT.md | target |
| Real-silicon t_q floor | `specs.t_q_floor()` = max(row RC, `pdk.jitter_budget_s`); row load `specs.c_row()` = 17 banks × 15 C_u + the bottom-plate selectors' drains + wire (101 fF on sky130, RC 16 ps: jitter-bound) | s | specs.py | derived |
| Pass time (both nibble windows plus two conversions) | `specs.pass_time()` | s | specs.py | derived (see §6.1 on the measured 4.12 µs) |
| Merged / ping-pong pass | `specs.merged_pass_time()`, `specs.pingpong_pass_time()` | s | specs.py (items S5/S6) | derived |

### 3.2 Accuracy and SNR

| Metric | Target / value | Unit | Source | Status |
|---|---|---|---|---|
| Tile MVM code accuracy, contract | ±1 | LSB | CONTRACT.md acceptance 1 | target (superseded, see next row) |
| Tile MVM code accuracy, relaxed gate | ±8 (`tb_tile_mvm` `CODE_TOL=8`) | LSB | ERROR_IMPACT.md, RESULTS3.md | target from a golden-model injection study |
| Tile MVM measured residual, real pass_05, in-contract columns | worst 3 | LSB | RESULTS3.md | measured |
| Single-column converter, 5 mac points | all ±1 | LSB | RESULTS3.md (`tb_integrator_conv`) | measured |
| Per-stage compute SNR, design point | `specs.SNR_S_DB` (FFN class 38 dB in `perlayer_k`) | dB | specs.py; STATUS "HETEROGENEOUS PER-TENSOR K" | target (paper point; see §6.2) |
| Per-stage compute SNR, measured | 19.9 attention / 16.7 FFN uncorrected; 27.8–30.1 with A10 per-column gain (fitted and scored on the same columns) | dB | COMPOSED_RESULTS.md (`tb_csnr.py`) | measured |
| End-to-end attention SNR target | `specs.SNR_T_ATTN_DB` | dB | specs.py | target |
| Servoed per-stage gain error | `specs.EG_SERVO` | — | specs.py; SERVO_EG.md: `test_gain_servo` 0.196–0.203 % typical, 0.437 % worst seed | measured-anchored |
| Cumulative gain-error bound | `specs.EPS_TOT` | — | specs.py | target |
| Series cascade depth | `specs.k_star()` | — | specs.py (eq. cascade) | derived |
| Swing-limited cascade depth at fixed C_int | `specs.cascade_k_swing()` | — | specs.py | derived |
| Parallel super-tile depth | `specs.parallel_k_star(snr_s, snr_t)` | — | specs.py | derived |
| ABFT checksum residual, pass_05 | 62 of budget 199 | acc LSB | RESULTS3.md | measured |

### 3.3 Throughput and energy

tok/s and tok/J are for the mini chip: one physical tile, time-multiplexed, on the
50×-slow simulation grid.

| Metric | Value | Unit | Source | Status |
|---|---|---|---|---|
| Tile passes per token (SmolLM2-135M blk.0 head-0 + FFN) | 10944 (576 attn + 10368 FFN) | pass | METRICS.md, STATUS A5 | counted |
| Pass time | 4.12 (17 coarse slots) | µs | METRICS.md | measured schedule |
| Pass time, current law | `specs.pass_time()` (`N_COARSE` slots) | s | specs.py | derived |
| Mini-chip tok/s | 22.2 at 4.12 µs; law form `specs.tokens_per_s()` | tok/s | METRICS.md | measured × counted |
| Mini-chip tok/J | 41,714; law form `specs.tokens_per_j()` | tok/J | METRICS.md | measured × counted + estimated digital |
| Energy per pass | 2190.5 (tile 820.83, coarse 1061.59, fine 283.51, digital 24.6) | pJ | METRICS.md | measured; digital estimated |
| E_conv at \|code\| 0 / 16 / 51 / 127 | 0.48 / 0.91 / 1.79 / 4.83 | pJ | METRICS.md, RESULTS3.md | measured |
| Early-termination ratio E(code≈0) / mean | 0.27 (bar < 0.30) | — | RESULTS3.md (`tb_eventrate`), CONTRACT acceptance 6 | measured |
| Coarse energy model | `specs.E_COARSE_FLOOR` + `specs.E_PKT`·packets, `specs.E_SAR` | J | specs.py (`out/tile_energy.json`) | measured fit |
| OTA static power (17 columns) | `specs.ota_static_w()` | W | specs.py | derived |
| Pass energy law | `specs.pass_energy_pj()` | pJ | specs.py | derived (calibrated to `tb_tile_mvm`) |
| Cascade K amortization, pass_05 tile | E/pass 0.55× (K=2) / 0.41× (K=4) | — | OPTIMIZATION_RESULTS.md (`tb_cascade`) | measured |
| Gain-cell write / 8-row read pass | 7.5 fJ / 2.4 pJ | — | METRICS.md, STATUS A3 | measured |
| Write-DAC slot / LoRA outer-product op | 1.2 / 67.0 | pJ | METRICS.md | measured |
| Digital rail | 3158 cells, 24712 µm², 0 latches | — | STATUS A4 | counted |
| 7B / 70B tok/s per die vs Sohu | see §6.2, no single agreed number | — | COMPOSED_RESULTS.md, OPTIMIZATION_RESULTS.md, NULLSEEK.md | projected |

## 4. Per-block allocation

Each block carries the system spec in column 2 as the block-level requirement in
column 3. The block's `docs/architecture.md` spec table implements that requirement
and names its testbench (`MIGRATION.md` lists the AnalogIOC testbenches per block).
Measured AnalogIOC anchors are recorded so a regression shows up.

| Block | System spec carried | Block-level requirement (source) | AnalogIOC anchor (measured) | Block doc |
|---|---|---|---|---|
| ota | charge-transfer accuracy; cadence; OTA static power | loop gain > 200 for 0.5 % transfer; 50 mV step settle < `coarse_cadence()`/2; SR ≥ 50 V/µs into `c_int()`; sized by `specs.ota()` at `I_SIDE` (SIZING.md, STATUS O1 item 3) | loop gain 483, settle 21.9 ns, SR 57 V/µs, tail 8.2 µA | `analog/ota/docs/architecture.md` |
| strongarm | coarse and fine decisions inside `u_cal()` | noise ≪ coarse LSB; clk→decision ≤ 3 ns; offset is range loss only | offset ≤ 2 mV, 0.48 ns (SIZING.md) | `analog/strongarm/docs/architecture.md` |
| cmos_switch | gain-cell write settle; tile steering injection | gain-cell write path settles 30 fF to 8 bit in 100 ns → R_on < 537 kΩ; write-level ceiling 0.9 V (SIZING.md §c); charge injection bounded (new tb) | write_tg 1.9–26 kΩ over 0–0.9 V | `analog/cmos_switch/docs/architecture.md` |
| pwm_driver | code-linear charge (one C·VDD per chop cycle) | transfer count = code for 0..15, both signs; width linearity ≤ 2 %; edges ≤ 3.3 ns (STATUS A2 2/5) | 0.26 %, 0.25 ns | `analog/pwm_driver/docs/architecture.md` |
| async_ctrl | t_q grid; phase ordering | tap spacing `TQ_SIM` (sim) scaling to `t_q_floor()`; ordering GO → xbar_rst → settle → adc_go → done (SIZING.md) | 10.15 ns/stage, first 7.7 ns | `analog/async_ctrl/docs/architecture.md` |
| gain_cell_array | LoRA A/B weight storage; read linearity | store error < 1 write-DAC LSB; 16 monotone read levels; non-destructive read; column current ≤ ~10 µA class-A budget | store −12..−30 mV, τ ≈ 27 ms (extrapolated), 10 reads −43 µV | `analog/gain_cell_array/docs/architecture.md` |
| write_dac | gain-cell programming | 16/16 monotone; LSB = vref/15 with vref at the 0.9 V write ceiling; settle inside the 150 ns write slot (100 ns spec) | exact levels, settle 4.6 ns, 1.2 pJ/slot | `analog/write_dac/docs/architecture.md` |
| rstring_ladder | converter reference spans at `u_cal()` | monotone taps; segment R = `r_seg()`; tap held within `V_TAP_TOL` under CDAC kick < 5 ns via `c_tap()` | worst tap err 0.21 mV; outside band 3.51 ns | `analog/rstring_ladder/docs/architecture.md` |
| weight_tile | charge per code `q_unit()`; linearity; multi-bank delivery; weight write | transfer = `k_cal()` per crosspoint; linear in code; multi-bank efficiency tracked by `multibank_efficiency()` or measured per-column gain; a row write inside `T_WRITE_CELL` at 0.9 VDD, disturb < 1 LSB | programmable: R² 0.999898, slope 97.5 % (k_cal 0.9747); busy-column delivery ≈ 0.92; write 0.63 ns at 1.62 V; disturb 0.004 LSB; 109 pJ/pass | `analog/weight_tile/docs/architecture.md` |
| integrator_conv | `B_Y`-bit conversion, tile accuracy gate, `conv_time()`, early termination | ±1 LSB single column; E(code≈0)/mean < 0.30; conversion inside `N_COARSE`·`coarse_cadence()` + `sar_time()`; OTA parked after coarse `done`, never in the fine phase (INTERFACES.md `ota_en`) | 5/5 ±1 LSB; E 0.48 → 4.83 pJ | `analog/integrator_conv/docs/architecture.md` |
| lora_sidecar | training step (CONTRACT acceptance 4) | outer-product column error ≤ 5 %; A-column current ≤ ~10 µA (STATUS A3) | 1.36 % pre-update, 0.93 % post-update; 67 pJ/op | `analog/lora_sidecar/docs/architecture.md` |
| chip_supertile | K-independent gain error, `parallel_k_star()` | parallel gain error flat in K; INT8 digital partial sum (STATUS #22) | flat 0.440 % at K = 1/2/4 vs series 0.44 → 1.125 % | `analog/chip_supertile/docs/architecture.md` |
| analogioc | CONTRACT acceptance 1–6; tok/s, tok/J | `tb_tile_mvm` within `CODE_TOL`, ABFT in budget, `tb_eventrate`, `tb_ffn_e2e`, `tb_audit`, `tb_training_step`, `tb_attention_e2e` | pass_05 worst 3 LSB; ffn/audit/training/attention not re-run under `CODE_TOL=8` (RESULTS3.md) | `analog/analogioc/docs/architecture.md` |

## 5. PDK hotswap

Three files carry the port:

1. **`pdk_specs.py`** reads `$PDK` (volare variant, default `sky130A`) and returns a
   `PDKConfig`. Process facts only: `vdd`, `min_l`, `min_w`, device names (plus
   `_lvt`/`_hvt`), `un_cox`/`up_cox`, `vth_*`, corner sections, `mc_section`,
   `mismatch_suffix`, the ngspice lib path, `r_sq_wire`, `wire_pitch`, `a_vt`,
   `ss_mv_dec`, `cap_density_mim`, `t_inv_ps_per_ff`, `jitter_budget_s`, and the
   layout-realisable passives (`mim_cap`, `res_poly`, densities).
   `model_library(corner)` returns the SpiceRack `ModelLibrary` per section.
2. **`gmid.py`** builds gm/ID LUTs from GmIDVisualizer for the active PDK into
   `gmid_tables/<pdk>/`, the first time a table is missing. `specs.ota()` and every
   block's netlist script size devices through `J_D`, `VGS`, `gm_gds`, `W_for_gm`.
3. **`specs.py`** derives the design from the two above: `c_int()` (kT/C law vs
   layout floor) → `c_u()` → `u1()`/`u_cal()` → `c_pkt()`; `ota()` → `kick_filter()`
   → `tau_absorb()` → `coarse_cadence()` → `conv_time()` → `pass_time()` →
   `tokens_per_s()`; `r_seg()`/`c_tap()`; `t_q_floor()`. Per-PDK measured
   calibration sits in `_CAL`; per-PDK design choices (layout-floor caps, delay-chain
   config) sit in `_DESIGN`.

Switching `$PDK` and re-running is the whole port only when all three have entries
for the target PDK. Today that holds for sky130 alone. Probed 2026-09-28 by calling
the specs functions per `get_pdk(name)`:

| PDK | Models installed | gm/ID tables | `c_int` / `c_u` | `t_q_floor` | OTA / timing chain | Why |
|---|---|---|---|---|---|---|
| sky130 (A/B) | yes | yes (`gmid_tables/sky130`) | ok | ok | ok; self-check PASS | — |
| gf180mcu | yes | no | KeyError | ZeroDivisionError | KeyError | raw tech params (`r_sq_wire`, `wire_pitch`, `a_vt`, `jitter_budget_s`, …) unsourced; no `_CAL`/`_DESIGN` entry |
| ihp-sg13g2 | not installed here | no | KeyError (`c_int_col`) | ZeroDivisionError | KeyError | same raw params missing; `_DESIGN` entry lacks `c_int_col`; no `_CAL` |
| asap7_proj | projection, no SPICE | n/a | ok | ok | KeyError | `specs.cal()` reads `_CAL`, not `PDKConfig.cal_proj`; no gm/ID tables without models |
| tsmc_n4_proj | projection, no SPICE | n/a | ok | ok | KeyError | same as asap7_proj |

The projection PDKs exist for AnalogIOC's `scripts/compiler/metrics` projection math. They are
math-only by design and have no simulation path.

Sky130 anchors still hard-coded in `specs.py` (the O1b debt list, STATUS entry O1b)
break the "switch `$PDK` and re-run" rule for any other process:

- `TQ_SIM` and the SAR schedule (`T_ACQ`, `T_TRIAL`, `T_SAR_TAIL`, and the literal
  5 ns in `sar_time()`) are sim-grid constants that do not scale with
  `tau_absorb()`.
- `V_SWING`, `MAC_MAX`, `RC_KICK`, `C_FILT_MIN`, the ladder-kick constants
  (`C_KICK_CDAC`, `V_KICK`, the 0.8 V band in `r_seg()`), and the energy constants
  `E_COARSE_FLOOR`/`E_PKT`/`E_SAR` are sky130 measurements or sky130-sized choices.
- `_selfcheck()` asserts sky130 values (cadence, `r_seg`, `c_tap`, AnalogIOC OTA widths)
  unconditionally, so it fails by construction on any other PDK.
- AnalogIOC block generators carry literal sizes and biases, for example the write DAC
  10 kΩ segments and 0.9 V vref, and the lora_sidecar C_int. Under the flow each
  becomes a gm/ID or `pdk_specs` derivation in the block's netlist script.

## 6. Open issues and contradictions

### 6.1 Numbers that moved after the docs were written

- **Pass time and tok/s.** METRICS.md measured a 4.12 µs pass and 22.2 tok/s with 17
  coarse slots per conversion. Later STATUS entries (A9, Task A, #22) keep calling
  "K=1 anchor 4.12 µs / 22.2 tok/s" unmoved. `specs.py` now uses `N_COARSE` = 9
  (`COARSE_CAP` 7, proved lossless against the ±127 clamp, plus a measured margin of
  2), so `specs.pass_time()` returns 3.16 µs on sky130 today. Nothing in the docs
  records a full-pass measurement at 9 slots. Treat 4.12 µs as the last measured
  schedule and `pass_time()` as derived.
- **Coarse count width.** INTERFACES.md `event_ctrl` counts to 15, and CONTRACT calls
  the loop 4b. The analog schedule only provisions `N_COARSE` slots. This is
  consistent (the RTL still clamps) but the per-block converter spec should state
  the 9-slot budget, not 15.
- **Kick filter.** LAYOUT_REQUIREMENTS.md lists R ≈ 5.3 kΩ and C ≈ 60 fF.
  `specs.kick_filter()` at the current `I_SIDE` gives a different R/C pair. The
  specs.py value governs.

### 6.2 Docs that disagree

1. **tok/s vs Etched Sohu.** Headline ratios across docs: 0.97× series / 1.20×
   parallel (OPTIMIZATION_RESULTS.md, STATUS #22), 1.83× (COMPOSED_RESULTS.md
   headline), 0.25× at measured CSNR (the same doc's bottom line), 0.29× "honest
   baseline" (NULLSEEK.md §5), and STATUS 2026-09-07: "old headline Sohu ratios …
   remain unsupported". Sohu's 62.5k tok/s/die is a vendor 70B FP8 batch-~1000
   number, and its tok/J band is inferred, not published (SOHU_VERIFIED.md). No
   system spec in this doc depends on the comparison.
2. **Per-stage SNR provenance.** `specs.SNR_S_DB` is commented "measured-class". The
   FFN 38 dB in `perlayer_k` likewise came from a paper target. COMPOSED_RESULTS.md
   says neither was ever measured; `tb_csnr` measured 19.9 dB (attention) and
   16.7 dB (FFN) uncorrected. At the measured CSNR the 28 dB end-to-end target is
   not met at any K, so K = 1 and every K > 1 throughput number is conditional.
3. **K\*.** METRICS.md calls the paper design K\* = 64. IMC_OPTIMIZATION_RESEARCH.md
   reads the paper's "256/K\*=64 conversions" as K\* = 4, which matches
   `specs.k_star()`.
4. **Parallel FFN depth.** `specs.parallel_k_star` docstring and STATUS #21 say
   K = 10; the `specs.py` self-check asserts 9; STATUS #22 says 9; SERVO_EG.md says
   9–10.
5. **Accuracy gate.** CONTRACT.md acceptance 1 is ±1 LSB. RESULTS3.md and
   ERROR_IMPACT.md relax `tb_tile_mvm` to ±8 LSB from a golden-model injection study,
   which uses a proxy head: one of 30 blocks, head 0 only.
6. **Weights "consumed" by reads.** THE_COMPILER_STRUCTURE.md Part IV rules out a
   weight chip because analog IMC is a "consuming substrate". STATUS 2026-09-07
   corrects this: "capacitor-coded weights are not consumed by read".
7. **Super-tile amortization.** `specs.tokens_per_s_parallel()` and STATUS #22 credit
   the parallel super-tile with one conversion per K windows. The adopted variant (B)
   in `chip_supertile.py` converts every partial with its own converter before the
   INT8 digital sum, which is K conversions. STATUS 2026-09-07 flags this: "current
   digital supertile performs K ADCs despite claiming /K amortization".

### 6.3 Accuracy findings carried over

- **Multi-bank charge deficit.** Real columns deliver ≈ 84 % of ideal charge
  (finite OTA gain on the shared rail plus C_RAIL). The spread comes from the cell
  pattern, not only the bank count (CASCADE.md A9). `multibank_efficiency()` is a
  first-order bulk fix; production needs a measured per-column gain (A10 /
  `test_gain_servo`).
- **Residual after gain calibration.** ±2–3 LSB on ordinary in-contract codes,
  root-caused to fine-SAR mid-code DNL entangled with the per-column gain. No
  readout-indexed LUT inverts it (STATUS #23). The closers are a SAR topology change
  or the parallel super-tile. Model-adequate under the ±8 LSB gate.
- **Gain servo floor.** Pelgrom unit-cap mismatch floors the uncorrelated gain error
  at ≈ 1.4 % on sky130, about 10× above the 0.15 % a 2× throughput story needs
  (SERVO_EG.md).
- **Charge-bus super-tile sum is lossy.** A K = 4 bus attenuates to 0.222 of the
  ideal sum, so the super-tile must sum in digital (STATUS #22).
- **Acceptance coverage.** After the gate relaxation, `tb_ffn_e2e`, `tb_audit`,
  `tb_training_step` and `tb_attention_e2e` were not re-run (RESULTS3.md). Full
  17-column `tb_tile_mvm` ran only on pass_05.

### 6.4 Research after 2026-09-07 (not part of the migrated blocks)

STATUS entries from 2026-09-07 onward, IMC_CIRCUIT_CONVERGENCE.md and
`docs/src/content/Project/campaign/` explore a different core: a passive charge-domain array with
no standing virtual-ground OTA in the multiply path, a null/VCM-start SAR, and native
pipelining. They explicitly leave the "ballast-heavy, OTA-integrated tile" as the
functional reference and make no integrated tok/s, tok/J or SoTA claim. The
study code was archived during migration and later deleted (2026-10-04); only their
write-ups in `docs/src/content/Project/` remain. If that core replaces the tile, the §1 signal chain changes at
`weight_tile`/`integrator_conv`/`ota`, and this document must be revised first.
