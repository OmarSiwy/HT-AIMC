# Architect: physics-robust (panel, round 1)

2026-10-06. The angle: the highest tok/s per 100 mm² die that **still passes N8's gate at the SS and FF corners**,
with the ASAP7 mismatch band, kT/C and supply noise priced, built only from levers whose quality credit was
measured and circuits that ASAP7 SPICE can sign off. Scored against `ARCH_METRIC.md`.

**Files.** Design: `scripts/compiler/metrics/arch_eval/designs/robust.json`. Corner cost model and search:
`designs/robust.py` (`--selfcheck` PASS, `--score d.json`, `--start d.json`). Raw output with every corner,
the reference designs and the baseline at each corner: `designs/robust.result.json`.

**Labels.** Every tok/s, TOPS/W, tok/W and tok/J below is **projected**: the node laws (search.py's joint
frame) applied to measured ASAP7 device tables and literature constants, plus my corner factors. The
corner factors are **measured** (ESPice ASAP7 tables: SS/FF FO4, Id, Ioff, 85 C Ioff) or **derived** from
them; the mismatch band end and the supply ripple are **projected** (literature). The quality anchor is the
**measured** SmolLM2 spot-check (`search/quality_spotcheck.json`). No SPICE was run in this phase.

## Bottom line

| | tok/s/die | TOPS/W | tok/W | tok/J | gate margin |
|---|---|---|---|---|---|
| **robust, TT (the ARCH_METRIC score)** | **47,766** | **9.63** | **512.0** | **549.3** | +2.26 dB |
| robust, SS 0.63 V 100 C + mismatch band end + 2 % ripple | 42,037 | 8.50 | 462.2 | 503.9 | +0.52 dB |
| robust, FF 0.7 V 85 C + mismatch band end + 2 % ripple | 48,204 | 7.68 | 425.0 | 456.4 | +0.86 dB |
| search winner r01, TT | 53,864 | 10.45 | 546.7 | 689.7 | +0.23 dB |
| r01 at SS / FF | **gate fails** (-1.60 dB) / **gate fails** (-1.02 dB, and SLVT leakage puts the FF die over 1 W/mm²) | | | | |
| baseline W8 KV8, ppa.json PE (derived), TT / SS | 41,356 / 35,196 | 7.66 / 7.61 | 423.9 / 421.9 | 839.2 / 832.9 | exact |
| baseline W8 KV8, literature PE (projected), TT / SS | 46,401 / 40,542 | 17.74 / 15.21 | 811.2 / 727.4 | 1,339.2 / 1,173.8 | exact |

| ratio | tok/s | TOPS/W | tok/W | tok/J |
|---|---|---|---|---|
| robust / baseline ppa PE, TT | **1.155x** | 1.26x | 1.21x | 0.65x |
| robust / baseline literature PE, TT | **1.029x** | 0.54x | 0.63x | 0.41x |
| robust / baseline ppa PE, both at SS | 1.19x | 1.12x | 1.10x | 0.61x |
| robust / baseline literature PE, both at SS | 1.04x | 0.56x | 0.64x | 0.43x |
| robust / r01, TT | **0.887x** | 0.92x | 0.94x | 0.80x |
| Sohu conditions, as-is (not re-tuned): 75,081 / 10.28 / 68.5 / 72.2 against FP8 baseline ppa PE 62,571 | 1.20x | 0.95x | 0.95x | 0.58x |
| same against the literature-PE Sohu baseline 86,229 | 0.87x | 0.55x | 0.57x | 0.28x |

**It does not beat the search's winner on tok/s per die, and I do not claim it does.** It is 11 % below r01 at TT.
The reason is that r01 is not a design that survives corners: at the stacked SS corner it misses the gate by
1.6 dB, and at FF it misses it by 1.0 dB, and its SLVT logic is over the power cap. A die that fails the gate
at SS delivers 0 tok/s at the quality bar. What the robust pick buys is a design that passes everywhere,
on a quality credit that was measured, and still beats the systolic baseline on the king metric in both PE
frames, at TT and at SS. Its lead over the literature-PE baseline (1.03x) is inside model resolution,
though. Read it as a tie that holds at SS, not as a win.

## The cost model the nodes lack (in `robust.py`, nothing in the nodes edited)

The core and the joint frame score TT 25 C only. That is the reporting habit 27i5 warns about: a
nominal-corner figure "carries no information about whether a macro works". `robust.py` re-runs the joint
frame inside a context that patches the constants every node reads, and adds one error term:

