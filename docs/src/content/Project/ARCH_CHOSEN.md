# Chosen architecture (spec for the Verilog-A and ASAP7 SPICE phase)

2026-10-06, round 1. The decision and the scoreboard behind it are in
`ArchResearch/DECISION.md`, and the metric is `ARCH_METRIC.md`.

This page is the spec for the next phase:

1. a Verilog-A behavioural model (VerA, simulated in ESPice);
2. ASAP7 transistor-level SPICE (BSIM-CMG, tt/ss/ff).

Post-layout is out of scope.

Labels: **P** projected, **D** derived, **M** measured. Every target below is P from the
`arch_eval` joint frame (the declared ranking frame) unless it says otherwise. This phase's job is
to replace the targets with M.

## 0. Summary

The design is a streaming charge-domain IMC with a position-tiered digital KV cache:

- **Weights.** It stores W8 weights as two 4-b slices of gain-cell charge on MOM6 capacitors,
  differential.
- **Inputs.** Every pair of input bits is applied as one of four rail levels on the row bottom
  plates (the charge rail).
- **Readout.** The two slices are merged 1:16 in charge, then read by pooled 12-b SAR converters,
  one conversion per weight column.
- **Partial sums.** Each column's partial sum is added digitally into a 24-b accumulator chain
  that runs down the K-adjacent tiles.
- **Data path.** Weights stream from HBM just ahead of the activations. Activations are INT8 per
  token after a Hadamard rotation. Attention runs on the digital rail with a 4-b KV cache, plus a
  4-b residual plane for 8 sink tokens and the 120 most recent tokens.

| condition set | | tok/s/die | TOPS/W | tok/W | tok/J |
|---|---|---|---|---|---|
| ARCH (Llama-3-8B, 512/128, 100 mm²) | as scored (P) | 67,922 | 15.56 | 825 | 834 |
| | **judge-corrected (P)** | **48,700** | **9.3** | **551** | **550** |
| Sohu (Llama-3-70B FP8, 2048/128, B 1000, TP-8, 1,063 mm²) | as scored (P) | 101,125 | 14.94 | 97.2 | 104.1 |
| | **judge-corrected (P)** | **72,500** | **9.0** | **64.8** | **68.7** |

The ARCH operating point:

- B = 587 streams (the KV limit) at 38.2 tok/s per stream;
- a 66.2 W die and 16.1 W of HBM;
- prefill bound by tile compute, decode by HBM.

The design is `scripts/compiler/metrics/arch_eval/designs/notes_native.json` plus three changes:

- `nodes.n9_circuits = "lead"` (the buffered reference);
- `params.buffer_MB = 16`;
- the T2 accumulator chain.

T2 is not an evaluator option yet. It was scored by replacing the tile's `buffer` pass energy with
R·e_buf + C × 90 fJ, in `scratchpad/dec_xf.py` and `dec_x3.py`. The N7 owner should adopt it as a
`n7_dataflow` option. Score the base with `notes_native.score_design(d)`.

```json
{"frame":"joint","name":"chosen",
 "nodes":{"n4_formats":"w8a8_lead_tokact","n6_readout":"sar_direct_pool_k4","n7_dataflow":"tdm_noc",
          "n8_quality":"lv_hadamard","n9_circuits":"lead"},
 "params":{"adc_bits":12,"k_dig":0,"mcast":16,"rail_headroom":2.0,"share_fins":16,"buffer_MB":16,
           "kv_bits":4,"nn_kv":true,"kv_lo_bits":4,"kv_hi_bits":8,"kv_sink":8,"kv_recent":120,
           "kv_scale_group":128}}
```

Nodes not listed take their lead option:

- N1 `stream_single`
- N2 `hybrid_msb_digital` with k_dig 0 (the charge rail)
- N3 `gaincell_mom_caps_mom6`
- N5 `blk_diff_r8_c256_s4`

Under Sohu, the KV format is FP8 (`kv_bits = 8`), as the conditions require.

**The frame credit to verify first.** `w8a8_lead_tokact` has `f_merge = True`, which is one
conversion per weight after a 1:16 charge merge, and `f_cu_lsb = 0.25`. Together with N9's 4-level
row drive, these two joint-frame credits are worth 1.52x tok/s. Without them, the core frame
(`cli.py`) reads 44,806 / 11.03, which is below the lever-matched baseline (`DECISION.md` §0).

## 1. Block diagram

