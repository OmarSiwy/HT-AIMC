# ASAP7 characterisation for analog IMC

What the AnalogIOC architecture scoring (`docs/src/content/Project/ARCH_METRIC.md`) needs to
know about ASAP7 (7 nm FinFET, predictive, r1p7). Every number carries a label:

- **measured**: simulated here, ESPice + the PDK's BSIM-CMG cards (VerA-compiled), TT 27 C unless stated.
- **derived**: a law applied to measured numbers or to PDK data files (liberty, MEJ geometry).
- **projected**: literature or law only. Use these with care.

The machine-readable output is `scripts/compiler/metrics/arch_eval/asap7_constants.json` (77 keys,
`{value, unit, label, source}`). The raw per-stage numbers are in `results.json` next to this file.

## How to reproduce

```sh
LOCK=<scratchpad>/spice.lock     # machine-wide SPICE lock, one espice at a time
nix-shell .flows/env/shell.nix --argstr type mixed --extra-experimental-features flakes --run \
  "PDK=asap7 flock -w 900 $LOCK timeout 1200 python3 analog/docs/asap7/char.py gmid inv leak sw cmp"
nix-shell ... --run "PDK=asap7 python3 analog/docs/asap7/char.py lib const"   # no SPICE
```

Run it from the repo root. The shell hook creates a `.venv/` in the current directory, and a venv
created inside `analog/docs/asap7/` breaks numpy. `char.py` builds every deck in Python and runs
it through `analog/docs/gmid._espice`, using model lines from `pdk_specs.Asap7.model_lines(corner)`,
i.e. `.lib $ASAP7_ROOT/models/espice/asap7.lib tt|ff|ss`. Each stage prints PASS/FAIL self-checks
and exits non-zero on a failure. All stages pass. Total SPICE time is about 3 min (gm/ID about
1 min, comparator about 1.2 min, the rest a few seconds each).

Limits that apply to everything below: ASAP7 has **one gate length** (21 nm drawn), **no
statistical models**, **no passives** (no MIM, no poly-R) and **no open PEX**. All device numbers
are therefore intrinsic, with no layout parasitics. The liberty cross-check below shows how much
that matters.

## (2) gm/ID tables: measured

`gmid/{nmos,pmos}_{rvt,lvt,slvt}_nfin{1..4}.csv`: VGS 0 to 0.7 V in 10 mV steps at |VDS| = 0.35 V,
TT 27 C. Columns: VGS, gm/ID, ID/fin, gm/gds, Cgg/fin, fT, ID, gm, gds. ID comes from DC. gm,
gds and Cgg come from a 1 MHz AC deck with one device copy per bias point. Per-fin quantities do
not depend on the fin count (checked to within 2 %).

| device | gm/ID max (1/V) | ID/fin @VGS=0.7 (µA) | Cgg/fin @0.7 (aF) | fT peak (GHz) | gm/gds @gm/ID=10 | fT @gm/ID=10 (GHz) | Vt lin-extrap (V) | Vt const-I (V) |
|---|---|---|---|---|---|---|---|---|
| nmos_rvt | 37.6 | 31.4 | 59.8 | 307 | 28.8 | 298 | 0.372 | 0.288 |
| nmos_lvt | 37.6 | 37.2 | 61.8 | 310 | 28.8 | 303 | 0.302 | 0.220 |
| nmos_slvt | 37.6 | 41.5 | 62.9 | 309 | 29.0 | 303 | 0.239 | 0.158 |
| pmos_rvt | 38.2 | 24.6 | 59.1 | 234 | 17.1 | 205 | 0.378 | |
| pmos_lvt | 38.1 | 29.5 | 61.2 | 243 | 17.0 | 215 | 0.318 | |
| pmos_slvt | 37.7 | 33.6 | 63.0 | 247 | 16.9 | 219 | 0.256 | |

The constant-current Vt uses 100 nA·Weff/L per fin. MEJ Tables 3/4 give Vtsat 0.17/0.10/0.04 V
(RVT/LVT/SLVT) with a different criterion, so the absolute values differ. The spacing between
flavors is about 70 mV in both. Intrinsic gain is low: about 29 for NMOS and about 17 for PMOS
at gm/ID = 10, and L cannot be raised in this PDK. Any OTA at ASAP7 needs cascoding, gain
boosting or a ring-amp/comparator-based topology (`pdk_specs` topology flag
`two_stage_or_ringamp_0V7`).

## (3) FO4 inverter, leakage, DFF