| corner | delay | switch Ron | kT (thermal SNR) | leakage | source |
|---|---|---|---|---|---|
| ss | x1.425 | x1.42 | x1.53 (373 K, and the -10 % rail folded in as signal² 0.81) | x0.64 SS/TT on the 85 C hold tables, x7.7 static | FO4 at the liberty SS point 0.63 V 100 C (measured, n9 `FO4_SIGNOFF`); Id_tt/Id_ss and Ron(V) measured |
| ff | x0.887 | x0.777 | x1.19 (358 K) | x1.51 on the 85 C hold tables, x18 static | fo4_ff, Id_ff, Ioff_ff, Ioff_85C (measured ASAP7) |
| both | mismatch band end: MOM 0.5 → 1.0 % at 1 fF, A_VT 1.3 → 1.5 mV·µm | | | | projected; ASAP7 ships no mismatch models |
| all | supply: SNR = 1/(ripple × rejection)², ripple 1 % rms at TT and 2 % at SS/FF, rejection 0.1 when the row-drive rails and the SAR reference come from one analog rail | | | | projected (15s1, 15s2; ratio rule 27i5, 27d7) |

The DLL-replica clock tracks the corner (N9 lead), so tile and rail times slow at SS. That gives the SS
tok/s row, and the baseline is rescaled the same way through N9's `op`. N8 carries a 1 dB die cushion for
"the p10 die and calibration drift over temperature". At SS and FF the corner models that explicitly, so
the cushion is replaced there instead of being added on top. TT keeps it.

Three robust-only rules, all logged as the `why` field in robust.result.json:

- **Measured levers only.** The n8 lever must be `g43_lossless` or `lv_hadamard`. `lv_protect_tensor`'s 6 dB
  was measured unrotated on one proxy tensor, and the harness could not emulate it (SEARCH.md point 2).
- **Charge arrays only, and SPICE-verifiable circuits only.** A time- or current-domain array's gain is a
  delay or a bias current, so it does not cancel under PVT (27i1 against 27d9). N9's corner-sensitive
  accuracy hooks are also off for those kinds. My first run found a 37k "robust" time-delay design by that
  hole, and the guard closes it. `ref_bandgap_ldo` is excluded because ASAP7 has no BJT or resistor models
  (N9.md).
- The worst stacked corner has to keep at least the margin r01 keeps at TT: `MARGIN_FLOOR_DB = 0.25`.

Search: coordinate descent (3 passes) from 9 seeds (r01, r03, p08, the Hadamard counterfactual, the
gate-tighter design, and Hadamard stacks at 1.5, 2 or 4 fF), about 4,900 designs × 3 corners, then a
polish from the best state. The optimizer's unconstrained pick (`share_fins 16`, `v_exc 0.43`, 48,432)
sat at +0.05 dB at SS, so the floor rejected it for this one. Single process, under a 4 GB cap, no SPICE.

## Block diagram (text)

```
HBM3 stack (819 GB/s, 24 GB: W8 weights 8 GB + KV8 15 GB, B = 368)
   | PHY 13 mm2
   v
TDM NoC (multicast 16) ---- digital INT8 rail (2.8 mm2: attention QK^T / A.V, softmax, FWHT Hadamard on
   |                         down_proj/o_proj inputs, per-token A8 scales, dequant)  [LVT logic, DLL clock]
   v
2,347 tiles x 0.0282 mm2 (66 mm2), each:
   row drivers: 2-b planes switched between 4 rails {0, V/3, 2V/3, V} (V/3, 2V/3 from two trimmed
                tile-shared buffers)  --- the SAME analog rail feeds the SAR CDAC reference (ratiometric)
   8 rows x 256 differential columns (+checksum), 2 slices/weight (INT8 per channel, LSB unit 0.25x)
     cell: 4T gain-cell weight bits (refreshed, t_ret 1.32 us at the 6-sigma 85 C corner) on
           binary-weighted min-pitch MOM units, 2.0 fF unit (14 fF/weight)
     weight MSB bit -> digital AND + adder tree (exact), low bits -> passive charge share (k_wbits 1)
   bootstrapped NMOS share/reset switch (16 fins, flat Ron), column 48 fF
   128 sampled 11-b SARs (own CDAC samples the column; 9.76 effective bits at TT), 4 columns per ADC
   per-column digital gain/offset trim, slice merge, shift-add
```

## Node choices and why

