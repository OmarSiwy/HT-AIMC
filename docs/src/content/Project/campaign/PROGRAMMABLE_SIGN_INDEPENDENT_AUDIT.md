# Shared sign-routing capacitor-bank review

Status: **Topology/accounting review and completed deterministic fixture checks**.
`tb_imc_programmable_cap.py` remains owned by the parent; this review does not
change it.

## Charge polarity and device counts

For sign=-1, the actual complementary row is rown=1.8-row, so its excursion
about0.9V is the negative of the original excursion. The compiled capacitor
oracle uses that same rown source. Integrating the column-clamp source current
therefore has expected charge sign*amplitude*code*Cu, consistent with the
analysis. This is a physical complementary stimulus port, not an ideal negative
capacitor or free in-cell inversion.

Each programmable bit has two transmission gates: selected-row and idle
(VCM or its own column). The shared sign selector adds two more TGs per cell.
Thus B bits use4B+4 MOS:16 for3 bits and20 for4 bits. The sign TGs are twice the
bit width, so width-based area differs from transistor count. For N/P widths
Wn/Wp and sign scale s,

```
Sigma_W = 2(B+s)(Wn+Wp)
```

At s=2 this is66.7% more width than the unsigned3-bit cell and50% more than the
unsigned4-bit cell. Layout diffusion, contacts, gates, SRAM and routing are not
represented by this width proxy. `geometry.definitions_annotated` counts model
subcircuit definitions, not expanded per-cell transistor instances.

## Ports, energy and loading

VDD, VCM, row, rown and every column clamp are included in the positive source-
energy expression. Although rown current is not individually written in the
short transient vector list, it is saved and used in the computed aggregate
power. The aggregate runs all codes and all three modes in parallel; it is not
one-cell energy or an array-pass result. Comparisons of total3-bit and4-bit
fixture energy are particularly misleading because the latter has twice as many
code fixtures. Complementary-row driver implementation, SRAM/sign programming,
control transitions and actual shared row loading remain unpaid.

The AC measurement clamps both row sources to AC0 and drives every column AC1.
With ideal source impedances and independent cell-local sign nodes this gives
the stated local column admittance. It does not reproduce finite row-driver
impedance, cross-column coupling or a floating integrating column. At low
frequency series switch resistance scarcely changes measured capacitance;
higher-frequency admittance and transient charge error are needed for delay.

## Completed3-bit SS85 evidence

At Wn0.50/Wp0.70um, sign-selector scale2 and the frozen fresh input sequence:

| Fixture | Worst grounded error / weight FS | Worst bypass error / weight FS |
| --- | --- | --- |
| unsigned3-bit |0.00002624|0.00002957|
| shared negative sign3-bit |0.00045814|0.00045809|

Both pass the0.001 gate. The signed worst case is code7; the unsigned worst case
is code1. The sign selector materially worsens error but does not fail this
fixture. Full-code bypass capacitance is30.35581254fF in both low-frequency
measurements. Source/deck/results are preserved in
`build/campaign/programmable_cap/wn050_wp070_bits3_signneg_ss85_fresh_step1_r1/`
and `wn050_wp070_bits3_ss85_fresh_step1_r1/`. Independent tighter timestep and
physical array integration remain separate requirements.

## Bounded alternative worth testing

Replace the shared sign TG plus each bit's row/idle selector with three
mutually exclusive TGs per bit going directly to row, rown and idle. This keeps
real polarity generation and idle loading, but reduces the active path to one
TG. It costs6B MOS:18 for3 bits or24 for4 bits. At unchanged bit dimensions,
Sigma_W=3B(Wn+Wp),10% less than the present scale2 shared selector for3 bits and
equal for4 bits. Extra diffusion, OFF capacitance, sign-and-bit decoding and
control routing may erase that advantage. This is an explicit area/delay
candidate, not an assumed winner or a free sign operation. The parent is running
one matched3-bit control rather than a broad sizing sweep.