```
          HBM3 stack: 819 GB/s, 24 GB, 4 pJ/bit
          |  W8 weights, 8.0 GB, streamed every weight sweep
          |  KV cache, ~15 GB:
          |    bulk plane: 4 b K,V codes + fp16 scale per (token, KV head)
          |    ring plane: 4 b residual for sink 8 + recent 120 tokens
          v
  +-- HBM PHY, 13.0 mm2 --+----- TDM NoC, mcast 16, 0.29 mm2 ------+
  |                        |                                         |
  |                16 MB activation SRAM, 4.7 mm2                    |
  |   weights: 32,768 b    |  activations: INT8 per token,           |
  |   per tile load        |  Hadamard-rotated, 8 rows per pass      |
  v                        v                                         |
  3,181 IMC tiles, 60.3 mm2, 18,962 um2 each (~138 um pitch)         |
  +------------------------------------------------------------+     |
  | B2 row drive: 4 rails (0, V/3, 2V/3, V), 2 b per slot      |     |
  |    -> 8 rows x 7.47 pF bottom-plate rails                  |     |
  | B1 array: 8 rows x 256 diff cols x 2 slices                |     |
  |    gain cell + MOM6 units, MSB 1 fF / LSB 0.25 fF          |     |
  | B3 column: bootstrapped share/reset switch, C_col 56 fF    |     |
  |    + 1:16 charge merge of the MSB and LSB slice columns    |     |
  | B4 readout: 12 b SAR, direct (column = sampler), pool K=4  |     |
  | B5 reference: class-A buffered, tile-shared                |     |
  | B6 digital: per-column affine cal                          |     |
  | B10 accumulator: 24 b add + register per column            |     |
  +------------------------------------------------------------+     |
       psum_in (24 b x 256) --> tile k --> psum_out --> tile k+1 ... |
                           | completed outputs, once per K           |
                           v                                         |
  B6' requant to INT8 at the chain end (per-token scale)             |
                           v                                         |
  Digital rail, 4.6 mm2: Q.K^T and P.V lanes (q8 x k4 bulk,          |
  q8 x k8 for sink + recent), online softmax (base-2 exp),           |
  RMSNorm / RoPE / SwiGLU, FWHT on q, k, v, o, KV pack/unpack -------+
```

**Die budget (P, ARCH)**

| block | area |
|---|---|
| tiles | 60.3 mm² |
| digital rail | 4.6 mm² |
| buffer | 4.7 mm² |
| NoC | 0.29 mm² |
| PHY | 13.0 mm² |
| unused (margin) | 17.1 mm² |
| **die** | **100 mm²** |

The T2 accumulators are about 256 × (24-b register + adder) per tile, roughly 1,500 µm² (P). They
come out of the unused margin.

**Supplies.** VDD_A = 0.7 V for the analog parts (the array, row drive, reference and converter
analog). VDD_L = 0.5 V for logic, at a 0.524 GHz clock. RVT logic.

## 2. Blocks: function and target specs

One pass is 2,048 MACs: the full 8 × 256 differential tile, both slices.

| pass timing (P) | value |
|---|---|
| t_word | 5.66 ns: 4 drive slots of 1.132 ns, plus 1 slot for the merge share |
| t_conv | 6.30 ns: 4 pooled rounds × 1.576 ns |
| **t_pass** | **6.30 ns** (conversion-bound) |

### B1. Gain-cell weight store (N3)

| spec | target |
|---|---|
| function | holds one W8 weight as two 4-b slices, differential, as charge on MOM6 units |
| units | MSB slice 15 × 1.0 fF; LSB slice 15 × 0.25 fF (`f_cu_lsb`). The n3 price is 14 unit-equivalents, c_weight 7 fF real per side, 2.93 µm² per weight. Reconcile the unit count in V6 |
| write energy | ≤ 0.70 fJ/bit (32,768 bits per tile load) |
| row write | ≤ 31.6 ps per row; t_load = 0.253 ns per tile load |
| retention | ≥ 1.32 µs at 6 σ and 85 °C (nominal 14.3 µs), to ½ LSB droop of a 4-b slice |
| refresh occupancy | ≤ 0.04 % |
| leakage | ≤ 14.2 nW per weight |
| unit mismatch | σ(ΔC/C) ≤ 1 % at 1 fF and ≤ 2 % at 0.25 fF, so that the mismatch term reaches ≥ 46.0 dB (P: ASAP7 has no MOM mismatch data) |
| constraint | no SRAM bitcells in the tile (ARCH_METRIC constraint 2) |

