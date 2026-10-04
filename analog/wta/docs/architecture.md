# wta — N-input source-follower running max (Chip 2 B3)

Leaf block. The online-softmax running max m = max(m_old, block max). `chip2_attention`
feeds one mrail/rrail pair to both the exp bank (`translinear_softmax`, B4) and the
rescale pair (`rescale`, B5); `ptat_bias` supplies `vb_tail`. See
`analog/docs/architecture.md` and AnalogIOC `docs/src/content/Project/CHIP2_SPEC.md` §2.3.

## Interface

`.subckt wta vin0 vin1 vin2 vin3 vin4 vin5 vin6 vin7 vin_hold vref mrail rrail vb_tail vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| vin0..7 | in | scores, 0.6–0.85 V window |
| vin_hold | in | held previous m_hat (input domain) for the running max; vss = fresh max |
| vref | in | replica gate, top of the score window (0.85 V) |
| mrail | out | shared source rail ≈ max(vin) − VGS (+ soft excess); Chold on it |
| rrail | out | replica rail = vref − VGS |
| vb_tail | bias | tail gate, VGS(gm/ID = 25) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

Consumer reads m_hat = mrail − rrail + vref (VGS cancelled by the replica).

## Topology

Nine NMOS followers (vin0..7, vin_hold) share the source rail `mrail` with one tail sink;
the highest gate holds the rail, the rest drop into weak conduction. A matched replica
follower + tail (gate `vref`) makes `rrail`. In subthreshold the rail is a logsumexp of
the gates with n·U_T smoothing and slope κ ≈ 0.8 (body effect), so

m_hat − max = (lse − max) + (1 − κ)(vref − lse) ≥ 0

— a safe overestimate as long as every input sits at or below vref. That is why vref is
the top of the window. Devices are AnalogIOC's one-for-one (`schematics/components/wta/wta.py`).
Chold is a MIM cap.

## Specs

This is a range spec, not an accuracy spec: softmax is shift-invariant, so a
consistent overestimate cancels. n·U_T(T) = `pdk_specs.ss_mv_dec`/ln10 · T/300.15 K
(39.1 mV at 27 °C).

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| m_hat − max(vin), 6 patterns (one-winner, all-equal, tie, 1 mV split, low winner, permuted) | −5 | | n·U_T(max(T, 27 °C))·ln8 + 18 (99 @ 27 °C) | mV | `tb_wta` |
| Settle of m_hat to ±5 mV | | | 1 | µs | `tb_wta` |
| Replica-cancelled offset (one winner at vref, 7 losers at the window bottom) | | | 5 + 17.5·(n·U_T(T)/n·U_T(27 °C) − 1)⁺ | mV | `tb_wta` |
| Permutation: \|Δm_hat\| when the winner moves | | | 5 | mV | `tb_wta` |
| Streamed running max, 3 blocks rising then falling, per-block error | −5 | | same ceiling | mV | `tb_wta` |
| Running max held across the falling block | block-2 max − 5 | | | mV | `tb_wta` |
| (vin_i − m_hat) drift at +50 mV common mode (R1, one m_hat node) | | | 2 | mV | `tb_wta` |
| Energy per update, 2 µs window (report only, METRICS mandate) | | 9.8 | | pJ | `tb_wta` |
| Random offset 3σ, Monte Carlo (mismatch) | | | 5 | mV | `tb_wta_mc` |
| Worst MC sample underestimate | −5 | | | mV | `tb_wta_mc` |

AnalogIOC ran the tb at 27/55/85 °C inside one script. Here each temperature is a
`TEMP=` run, and the corners rung covers −40/27/55/85/125 °C. The 18 mV range margin
and the offset's systematic term are AnalogIOC's. Its n·U_T came from the measured
softmax β (27.31 /V → 36.6 mV); here it comes from the PDK subthreshold swing. Both
temperature-scaled bounds only grow above 27 °C. They never shrink when cold: the
headroom is reserved at the design temperature.

Bench, not block (`tb_wta` docstring):

* `vb_tail` is driven by I_TAIL into a diode-connected copy of the tail, standing in
  for `ptat_bias`, instead of AnalogIOC's fixed 0.44 V. A fixed subthreshold VGS let the
  tail current collapse at ss/fs −40 °C, and settle hit 1.2 µs.
* The offset test's losers sit at the window bottom instead of vref − 150 mV. AnalogIOC's
  "replica residual" (+3.4 mV at 27 °C, growing with T) was mostly the losers'
  soft-max share, n·U_T·ln(1 + 7·e^(−150 mV/n·U_T)). With the losers moved, the residual
  is +0.22 mV, and it was +13.8 mV at 125 °C before the change.

## Sizing

Derived in `netlist/wta.py` from `docs/gmid.py`. All devices are one matched coordinate,
so the replica sees the winner's operating point:

| Device | Role | Coordinate | AnalogIOC hand |
|--------|------|------------|--------------|
| followers ×9, tail, replica follower + tail | matching / low power | gm/ID = 25, L = 1.0 µm, W·L from the offset budget → 97.58/1.0, nf = 4 | 47.4/1.0 |
| vb_tail | bias | VGS(25, 1.0) = 0.450 V | 0.44 V |
| I_tail | consequence | W·J_D(25, 1.0) = 1.36 µA | ~0.58 µA measured |
| Chold | settle cap | `specs.design()["c_hold"]` = 200 fF (MIM 9.83 × 9.83 µm) | 200 fF |

Area: σ_off = K_OFF·A_VT/√(WL), with A_VT the pair coefficient (`pdk_specs.a_vt`,
5.26 mV·µm measured by `pdk_char.py`). VT alone would give K_OFF = √2. `tb_wta_mc`
measured σ·√(WL) = 13.5 mV·µm at WL = 36, 51 and 98 µm², so K_OFF = 2.56: subthreshold
current-factor mismatch adds through n·U_T. The block is sized for 3σ = 4.1 mV. That
keeps 18 % margin on a 30-sample σ, and W ≤ 100 µm keeps one instance in sky130's W
bins. With `m=2`, the model would see half the area for mismatch, because sky130
scales it by its own `mult` param. The cost is 2.3× AnalogIOC's current: 9.8 pJ vs
4.2 pJ per update.

## Results

| Rung | Result | Notes |
|------|--------|-------|
| pre-layout (`DUT=sch`, tt 27 °C) | PASS 13/13 | one-winner +3.4, all-equal +81.9, tie +29.9, 1 mV split +36.2, winner-low +91.5 mV (ceiling 99.3); settle 3–68 ns; offset +0.22 mV; permutation 0.00 mV; stream +31.6/+17.1/+20.8 mV, held 860.8 mV; CM drift 0.053 mV; 4.9 µW, 9.8 pJ/update |
| golden model (`DUT=va`) | PASS 13/13 | winner-low +93.4, all-equal +83.2, offset +0.29 mV, CM drift 0.000 mV (nut 38 mV, kappa 0.8 fitted to sch) |
| layout (Philis, kept `it4_seed2`) | DRC 0 (1 density waived), LVS MATCH | advanced 4/6. IrDrop (`vdd_load` 176 %) and EsdLatchup (57 Ω vs 28 Ω) are flagged; the exit code ignores both. 1 ERC `unconnected_pin` stub. Budget `parasitic_mrail` is 22 kΩ over. Die 90 × 70 µm |
| post-layout (`DUT=pex`, it4_seed2) | PASS 13/13 | identical to sch within 0.1 mV; settle 13–61 ns. pex.py lumps C only (mrail 79 fF); per-net R is not placed |
| corners (`DUT=sch`, tt/ss/ff/sf/fs × −40/27/55/85/125 °C) | PASS 25/25 | |
| Monte Carlo (30 × tt_mm, offset) | PASS | mean +0.19 mV, σ 1.40 mV (3σ 4.19 < 5), range −3.85…+2.85 mV |

Philis runs (`--interface layout/interface.json`):

| Run | Knob | Runtime | DRC | LVS | Unrouted | Advanced | Note |
|-----|------|---------|-----|-----|----------|----------|------|
| if_seed1 | seed 1, max-iters 100 | killed at iter 21 (~12.7 h) | 0 in-loop | MATCH in-loop | 0 | — | about 45 min/iter in "extracting feedback"; never converged; no GDS |
| if_seed2 | seed 2, max-iters 100 | killed at iter 25 (~12.7 h) | 0 in-loop | MATCH in-loop | 0 | — | same |
| it4_seed1 | seed 1, max-iters 4 | 6948 s | 0 | MATCH | 0 | 4/6 | C 769 fF, IR 192 %, ESD 65 Ω |
| **it4_seed2** | seed 2, max-iters 4 | 3321 s | 0 | MATCH | 0 | 4/6 | **kept**: C 695 fF, IR 176 %, ESD 57 Ω |

AnalogIOC reference (47.4/1.0, 27 °C): clear winner +3..+8 mV, all-equal +82 mV, replica
residual +3.4 mV, settle 13–117 ns, 4.2 pJ/update, shift drift 0.053 mV.