**FO4 (measured).** The test chain is pulse → shaper → shaper → DUT → stage → stage. Every
internal node drives 4 identical 1n+1p-fin RVT inverters. The DUT has its own supply.
Energy per output transition = VDD·Q(one period)/2. It includes the 4 gate loads, the DUT's
own drain and short-circuit current.

| corner @VDD | FO4 (ps) | E/transition (fJ) |
|---|---|---|
| tt @0.45 | 25.9 | 0.041 |
| tt @0.50 | 18.8 | 0.053 |
| tt @0.60 | 12.5 | 0.083 |
| tt @0.70 | **9.88** | **0.121** |
| ff @0.70 / @0.50 | 8.76 / 16.1 | 0.139 / 0.059 |
| ss @0.70 / @0.50 | 11.35 / 22.5 | 0.108 / 0.048 |
| tt @0.70, SLVT | 7.15 | |

**These intrinsic numbers are optimistic (correction).** The ASAP7 INVx1 cell
(`asap7sc7p5t_INVBUF_RVT_TT`, 0.7 V, 25 C) has Cin = 0.62 fF, against about 0.12 fF of gate cap
on our 1+1-fin inverter. Driving 4·Cin at 20 ps slew, the NLDM tables give **FO4 = 18.3 ps and
0.66 fJ per transition**, which is 1.85× the delay and 5.4× the energy. That gap is the cell's
own parasitics (local interconnect, gate contacts, 3 fins per device) plus a larger device. Use
`fo4_delay_ps_lib` and `inv_switch_energy_fJ_lib` for any digital-logic estimate. The bare-device
values are a floor.

**Leakage and Ion per fin (measured)**, VGS = 0 or VDD, |VDS| = 0.7 V:

| device | Ion TT (µA) | Ioff TT 27C (nA) | Ioff FF | Ioff SS | Ioff TT 85C | MEJ Ioff |
|---|---|---|---|---|---|---|
| nmos_sram | 26.1 | 0.0049 | 0.0070 | 0.0037 | 0.014 | 0.001 |
| nmos_rvt | 35.3 | 0.0164 | 0.0247 | 0.0105 | 0.132 | 0.019 |
| nmos_lvt | 42.8 | 0.134 | 0.209 | 0.078 | 1.09 | 0.242 |
| nmos_slvt | 48.5 | 1.32 | 2.06 | 0.77 | 7.67 | 2.444 |
| pmos_rvt | 31.0 | 0.0180 | 0.0239 | 0.0132 | 0.307 | 0.023 |
| pmos_slvt | 43.7 | 1.87 | 2.47 | 1.38 | 14.7 | 2.410 |

NMOS RVT Ion is 35.3 µA/fin TT (FF 45.5, SS 27.6). MEJ Table 3 gives an Idsat of 37.85, which is
close; the shipped 160803 cards postdate the paper. The PDK's FF/SS spread is narrow, about ±25 %
on Ion and +50 %/−35 % on Ioff. Temperature matters more than the process corner here: RVT
leakage rises 8× from 27 C to 85 C.

**DFF (derived from the liberty).** The test set has SEQ libraries only at FF (0.77 V, 0 C) and
SS (0.63 V, 100 C). There is **no TT**, so this number is interpolated. DFFHQNx1_ASAP7_75t_R has
area 0.2916 µm² and CLK pin cap 0.52 fF. Clock internal energy per cycle (D static) is
0.679 fJ (FF) and 0.424 fJ (SS). A Q toggle costs 0.701 / 0.439 fJ. TT 0.7 V is estimated as the
mean of E/V² over the two corners times 0.49, which gives **0.82 fJ/cycle at data activity 0.5**,
excluding the clock-net load (0.52 fF·V² ≈ 0.25 fJ more). NAND2xp33 is 0.0583 µm², NAND2x1
0.0875 µm² and INVx1 0.0437 µm².

## (4) Switches: measured

NMOS, 1 fin, 10 mV across the switch, TT. Ron is in Ω per fin.

| VG (V) | 0.45 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 |
|---|---|---|---|---|---|---|
| RVT, VS=0 | 11 569 | 9 133 | 6 917 | **5 950** | 5 437 | 5 129 |
| LVT, VS=0 | 8 152 | 7 079 | 5 928 | 5 349 | 5 014 | 4 801 |
| SLVT, VS=0 | 6 710 | 6 112 | 5 404 | 5 012 | 4 771 | 4 611 |