| node | choice | why (robust angle) |
|---|---|---|
| N1 | `stream_single`, KV8 | The ARCH_METRIC rule (weights stream). KV8 is the lossless tier (N8 `lv_kv8`). B = 368 is the KV limit, the same ceiling as r01. |
| N2 | `hybrid_wmsb_digital`, k_dig 0 | Every input plane is passive charge, and the weight MSB goes through an exact digital AND + adder tree. The MSB carries most of the signal energy, so the part that must be exact is exact, and the analog error is referred to the low bits. The charge share itself is a capacitor ratio, which is PVT-immune (27i1). Against `charge_rail` it is +55 % tok/s at equal margin (30,789 → 47,766 in the corner frame). |
| N3 | `gaincell_mom_caps_mom6` (default) | MOM fingers are the lithographic ratio element (27i1). MOS units have a C(V) that moves with the corner. The gain cell meets "no SRAM bitcells". Unit 2.0 fF: kT/C (27g2) and mismatch (σ/√C, 27i1) are what fail at SS. 1.75 fF fails SS (-0.01 dB, at 49,024 TT), and 2.5 fF costs 16 % tok/s (40,175). |
| N4 | `w8a8_lead_tokact` | W8 per channel in 2 slices, **A8 per token**, Hadamard. This is exactly the configuration the quality harness measured: +0.06 ± 0.23 % for the format, and noise at 39.8 dB adds +0.51 %. The block-32 activation variant (`w8a8_lead`) scores the same (47,766) but was never measured on the analog path. |
| N5 | `blk_diff_r8_c256_s4` (default) | Differential: the pair rejects common-mode supply, injection and C(V) to rej_cm (18c1). R8 is hard-bounded (k_hard 9.4σ), so nothing clips at any corner. |
| N6 | `sar_sampled`, 11 b | The plain charge-redistribution SAR: its LSB is a capacitor ratio of the CDAC, and the CDAC reference is the array rail. That is the "ratio of like things" rule of 27i5. It has no residue amp, whose open-loop gain moves with PVT, and no continuous-time VTC, which N6 marks as conditional on an unmeasured κ. The VTC readout (`sar_vtc_fine` at 12 b, 44,350) and the residue amp at 12 b (44,153, SS +0.49 dB) come within 7.5 %, so the simplest circuit is also the best here. At 11 b the ADC's own budget (27h1) is not the binding term (43.1 dB at SS). |
| N7 | `tdm_noc`, mcast 16, 8 MB | Ties the alternatives. Rail headroom left at default: 2.0x adds +0.3 TOPS/W but costs 1 %. |
| N8 | `lv_hadamard` | The only lever with a measured credit (4.5 dB, inside the 3-8.5 dB band measured on the proxy). At the SS corner the design's SNR is 39.3 dB. The measured +0.51 % at 39.8 dB extrapolates to about +0.57 % at 39.3 dB, inside G2's 1 % budget. That is the strongest quality evidence on the board. |
| N9 | `vt_lvt_logic` | **SLVT logic (r01's choice) is not robust.** On this design, FF 85 C puts SLVT over the 1 W/mm² cap: no feasible point (on r01's Hadamard variant the die reaches 256 W). SS loses 53 % tok/s (22,612). LVT keeps the FF die at 95 W. RVT (`lead`) ties on TT tok/s (47,766) at 4.9 % lower TOPS/W (9.16), but at the corners it is better: FF 49,562 tok/s at 86 W, and SS 9.00 TOPS/W. LVT wins only the TT tie-break. If FF power or corner TOPS/W ends up deciding, switch to RVT. The rest stays the N9 lead bundle: buffered class-A reference, bootstrapped column switch (signal-independent Ron, measured flat), 4-rail 2-b driver, DLL-replica clock. |
| N10 | `none` | No wildcard survived the search. |

## Why it cannot reach r01's 53,864 (honest negative)

1. **r01's tok/s is bought with gate margin it does not have at a corner.** Its per-conversion SNR is
   38.5 dB against a 38.28 dB target at TT. The stacked SS corner takes about 2.8 dB off: mismatch 46 → 40 dB
   is the largest piece, then thermal 43.3 → 41.5 and the ADC 39.5 → 38.1. Replacing the 1 dB cushion
   gives back only 1 dB.
2. **The measured lever is 1.5 dB weaker than the unmeasured one.** Hadamard is 4.5 dB, protect-tensor is 6 dB.
3. Those ~3.3 dB are paid in capacitance and converter energy (199 fJ/MAC against r01's 139). The power
   cap then makes prefill compute-bound (1.58 s per wave) instead of rail-attention-bound. Decode stays HBM-bound
   in both designs, and B = 368 is the same KV ceiling. So the 11 % is the price of the corner, not a
   tile defect.
4. **The core frame says it loses to the baseline.** `cli.py`'s core frame scores it at 35,505 (0.86x the
   ppa baseline). r01 is also below the baseline there (39,997). The joint/core disagreement (+35 %)
   is larger than every margin in this file, so the integration of N4/N8/N9's hooks into the core decides
   whether either design beats the systolic die at all.

