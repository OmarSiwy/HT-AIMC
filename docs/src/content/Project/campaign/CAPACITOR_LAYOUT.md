# Capacitor layout and parasitic extraction

Status: **VERIFIED within the installed DRC/extraction model**. Four full-top-metal
and four contact-only-top-metal coupons pass full Magic DRC and independent
native ngspice terminal-capacitance matrix checks. This is not array PEX.

The experiment generates isolated square Sky130 MIM capacitors with Substrate2
and uses Magic for DRC/extraction. It tests unit-cap feasibility and parasitic
plate loading before assigning an area or gain to the charge-stack architecture.
An isolated coupon excludes neighboring wires, switches, wells and array routing.

Generator data contract, stated before implementation:

1. Inputs are fixed capacitor widths; outputs are four GDS coupons, followed
   by independent DRC and extracted electrical networks.
2. Four sizes are generated: 1, 2, 5 and 20 micrometres square.
3. Widths are 1000–20000 integer nanometres, stored as u16. Geometry arithmetic
   converts to the Substrate i64 coordinate type, including the negative
   140-nm bottom-plate enclosure. No unbounded numeric input is accepted.
4. Each width is read once; all geometry for that coupon is emitted together.
   A fixed array of scalar widths is sufficient.
5. Geometry lives for one generator invocation. GDS and extraction artifacts
   are retained under a uniquely named build directory.
6. Coupons are independent and could run in parallel; four tiny generators
   are emitted sequentially, while extraction may run independently.

The pinned sky130 crate lacks CAPM in its layer enum. The coupon therefore
uses Substrate's generic layout schema with explicit GDS layers, retaining
the repository's Substrate2 layout requirement. Installed Magic technology
maps CAPM to89/44, metal3 to70/20 and metal4 to71/20. DRC is the acceptance
check; drawing a plausible rectangle is not a legal-layout result.

## Extracted results, 2026-09-11

The contact-only variant retains the same MIM and metal3 plates but replaces
full-area metal4 with a 500-nm contact patch. Both variants use one via.
The new bounded top-metal-width field is also an integer u16 in nanometres.

| MIM width (µm) | PDK capacitor (fF) | Mutual C, full/contact (fF) | Top-to-substrate, full/contact (fF) | Bottom-to-substrate (fF) | Bottom footprint (µm²) |
|---:|---:|---:|---:|---:|---:|
| 1 | 2.64225 | 2.76778 / 2.71535 | .14452 / .07030 | .23014 | 1.6384 |
| 2 | 9.30225 | 9.72136 / 9.41138 | .28904 / .06641 | .43813 | 5.1984 |
| 5 | 53.28225 | 55.59048 / 53.42238 | .72259 / .05549 | 1.21056 | 27.8784 |
| 20 | 813.18225 | 847.62415 / 813.33763 | 2.89037 / .02982 | 8.41262 | 411.2784 |

Reducing metal4 substantially reduces extracted top-plate loading. It does
not remove bottom-plate loading: the latter remains approximately 8.48% of
mutual C at 1 µm and 1.03% at 20 µm in the contact variant. Charge-stack
analyses must retain this size-dependent loading, rather than assigning one
arbitrary parasitic percentage to all capacitors.

The electrical audit exposes and grounds extracted SUB, verifies reciprocity
and positive shunt capacitance, and checks the PDK capacitor independently.
Magic's SI-valued `l=1u w=1u` instance dimensions are converted to the wrapper's
numeric-micrometre convention before simulation; unchanged double-scaled
dimensions would produce invalid results. Width assertions guard this step.

Evidence: `build/campaign/mim_layout_r1`, `mim_extract_r1`,
`mim_electrical_r1`, and corresponding `*_contact_r1` directories. Exact
generator, technology hashes, GDS, DRC output, extracted decks and electrical
matrices are preserved. Source: `analog/layout/examples/mim_coupon.rs` and
`analog/testbenches/tb_imc_mim_coupon.py`.

**Limits:** Magic uses approximate overlap/shielding rules; the extra full-area
M3–M4 mutual capacitance is not independently verified by a 3D field solver.
No extracted distributed resistance or actual single-via resistance audit has
been completed. The PDK capacitor's built-in series resistance alone does not
qualify this contact geometry at high bandwidth. Neighbor routing, shields,
switches, SRAM overlap and statistical mismatch remain outside these coupons.

## Actual unit-capacitor dimensions

A second bounded size set uses1.260/1.580/1.840µm square MIM plates with
500nm contact-only top metal. These are10nm-grid width choices targeting
approximately4/6/8fF after the installed model's−.025µm dimension correction
and fringe term, not the area-only2fF/µm² approximation. The generator retains
fixed arrays of u16 widths; all prior size-set behavior remains available.
All three coupons pass full DRC and the native terminal-matrix audit under
`build/campaign/mim_units_contact_electrical_r1`. These dimensions do not
yet establish layout of binary banks, matching yield or routed macro area.

| Width (µm) | PDK C (fF) | Extracted mutual C (fF) | Top/body C (fF) | Bottom/body C (fF) | Bottom footprint (µm²) | Bottom/mutual |
|---:|---:|---:|---:|---:|---:|---:|
|1.260|3.98905|4.07454|.06928|.28183|2.3716|6.917%|
|1.580|6.01785|6.11535|.06804|.34776|3.4596|5.687%|
|1.840|7.96785|8.07301|.06703|.40319|4.4944|4.994%|

These are closer to actual arithmetic-unit sizes than the20µm large capacitor
coupon. Using the large coupon's1% bottom parasitic for individual4–8fF
units would be optimistic. Unit segmentation versus one larger binary-weight
capacitor trades deterministic fringe ratios, mismatch averaging and wiring;
this experiment does not yet select between them.


## Unequal low/high digit sizing — 2026-09-11 16:06 UTC

Substrate2 `contact unequal` generates1.00/1.36µm unit coupons. Both pass
full DRC and the extracted native terminal-matrix audit. Results and hashes:
`build/campaign/mim_unequal_contact_electrical_r1/result.json`.

| Unit width | Mutual C | TOP substrate C | BOTTOM substrate C | Isolated footprint |
|---|---:|---:|---:|---:|
|1.00µm|2.71535fF|.07030fF|.23014fF|1.6384µm²|
|1.36µm|4.66865fF|.06889fF|.30217fF|2.6896µm²|

Using seven low-digit and fifteen high-digit units gives51.8128µm² isolated
footprint versus52.1752µm² for equal1.26µm coupons, and89.0372fF mutual
capacitance versus89.63988fF. This reallocates nearly the same capacitance
and footprint toward the numerically higher-weight bank; it is not a full
cell or macro area result.

A conditional grounded32-row ledger with120fF floor, two-holder kT/C,
independent50µV receiver noise and no CDAC predicts total reconstructed
noise variance ratio .91291 (−8.71%). Thermal variance alone falls13.10%.
The calculation uses Ctotal/Cmutual for signal normalization, preserving
substrate loading separately. MOS loading, actual receiver scaling, mismatch,
sharing radix, fine DAC, clock/control and full network quality remain
unverified. This is STRONGLY SUPPORTED geometry and SPECULATIVE system benefit.
The small low bank passes its first signed SS85 charge test; the larger high
bank is being tested with admittance-informed .63/.70µm switching devices.
