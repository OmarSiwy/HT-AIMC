# softmax_combine — level-1 group combine stage (Chip 2 B4/B5, cross-bank)

Leaf block. It combines G level-0 bank partials (m, l, o) into one group partial
(CHIP2_SPEC §4 level 1). It is a second shared-source translinear stage whose gates are
the banks' V_ls readouts (level-shifted into the score window) rather than raw scores.
KCL on the group source node splits the tail as

    I_b = I_B · e^(β V_ls,b) / Σ_c e^(β V_ls,c) = I_B · l_b / l_group

so the mirrored branch currents are the per-bank rescale weights g_b. The group node
itself (`vls_group`) carries ln l_group, the logsumexp of logsumexps, in the same log
code the level-0 banks emit. G = 2 at mini scale. Combining G banks grows the log axis
by ln(G)/β (26 mV at G = 2, 104 mV at G = 16), which caps G at 16 inside the 120 mV
constant-β window. See `analog/docs/architecture.md` §Chip 2 and AnalogIOC
`docs/src/content/Project/CHIP2_SPEC.md` §4.

## Interface

`.subckt softmax_combine vls0 vls1 igrp0 igrp1 vls_group vb_tail vdd vss` (AnalogIOC port
order; `build(g=G)` generalises it to vls0..G-1, igrp0..G-1)

| Port | Dir | Meaning |
|------|-----|---------|
| vls0, vls1 | in | bank b's V_ls (level-0 shared-source readout), level-shifted into the score window |
| igrp0, igrp1 | out | mirrored branch currents, sourced from vdd into loads near VDD/2; g_b = igrp_b / Σ igrp |
| vls_group | out | group shared-source node = ln l_group (log-domain readout) |
| vb_tail | in | tail gate bias: the same vb_tail as the banks and the rescale pairs (β match, CHIP2_SPEC R1/R2) |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

## Specs

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| Group node carries ln l_group: worst residual of one (slope, const) fit to the golden logsumexp of 4 bank-V_ls pairs | | | 0.02 | nat | `tb_combine_tree` |
| B5 rescale pair ratio vs group-stage weight ratio igrp0/igrp1, same gates | −2 | | +2 | % | `tb_combine_tree` |
| Flat group l vs `golden.group_combine` | | | 2.5 | % | `tb_combine_tree` |
| Flat group o (worst of d_v = 3) vs golden | | | 2.5 | % | `tb_combine_tree` |
| Group m error vs golden | −5 | | 80 | mV | `tb_combine_tree` |
| Golden associativity (flat == pairwise) and analog o/l vs golden | | | 2.5 | % | `tb_combine_tree` |
| Input-referred offset (vls0 − vls1 at igrp0 = igrp1), 3σ + \|mean\|, Monte Carlo | | | 5 (`specs.VOS_SOFTMAX`) | mV | `tb_softmax_combine_mc` |

Sources: every `tb_combine_tree` row is a AnalogIOC assertion with its threshold unchanged
(2.5 % = CHIP2_SPEC T5, 1.4 %·√2 + margin). The m row is AnalogIOC's too, and it is
trivially met: m is the digital max of the bank maxima, not an analog readout of this
block. The MC row is new: a group weight errs exactly like a rescale g, so it takes the
score-path offset budget `specs.VOS_SOFTMAX` (CHIP2_SPEC T2). Reported but not asserted,
as in AnalogIOC: energy per 3 µs window and the ln G log-axis projection.

Testbench conditions. The level-0 banks are stimulus from `translinear_softmax.build()`,
and the B5 pair from `rescale.build()`. Both always run the schematic, whatever `$DUT`
is. AnalogIOC's two 8-score banks are re-centred from 0.75 V onto this PDK's score-window
CM (`rescale.score_window()`). Bias is current-referenced: vb_tail is servoed on the DUT
so that Σ igrp = I_B at equal gates, and the same vb_tail drives the banks and the B5
pair (one bias line in the system). The level shift is derived as score CM − mean bank
V_ls, where AnalogIOC typed 0.47 V. It is a common offset on both gates and cancels in
every ratio. Loads hold the outputs at `specs.VCM_FRAC`·VDD. Values are read at the end
of the 3 µs evaluation window.

## Sizing

The stage is a softmax bank of N = G = 2, which is the B5 rescale pair's circuit with
its source node brought out. It therefore imports the pair's coordinate
(`rescale.sizes()`) and does not re-derive it. That coordinate is: gm/ID = 0.91 × the
weak-inversion ceiling at I_B, and L stepped up from min_l until the pair meets its
offset share on measured mismatch (`docs/mismatch.py`). The mirror is the lowest gm/ID
that leaves the branch V_DS_MIN at the window top, with L stepped until it meets its
share. Fingers use rescale's `_fingered` (even nf ≈ √(W/L), W rounded up to 10 nm per
finger).

| Device | Role | sky130 | gf180mcuD | AnalogIOC |
|--------|------|--------|-----------|---------|
| tail | I_B sink on the group node | 63.12/2.4 nf 6 | 75.36/1.12 nf 8 | 47.4/1.0 |
| b0, b1 | translinear branches | 63.12/2.4 nf 6 | 75.36/1.12 nf 8 | 47.4/1.0 |
| md, mo ×2 | pfet diode + output mirror | 2.16/9.6 | 0.58/4.48 | 5.0/1.0 |

RESULTS_PLACEHOLDER