### B2. Row drive (N9 `ml2_rails`)

| spec | target |
|---|---|
| function | puts 2 activation bits per slot on each row's bottom-plate rail by switching between 4 levels |
| levels | V/3 and 2V/3 come from two trimmed, tile-shared class-AB buffers |
| slot | 1.132 ns; 4 slots per 8-b word |
| load | 8 rows × 7.47 pF, which is 10 to 14 pC of data-dependent charge per slot |
| level accuracy | code-dependent droop and INL ≤ 0.1 % of V (drive-INL term ≥ 54.8 dB) |
| energy | ≤ 4.8 pJ per pass |
| excitation | v_exc = 0.35 V per side. The reported `n9_exc_V` of 1.19 V is a reporting artefact (§9) |
| fallback | `drv_inv_bitserial`: rail-only drive, 8 slots, 61,740 / 14.04 (P), +0.15 dB of margin |

### B3. Column, share switch and slice merge (N2 charge rail, N4 merge, N5, N9 `bootstrap`)

| spec | target |
|---|---|
| function | the passive charge share sums weight × input-plane products on each slice column. Then a 1:16 charge share merges the MSB and LSB slice columns into one sample |
| C_col | 56 fF, so kT/C gives a thermal term ≥ 43.3 dB |
| merge | 1:16 ratio error ≤ 0.1 % (P: about 10-b ratio accuracy, so the merge stays below the ADC term). Occupies 1 slot (1.132 ns) |
| array energy | 3.66 fJ per MAC (15.4 pJ per pass) |
| switch | bootstrapped NMOS, constant V_GS. τ_sw ≤ 64.5 ps (N9 model: 20.8 ps); colsw ≤ 17.3 pJ per pass |
| error terms (dB) | injection ≥ 73.9; coupling ≥ 63.0; row coupling ≥ 74.8; column hold droop ≥ 60.7; row gain after calibration ≥ 76.9 |
| reliability | the bootstrapped gate (about 1.3 V) must stay inside the ASAP7 V_GS limit |

### B4. Column ADC (N6 `sar_direct_pool_k4`)

| spec | target |
|---|---|
| function | converts the merged differential column charge directly, with the column as the sampler (no driver) |
| sharing | 128 converters per tile, with charge pooling K = 4 (4 rounds per pass) |
| resolution | 12 b nominal, 13 decisions (5 of them quiet); **≥ 9.63 ENOB** |
| speed | **t_conv ≤ 1.576 ns** (≥ 635 MS/s) |
| energy | **≤ 253.5 fJ per conversion** in total; ≤ 129.8 pJ per pass for the converters |
| full scale | v_eff 0.705 V differential; LSB 172 µV |
| noise budget | comparator ≤ 86 µV rms; C-DAC ≤ 193 µV; reference ≤ 137 µV |
| ADC term | ≥ 43.3 dB (class weight +3 dB, N8) |
| area | 43.45 µm² each (2,781 µm² per tile) |
| range | clip-free to ±32 σ of the column partial sum (G2 range rule) |
| FoM | Schreier 182.7 dB, 5 to 8 dB past the published envelope above 500 MS/s (P). **The top risk** |

### B5. Reference (N9 `lead`, class-A buffered)

| spec | target |
|---|---|
| function | the C-DAC reference for the tile's converters |
| droop | ≤ 3.7 µV per conversion while 128 conversions run at once (ref-droop term ≥ 54.0 dB) |
| energy | ≤ 46.0 pJ per pass (η = 0.3) |
| area | 5,798 µm² per tile |
| constraint | no bandgap: ASAP7 has no BJT or resistor models. The absolute level is trimmed per die, and the slow level is set from the rail |

### B6. Digital calibration (tile edge) and requant (chain end)

| spec | target |
|---|---|
| function | applies the per-column affine calibration (gain, offset) to each code before it enters the accumulator. Requant to INT8 with the per-token scale happens once per output at the chain end |
| slice recombination | none in digital: B3's charge merge does it |
| energy | ≤ 18.7 pJ per pass |
| check | bit-exact against `scripts/golden/` |

### B7. Activation buffer and NoC (N7 `tdm_noc`)

| spec | target |
|---|---|
| buffer | 16 MB SRAM (4.7 mm²). With T2 it carries activations only (8 B per pass in); psums no longer go through it |
| why 16 MB | it hides the prefill activation spill (about 4.9 MB per token) under compute and removes the decode spill (system judge, D) |
| NoC | TDM circuit-switched, multicast 16, rail headroom 2.0 |