At mid-rail (VS = 0.35 V, VG = 0.7 V) the RVT switch is 31 kΩ, LVT 13.6 kΩ and SLVT 9.2 kΩ. A
1n+1p RVT transmission gate is 5.9 to 18.4 kΩ across 0 to VDD, with the worst case at mid-rail.
Ron saturates near 5 kΩ/fin even with boosted gates, because the series S/D resistance in the
cards dominates. Boosting is therefore weak at 7 nm: going from 0.7 V to 0.9 V buys only 14 %.
**Coff = 11.3 aF/fin** (off device, drain to AC ground, equal for all flavors).
Drain-source feedthrough reads about 0 because the BSIM-CMG cards carry no direct Cds; real
layout adds M0/M1 coupling. Ron·Coff ≈ 67 fs (RVT).

## (5) StrongARM comparator

Topology after Razavi (SSC-M 2015, notes 19j…19p): clocked tail, NMOS input pair, cross-coupled
NMOS+PMOS latch, 4 reset PMOS on P, Q, X and Y. X and Y each drive an inverter. Clock 1 GHz,
2 ps edges, VCM 0.55 V, input sign alternating every cycle. Every decision is correct at 1 mV
in tt, ff and ss.

| variant | E/decision (fJ) | t_dec @1 mV (ps) | C on P/Q (fF) | noise (mV rms) | offset σ (mV) |
|---|---|---|---|---|---|
| min (in 4, tail 4, latch 2/2, reset 1 fin), TT | **0.44** (measured) | 26.8 | 0.081 | **7.5** (γ=1) / 9.0 (γ=1.5), derived | **16.9** (projected) |
| min, FF / SS | 0.50 / 0.39 | 23.3 / 31.5 | | | |
| min, TT, 50 mV input | 0.38 | 11.1 | | | |
| IMC-grade (in 16, tail 8, latch 4/4, reset 2, +2 fF MOM on P/Q) | **2.94** (measured) | 32.6 | 2.25 | **1.24** / 1.50, derived | **8.4** (projected) |

- **Noise (derived).** Note 19p gives vn² = 4kTγ/((gm/ID)·C1·Vthn). Note 19p1 adds the reset
  kT/C1 term, referred to the input through the phase gain A = (gm/ID)·Vthn. Inputs: the
  measured Iss and dVP/dt during integration give C1. gm/ID comes from the table at the measured
  VGS of the input pair (11 /V min, 14 /V IMC). Vthn = 0.372 V. γ for short-channel FinFETs is
  1 to 1.5, which is not characterised. No transient-noise simulation was run.
- **Offset (projected).** ASAP7 has no mismatch models. The value is Pelgrom σ(ΔVT) = Avt/√(Weff·L)
  for the input pair only (note 19l), with Avt = 1.3 mV·µm (1.0 to 1.5 gives 13.0 to 19.5 mV
  for the min variant). The latch adds more (note 19g). With L fixed at 21 nm, area grows only
  through fins. Halving σ costs 4× the fins.
- **Correction for IMC.** The bare minimum comparator is cheap (0.44 fJ) but noisy (7.5 mV) and
  badly offset (17 mV). For a 6 to 8 b column the LSB is a few mV, so a usable comparator costs
  about 3 fJ and still needs **offset calibration** (8 mV σ). These numbers also exclude layout
  parasitics. By the liberty ratio above, expect 2 to 5× the energy after layout.

## (6) Capacitors

There is no MIM in ASAP7, so caps are MOM (metal fingers). Pitches come from MEJ Table 1:
M1–M3 at 36 nm, M4–M5 at 48 nm, M6–M7 at 64 nm. The metal aspect ratio is 2:1 (MEJ §4.4) and
k = 2.7 is assumed. The lateral finger density per layer is ε·t/(s·p).

- **Derived:** M1–M5 at minimum pitch gives 5.98 fF/µm². This is an upper bound: M1 is taken by
  cells and there is no derating for density rules. M2–M5 with space = 3w gives 0.77 fF/µm².
  **Design value 2.0 fF/µm²** (label derived; the derating is an assumption), the same value
  `pdk_specs.Asap7.mim_ff_um2` already carries. The literature cross-check is 2 to 4 fF/µm² for
  FinFET-node MOM (projected, not re-read here).
- **Minimum practical unit cap: 0.2 fF (projected).** Below this, routing, fringe and line-edge
  parasitics dominate. kT/C at 0.2 fF is 4.55 mV (√(kT/C)).
