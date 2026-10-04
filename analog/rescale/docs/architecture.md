# rescale — translinear rescale ratio pair (Chip 2 B5)

Leaf block. The online-softmax rescale factor g = e^(β·(v_lo − v_hi)) ≤ 1: it shrinks a
bank's running partial (l, o) when a new block raises the max (v_hi = m_new, v_lo =
m_old, both from the one WTA m̂ rail pair), and at level 1 applies
g_b = l_bank / l_group (v_hi = V_ls,group, v_lo = V_ls,bank). See
`analog/docs/architecture.md` §Chip 2 and AnalogIOC `docs/src/content/Project/CHIP2_SPEC.md` §2.4.

One subthreshold shared-source pair (a softmax bank of N = 2): KCL on the common source
splits the tail current as I_hi : I_lo = e^(β v_hi) : e^(β v_lo), so the ratio of the
mirrored outputs is g, with no exp or divide circuit. β matches the exp bank
(`translinear_softmax`) only because both use the same device coordinate and the same
`vb_tail` (CHIP2_SPEC R1/R2). That coordinate is defined in `netlist/rescale.py` until
the bank migrates.

## Interface

`.subckt rescale vhi vlo ihi ilo vb_tail vdd vss` (AnalogIOC port order)

| Port | Dir | Meaning |
|------|-----|---------|
| vhi | in | reference gate (larger V, the normalizer branch) |
| vlo | in | rescaled gate (smaller V, the partial branch); g = I(ilo)/I(ihi) |
| ihi, ilo | out | mirrored branch currents, sourced from vdd into loads near VDD/2 |
| vb_tail | in | tail gate bias: the voltage that makes the tail sink I_B (a bias generator, `ptat_bias` in the system, supplies it) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

Score window: `rescale.score_window()`, bottom = VGS(coordinate) + V_DS_MIN, 250 mV wide
(sky130 0.595–0.845 V; AnalogIOC 0.6–0.85 V). Spread |vlo − vhi| ≤ 120 mV.

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| g(ΔV = 0) | 0.99 | 1 | 1.01 | — | `tb_rescale` |
| g ≤ 1 and monotone, ΔV = −120…0 mV | yes | | | — | `tb_rescale` |
| Exponential law, max \|g/e^(β_fit ΔV) − 1\|, vhi = window CM | | | 6 | % | `tb_rescale` |
| Same, vhi = window top (least branch V_DS) | | | 6 | % | `tb_rescale` |
| β_fit vs the bank's β (`rescale.beta_ref`, gm/ID ceiling × 300 K/T) | −10 | | +10 | % | `tb_rescale` |
| g settles to ±0.01 (absolute) of final after a 0 → −120 mV step | | | 3 | µs | `tb_rescale` |
| Energy per evaluation (3 µs window) | | | 1.3 × 2·I_B·VDD·3 µs | pJ | `tb_rescale` |
| Input-referred offset 3σ + \|mean\|, Monte Carlo (mismatch) | | | 5 | mV | `tb_rescale_mc` |

