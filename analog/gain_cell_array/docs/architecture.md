# gain_cell_array — 8×8 2T gain-cell array

Schematic, drawn by cktImg from `netlist/gain_cell_array.spice` (`make import NETLIST=gain_cell_array`): [gain_cell_array.svg](gain_cell_array.svg)

LoRA A/B weight storage: `lora_sidecar` reuses the single cell (`gain_cell_subckt`).
Written by `write_dac` (4b, 0…V_W); read as a charge-domain dot product onto the column
integrators. See `analog/docs/architecture.md` §Signal chain.

## Interface

`.subckt gain_cell_array wdata0..7 wsel0..7 rd0..7 col0..7 vss` (AnalogIOC
`components/gain_cell_array`), built from `.subckt gain_cell_array_cell wdata wsel rd col vss`.

| Port | Dir | Meaning |
|------|-----|---------|
| wdata<r> | in | row-shared write data from the write DAC, [0, V_W] |
| wsel<c> | in | per-token column write select (VDD = write) |
| rd<r> | in | row read-enable **source** line: VCM idle (read device off), 0 V during the PWM read pulse |
| col<c> | inout | column rail, held at VCM by the tile integrator; each read cell sinks I_read(store) from it |
| vss | supply | 0 (all-NMOS cell, no vdd rail) |

Cell: write switch `w` (wdata → store, gate wsel), storage MIM `s` (store → vss), read
device `r` (col → rd, gate = store). One token = one column: raise wsel<c>, drive the 8
wdata<r>. Column charge = Σ_r I(store[r][c])·t_r = q·K_c. Reads are non-destructive
(storage is gate-coupled only).

V_W = `cmos_switch.v_write()` = `specs.VCM_FRAC`·VDD (0.9 V on sky130): the NMOS-only
write switch cuts off near VDD − Vth(body) (AnalogIOC A1: 22.9 MΩ at 1.2 V), so storage
stays in [0, V_W]. LSB = V_W/15 = 60 mV (4b write DAC). Upgrade path for a larger range:
swap `w` for a `cmos_switch` copy (the declared DEPENDS; today only its write-path
budget functions are imported).

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| Stored level error, 16 levels, 120 ns wsel pulse | −LSB = −60 | | +60 | mV | `tb_gain_cell` |
| Read current monotone in stored level (16 levels) | 16/16 | | | — | `tb_gain_cell` |
| K vs V array read-current agreement (levels > 1 nA) | | | 2 | % | `tb_gain_cell` |
| Full-scale read current (level 15, col = VCM, rd = 0) | | | `specs.I_SIDE` = 6 | µA | `tb_gain_cell` |
| Retention droop over 10 × 320 ns (wdata parked at 0 V) | | | LSB = 60 | mV | `tb_gain_cell` |
| Non-destructive read: shift after 10 read pulses | | | 60 | mV | `tb_gain_cell` |
| Write disturb: victim shift during a neighbour-column write | | | 60 | mV | `tb_gain_cell` |
| E_write per cell, E_read per 8-row pass | | report | | fJ, pJ | `tb_gain_cell` |
| Level separation, Monte Carlo: 3σ(I_k) < ½(I_k+1 − I_k) at k = 7/8 and 14/15 (≙ 3σ input-referred < LSB/2) | pass | | | — | `tb_gain_cell_array_mc` |

Read interval = full INT8 PWM = 2 nibbles × 16 slots × `specs.TQ_SIM` = 320 ns. Column
current ceiling: the column OTA is class A, AnalogIOC measured a ~10 µA sink at its
10 µA/side bias; the migrated OTA runs `specs.I_SIDE` = 6 µA/side, so one cell at full
scale stays under I_SIDE (simultaneous-row PWM schedules keep the sum inside it —
compiler constraint, unchanged from AnalogIOC).

## Sizing

Derived in `netlist/gain_cell_array.py`.

| Device | Role | Derivation | AnalogIOC hand | sky130 | gf180mcuD |
|--------|------|------------|--------------|--------|-----------|
| s | storage | `specs.design()["c_store"]` = 30 fF, MIM | 30 fF ideal C (MOM) | 3.71 × 3.71 µm | 3.65 µm side (below the 5 µm MIM minimum — see issues) |
| w | write switch (triode, no gm/ID) | L = smallest k·Lmin where the width meeting R_on(V_W) ≤ `cmos_switch.R_GUARD`·`r_on_budget()` (401 kΩ) on every corner × {−40, 27, 125} °C also keeps I_off(\|V_DS\| = V_W) ≤ ½·LSB·C/(10·320 ns) = 281 pA on every corner — `switch_char()`, cached in `netlist/char/<pdk>.json` | 0.42/0.5 | 0.54/0.30 | 0.22/0.28 |
| r | read transconductor | gm/ID coordinate: full scale at VGS = V_W, VDS = VCM (the tables' mid-VDS slice); W = I_SIDE / J_D(V_W, L); L = smallest k·Lmin with W ≥ min_w and **measured** σ(VGS) (`docs/mismatch.py`) at mid- and full-scale current ≤ (LSB/2)/3·√0.9 = 9.49 mV | 0.42/0.5 (same as w) | 0.50/1.20 | 0.23/2.24 |

Write switch, sky130 min-width measurements (worst over 5 corners × 3 temperatures):
L = 0.15: R_on 2.53 MΩ (fs −40 °C) → W 2.66 µm → I_off 665 pA (sf 125 °C) fails;
L = 0.30: 510 kΩ → W 0.54 µm, I_off 53 pA ≤ 281 pA passes. Longer L only adds R_on
(0.45: 250 kΩ, 3.0: 453 kΩ). At tt/27 °C the leakage sits on ngspice's gmin floor
(~1 pA at 0.9 V), which is what sets AnalogIOC's τ ≈ 27 ms and the τ ≈ 30 ms here.

Read device, sky130: L ≤ 0.90 needs W < min_w for 6 µA (min_w would overshoot the
column ceiling); L = 1.05, W 0.45: σ(VGS) 9.70 mV at mid scale (6.2 nA) — fails;
L = 1.20, W 0.50: 8.56 mV (6.8 nA) / 4.08 mV (6.0 µA) — passes. Subthreshold (mid-scale)
mismatch dominates. AnalogIOC's 0.42/0.5 read device would sit near 11–14 mV σ (Pelgrom
estimate, WL 0.21 µm²): its 16 levels were not separable cell-to-cell at 3σ.

## Results

| Rung | Result | Notes |
|------|--------|-------|