- **Matching: σ(ΔC/C) ≈ 0.5 % at 1 fF (projected).** The 32/40 nm sub-fF MOM measurements in
  Tripathi & Murmann (TCAS-I 2014) and Omran et al. (TCAS-I 2016) put it at 0.3 to 1 %, scaling
  as A_C/√area (note 27i1). This is not checked for ASAP7.
- **Area consequence for charge-domain IMC.** A 1 fF unit cap at 2 fF/µm² occupies 0.5 µm²,
  which is **21× a 6T bitcell** (0.0233 µm²). At 65 nm, a 1.5 fF fringe cap fit over a 2.3 µm²
  cell (notes 27i1/27i3, CAP-RAM). At 7 nm the bitcell shrank about 100× and the cap density did
  not. A capacitor per bitcell no longer fits over the cell. Charge-domain columns at ASAP7 must
  share caps (one per row group or per column ADC) or accept the area.

## (7) SRAM bitcells

- **6T: 0.0233 µm² (derived).** MEJ §5.2 and Fig. 7 describe the "111" cell as 8 fins tall
  (8 × 27 nm) and 2 CPP wide (2 × 54 nm). The commercial N7 high-density 6T is about
  0.027 µm² (projected cross-check). The "112" cell (2-fin pull-down) is larger; MEJ does not
  give its height.
- **8T: 0.035 µm² (projected).** This assumes the 111 cell plus a 2-transistor read port as one
  more CPP column, which has not been drawn. The literature 8T/6T ratio is 1.3 to 1.5×
  (note 27i7).
- The OpenROAD set's `fakeram7_*` macros are abstract LEFs, not bitcell layouts. They were not
  used.

## (8) Wires, kT/C, ADC FoM

- **Wire (projected):** 0.173 fF/µm and 32.3 Ω/µm. This is the ORFS `setRC.tcl` signal-wire
  value, a correlation fit and not a PDK extraction. Per layer: M2 46 Ω/µm, 0.18 fF/µm; M4
  20 Ω/µm; M6 12 Ω/µm.
- **kT at 300 K** is 4.14e-21 J. √(kT/C) at 1 fF is 2.04 mV (derived; matches `kTC_noise_uV_rms_at_1fF` in asap7_constants.json).
- **SAR ADC FoM: 3.4 fJ/conv-step (projected).** This is the Gonugondla et al. 2022 column-ADC
  model cited in note 27h1, E = k1(B + log2 r) + k2·r²·4^B with k1 = 100 fJ and k2 = 1 aJ. At
  B = 8 and r = 1 it gives 866 fJ per conversion. The Murmann ADC survey SAR envelope of about
  1 to 5 fJ/step at 10 to 500 MS/s agrees. A bottom-up floor built from the measured parts here
  (8 × IMC comparator + CDAC 0.3·256·0.2 fF·V² + 64 DFF-cycles) gives **84 fJ = 0.33 fJ/step**.
  That floor excludes references, clock tree, wiring and layout parasitics. It is about 10×
  better than the model and is not a design number. The value to carry is 3.4 fJ/step. Note
  27h1 explains why the swing ratio r (V_DD/V_c) of a compute column pushes the noise term up
  between 5 and 7 b.

## Corner deltas (ss / tt / ff, 27 C)

| quantity | ss | tt | ff |
|---|---|---|---|
| FO4 @0.7 V (ps) | 11.35 (+15 %) | 9.88 | 8.76 (−11 %) |
| inverter E/transition (fJ) | 0.108 | 0.121 | 0.139 |
| NMOS RVT Ion (µA/fin) | 27.6 (−22 %) | 35.3 | 45.5 (+29 %) |
| NMOS RVT Ioff (nA/fin) | 0.0105 | 0.0164 | 0.0247 |
| comparator E/decision (fJ) | 0.39 | 0.44 | 0.50 |
| comparator t_dec @1 mV (ps) | 31.5 | 26.8 | 23.3 |

## What is missing

- **Mismatch.** No statistical models exist. Every offset and matching number is projected.
  Wiring DELVTRAND per instance with Avt is possible but would only restate the assumption.
- **Layout parasitics.** No open PEX exists for ASAP7. The liberty comparison (1.85× delay,
  5× energy) is the only calibration point.
- **Transient noise.** The comparator noise is from the analytical formula. A counting
  measurement (note 19q) needs a noise-capable transient run.
- **TT SEQ liberty.** The DFF energy is interpolated from FF and SS.
