# PDK PROJECTIONS (O2) — specs.py parameter evaluation, NO SPICE

Labels: **measured** = sky130 SPICE tb (STATUS/METRICS); **derived** = specs.py formula on measured/sourced params; **projected** = projection-grade parameter set (library/pdks/{asap7_proj,tsmc_n4_proj}.py, every raw value sourced + confidence-labeled); **vendor** = Etched Sohu claims.

## Derived specs per PDK (specs.py formulas)

| spec | sky130 (sim grid) | sky130 (real t_q) | asap7_proj | tsmc_n4_proj |
|---|---|---|---|---|
| t_q (chop grid) | 10.00 ns | 0.20 ns | 0.10 ns | 0.10 ns |
| t_q floor (row RC vs jitter) | 0.20 ns | 0.20 ns | 0.09 ns | 0.09 ns |
| C_int / C_u | 200f / 150a | 200f / 150a | 52f / 100a | 52f / 90a |
| tau_absorb | 30.00 ns | 25.13 ns | 4.43 ns | 3.65 ns |
| coarse cadence (chop cadence) | 60.00 ns | 50.40 ns | 8.90 ns | 7.30 ns |
| conversion time | 780.00 ns | 654.68 ns | 115.53 ns | 94.86 ns |
| pass time (baseline) | 3.16 us | 1.34 us | 247.05 ns | 205.73 ns |
| pass time (S5+S6 ping-pong) | 1.40 us | 655.48 ns | 115.93 ns | 95.26 ns |
| pass energy (baseline) | 1460.5 pJ | 792.6 pJ | 47.1 pJ | 45.1 pJ |
| pass energy (squeezes, duty 0.3) | 454.3 pJ | 372.2 pJ | 16.8 pJ | 18.0 pJ |
| OTA static | 367 uW | 367 uW | 143 uW | 153 uW |

Anchor check: sky130 (sim grid) reproduces the O1 falsifier points (tau_absorb 30 ns, cadence 60 ns, r_seg 8k, c_tap 29 pF — asserted at the bottom of this script). Model pass energy 1813 pJ vs 2697 pJ measured (METRICS.md) — the measured point is the PRE-squeeze 80 ns-cadence schedule plus ladder-rail residuals; the model is the post-O1 schedule. C_int at both advanced nodes re-derives to 52 fF: the kT/C noise law (12kT*4^B_y/V_swing^2), not the layout floor, binds once caps shrink (derived).

Binding constraint per PDK (from the formulas above):

- **sky130 (sim grid)**: t_q set by jitter budget (floor 0.20 ns); pass limited by PWM window (t_q) — conv 780.00 ns vs window 1.36 us.
- **sky130 (real t_q)**: t_q set by jitter budget (floor 0.20 ns); pass limited by conversion (OTA absorb cadence + SAR) — conv 654.68 ns vs window 27.20 ns.
- **asap7_proj**: t_q set by row RC (floor 0.09 ns); pass limited by conversion (OTA absorb cadence + SAR) — conv 115.53 ns vs window 13.60 ns.
- **tsmc_n4_proj**: t_q set by row RC (floor 0.09 ns); pass limited by conversion (OTA absorb cadence + SAR) — conv 94.86 ns vs window 13.60 ns.

## tok/s and tok/J vs Etched Sohu

Assumptions (projected, low confidence): die 400 mm2 x 70% fill; tile macro mm2 = {'sky130': 0.06, 'asap7_proj': 0.008, 'tsmc_n4_proj': 0.006}; squeezes = S5 merged window + S6 ping-pong + S4 duty 0.3; weights time-multiplexed (rewrite energy excluded, as in METRICS.md); analog+static path only (digital rail ~1% at sky130, counted).