## Risks

- FF power: 95.4 W on a 100 W cap (4.6 % headroom). RVT logic gives 86 W at no tok/s cost (TT TOPS/W -4.9 %).
- The mismatch band end (1 % at 1 fF) is an assumption: ASAP7 has no mismatch models. It is also the term
  that sizes the pick. At the band middle (0.5 %) the same design keeps +2.20 dB at SS and +2.71 dB at FF,
  instead of +0.52 / +0.86. A smaller unit would then pass: 1.75 fF reaches 49,024 TT. So the assumption is
  worth about 3 % tok/s, and it errs on the safe side.
- The supply term relies on the drive rails and the SAR reference sharing one rail with 20 dB rejection
  (27i5's ratio rule). If the reference buffer decouples them, the term falls from 54 to 34 dB at 2 %
  ripple and the design fails.
- Model sanity flags I could not resolve from the scorer: n2 reports v_exc 0.577 V and N9 a 1.19 V
  excitation, and n6 a 2.2 V converter range (√2 bookkeeping included). The real column and CDAC must stay
  within 0 to 0.7 V.
- The buffered reference is 42 % of tile area (12,000 of 28,214 µm²). A layout-driven change there moves
  the tile count.
- Gain-cell retention is 1.32 µs at the 6σ 85 C corner. Refresh is priced, but its corner behavior is
  N3's TT-plus-6σ model, not a corner run.
- The quality anchor is one proxy run at 39.8 dB, not 39.3 dB, and per-token scales on SmolLM2, not
  Llama-3-8B.

## What Verilog-A, then SPICE, must prove first (in order)

1. **Verilog-A (VerA → ESPice):** an R8 × C256 differential column with 2 fF units, passive share, and the
   sampled 11-b SAR, behavioral, with the corner knobs as parameters (kT at 373 K, signal at 0.63 V,
   1 % unit σ, injected 2 % rail ripple). It must reproduce the class-weighted SNR budget: thermal 43.6,
   mismatch 43.0, ADC 43.1, supply 54 dB at SS, combining to at least 39.3 dB. It must also show that the
   column and CDAC never leave 0 to 0.7 V (the v_exc / range flag above).
2. **Verilog-A:** the ratiometric reference. Ripple on the shared analog rail should cancel to ≤ 0.2 % gain
   error per conversion, the 20 dB rejection the supply term assumes.
3. **ASAP7 SPICE, one column slice (8 rows, 2 columns, one SAR) at tt/ss/ff:** bootstrapped-switch Ron
   flatness and charge injection at SS 0.63 V; the 4-rail driver's V/3 and 2V/3 settling in a 1.05 ns slot
   at SS (Ron x1.42); SAR conversion in 1.34 ns × 1.425 at SS; FF 85 C hold droop on the off share switch
   (N9 predicts 60 dB). Serialized under the flock, one corner per run.
4. **SPICE transient with a supply-noise source** (2 % rms) on the analog rail and an IR-drop step: the measured
   rejection replaces the projected 0.1.
5. **Leakage/power at FF 85 C:** LVT rail and buffer logic plus gain-cell refresh, to confirm the 95 W.
6. **Quality harness (when re-enabled):** the measured Hadamard / per-token / R8 path at 39.3 dB and with
   a static per-cell weight error at σ 1 % (the mismatch class, which N8 brackets at -3.6 to +7 dB and has
   never measured). That decides whether the mismatch term is even the right weight.

## Notes used

27i5 (PVT reaches the output only through C_P/C, the DAC/ADC reference ratio and the comparator offset; make
every ratio a ratio of like things), 27i1 (a capacitor ratio is lithographic and cancels common PVT), 27g2 (kT/C
sets the capacitor; the thermal term I scale with temperature), 27d7 (correct drift with ratios and
recalibration), 27d9 (temperature does not cancel in exponential or current-ratio cells, which is why
current-domain and log arrays are excluded), 27h1 (converter energy law, why 11 b and not 12-13), 15s1 and
15s2 (separate analog supply; decap and package resonance set the ripple), 16v1 (temperature reverses the
corner trend: why both slow-hot and fast-hot corners are run), 24n5 (reference bounce, the existing
`ref_droop` term), and 27h9 (PWM costs 2^b time steps: not used).
