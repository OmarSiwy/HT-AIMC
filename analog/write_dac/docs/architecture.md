# write_dac — 4-bit R-string write DAC

Schematic, drawn by cktImg from `netlist/write_dac.spice` (`make import NETLIST=write_dac`): [write_dac.svg](write_dac.svg)

Programs gain-cell storage nodes: `gain_cell_array` writes (row-shared `wdata`) and the
two `lora_sidecar` update DACs (`wda`/`wdb`). Depends on `cmos_switch` (tap mux). See
`analog/docs/architecture.md`.

## Interface

`.subckt write_dac b0 b1 b2 b3 out vref vdd vss` (AnalogIOC `components/write_dac`)

| Port | Dir | Meaning |
|------|-----|---------|
| b0..b3 | in | binary code, b3 MSB, VDD logic |
| out | out | tap `code`·vref/15 through the selected TG (drives the gain-cell write switch) |
| vref | ref | ladder top = write ceiling V_W = `specs.VCM_FRAC`·VDD (AnalogIOC 0.9 V) |
| vdd, vss | supply | `pdk_specs.vdd`, 0; vss is also the ladder bottom |

Topology (AnalogIOC, device for device): 15 equal poly segments vss..vref; one inverter
per bit; per tap a 4:16 decoder slice nand2(b3,b2 literals), nand2(b1,b0 literals),
nor2 → `sel_k`, inverter → `seln_k`; 16 `write_dac_sw` transmission gates tap_k → out.
264 FETs + 15 resistors. Monotone by construction. Parents build a uniquely named copy:
`children(name)` + `build(name)` (switch `<name>_sw`, as AnalogIOC's `generate(name)`).

## Specs

LSB = V_W/15 = 60 mV. Load in every testbench = the real write path: an ON gain-cell
write switch (AnalogIOC `gc_write_n` 0.42/0.5 µm, gate at VDD) into `c_store` (30 fF).

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| 16 settled store levels strictly monotone | 16/16 | | | — | `tb_write_dac` |
| Level error \|v_k − k·vref/15\| | | | 5 | mV | `tb_write_dac` |
| Settling to ±LSB/2, every step incl. 15→0→15 | | | 100 | ns | `tb_write_dac` |
| Energy per 200 ns code slot (ladder from vref + logic from vdd) | | | 1.2 | pJ | `tb_write_dac` |
| Level error per tap, \|mean\| + 3σ, Monte Carlo (FET mismatch simulated + segment mismatch from `<kind>_a_r`) | | | 5 | mV | `tb_write_dac_mc` |
| Every MC sample strictly monotone | 30/30 | | | — | `tb_write_dac_mc` |

* 5 mV, 100 ns: AnalogIOC `tb_write_dac` thresholds. 1.2 pJ: AnalogIOC's measured 1.208 pJ
  (`docs/src/content/Project/METRICS.md`, A3), made a ceiling; it holds on every corner.
* Segment mismatch is not simulated by either PDK in ngspice (sky130 fixes
  `res_high_po__slope_spectre` = 0 in `model__linear`; gf180 `ppolyf_u*` has only global
  terms), so the MC testbench draws it per sample from `pdk_specs.<kind>_a_r` (sky130:
  the model files' `body_pelgrom`).

## Sizing

Derived in `netlist/write_dac.py`. No gm/ID coordinate: passives, triode switches and
rail-to-rail logic.

| Device | Derivation | AnalogIOC hand | sky130 | gf180mcuD |
|--------|------------|--------------|--------|-----------|
| segment R | RC ceiling: worst-tap Thevenin k(15−k)/15·R (k = 7) = (1 − `cmos_switch.R_GUARD`)·`cmos_switch.r_on_budget()` — the write-path budget the TG leaves | 10 kΩ ideal R | 35.8 kΩ | 35.8 kΩ |
| segment kind / length | mismatch floor: 3σ worst-tap error vref·σ_R·√(56/15³) ≤ √0.9·5 mV, σ_R = a_r/√(W·L); fixed-width device → area ∝ R → minimum R per kind. First kind (dense first) whose floor is under the RC ceiling | — | `res_high_po_0p35`, 0.35 × 30.71 µm (σ_R 1.08 %, 3σ 3.8 mV) — dense xhigh_po needs ≥ 107 kΩ (8.2 mV at 35.8 kΩ) | `ppolyf_u_1k` 1 × 34.2 µm; a_r undeclared (unsized, warned) |
| tap TG | `cmos_switch` default instance (its write-DAC tap role) | 0.42/0.15, 0.84/0.15 | n 0.58/0.15, p 0.42/0.15 | 0.22/0.28 both |
| logic N / P | N min_w; P = N·J_ON,n/J_ON,p at L (equal drive); L = smallest k·Lmin whose worst-corner 125 °C leakage, all 232 logic FETs off, ≤ the ladder's static power (`char/<pdk>.json`) | 0.42/0.15, 0.84/0.15 | 0.42/0.30, 1.74/0.30 | see hotswap |

Why L = 2·Lmin for the logic: sky130 pfet 1.16/0.15 leaks 423 nA at the worst corner,
125 °C (AnalogIOC's 0.84/0.15: 452 nA at ff) against 131 pA at L = 0.30. The first
Lmin draft burned 1.72 pJ of logic leakage per slot at ff/125 °C and failed the energy
row; the ladder alone draws 1.5 µW.

## Golden model

`va/write_dac.va`: tanh bit thresholds at vdd/2 → continuous code; out is a Thevenin
source code·vref/15 behind rseg·code(15−code)/15 + ron, with `cout` on out; vref draws
vref/(15·rseg). Defaults rseg 35.8 kΩ, ron 10 kΩ, cout 10 fF. Not modelled: decoder
delay, TG injection/leakage, segment mismatch and voltage coefficient, logic current
(logic energy reads 0 on `DUT=va`).

## Results

RESULTS_PLACEHOLDER