| PDK (squeezes) | scale | passes/tok | tiles/die | tok/s/die | tok/J | tag |
|---|---|---|---|---|---|---|
| sky130 (sim grid) | mini (135M subset) | 10,944 | 1 | 65 | 201,127 | measured/derived |
| sky130 (sim grid) | 7B | 27,343,750 | 4,666 | 122 | 80 | measured/derived |
| sky130 (sim grid) | 70B | 273,437,500 | 4,666 | 12 | 8 | measured/derived |
| sky130 (real t_q) | mini (135M subset) | 10,944 | 1 | 139 | 245,466 | projected |
| sky130 (real t_q) | 7B | 27,343,750 | 4,666 | 260 | 98 | projected |
| sky130 (real t_q) | 70B | 273,437,500 | 4,666 | 26 | 10 | projected |
| asap7_proj | mini (135M subset) | 10,944 | 1 | 788 | 5,438,169 | projected |
| asap7_proj | 7B | 27,343,750 | 35,000 | 11,042 | 2,177 | projected |
| asap7_proj | 70B | 273,437,500 | 35,000 | 1,104 | 218 | projected |
| tsmc_n4_proj | mini (135M subset) | 10,944 | 1 | 959 | 5,088,334 | projected |
| tsmc_n4_proj | 7B | 27,343,750 | 46,666 | 17,915 | 2,037 | projected |
| tsmc_n4_proj | 70B | 273,437,500 | 46,666 | 1,792 | 204 | projected |
| Etched Sohu | 70B (Llama) | — | 1 | 62,500 | 35–60 (server) | tok/s vendor-derived (500k/8, FP8 batch~1000); tok/J INFERRED (no vendor power published) |

## Crossover verdict

- **tok/J**: every projection beats the Sohu server estimate (35–60 tok/J at 70B is INFERRED — Etched published no power/TDP; see SOHU_VERIFIED.md). 70B: asap7_proj 218 tok/J, tsmc_n4_proj 204 tok/J — **3–5x margin** (our projection vs an INFERRED Sohu tok/J; not a vendor number).
- **tok/s/die**: NO projection beats 62.5k tok/s/die on pass cadence alone; best is tsmc_n4_proj at 7B = 17,915 tok/s/die (28.7% of Sohu). The pass is conversion-bound (conv/window = 7x): with conversion amortization K >= 7 windows/conversion (paper law:wrapper, K*=64) the pass goes window-bound -> 121,903 tok/s/die at 7B = 2.0x Sohu (projected). 70B stays 0.20x -> needs ~6 dies or larger tiles.

## Per-PDK notes

- **sky130** (anchor, measured): OTA absorb (tau 30 ns measured-anchored) sets the 60 ns cadence and a us-class conversion; t_q floor is the 200 ps jitter budget, wire RC is free. It buys falsifiability, not throughput.
- **asap7_proj**: 0.7 V breaks the 5-stack telescopic (topology flag: two-stage/ring-amp at the same gm_in point); fin quantization invalidates the sky130 gm/ID widths. Enables ~7x cadence and ~30x pass-energy cuts (CV^2 + shorter pass); limits: conversion still dominates the pass, row RC (M6-class route) now sets t_q (~85 ps floor).
- **tsmc_n4_proj**: best cadence/energy of the set; row RC sets t_q (~75 ps floor > 50 ps jitter class) exactly as the formulas predict for tight-pitch BEOL; same 0.75 V topology flag. The win is density (tiles/die) + CV^2, not cadence — tau_absorb is C_FILT_MIN-floored (60 fF CDAC-match floor binds once device caps shrink).

## Missing hooks for O1b (specs.py owned)

- `specs.TQ_SIM` is a module constant (sky130 sim grid); should derive from max(t_q_floor, jitter) per PDK. This script substitutes it at runtime.
- `specs.sar_time`/T_ACQ/T_TRIAL/T_SAR_TAIL are constants; OTA-settle-limited -> should scale with tau_absorb (runtime substitution here; the 5 ns literal inside sar_time is unreachable).
- `specs._CAL` keyed by name in specs.py; projections carry `cal_proj` on the PDKConfig — promote to a PDKConfig field.
- `specs.pass_energy_pj` hard-wires `pass_time`; needs a pass-time argument for S5/S6 schedules (computed manually here).
- `V_SWING`, `MAC_MAX`, ladder kick constants (C_KICK_CDAC, V_KICK, 0.8 V band) are sky130-anchored module constants -> r_seg/c_tap do not re-derive per PDK yet.
- `C_FILT_MIN` (60 fF CDAC match) becomes the tau_absorb floor at advanced nodes — needs the CDAC-side scaling law.
- per-PDK gm/ID tables (fin-quantized) so specs.ota() widths mean something off sky130.
