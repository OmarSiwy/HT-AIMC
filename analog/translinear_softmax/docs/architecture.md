# translinear_softmax — 8-input translinear softmax bank (Chip 2 B4)

Leaf block. The exp + local-sum stage of the online softmax: scores sampled onto the
bank gates come out as normalised currents a_i·I_b that drive the A·V stage (B6).
`ptat_bias` supplies `vb_tail`; `wta` (B3) and `rescale` (B5) run on the same
subthreshold coordinate. See `analog/docs/architecture.md` and AnalogIOC
`docs/src/content/Project/CHIP2_SPEC.md` §2.4. AnalogIOC source:
`schematics/components/translinear_softmax/translinear_softmax.py`, testbench
`testbenches/tb_softmax.py`.

## Interface

`.subckt translinear_softmax vin0 … vin7 iout0 … iout7 vb_tail vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| vin0..7 | in | scores on the branch gates, inside the score window (`score_window()`: vb_tail + 6kT/q … + `specs.SCORE_SPAN`; AnalogIOC 0.6–0.85 V) |
| iout0..7 | out | branch currents I_b·e^(β·vin_i)/Σ e^(β·vin_j), sourced from vdd into loads held near VDD/2 |
| vb_tail | bias | tail gate; `ptat_bias` drives it from a diode replica of the tail (same W/L) |
| vdd, vss | supply | `pdk_specs.vdd`, 0. All branch current returns through vss (= the tail current) |

## Topology

Shared-source NMOS bank over one tail sink: the source node s settles where the branch
currents sum to I_b, so KCL is the normalisation and β = 1/(n·U_T) is the exponent. Each
branch drain feeds a PMOS diode (md) mirrored 1:1 (mo) to its output. AnalogIOC's devices
one-for-one:

| Device | Role | Nets (d g s b) |
|--------|------|----------------|
| tail | I_b sink | s vb_tail vss vss |
| b0..7 | translinear branch | d_i vin_i s vss |
| md0..7 | mirror diode | d_i d_i vdd vdd |
| mo0..7 | mirror output | iout_i d_i vdd vdd |
