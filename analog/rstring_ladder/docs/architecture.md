# rstring_ladder — 4b R-string reference ladder + tap mux

Child: `cmos_switch` (one sized copy, `rstring_ladder_sw`, for all 16 taps). Used by
`analogioc` (four instances): coarse comparator thresholds (vcm ± 15.5·D·u) and SAR CDAC
span rails (vcm ± 16·D·u). Packet references are not taken from here (ratiometric to
VDD, see `integrator_conv`). See `analog/docs/architecture.md`.

## Interface

`.subckt rstring_ladder b0 b1 b2 b3 out vrn vrp vdd vss` (AnalogIOC
`components/rstring_ladder`)

| Port | Dir | Meaning |
|------|-----|---------|
| b0..b3 | in | 4b tap code, b3 = MSB, CMOS levels |
| out | out | selected tap through its TG: vrn + code·(vrp − vrn)/15 |
| vrn, vrp | in | external ladder rails (tap0 = vrn, tap15 = vrp) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 (decoder, TG bulks, decap / resistor bodies) |

Structure: 15 equal poly segments, a MIM decap on each inner tap (tap1..tap14), a 4:16
decoder (NAND2 / NOR2 / NAND2 + INV per tap, write_dac idiom) one-hotting a TG per tap.
The tap set is static during a conversion; kickback comes only from CDAC/comparator
sampling, and the decap holds it.

## Specs

Test band: rails vcm ± 0.4 V (the worst rail-to-rail band `specs.r_seg()` is sized for),
16 codes × 100 ns, 20 fF on `out`. Kick: tap 7 (mid-string, worst Thevenin 15R/4).

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| 16 taps strictly monotone | yes | | | — | `tb_rstring` |
| \|tap error\| vs vrn + k·(vrp − vrn)/15 | | | 2 | mV | `tb_rstring` |
| String power at the 0.8 V band | | | `specs.P_LADDER_BUDGET` = 5.5 | µW | `tb_rstring` |
| Kick: time `out` spends outside ±`specs.V_TAP_TOL` (0.5 mV) after `specs.C_KICK_CDAC` (96 fF) precharged `specs.V_KICK` (75 mV) away is switched on | | | `T_KICK` = 5 | ns | `tb_rstring` |
| Monotone in every mismatch sample | yes | | | — | `tb_rstring_ladder_mc` |
| Worst tap error at the SAR span vcm ± 16·`u_cal`, mean + 3σ (FET mismatch in SPICE + resistor mismatch) | | | `specs.V_TAP_TOL` = 500 | µV | `tb_rstring_ladder_mc` |

* 2 mV and 5 ns are AnalogIOC `tb_rstring` thresholds (it measured 0.21 mV / 3.51 ns).
* The kick check's switch stands in for the CDAC's own sampling switch: a `cmos_switch`
  at `KICK_SCALE` = ½ the mux TG width (AnalogIOC: 4× vs 8× write_tg).
* Monte Carlo error budget: `V_TAP_TOL` ≈ u_cal/3 is the tap tolerance the whole
  reference chain is held to (specs.py §reference ladder); the SAR span is the widest
  span the ladder serves in the system, so it bounds the absolute error.

## Sizing

Derived in `netlist/rstring_ladder.py` from `specs.py` / `pdk_specs.py` / `gmid.py`.

| Device | Derivation | AnalogIOC hand | sky130 | gf180mcuD |
|--------|------------|--------------|--------|-----------|
| segment R ×15 | `specs.r_seg()` (static power ≤ P_LADDER_BUDGET at the 0.8 V band), low-tempco poly `res_poly_lotc` (a reference) | 8 kΩ ideal R | high_po_0p35, L 6.86 µm | ppolyf_u 1 × 20.98 µm |
| tap decap ×14 | `specs.c_tap()`: C_KICK·V_KICK / c_tap ≤ V_TAP_TOL/2 | 29 pF ideal C | MIM 118.4 µm square | MIM 117.9 µm square |
| tap TG n / p (L = min) | R_mux·(1 + 1/KICK_SCALE)·C_KICK·ln(V_KICK/(V_TAP_TOL/2)) ≤ T_KICK → R_mux = 3.04 kΩ; W_p/W_n = un_cox/up_cox; W_n from the **measured** peak R_on over (0, VDD) at the typical corner (R_on·W constant, referenced at 10·min W) | 3.36 / 6.72 (write_tg × 8) | 2.87 / 8.61 | 0.73 / 3.21 |
| logic (INV, NAND2, NOR2) | W_n = min W, W_p = W_n·√(J_n/J_p) at \|V_GS\| = VDD (async_ctrl's min-average-delay ratio); code is static, speed is no budget | 0.42 / 0.84 | 0.42 / 0.70 | 0.22 / 0.32 |

Why measured R_on: the peak sits near mid-rail (0.95 V on sky130), where square law is
~20× optimistic (`cmos_switch` doc); `sizes(r_on)` would clamp the TG to min W.

Dropped from AnalogIOC: the 1 fF ideal cap on each NAND2 stack node (a convergence stub,
below the MIM minimum). No other topology change.

Kept on purpose: the TG's standard-Vt devices (see Results: corners).

## Results

(filled per rung below)