Sources: the 6 % law limit is AnalogIOC's raw (no-PTAT) rescale budget from
tb_online_softmax_analog (measured 5.2 % there against the bank's β). The 3 µs window is
AnalogIOC's evaluation window: it read g at the end of it. Settling is measured against
the normalizer (absolute error on g), because g multiplies a partial that is summed
with the new block's weight-1 term. The 5 mV offset is the CHIP2_SPEC T2 m̂ offset
line: this pair's offset lands on g exactly like a forked m̂. The energy limit is 1.3×
the ideal 2·I_B from vdd (AnalogIOC measured 6.2 pJ, 1.15×).

Bias in every testbench is current-referenced, as in the system: `vb_tail` is swept at
ΔV = 0 and set where I(ihi) + I(ilo) = I_B. Corners therefore see the design current,
not a fixed-voltage bias that drifts (AnalogIOC R2: 0.58 → 2.2 µA over 27 → 85 °C at a
fixed 0.44 V). Loads hold ihi/ilo at `specs.VCM_FRAC`·VDD.

AnalogIOC's other assertion on this block, tb_combine_tree's "B5 pair ratio = group-stage
weight ratio within 2 %", needs `softmax_combine` and belongs to that block's testbench.

## Sizing

Derived in `netlist/rescale.py` from `docs/gmid.py`, `docs/mismatch.py` and
`pdk_specs` (min_l, vdd). Every L steps up from min_l by doubling until the device meets
its share of the offset budget. The budget is checked against the PDK's own measured
mismatch at that geometry and current (`mismatch.pair_offset`), not Pelgrom.

| Device | Role | Derivation | sky130 | AnalogIOC |
|--------|------|------------|--------|---------|
| tail | I_B sink | gm/ID = 0.91 × weak-inversion ceiling at I_B = 500 nA; L from the pair's offset share | 63.12/2.4 nf 6 | 47.4/1.0 |
| branch ×2 | translinear pair | same coordinate and W as the tail | 63.12/2.4 nf 6 | 47.4/1.0 |
| mirror ×4 | pfet diode + out | lowest gm/ID whose \|VGS\| leaves the branch V_DS_MIN at the window top (10); W = (I_B/2)/J_D; L from the mirror's offset share | 2.16/9.6 | 5.0/1.0 |
| vb_tail | bias | VGS at the coordinate | 0.440 V | 0.44 V |

Offset budget: σ = 5 mV / 3. Half the variance goes to the branch pair and a quarter to
each mirror. A mirror's ΔVGS refers to the input as (gm/ID)_p/β. Measured on sky130 at
I_B/2:

| Device | Candidate | Measured pair σ | Share | Verdict |
|---|---|---|---|---|
| nfet | 35.69/1.2 | 1.66 mV | 1.18 | fail |
| nfet | 63.08/2.4 | 1.11 mV | 1.18 | pass |
| pfet | 0.82/4.8 | 3.45 mV → 1.27 at the input | 0.83 | fail |
| pfet | 2.16/9.6 | 1.64 mV → 0.61 at the input | 0.83 | pass |

Pelgrom on a_vt under-predicts here: sky130 also varies `voff`, which dominates in weak
inversion. On gf180 the same search lands on tail/pair 75.36/1.12 and mirror 0.58/4.48.

Devices stay single instances. `m=` would break the Monte Carlo: sky130 scales mismatch
by `mult` and gf180 by `par`, never by `m`, so m units are simulated with the mismatch
of one unit. Fingering is `nf`: the even count nearest √(W/L), a near-square footprint
(sky130 tail/pair nf = 6), with W rounded up to a whole 10 nm per finger
(63.08 → 63.12) so the extracted W equals the deck's. Left at nf = 1, Philis drew
64 µm-tall cells that did not fit the die. On gf180, `tb_rescale` passes at DUT=sch:
law 2.25 %, β 26.56 vs 28.57 /V, 397 ns, 9.89 pJ.

Why the sizes move from AnalogIOC. At AnalogIOC's sizing (47.4/1, mirror 5/1), MC measured
σ(V_os) = 5.3 mV, so 3σ = 16 mV. Mirror mismatch dominated: gm/ID ≈ 17 on 5 µm² of
gate. The derived sizing measures σ = 1.52 mV, and settles more slowly on the losing
branch: the mirror diode node's C/gm at ~20 nA gives 0.95 µs to ±0.01 on g, against
AnalogIOC's ~0.6 µs. Sweep data (tt_mm, N = 30): pair 36/1 with mirror 3.0/8 gave σ 2.1 mV;
pair 83/2 with the same mirror gave 1.24 mV. The pair's area is what brought the offset
down.

## Results

| Rung | Result | Notes |
|------|--------|-------|
| pre-layout (`DUT=sch`, tt 27 C) | PASS | g(0) 1.0000; law 2.21 % (CM) / 2.37 % (top); β 25.83 vs 27.09 /V; settle 953 ns; 5.40 pJ; vb_tail 0.444 V |
| golden model (`DUT=va`) | PASS | exact exponential (law 0.00 %, β 27.04 /V); settle 391 ns; 5.40 pJ. `tb_rescale_mc` is model-inapplicable (no mismatch in the model; it passes trivially) |
| layout (Philis, sky130, interface 100×70 µm, --max-iters 25) | DRC 8 / LVS MATCH | seed 1 kept: DRC 8 blocking (all `poly min_extension` −250 < 130 nm on the four L = 9.6 µm pfets: Philis device generator), LVS match, 0 unrouted, advanced 6/6, ERC 2 (p2p R > limit on 2 nets), 29.7 min. Seed 2: same DRC/LVS/advanced, ERC 3, 26.6 min |
| post-layout (`DUT=pex`, seed 1) | PASS | law 2.21 % / 2.37 %; β 25.83 /V; settle 993 ns (sch 953); 5.40 pJ. 9 lumped caps (≤ 30 fF), per-net R not placed (pex.py) |
| corners (`DUT=sch`, 5 corners × −40/27/125 C) | PASS 15/15 | worst law 4.68 % (ff −40 C, top); worst β −7.8 % (fs −40 C); settle 0.79–1.14 µs; servoed vb_tail 0.309 (sf 125) … 0.537 V (fs −40) |
| Monte Carlo (tt_mm, N = 30) | PASS | sch: V_os mean −0.10 mV, σ 1.52 mV → 3σ + \|mean\| = 4.66 mV < 5. pex: mean −0.20, σ 1.37 → 4.31 mV |

AnalogIOC reference (ngspice tt 27 C, its sizing): g(0) = 1.0000; error against the bank's
β of 0/1.7/3.3/4.4/5.1/5.2/4.9 % over ΔV = 0…−120 mV; ~6.2 pJ/eval.
