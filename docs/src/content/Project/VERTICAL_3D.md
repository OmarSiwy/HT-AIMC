# VERTICAL 3D CHARGE ACCUMULATION (lever #16 / law L18) — feasibility + projection

Assessment of AnalogIOC's vertical charge-accumulation lever: stack `L` crossbar
layers in the BEOL and accumulate their partial products as **charge on one
shared column** before a **single** conversion,

    Q_col = sum_l sum_i  G_ij^(l) · V_r · t_i          (paper eq. vertacc)

so one conversion covers `L·N` MACs — capacity **and** throughput scale with
`L`, and conversions/MAC fall another `/L`. This is the paper's route to
"7B: 11 dies (2D) → 1–2 dies at L=8" **with throughput restored**, as opposed
to conventional front-end-shared stacking (note 27l8, law:threed) which is
capacity-only and cuts throughput `/L`.

NO SPICE. Compiler math is `scripts/compiler/metrics/pdk_projections.py::l_stack()`
(specs.py imported read-only; default path bit-identical, additive only).

---

## TASK 1 — Research verdict: is L=8 charge-domain vertical accumulation real?

**Short answer: the *stacking substrate* is real and demonstrated to L≈8; the
specific step AnalogIOC needs — summing L layers' partial products *in the charge
domain* on one shared column integral — is NOT demonstrated. It is
current-domain layer-summing that has silicon, not charge-domain. The paper is
honest about this ("the charge-domain BEOL column integral proposed here is the
un-demonstrated step, not layer-summed compute itself").**

### (a) Can compute devices be stacked in BEOL at <400 °C without damaging lower layers? — YES, demonstrated.
- Monolithic 3D integration of MoS₂ transistors + vertical RRAM (1T–nR) in
  Nature Communications 2023: whole process **<300 °C**, and measurement
  confirms top-plane fabrication does **not** disturb bottom-plane devices —
  the load-bearing feasibility claim for BEOL compute stacking.
  (nature.com/articles/s41467-023-41736-2)
- BEOL oxide-semiconductor (IGZO/ZnO) transistors are the mature <400 °C path:
  TFTs process below the low-k/Cu thermal ceiling (~400 °C) by construction;
  Kioxia's 2024 OCTRAM (GAA-IGZO over a capacitor, 275 Mbit) and ALD-ZnO BEOL
  logic+memory arrays are real silicon.
  (pmc.ncbi.nlm.nih.gov/articles/PMC10539278, Wiley aelm.202500521)
- BEOL FeFET CIM (Qian 2025, arXiv:2512.17165) fabricates a 32×256 HfZrO₂ array
  over a ~1000 °C-annealed front end at a **<400 °C** back-end budget — the
  exact ceiling law:threed cites. This device is BEOL-legal.

Verdict (a): **confirmed.** The <400 °C BEOL-legal compute-device requirement is
met by multiple real fabricated parts.

### (b) What L is demonstrated in real silicon vs projected?
- **L=8 is demonstrated — but as stacked *separate* crossbars, not one summed
  integral.** Lin et al. 2020 (Nat. Electron. 3:225) built **eight** layers of
  monolithically integrated memristors and ran CNN VMMs to software-comparable
  MNIST accuracy. The eight layers hold *different* weight planes with vertically
  aligned electrodes; they are eight crossbars, not L partial products landing on
  one accumulation node.
- **3D-VRRAM CIM macros** (Huo 2022; and 3D-VRRAM multilevel-programming work)
  do perform **layer-summed MACs** on a shared vertical structure — but the
  summation is **current-domain** (Kirchhoff current on the shared wordline/via,
  current-shaped and sensed), which is what all measured 3D-CIM does.
  (nature.com/articles/s41928-022-00795-x)
- Charge-domain CIM is real (superior linearity/robustness, 8-b multi-bit
  charge accumulation) but demonstrated **in 2D**, per-column
  (sciengine SCIS 11432-025-4615-6; CAP-RAM arXiv:2107.02388).

Verdict (b): stacking to **L=8 has silicon**; layer-summed MAC has silicon
(current-domain); **charge-domain vertical layer-sum has none.** L=8 for
AnalogIOC's mechanism is **projection-only**.

### (c) Thermal: does stacking L active compute layers corrupt analog margins / retention?
- General 3D-stack thermal result: stacking raises power density with **no**
  matching increase in heat-removal capacity; upper layers run hotter and the
  logic-to-heatsink distance grows, so **retention loss (not peak T) is the
  binding reliability failure** in 3D-stacked memory (multiple 3D-DRAM thermal
  studies; IEEE HIR 2023 ch.20).
- Both device conductance **and** the peripheral transfer function move with
  temperature (note 27d9), so a layer-to-layer gradient is a **shared-fate gain
  error** on the very quantity the MAC computes.
- **No source — read here or cited by the paper — measures layer-to-layer
  thermal gradients in an *analog* stack.** The paper flags this as "the
  experiment this section needs" (sec_system item iv). Genuinely open.

Verdict (c): thermal is an **unquantified risk**, not a demonstrated failure; but
for an analog stack it lands directly on gain, and the servo needs per-layer
checksum rows (paper item iii) to even observe it.

### (d) Does charge-domain vertical accumulation actually work, or only current-domain?
**Only current-domain is demonstrated for vertical/layer-summed CIM.** Charge-
domain summation on a shared column is demonstrated in 2D only. The paper's
Q_col integral over L layers is the un-built step. Feasibility hinges on (i)
per-layer partial-select on a shared via without sneak/IR corrupting the
charge, and (ii) L layers' leakage integrating onto one node within the
converter's window — neither measured.

Verdict (d): **aspirational.** The mechanism is physically plausible (it is just
KCL→charge integration extended vertically) but has no silicon precedent in the
charge domain.

---

## TASK 2 — Projection (compiler math, specs.py read-only)

`l_stack(L)` in `scripts/compiler/metrics/pdk_projections.py`. K=1 (cascade off, to
isolate the L lever), passes/token 10,944 (A5). B_y baseline 8 b, V_swing 0.25 V,
N(2D)=512 sitting on the law:ir N_crit ceiling. Tile 0.1 mm² (paper conservative
converter-limited), reticle 500 mm². All PROJECTION-grade.

| L | conv/token | B_y ideal | B_y built | past 8-b? | E_conv/conv | conv-energy/MAC | C_int(kT/C) | eff LN | LN/N_crit | IR ok? | 7B dies | dies vs L=1 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 21,888 | 8.00 | 8 | no  | 1×  | 1.00× | 52 fF  | 512   | 1.0× | yes | 11 | 1.0× |
| 2 | 10,944 | 8.50 | 9 | yes | 4×  | 2.00× | 209 fF | 1,024 | 2.0× | **NO** | 6 | 1.8× |
| 4 |  5,472 | 9.00 | 9 | yes | 4×  | 1.00× | 209 fF | 2,048 | 4.0× | **NO** | 3 | 3.7× |
| 8 |  2,736 | 9.50 | 10| yes | 16× | 2.00× | 834 fF | 4,096 | 8.0× | **NO** | 2 | 5.5× |

Reproduces the paper's own die counts (11 → 2 at L=8).

**What binds, per L:**
- **conversions/token** falls cleanly `/L` (21,888 → 2,736) — the throughput/
  amortization lever works as advertised. This survives.
- **die count** falls `/L` (11 → 6 → 3 → 2) — the capacity lever works. This
  survives. (The headline "11 → 1–2 dies" needs L=8 *and* the conservative
  0.1 mm² tile; at the converged cell-limited tile the paper itself only needs
  **L=2–4** for a single die — see bottom line.)
- **+½·log2(L) output bits (law:bout):** at **any L≥2** the ideal fractional
  bit rounds UP to a whole converter bit, so B_y ≥ 9 — **past the buildable 8-b
  statistical ceiling** the whole architecture is designed around. This forces a
  4^ΔB per-conversion energy penalty (4× at L=2/4, 16× at L=8) and a matching
  kT/C cap growth (52 → 834 fF at L=8, i.e. bigger, slower integrator).
- **effective LN into IR (law:ir):** the 2D point was placed *on* N_crit=512, so
  the stack re-multiplies it — LN reaches 2×–8× N_crit. IR/sneak is violated at
  **every L≥2** unless per-layer **partial-select** is used, which the paper
  mandates. That means the layers are read select-gated on the shared via — they
  are **not** one free shared integral; selection is an extra per-layer cost the
  clean Q_col equation hides.

**Falsifier at L=2 (checked before endorsing L=8, via `_l_stack_selfcheck`):**
The +½log2(2)=+0.5 bit rounds to a **full** extra converter bit → B_y=9, ADC
energy 4×. The `/L=2` conversion win only halves the count, so
**conversion-energy/MAC = 2.0× WORSE than L=1, not better.** The energy lever the
note implies does not appear at L=2, and it is **non-monotone**: L=4 breaks even
(1.00×), L=2 and L=8 are 2× worse. Vertical accumulation is a **capacity +
throughput** lever, **not** an energy lever — the bit-cost eats the energy win.

---

## BOTTOM LINE (honest)

**How much of "11 dies → 1–2 dies" survives scrutiny:**
- The **capacity/area** arithmetic survives: dies scale `/L`, so L=8 does reach
  1–2 dies for the 7B weight budget (this is just `A = P/(ρ_W·L)`, and the /L is
  unavoidable geometry).
- The **throughput-restored** claim (the thing that distinguishes lever #16 from
  plain front-end-shared stacking) survives **on paper only**: conversions/token
  fall `/L`, but the mechanism that delivers it — charge-domain summation of L
  layers on one column integral — **has no silicon**. Current-domain layer-sum
  and L=8 stacking each have silicon *separately*; the charge-domain vertical
  integral is the un-demonstrated bridge.
- The **energy** improvement does **not** survive: the +½log2(L) bit pushes B_y
  past 8 at every L≥2, and conversion-energy/MAC is flat-to-2×-worse across the
  sweep. Do not sell L as an energy win.
- **IR/sneak** forces mandatory per-layer partial-select (LN = 2–8× N_crit), so
  the "one free shared integral" picture is optimistic; selection is a real
  per-layer cost.

**Realistic near-term L:** **L=2–4, monolithic.** This is what silicon supports
(L=8 stacking exists for separate crossbars; L=2–4 is comfortable for BEOL
monolithic integration) AND it is all the paper actually needs at the converged
cell-limited tile, where the converter fix alone already gets 7B to ~3–4 dies and
**L=2–4 reaches a single die** (paper sec_eval: "vertical accumulation relaxes
from load-bearing to accelerant"). L=4 is also the one point where the
converter-bit cost breaks even on energy.

**L=8 is aspirational** — projection-only for the charge-domain mechanism, needs
per-layer partial-select against 8× N_crit, pays a 16× per-conversion energy
penalty, and its layer-to-layer thermal gradient across an *analog* stack is
unmeasured anywhere in the literature.

---

### Sources
- Monolithic 3D MoS₂+VRRAM, <300 °C, non-disturbing top-plane fab — https://www.nature.com/articles/s41467-023-41736-2
- 3D-RRAM CIM macro (current-domain layer-summed MAC) — https://www.nature.com/articles/s41928-022-00795-x
- Lin et al. 2020, eight-layer 3D memristor circuits as neural networks — https://www.nature.com/articles/s41928-020-0397-9
- BEOL FeFET CIM Ising machine, <400 °C back-end budget (qian2025beol) — https://arxiv.org/pdf/2512.17165
- BEOL IGZO/ZnO TFT CIM, <400 °C thermal ceiling — https://pmc.ncbi.nlm.nih.gov/articles/PMC10539278/ ; https://advanced.onlinelibrary.wiley.com/doi/10.1002/aelm.202500521
- 2D charge-domain multi-bit CIM (not vertical) — https://www.sciengine.com/SCIS/doi/10.1007/s11432-025-4615-6 ; https://arxiv.org/pdf/2107.02388
- 3D-stack thermal / retention-loss binding failure — https://eps.ieee.org/images/files/HIR_2023/ch20_thermalfinal.pdf