### B8. Digital rail and KV format (N1, N7, notes_native)

| spec | target |
|---|---|
| attention throughput | 14.7 TMAC/s at 45.6 fJ per attention MAC |
| lanes | q8 × k4 for the bulk; q8 × k8 for the protected sink 8 + recent 120 |
| softmax | online, base-2 exp from a ROM |
| rotation | FWHT on q, k, v and o |
| KV format | effective 5.01 b. Bulk: 4-b codes + fp16 scale per (token, KV head). Ring plane: a 4-b residual, dropped without requantization when a token leaves the window |
| quality | +0.21 ± 0.18 % PPL (M, proxy, 1 seed) |

### B9. HBM interface

| spec | target |
|---|---|
| PHY | 13 mm², 819 GB/s, 0.50 pJ/bit on the die side |
| KV capacity | 15 GB after the weights; B = 587 × 640 tokens |
| decode step | 26.2 ms; 38.2 tok/s per stream (floor 20) |

### B10. Accumulator chain (T2, adopted)

| spec | target |
|---|---|
| function | an output-stationary partial-sum chain. Each tile adds its 256 calibrated column codes to the incoming 24-b partial sums and passes them to the K-adjacent tile. Only completed outputs leave the chain |
| width | 24 b per column: 12-b codes accumulated over K/8 ≤ 1,792 tiles needs ≤ 23 b |
| energy | ≤ 90 fJ per column-pass: 7 fJ add + 83 fJ hop over a 138 µm tile pitch at 0.7 V (D estimate, not synthesized) |
| timing | one hop per t_pass (6.3 ns). The chain is pipelined, so it adds latency of K/8 × t_pass (≤ 11.3 µs per layer for FFN-down, D) but no throughput loss |
| placement | the K-chunks of one output column must sit on physically adjacent tiles |
| exactness | bit-exact. It changes neither the model nor the SNR |
| gain (P) | ARCH TOPS/W 14.84 → 15.56 (+4.9 %; +10.5 % at the study's 50 µm hop). Sohu tok/s 97,064 → 101,125 (+4.2 %): the die is power-capped, so lower energy buys VDD |

### Per-pass energy budget (P, with T2: 256 pJ per 2,048 MACs = 125 fJ/MAC)

| part | pJ per pass |
|---|---|
| converters | 129.8 |
| reference | 46.0 |
| recombination / calibration | 18.7 |
| column switch | 17.3 |
| array | 15.4 |
| accumulator chain (T2) | 23.6 |
| drivers | 4.8 |
| format side | 0.4 |

Without T2 the buffer line would be 36.5 pJ and the total 269 pJ.

### SNR budget (P, dB)

| term | dB |
|---|---|
| thermal | 43.31 |
| mismatch | 46.02 |
| ADC | 43.30 (class-weighted +3) |
| ref droop | 53.98 |
| drive INL | 54.81 |
| hold droop | 60.7 |
| coupling | 63.0 |
| injection | 73.9 |
| row coupling | 74.8 |
| row gain | 76.9 |
| **unweighted total** | **38.96** |
| **class-weighted SNR_eff** | **39.84**, against a G2 target of **39.78**: margin **+0.05 dB** |

## 3. Interfaces (tile boundary)

| port | direction | width / level | timing |
|---|---|---|---|
| `w_data` | in | 32,768 b per load (8 rows × 256 cols × 2 slices × 8 b, differential pairs), from the NoC | one load per t_load (0.253 ns of array occupancy, rewritten just in time) |
| `x_in` | in | 8 rows × INT8, Hadamard-rotated; the per-token scale is held at the rail | one word per t_pass |
| `psum_in` | in | 256 × 24 b, from the K-previous tile (zero at the chain head) | one per t_pass |
| `psum_out` | out | 256 × 24 b, to the K-next tile; at the chain end, to requant | one per t_pass (≤ 6.3 ns) |
| `phi_drv[4]`, `phi_merge`, `phi_share`, `phi_reset`, `phi_samp`, `sar_clk` | in | 0.5 V logic | from the DLL replica timebase: 1.132 ns slots, a 1.576 ns conversion window |
| `refresh` | in | per row | ≤ 0.04 % occupancy |
| `cal` | in | per column: gain and offset words | written once per die |
| VDD_A, VDD_L | supply | 0.7 V / 0.5 V | |
| V_1/3, V_2/3 | analog | from the tile-shared class-AB buffers | settle inside one 1.132 ns slot |
| VREF | analog | buffered, 0.705 V full scale | |

## 4. Quality gate (settled; `DECISION.md` §1)

- **G1.** The whole format stack may cost at most ΔPPL +3.0 % on the SmolLM2-135M proxy. Measured
  so far: +0.06 % for W/A and +0.21 % for KV 4/8 (M).
- **G2.** The analog increment may be at most +1.0 % PPL (KL ≤ 0.01 nats).
  - Class-weighted SNR_eff ≥ 39.78 dB, using the 4.5 dB Hadamard credit.
  - The range is clip-free to ±32 σ.
  - `lv_protect_tensor` earns 0 dB until it is measured on the analog path.
- **Corners (gate for this phase).** G2 margin ≥ 0 dB at SS (0.63 V, 100 °C) and at FF (85 °C),
  for ≤ 3 % tok/s.
- **Transforms that change the model** (2:4, codebook weights, KV formats) stay conditional until
  the cumulative G1 total on SmolLM2 is measured at ≤ +3.0 %. Any retraining they need is counted.

## 5. Transforms: adopted, conditional, rejected

All scores are P, from the joint frame on the pick (`DECISION.md` §5). The base point is ARCH
67,922 / 14.84 and Sohu 97,064 / 13.36.

| transform | status | reason | projected gain on the pick, ARCH / Sohu | same transform on the baseline |
|---|---|---|---|---|
| **T2** accumulator chain between K-adjacent tiles (output-stationary) | **adopted** | exact, no model change, cheap logic | tok/s +0 % / **+4.2 %**; TOPS/W +4.9 % / +11.8 % (138 µm hop) | n/a: the systolic array already accumulates in place |
| **KV 4/8** (4-b codes, 8-b sink 8 + recent 120, Hadamard) | **adopted** under ARCH; not applicable under Sohu (FP8 KV is fixed) | measured +0.21 ± 0.18 % (M, 1 seed); 5 seeds in V9 | it is already in the base: +36 % against the tile at KV8 (50,086 → 67,922) | the same lever on the baseline: 41.4k → 46.4k (ppa), 46.4k → 61.0k (lit). Ratio-neutral |
| **T1** 2:4 structured sparsity along K (2-b index per cell, 4:1 activation mux) | **conditional** (quality) | it changes the model. One-shot 2:4 is expected to fail G1 on 135M (P), so it needs counted retraining | **+35 % / +34 %** (91,945 / 130,362); TOPS/W −14 % / −10 % | **+65 % / +66 %** on the ppa PE: it helps the baseline more, which lowers the analog ratio |
| **T4** 4-b lattice-codebook weights (QuIP#-class), decoded on the write path | **conditional** (quality) | it changes the weight format; unmeasured on our gate | +14.5 % / **−1.8 %** (the FWHTs load an attention-bound rail under Sohu). In the full stack: +9 % / +3.6 % | +9.5 % / +2.7 % (ppa) |
| **T5** analog partial sums shared across 2 tiles (`analog_psum`, K = 2) | **rejected for round 1** | −0.59 dB SNR against a +0.05 dB margin: infeasible under both sets. Revisit if V3 leaves ≥ 0.65 dB, or if the decision moves to robust (feasible there, margin 1.22 dB) | infeasible (it was +11 % / +18 % on a design with margin) | n/a (analog-only) |
| **T3** DPS-48 rank-48 bilinear with a per-column adder | **rejected** | −0.13 dB makes it infeasible. Bought back with the bit-serial drive, it scores 60,098: below the bit-serial pick without it (61,740). Needs an exact widened cell and the 2026 low-growth scheme | infeasible, or −3 % when made feasible | the digital baseline does not gain (N10) |
| Strassen, Winograd FIP/FFIP, Karatsuba/Toom-Cook, AlphaTensor ⟨4,5,5⟩, MADDNESS/LUT | **rejected** | they cut multiplies, which cost nothing here; they add conversions, dynamic range or bytes (`LIT_SYSTOLIC_ALGOS.md` §2) | ≤ 0 or infeasible | FIP and Karatsuba help the digital PE |
| low-rank, Monarch, unstructured sparsity | **rejected** | low-rank and Monarch change the model far outside G1; unstructured sparsity saves bytes only (+9 %, TOPS/W −48 %) | — | — |
| **full feasible stack, T1 + T2 + T4** | conditional (T1, T4) | — | **100,432 / 135,048 as scored; 72,000 / 96,800 corrected** | ppa 82,124 / 103,656 |

## 6. Comparison against the systolic baseline and the Sohu-equivalent

The baseline is `baseline_systolic.py`:

- ppa.json PE: **D-PE**, from ASAP7 open-source synthesis;
- literature PE: **P**.

The Sohu-equivalent is the ppa-PE baseline on the Sohu-iso-area die (1,063.4 mm²,
`cli.py --sohu-target`). ARCH_METRIC's 666 mm² row is stale.

| | ARCH tok/s | ARCH TOPS/W | ARCH tok/W | ARCH tok/J | Sohu tok/s | Sohu TOPS/W | Sohu tok/W | Sohu tok/J |
|---|---|---|---|---|---|---|---|---|
| **pick, corrected** | **48,700** | 9.3 | 551 | 550 | **72,500** | 9.0 | 64.8 | 68.7 |
| pick, as scored | 67,922 | 15.56 | 825 | 834 | 101,125 | 14.94 | 97.2 | 104.1 |
| baseline, ppa PE (ARCH KV 4/8; Sohu FP8 = **Sohu-equivalent**) | 46,398 | 10.61 | 600 | 968 | **62,571** | 10.81 | 71.9 | 124.3 |
| baseline, lit PE | 61,005 | 18.30 | 939 | 1,705 | 86,229 | 18.77 | 119.8 | 255.6 |
| **pick corrected / ppa** | **1.05x** | 0.88x | 0.92x | 0.57x | **1.16x** | 0.83x | 0.90x | 0.55x |
| pick corrected / lit | 0.80x | 0.51x | 0.59x | 0.32x | 0.84x | 0.48x | 0.54x | 0.27x |
| stacked (T1 + T4 on both, T2 on the pick), corrected / ppa | **0.88x** | | | | **0.93x** | | | |
| stacked, corrected / lit | 0.77x | | | | 0.80x | | | |

**Unranked metrics**

| | tok/s/mm² | tok/s/mm²/W |
|---|---|---|
| ARCH: pick, as scored | 679 | 10.3 |
| ARCH: pick, corrected | 487 | — |
| ARCH: ppa baseline | 464 | 7.0 |
| Sohu: pick, as scored | 95.1 | 0.099 |
| Sohu: pick, corrected | 68.2 | — |
| Sohu: Sohu-equivalent | 58.8 | 0.072 |

## 7. Verification plan, ordered by risk

Use the `analog-design-flow` skill. Each block lives in `analog/<block>/`:

- the Verilog-A model goes in `va/` (`vera` lint and unit tests);
- the self-checking testbench goes in `test/` (SpiceRack, ESPice backend) and prints PASS or FAIL
  with numeric asserts.

Every ESPice run is serialized under the machine-wide flock with a 4 GB cap.

| # | step | what it settles | pass | fail action |
|---|---|---|---|---|
| **V1** | Verilog-A, then ASAP7 SPICE (tt/ss/ff), of the 12-b direct SAR with K = 4 pooling, the quiet comparator and the C-DAC | the converter FoM, the top risk | ENOB ≥ 9.63 at ≥ 635 MS/s; E ≤ 253.5 fJ per conversion (comparator, DAC and logic); comparator noise ≤ 86 µV rms; metastability ≤ 1e-9 per conversion within 1.576 ns | re-score with the measured E and t. If E > 380 fJ or t_conv > 1.97 ns, apply §8 |
| **V2** | Verilog-A column slice: R8 × C256 differential, 2 slices, charge rail, **1:16 charge merge**, ideal 12-b quantizer, then the V1 model | the joint-frame merge credit and the column SNR, against the bit-exact golden dot product | class-weighted SNR_eff ≥ 39.78 dB (goal ≥ 40.3 dB); every term within 0.5 dB of the §2 budget; merge ratio error ≤ 0.1 %; merge share settles inside 1.132 ns | without the merge (one conversion per slice), re-score: about 0.66x (core-frame 44.8k). That is NO-GO unless V4 recovers it. Otherwise switch to bit-serial drive (+0.15 dB) or derate VDD, then re-score |
| **V3** | corners: V2 at SS (373 K, 0.63 V signal), FF (85 °C), mismatch at the band end (1 % at 1 fF, 2 % at 0.25 fF), plus 2 % rms supply ripple | manufacturability, and the pick-vs-robust choice | G2 margin ≥ 0 dB at SS and FF, with closure (trim or adaptive VDD) costing ≤ 3 % tok/s | closure costing more than 0.87x tok/s: **switch to the robust tile + KV 4/8 + 16 MB** (47,500 corrected, P; corners already closed) |
| **V4** | ASAP7 SPICE of the V/3 and 2V/3 class-AB buffers driving 8 × 7.47 pF rows at worst-case codes | the 4-level drive credit, which the model never checked for stiffness | level within 0.1 % of V by the end of a 1.132 ns slot; drive-INL term ≥ 54.8 dB; ≤ 4.8 pJ per pass | adopt `drv_inv_bitserial` (61,740 / 14.04, P) |
| **V5** | ASAP7 SPICE of the class-A buffered reference under 128 simultaneous conversions | reference droop | ≤ 3.7 µV per conversion (ref term ≥ 54.0 dB); ≤ 46 pJ per pass | add decap (area) or slow the SAR, then re-score |
| **V6** | ASAP7 SPICE (BSIM-CMG) of the gain cell and its MOM6 units (1 fF and 0.25 fF): write and hold | weight integrity | write ≤ 0.70 fJ/bit within 31.6 ps per row; retention ≥ 1.32 µs at 6 σ and 85 °C to ½ LSB (4-b slice); leakage ≤ 14.2 nW per weight | raise the refresh rate (check occupancy), or grow C_unit |
| **V7** | ASAP7 SPICE of the bootstrapped share switch | linearity and reliability | τ ≤ 64.5 ps; injection term ≥ 73.9 dB; Ron flat within 1 % over the swing; V_GS within the ASAP7 limit | use a mid-rail transmission gate (N9 `colsw_midrail_tg_*`), then re-score |
| **V8** | RTL plus yosys (ASAP7 lib) of the B10 accumulator: 256 × 24-b add + register, and the 138 µm hop | the adopted T2 | ≤ 90 fJ per column-pass; one hop inside 6.3 ns at 0.5 V; bit-exact against the golden | if > 150 fJ, keep psums in the buffer (TOPS/W 14.84) |
| **V9** | non-circuit, run alongside: the quality harness on the analog path (Hadamard, A8 per token, ideal 12-b ADC at ±32 σ, static per-cell σ 1 %); KV 4/8 over 5 seeds with a KV8 control; SmolLM2 2:4 (SparseGPT, then counted short distillation) and 4-b lattice codebook | G2 on the real error classes; whether T1 and T4 pass the gate | analog increment ≤ +1.0 %; KV 4/8 within +0.3 % of KV8; the cumulative G1 with T1 and T4 ≤ +3.0 % | KV: fall back to KV8 (50,086, P). T1 and T4 stay rejected |
| **V10** | deferred: the systolic synthesis (`digital/sysreference`) at signoff quality | which baseline PE frame applies | none: it selects the frame | none |

## 8. Go / no-go after the ladder

1. Re-score the pick with every measured V1 to V8 number in place of its target, in the joint
   frame.
2. **GO** if all three hold:
   - tok/s/die ≥ **51,000** under ARCH, which is 1.10x the lever-matched ppa baseline (46,398);
   - tok/s/die ≥ **68,800** under Sohu, which is 1.10x the Sohu-equivalent (62,571);
   - G2 margin ≥ 0 dB at TT, SS and FF.
3. **SWITCH to the robust tile** (keeping KV 4/8, 16 MB and T2) if the pick's corner closure
   costs more than 0.87x tok/s, or if its re-score falls below robust's corrected 47,500.
4. **The IMC case against the literature-PE frame** needs ≥ 61,005 (ARCH) and ≥ 86,229 (Sohu).
   That means essentially every target met with no penalty: as scored, the pick is only 1.11x and
   1.17x of those numbers.
5. **NO-GO** if the re-score falls below 46,398 (ARCH) or 62,571 (Sohu). The analog design then
   loses the king metric in every baseline frame. Report it as such, and do not add margin to the
   projections.
6. **The transforms do not rescue a NO-GO.** With 2:4 and codebooks on both dies, the pick's
   corrected ratio *falls* (0.88x ARCH, 0.93x Sohu against the ppa PE).

## 9. Known model issues to carry into the phase

- **Frame dependence.** The joint frame credits the 1:16 merge and the 4-level drive (1.52x). The
  core frame (`cli.py`) does not. V2 and V4 settle it.
- **Reporting artefact.** `n9_exc_V` reads 1.19 V, above VDD. It is a reporting artefact in
  `_excursion`, and the real swing is about ±0.25 V per side. V2 must show every node stays
  inside 0 to 0.7 V.
- **Spill missing in core.** The core scorer charges no activation spill. The 16 MB buffer makes
  that harmless here, but that rests on the system judge's check, not on the core.
- **Write bits.** `write_bits_per_load` assumes 4 b per slice, which is right for this 2-slice
  tile; check it anyway.
- **LM head.** The LM-head MACs for the 511 non-final prompt tokens are counted as useful (about
  −1.6 % TOPS/W if excluded).
- **T2 in the evaluator.** T2 is a scratch patch. Add it to `n7_dataflow`, with the hop length
  taken from the floorplan.
- **Baseline anomaly.** The Sohu ppa baseline scores lower with T1 + T4 (93,522) than with T1
  alone (103,656). Use the maximum; the N4 owner should fix it.
- **No-margin measurements.** The 6 dB `lv_protect_tensor` credit and the KV 4/8 transfer to
  Llama-3-8B have no margin and are untested. The design does not use the first; V9 covers the
  second.

## 10. Bottleneck order and ownership (documented 2026-10-06, not yet researched)

Method (P): `arch_eval` what-ifs on `r2_A5_fast` under ARCH conditions. Each resource is made 2× better
on its own to see what binds next. Drive and conversion overlap, so a pass takes the longer of the two.

| # | Bottleneck | Phase | Owner | Evidence | Fix direction | Status |
|---|---|---|---|---|---|---|
| 1 | Tile pass time | prefill (about 60 % of the wave) | **analog** | Evaluator: drive 13.4 ns, conversion 12.6 ns. Verilog-A: drive 7.95 ns bit-serial (4.54 ns ml2), conversion 6.25 ns. ADC alone 2× faster: +0 %. Drive alone: +4 %. Both: 1.34×, then #2 binds | BS6H drive (`DRIVE_ALT.md`), E-trim SAR (`COMPARATOR_ALT.md`), AdcShare 3 or 4 | in the tile upgrade |
| 2 | Power density cap (1 W/mm²) | both | **analog** | ARCH die goes from 73 W to the 100 W cap after a 1.34× faster tile. Under Sohu it is at 852 of 1,063 W already, so a faster tile gains nothing. With the cap lifted: 1.45× | Less energy per pass. Drive delivery (about 108 pJ) and converters (about 71 pJ) dominate | documented only |
| 3 | HBM bandwidth | decode (about 37 %) | **digital / system** | A decode step moves 7.5 GB of W8 weights plus 13.9 GB of KV4 (B = 736) at 819 GB/s = 26 ms. 2×: 1.2× | Fewer bytes per token: KV and weight formats, speculative decoding (k tokens per weight and KV read), more HBM | documented only |
| 4 | KV capacity | concurrency | **digital / system** | B = 736 is the KV limit. 2× capacity gives +4 to 8 %, because KV is already 65 % of decode bytes | KV compression, more HBM | documented only |
| — | Attention rail, latency chain, die-to-die | — | digital | Prefill attention takes 1.09 s against 5.5 s of tile time; the rest is far from binding | — | not binding |

**Why the tile cannot fix #3 and #4 (roofline).** The die has about 960 TOPS and 819 GB/s, so a
phase needs about 1,170 ops per HBM byte to be compute-bound. Prefill reaches about 285,000:
every weight byte meets B × 512 tokens. Decode does not. Each weight byte meets one token per stream,
and each KV byte meets only its own stream's query. Decode intensity is 526 ops/byte at B = 736
and levels off near 800 as B grows, because KV traffic grows with B. Decode is therefore memory-bound
on any compute engine at this bandwidth.

The systolic baseline shows the same thing. With matched weight and KV formats (`cli.py <design>`),
the pick and the baseline tie on tok/s: 1.01× under ARCH and 0.996× under Sohu (plain evaluator,
round-1 pick as scored). Both are at the same KV-limited batch, and both decode at full HBM
bandwidth. What the analog tile changes is prefill time and energy. It wins about 1.04× on TOPS/W
and loses on tok/J (0.6×).

**Model issue for #1.** The evaluator's tile timing is about 2× slower than the Verilog-A
measurement. It converts both slices (512 conversions per pass), while the Verilog-A tile merges
first and converts 256. The tile upgrade recalibrates it.
