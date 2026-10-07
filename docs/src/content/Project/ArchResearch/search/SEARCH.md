# Joint architecture search, round 1

2026-10-06. Scored against `ARCH_METRIC.md`: tok/s per 100 mm² die > TOPS/W > tok/W > tok/J, Llama-3-8B, 512 + 128
tokens, ASAP7 TT. The search code is `scripts/compiler/metrics/arch_eval/search.py` and the raw output is `results.json`.
Every design named here exists as `designs/<name>.json`, and `cli.py` / `search.py --score` can score it.

**Labels.** Every tok/s, TOPS/W, tok/W and tok/J here is **projected**: node laws applied to measured
sky130 anchors, measured ASAP7 device tables and literature constants. Nothing is silicon or post-layout.
The systolic baseline's PE energy and area come from `digital/sysreference/build/ppa.json` (**derived**
from the s16 ASAP7 synthesis). The baseline is also shown with the literature PE (**projected**), which is
the frame the deferred synthesis would replace. The quality spot-check rows are **measured** on the
SmolLM2-135M proxy.

## Bottom line

**Winner (joint frame):** `designs/winner.json` (= `r01`). It scores **53,864 tok/s/die, 10.45 TOPS/W,
546.7 tok/W, 689.7 tok/J** (projected).

| node | choice |
|---|---|
| N1 | `stream_single`: weights streamed from the die's own HBM, one bank, skewed just-in-time rewrite, KV8 |
| N2 | `hybrid_msb_digital` at `k_dig = 0`: every input plane passive charge on the rail bottom plates. This is the `charge_rail` physics; the hybrid's digital planes do not pay off at this gate |
| N3 | `gaincell_mom_caps_mom6`: 4T gain-cell bits on min-pitch M2-M5 MOM units |
| N4 | `w8a8_lead_norot`: INT8 per channel in two slices with a 0.25x LSB unit, slice merge, block-32 activations, 32 sigma, no Hadamard |
| N5 | `blk_diff_r8_c256_s4`: differential, 8 rows per conversion, 256 columns, 4 columns per ADC |
| N6 | `sar_direct_residue_amp` at 11 b nominal (9.0 effective bits) |
| N7 | `tdm_noc`: the lean INT8 rail with a TDM NoC, rail headroom 2.0x, 8 MB buffer, multicast 16 |
| N8 | `lv_protect_tensor`: the gate G43 plus one massive-activation FFN-down tensor kept digital, a 6 dB credit |
| N9 | `vt_slvt_logic`: the lead circuit bundle with SLVT logic, 32-fin share switch |
| N10 | `none` |

The peak point is VDD 0.7 V, full clock, B = 368 streams (the KV-capacity limit), 38 tok/s per stream and
78 W of die power. The gate margin is **+0.26 dB**. Tile energy is 139 fJ/MAC: converters 36, buffer 36,
digital recombination 23, column switch 17, reference 14, array 10.

**Against the systolic baseline (identical metric, same die, HBM, rail and schedule):**

| comparison | tok/s/die | TOPS/W | tok/W | tok/J |
|---|---|---|---|---|
| baseline W8 KV8, PE from ppa.json (derived) | 41,356 | 7.66 | 423.9 | 839.2 |
| **winner / baseline** | **1.30x** | **1.37x** | **1.29x** | **0.82x** |
| baseline W8 KV8, literature PE (projected; the specified deferred-synthesis frame) | 46,401 | 17.74 | 811.2 | 1,339.2 |
| **winner / baseline** | **1.16x** | **0.59x** | **0.67x** | **0.51x** |
| baseline W4 KV8, literature PE (strongest baseline; W4 fails the lossless G1 tier for the IMC) | 53,833 | 18.02 | 876.7 | 1,520.0 |
| winner / baseline | 1.00x | 0.58x | 0.62x | 0.45x |
| Sohu conditions, 1,063 mm² die: baseline FP8 (ppa.json) | 62,571 | 10.81 | 71.9 | 124.3 |
| winner as-is / baseline | 1.57x | 1.29x | 1.27x | 0.81x |
| winner re-tuned for Sohu (`sohu_best`: 105,709 / 14.83 / 96.5 / 124.1) / baseline | 1.69x | 1.37x | 1.34x | 1.00x |
| Sohu baseline, literature PE: 86,229 / 18.77 / 119.8 / 255.6; re-tuned winner / it | 1.23x | 0.79x | 0.81x | 0.49x |

So the IMC wins the king metric in every frame, by 1.16-1.30x under ARCH and 1.23-1.69x under Sohu. It wins
TOPS/W only against the synthesized PE, and it loses tok/J everywhere. Read that win together with the
points below.

1. **The king metric is pinned at a system ceiling, not by the tile.** Weights stream at W8 (8 GB), which
   leaves 15 GB of the 24 GB stack for KV8, so B ≤ 368. Decode is then HBM-bound and prefill is bound by
   the rail's attention rate. Dozens of designs tie at exactly 53,864, and the 15 ranked rows differ only
   in TOPS/W. Once a tile is fast enough, tile choices move only the energy metrics. The systolic die
   reaches 41k because its prefill is compute-bound at 1 W/mm². Within model resolution, the
   decision-relevant set is the Pareto front, not r01. For example, **`p08` gives up 3.2 % of tok/s
   (52,157) for 1.57x TOPS/W (16.38), 1.40x tok/W and 1.37x tok/J**. That is the pick to make if a 3 % tok/s
   difference is below the model's error, which it is.
2. **The win rests on a compiler lever's credit.** With the bare G43 gate (`g43_lossless`, no lever) the
   best reachable design is 35,813 tok/s, **0.87x the baseline**. The winner needs the protect-tensor
   lever's 6 dB credit, which N8 measured unrotated on one proxy tensor. The Hadamard path (`lv_hadamard`,
   4.5 dB) reaches 51,026 / 14.66 / 708 / 778, and it is the path the quality harness measured directly
   (point 3).
3. **Quality spot-check (measured, `quality_spotcheck.json`).** The SmolLM2 proxy was run at W8 per
   channel, A8 per token, 8 rows per conversion, clip-free range, with noise at the design's uncredited
   class-weighted SNR:
   - **No rotation** (stand-in for the winner): digital format alone **+3.36 ± 0.68 %**, on the 3 % G1
     edge. Noise at 38.5 dB adds **+1.63 %**, over the 1 % G2 budget without the protect-tensor credit;
     the harness cannot emulate per-tensor protection. At 44.5 dB (the credited level) it adds +0.91 %.
   - **Hadamard** (stand-in for `lv_hadamard`): format **+0.06 ± 0.23 %**. Noise at 39.8 dB adds
     **+0.51 %** and at 43.0 dB adds +0.29 %, both inside the 1 % budget. The Hadamard credit holds on
     the proxy.

   The harness asserts per-token activation scales on the analog path, so the winner's block-32
   activations could not be emulated. That works against the winner here. **Verdict: the Hadamard design
   (`cf_n8_quality__lv_hadamard`, 0.95x the winner's tok/s, 1.40x its TOPS/W) is the quality-safe
   pick.** The winner stays the lexicographic pick only if the block-32 format and the protect-tensor
   credit are confirmed.
4. **Every lexicographic optimum sits on the gate edge** (margins +0.03 to +0.26 dB). The strict end of
   N8's band (45.8 dB) makes the winner infeasible, and the best re-optimized design (32,734) then
   **loses to the baseline (0.79x)**. The loose end (40 dB) leaves the winner unchanged; the best becomes
   56,087, using the HWA-distill lever at 46,000 GPU-h one-time.
5. **The frames disagree by more than the plateau's spread.** The core frame (`cli.py`) scores the winner
   at 39,997. The core frame's own best (`frame_core_best`, 60,444 / 18.7) **fails the gate in the joint
   frame** (-0.45 dB), because N9's droop/INL terms are missing from the core. Until the core adopts the
   N4/N8/N9 hooks and this file's guards, the ranking is only as good as that integration.
6. **What streaming costs.** The rule-pruned `resident` reaches 72,711 (+35 %). Constraint 2 (no SRAM
   bitcells) costs about 26 % of TOPS/W at equal tok/s (`sram6t_binary_caps`: 53,864 at 14.10).
7. **What died.** Every W4/W5/W6 and FP/LNS/MX format died at the lossless gate. So did current-mode
   arrays (≤ 5.9k), CCO/translinear log (≤ 5.9k; the log-domain hypothesis is not competitive),
   C2C/OTA/analog-weight charge, integrators (the sky130 ports), flash, ramp, CCO and DSM readouts, and
   most N10 wildcards (DPS-48 -15.7 %, Strassen -23 %, analog psum -10 %, stack3d -26 %). Time-domain
   arrays reach 42k at best. The node leads for N2 (hybrid digital planes), N4 (Hadamard lead), N5 (R8
   C256 S4) and N6 (residue-amp SAR) survive the joint search. N3's lead survives, and N9's lead loses
   3.6 % to SLVT logic.

## Frames side by side

| design | core (`cli.py`) | joint (ranking) | credit (N2 relief) |
|---|---|---|---|
| winner `r01` | 39,997 / 10.71 / 557.5 / 605.8 | **53,864 / 10.45 / 546.7 / 689.7** | 53,864 / 10.45 / 546.7 / 689.7 |
| `frame_core_best` | 60,444 / 18.67 / 840.4 / 840.4 | infeasible (gate margin -0.45 dB) | infeasible |

The credit frame's best is the joint winner itself. N2's hybrid relief does not change the pick, because
the winner runs `k_dig = 0`.

## Sensitivity

The search re-optimized from the top 5 designs under each change. "Winner as-is" is r01 scored under the
changed knob. The baseline is W8 KV8 with ppa.json PE under the same knob.

| case | best re-optimized (tok/s, TOPS/W, tok/W, tok/J) | its choices | winner as-is | baseline W8 KV8 (ppa.json PE) | winner changes? |
|---|---|---|---|---|---|
| die_50 | 39,533 / 16.05 / 755.9 / 836.1 | n8=lv_protect_tensor, n9=ref_bandgap_ldo, n7=tdm_noc, n4=w8a8_lead_norot; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 | 38,217 / 15.67 / 743.0 / 743.0 | 24,524 / 7.66 / 424.0 / 839.3 | yes |
| die_400 | 63,459 / 7.42 / 412.8 / 561.1 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=lean_int8_rail, n4=w8a8_lead_amp, n2=hybrid_wmsb_digital, n6=flash_sar_hybrid; adc_bits=11, buffer_MB=32, kv_bits=8, mcast=16, rail_headroom=2.0 | 63,459 / 6.11 / 349.4 / 501.9 | 61,278 / 7.65 / 423.6 / 838.6 | yes |
| hbm_x0p5 | 26,178 / 8.92 / 468.2 / 647.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=global_mesh, n4=w8a8_lead_norot, n6=flash_sar_hybrid; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 | 26,178 / 8.33 / 443.1 / 625.2 | 23,386 / 7.62 / 412.3 / 839.0 | yes |
| hbm_x2 | 87,554 / 14.83 / 714.2 / 787.5 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 | 86,850 / 14.59 / 705.5 / 732.7 | 50,633 / 10.47 / 547.4 / 839.3 | yes |
| floor_10 | 53,864 / 10.45 / 546.7 / 689.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 | 53,864 / 10.45 / 546.7 / 689.7 | 41,356 / 7.66 / 423.9 / 839.2 | no |
| floor_50 | 35,839 / 9.16 / 438.5 / 689.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 | 35,839 / 9.16 / 438.5 / 689.7 | 29,835 / 7.52 / 378.6 / 839.2 | no |
| gate_looser | 56,087 / 8.85 / 478.0 / 536.4 | n8=lv_hwa_distill, n9=drv_inv_bitserial, n7=tdm_noc, n4=w8a8_lead_norot, n3=gaincell_mos_caps_sramrule, n6=sar_vtc_fine_bpdac; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, q_snr_target_db=40.0, rail_headroom=2.0, share_fins=32 | 53,864 / 10.45 / 546.7 / 689.7 | 41,356 / 7.66 / 423.9 / 839.2 | yes |
| gate_tighter | 32,734 / 6.09 / 348.7 / 360.3 | n8=lv_hwa_distill, n9=lead, n7=tdm_noc, n4=w8a8_lead_norot, n2=time_delay_cal, n6=sar_sampled; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, q_snr_target_db=45.8, rail_headroom=0.5 | 0 / 0.00 / 0.0 / 0.0 | 41,356 / 7.66 / 423.9 / 839.2 | yes |

- **Die area.** The IMC advantage on the king metric is largest on a small die: 39,533 against 24,524 at
  50 mm² (1.61x), where the systolic die is compute-bound. It nearly vanishes at 400 mm²: 63,459 against
  61,278 (1.04x), with lower TOPS/W (7.42 against 7.65), because both dies then sit on the same KV/HBM
  ceiling. The pick changes only within the same family (reference or readout variant).
- **HBM bandwidth.** At x0.5 the result is 26,178 against 23,386 (1.12x). At x2 it is 87,554 against 50,633
  (1.73x). The IMC's lead is the bandwidth it can use.
- **Per-stream floor.** At 10 tok/s nothing changes (B is already KV-capacity-bound). At 50 tok/s the
  same winner scores 35,839 against 29,835 (1.20x).
- **Gate one step looser (40.0 dB) or tighter (45.8 dB), applied as a shift on every lever's target.**
  Looser leaves the winner unchanged; the best becomes 56,087 with HWA distillation (46,000 GPU-h,
  not in the metric). Tighter makes the winner infeasible, and the best (32,734) **loses to the
  baseline**. This is the most fragile axis.

## Ranked (top 15, one per distinct node-option tuple; all joint frame, projected)

| # | tok/s/die | TOPS/W | tok/W | tok/J | non-default choices (file `designs/<#>.json`) |
|---|---|---|---|---|---|
| r01 | 53,864 | 10.45 | 546.7 | 689.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r02 | 53,864 | 10.44 | 546.0 | 689.3 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_tokact; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r03 | 53,864 | 10.43 | 545.7 | 689.1 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r04 | 53,864 | 10.41 | 544.9 | 688.1 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_norot; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r05 | 53,864 | 10.39 | 544.2 | 687.6 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_tokact; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r06 | 53,864 | 10.39 | 544.2 | 687.8 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_norot, n7=mixed_rail; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r07 | 53,864 | 10.38 | 543.9 | 687.4 | n8=lv_protect_tensor, n9=vt_slvt_logic; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r08 | 53,864 | 10.37 | 543.5 | 687.3 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_tokact, n7=mixed_rail; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r09 | 53,864 | 10.37 | 543.2 | 687.1 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=mixed_rail; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r10 | 53,864 | 10.36 | 542.9 | 687.2 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_norot, n7=lns_rail; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r11 | 53,864 | 10.34 | 542.2 | 686.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_tokact, n7=lns_rail; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r12 | 53,864 | 10.34 | 541.9 | 686.6 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=lns_rail; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| r13 | 53,864 | 9.65 | 512.8 | 637.1 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=global_mesh, n4=w8a8_lead_norot, n6=sar_ra_bpdac; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32, v_exc_frac=0.43 |
| r14 | 53,864 | 9.65 | 512.8 | 637.1 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_ra_bpdac; adc_bits=11, k_dig=0, kv_bits=8, rail_headroom=2.0, share_fins=32, v_exc_frac=0.43 |
| r15 | 53,864 | 9.64 | 512.4 | 636.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_ra_bpdac; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32, v_exc_frac=0.43 |

All 15 tie on tok/s at the KV/HBM ceiling. `ranked_same_arch` in results.json lists the top 5 including
param-only variants.

## 4-metric Pareto set (24 points, thinned evenly to 24 rows; joint frame, projected)

| # | tok/s/die | TOPS/W | tok/W | tok/J | non-default choices |
|---|---|---|---|---|---|
| p01 | 53,864 | 10.45 | 546.7 | 689.7 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| p02 | 53,836 | 10.46 | 547.2 | 690.2 | n8=lv_protect_tensor, n9=vt_slvt_logic, n4=w8a8_lead_norot; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| p03 | 53,830 | 11.16 | 575.9 | 741.3 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| p04 | 53,781 | 11.88 | 604.2 | 790.5 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16 |
| p05 | 53,431 | 11.93 | 606.4 | 793.5 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16 |
| p06 | 52,782 | 12.50 | 628.5 | 778.3 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_direct_pool_k4; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p07 | 52,414 | 13.59 | 669.5 | 781.4 | n8=lv_protect_tensor, n9=vt_slvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_direct_pool_k4; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p08 | 52,157 | 16.38 | 767.0 | 945.1 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=32, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p09 | 50,893 | 16.82 | 781.6 | 916.0 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_direct_pool_k4; adc_bits=11, buffer_MB=32, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p10 | 50,783 | 16.82 | 781.7 | 916.1 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_direct_pool_k4; adc_bits=11, buffer_MB=32, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p11 | 49,447 | 19.56 | 867.2 | 1,086.5 | n8=lv_protect_tensor, n9=ref_bandgap_ldo, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=2, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16 |
| p12 | 47,257 | 19.73 | 872.2 | 942.6 | n8=lv_protect_tensor, n9=vt_lvt_logic, n4=w8a8_lead_norot, n7=tdm_noc, n6=sar_direct_pool_k4; adc_bits=11, k_dig=0, kv_bits=8, rail_headroom=2.0 |
| p13 | 46,843 | 19.74 | 872.6 | 943.2 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_direct_pool_k4; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0 |
| p14 | 46,831 | 19.68 | 870.8 | 1,029.5 | n8=lv_protect_tensor, n9=drv_pwm, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, k_dig=2, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32, v_exc_frac=0.43 |
| p15 | 46,769 | 20.29 | 888.8 | 962.2 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0 |
| p16 | 45,797 | 20.97 | 908.4 | 985.6 | n8=lv_protect_tensor, n9=vt_lvt_logic, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=32, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, v_exc_frac=0.43 |
| p17 | 45,098 | 19.81 | 874.8 | 1,014.4 | n8=lv_protect_tensor, n9=drv_inv_bitserial, n7=lean_int8_rail, n4=w8a8_lead_amp, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, double_buffer=True, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, v_exc_frac=0.43 |
| p18 | 44,118 | 22.63 | 954.3 | 1,086.4 | n8=lv_protect_tensor, n9=ref_bandgap_ldo, n7=no_pingpong, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=2, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16 |
| p19 | 42,067 | 22.96 | 963.2 | 1,044.0 | n8=lv_protect_tensor, n9=drv_pwm, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p20 | 35,778 | 23.86 | 986.9 | 1,025.7 | n8=lv_protect_tensor, n9=ref_reservoir, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| p21 | 35,295 | 23.86 | 986.9 | 1,025.7 | n8=lv_protect_tensor, n9=ref_reservoir, n7=tdm_noc, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |
| p22 | 34,976 | 27.17 | 1,068.7 | 1,114.6 | n8=bundle_raw, n9=ref_reservoir, n7=lean_int8_rail, n4=w8a8_lead_norot, n6=sar_vtc_pool; adc_bits=11, buffer_MB=32, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=16, v_exc_frac=0.43 |
| p23 | 17,548 | 27.55 | 1,077.6 | 1,077.6 | n8=lv_protect_tensor, n9=drv_pwm, n4=w8a8_lead_norot, n6=sar_vtc_pool, n2=charge; adc_bits=11, buffer_MB=8, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32, v_exc_frac=0.43 |
| p24 | 3,400 | 27.25 | 847.0 | 1,104.7 | n8=lv_hwa_distill, n9=drv_pwm, n7=tdm_noc, n4=w8a8_1cell8b, n2=charge, n5=blk_diff_r8_c64_s16, n6=sar_vtc_pool; adc_bits=11, buffer_MB=8, k_dig=0, kv_bits=8, mcast=16, rail_headroom=2.0, share_fins=32 |

## Counterfactuals: every option of every node, with everything else re-optimized

These rows are the decision tree to audit: if this choice were wrong, where would the design have gone?
Each row is a coordinate-descent **lower bound** (2 passes, joint frame). It starts from the winner with
the option swapped in and from the best explored design that already carried it. A rule-pruned option
is re-optimized as well, so its row shows what the rule costs. A row at 0 means no gate-feasible design
was found with that option.

| node | option | best reachable tok/s/die | TOPS/W | tok/W | tok/J | Δ tok/s vs winner | rule (if pruned) |
|---|---|---|---|---|---|---|---|
| n1_system | `stream_single` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n1_system | `streaming` | 52,412 | 8.93 | 481.6 | 661.8 | -2.7 % |  |
| n1_system | `resident` | 72,711 | 11.05 | 617.7 | 776.1 | +35.0 % | ARCH_METRIC: weights stream from HBM (user decision 2026-10-05) |
| n2_domain | `charge` | 17,126 | 7.01 | 393.3 | 445.9 | -68.2 % |  |
| n2_domain | `charge_rail` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n2_domain | `charge_bitslice` | 17,998 | 3.70 | 223.1 | 244.3 | -66.6 % |  |
| n2_domain | `charge_pulse_count` | 53,864 | 8.62 | 467.6 | 568.5 | +0.0 % |  |
| n2_domain | `charge_c2c` | 4,030 | 2.58 | 150.5 | 150.5 | -92.5 % |  |
| n2_domain | `charge_ota` | 665 | 0.67 | 41.2 | 44.6 | -98.8 % |  |
| n2_domain | `charge_analog_weight` | 16,361 | 2.71 | 167.5 | 167.5 | -69.6 % |  |
| n2_domain | `current_pwm` (no feasible design found) | 0 | 0.00 | 0.0 | 46.8 | -100.0 % |  |
| n2_domain | `current_tia` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n2_domain | `current_gaincell` | 404 | 3.17 | 124.2 | 283.6 | -99.2 % |  |
| n2_domain | `current_gaincell_cal` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n2_domain | `cco_freq_mac` | 5,864 | 3.52 | 210.5 | 214.5 | -89.1 % |  |
| n2_domain | `log_translinear` | 5,176 | 6.31 | 352.1 | 360.6 | -90.4 % |  |
| n2_domain | `time_delay` | 38,099 | 5.81 | 334.7 | 334.7 | -29.3 % |  |
| n2_domain | `time_delay_cal` | 42,412 | 7.22 | 403.3 | 412.9 | -21.3 % |  |
| n2_domain | `hybrid_msb_digital` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n2_domain | `hybrid_wmsb_digital` | 53,514 | 9.44 | 503.9 | 637.4 | -0.7 % |  |
| n2_domain | `digital_cim_ref` | 34,536 | 6.87 | 386.6 | 386.6 | -35.9 % | ARCH_METRIC scope: all-digital CIM is not analog/mixed IMC (N2 verdict) |
| n3_cell | `sram6t_binary_caps` | 53,864 | 14.10 | 687.9 | 822.5 | +0.0 % | ARCH_METRIC constraint 2: no SRAM bitcells in the tile (N3 verdict) |
| n3_cell | `sram6t_c2c` | 53,864 | 14.07 | 686.9 | 821.1 | +0.0 % | ARCH_METRIC constraint 2: no SRAM bitcells in the tile (N3 verdict) |
| n3_cell | `sram6t_mos_caps` | 37,906 | 6.76 | 381.1 | 401.2 | -29.6 % | ARCH_METRIC constraint 2: no SRAM bitcells in the tile (N3 verdict) |
| n3_cell | `gaincell_mom_caps` | 53,514 | 9.44 | 503.9 | 637.4 | -0.7 % |  |
| n3_cell | `gaincell_mom_caps_mom6` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n3_cell | `gaincell_c2c` | 53,514 | 9.33 | 499.0 | 632.6 | -0.7 % |  |
| n3_cell | `latch_mos_caps` | 36,188 | 5.82 | 334.9 | 334.9 | -32.8 % |  |
| n3_cell | `customlatch_mos_caps` | 37,229 | 5.84 | 336.1 | 336.1 | -30.9 % |  |
| n3_cell | `gaincell_mos_caps` | 37,989 | 5.84 | 335.8 | 335.8 | -29.5 % |  |
| n3_cell | `gaincell_mos_caps_sramrule` | 42,412 | 7.22 | 403.3 | 412.9 | -21.3 % |  |
| n3_cell | `gaincell_mos_r08` | 46,825 | 8.74 | 473.1 | 516.2 | -13.1 % | ARCH_METRIC: VDD in [0.45, 0.7] V; a supply rail above 0.7 V on ASAP7 thin oxide (reliabil |
| n3_cell | `gaincell_mos_r08_vlo035` | 50,821 | 11.96 | 607.5 | 685.2 | -5.7 % | ARCH_METRIC: VDD in [0.45, 0.7] V; a supply rail above 0.7 V on ASAP7 thin oxide (reliabil |
| n3_cell | `gaincell_mos_plus_mom` | 37,989 | 5.84 | 335.8 | 335.8 | -29.5 % |  |
| n3_cell | `dualp_mos_caps` | 38,099 | 5.81 | 334.7 | 334.7 | -29.3 % |  |
| n3_cell | `gaincell_mom_shared_bank` | 53,514 | 9.44 | 503.9 | 637.4 | -0.7 % |  |
| n3_cell | `gaincell_mos_shared_bank` | 37,989 | 5.84 | 335.8 | 335.8 | -29.5 % |  |
| n4_formats | `w4a8_g128` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w4a8_g128_had` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w5a8_sign_routed` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w8a8_2slice` | 36,742 | 12.15 | 615.1 | 716.6 | -31.8 % |  |
| n4_formats | `w8a8_q8_0_g32` | 36,113 | 12.14 | 609.7 | 709.4 | -33.0 % |  |
| n4_formats | `w8a8_q8_0_g32_had` | 36,113 | 12.10 | 608.5 | 708.7 | -33.0 % |  |
| n4_formats | `w8a8_1cell8b` | 21,905 | 3.33 | 202.5 | 202.5 | -59.3 % |  |
| n4_formats | `w6a8_1cell` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w7a8_1cell` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w8_2b_slices` | 13,748 | 2.10 | 125.5 | 129.3 | -74.5 % |  |
| n4_formats | `w6a8_fp6` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w8a8_fp8_bfp5` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `mxint4_g32` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `nvfp4_g16` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `mx_g128_pow2` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `fp8_per_element_analog` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `lns4_linear_tile` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `lns6_linear_tile` (no feasible design found) | 0 | 0.00 | 0.0 | 0.3 | -100.0 % |  |
| n4_formats | `posit8` | 36,742 | 12.15 | 615.1 | 716.6 | -31.8 % |  |
| n4_formats | `ternary_bitnet` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `binary` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `w3a8` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `w2a8` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `csd_weights` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `offset_binary_w` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `mixed_w4_w8_sensitive` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_bitserial` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_booth4` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_amplitude_dac` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_nibble_amp` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_pwm` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible + ARCH_METRIC constraint 3 (no PWM inputs by default) |
| n4_formats | `a8_pwm_split_nibble` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible + ARCH_METRIC constraint 3 (no PWM inputs by default) |
| n4_formats | `a8_thermometer` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_csd_input` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a8_log_input` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a10_common_scale` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `a6` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `a4_rotated` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `outlier_digital_lane` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `smoothquant_fold` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w8a8_bfp_act` | 36,742 | 12.14 | 614.7 | 716.3 | -31.8 % |  |
| n4_formats | `w4a8_had_bfp` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `outlier_lane_bfp` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w4a8_kv8` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w4a8_kv4` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w8a8_lead` | 53,864 | 10.43 | 545.7 | 689.1 | +0.0 % |  |
| n4_formats | `w8a8_lead_norot` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n4_formats | `w8a8_lead_plain` | 36,742 | 12.11 | 613.5 | 715.7 | -31.8 % |  |
| n4_formats | `w8a8_lead_merge` | 49,243 | 8.69 | 470.8 | 529.2 | -8.6 % |  |
| n4_formats | `w8a8_lead_asym` | 42,271 | 15.72 | 744.9 | 823.4 | -21.5 % |  |
| n4_formats | `w8a8_lead_q80` | 52,522 | 10.35 | 538.9 | 680.4 | -2.5 % |  |
| n4_formats | `w8a8_lead_1cell` | 31,457 | 5.09 | 297.6 | 307.9 | -41.6 % |  |
| n4_formats | `w8a8_lead_lsb1` | 43,495 | 16.50 | 770.9 | 855.2 | -19.2 % |  |
| n4_formats | `w8a8_lead_lsb4` | 26,959 | 4.22 | 251.7 | 251.7 | -50.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `w8a8_lead_k24` | 53,864 | 10.43 | 545.7 | 689.1 | +0.0 % |  |
| n4_formats | `w8a8_lead_k16` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n4_formats | `w8a8_lead_amp` | 50,792 | 8.84 | 477.5 | 537.1 | -5.7 % |  |
| n4_formats | `w8a8_lead_bitserial` | 35,168 | 6.49 | 368.2 | 394.1 | -34.7 % |  |
| n4_formats | `w8a8_lead_tokact` | 53,864 | 10.44 | 546.0 | 689.3 | +0.0 % |  |
| n4_formats | `w5a8_lead` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w6a8_lead_1cell` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w7a8_lead_1cell` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w4a8_lead` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w4a8_lead_amp` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w4a8` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n4_formats | `w8a8` | 36,742 | 12.15 | 615.1 | 716.6 | -31.8 % |  |
| n4_formats | `w4a4` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N4 verdict infeasible: fails the lossless format tier or range (N4.md) |
| n5_array | `diff_r128c64` | 2,855 | 0.66 | 42.6 | 59.2 | -94.7 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `se_r128c64` (no feasible design found) | 0 | 0.00 | 0.0 | 0.8 | -100.0 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `pseudo_r128c64` | 594 | 0.17 | 11.0 | 11.5 | -98.9 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `diff_rot` | 2,855 | 0.66 | 42.6 | 59.2 | -94.7 % |  |
| n5_array | `se_rot` (no feasible design found) | 0 | 0.00 | 0.0 | 1.8 | -100.0 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `pseudo_rot` | 282 | 5.62 | 111.2 | 432.7 | -99.5 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_r8_c256_s4` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n5_array | `blk_diff_r8_c64_s16` | 40,165 | 8.56 | 464.9 | 519.1 | -25.4 % |  |
| n5_array | `blk_diff_r16_c256_s8` | 43,080 | 6.72 | 379.2 | 386.9 | -20.0 % |  |
| n5_array | `blk_diff_r32_c256_s32` | 43,117 | 7.49 | 416.1 | 416.1 | -19.9 % |  |
| n5_array | `blk_diff_r32` | 37,156 | 6.64 | 375.6 | 422.6 | -31.0 % |  |
| n5_array | `blk_se_r32` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n5_array | `blk_pseudo_r32` | 66 | 0.14 | 7.5 | 14.8 | -99.9 % |  |
| n5_array | `blk_diff_r16` | 42,395 | 6.47 | 359.5 | 375.4 | -21.3 % |  |
| n5_array | `blk_diff_r64` | 38,805 | 7.07 | 396.4 | 396.4 | -28.0 % |  |
| n5_array | `blk_diff_r128` | 33,097 | 5.59 | 323.6 | 338.9 | -38.5 % |  |
| n5_array | `blk_diff_r256` | 127 | 1.14 | 39.0 | 171.3 | -99.8 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_r512_m6` | 193 | 1.08 | 37.9 | 86.9 | -99.6 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_r1024_hier` (no feasible design found) | 0 | 0.00 | 0.0 | 11.9 | -100.0 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_r4096_hier` (no feasible design found) | 0 | 0.00 | 0.0 | 1.6 | -100.0 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_c16` | 36,181 | 6.75 | 380.9 | 410.2 | -32.8 % |  |
| n5_array | `blk_diff_c256` | 37,219 | 6.63 | 375.2 | 422.3 | -30.9 % |  |
| n5_array | `blk_diff_c1024` | 36,574 | 6.72 | 379.5 | 409.4 | -32.1 % |  |
| n5_array | `blk_diff_s2` | 40,530 | 6.17 | 351.2 | 351.2 | -24.8 % |  |
| n5_array | `blk_diff_s32` | 36,184 | 5.50 | 318.6 | 318.6 | -32.8 % |  |
| n5_array | `blk_diff_s128` | 36,434 | 5.81 | 334.4 | 405.4 | -32.4 % |  |
| n5_array | `blk_diff_nochk` | 37,471 | 6.72 | 379.3 | 427.0 | -30.4 % |  |
| n5_array | `blk_diff_unshielded` | 437 | 2.08 | 94.6 | 137.4 | -99.2 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_nocal` | 7,087 | 1.08 | 67.1 | 67.5 | -86.8 % |  |
| n5_array | `blk_diff_bitserial_share` | 40,366 | 6.14 | 342.8 | 351.7 | -25.1 % |  |
| n5_array | `blk_diff_r8_c256_s4_e8m0` | 45,392 | 7.57 | 419.8 | 627.4 | -15.7 % |  |
| n5_array | `blk_diff_r8_c256_s4_e8m0w` | 45,421 | 7.60 | 421.4 | 633.3 | -15.7 % |  |
| n5_array | `blk_diff_r8_c256_s4_wblk32` | 45,421 | 7.60 | 421.4 | 633.3 | -15.7 % |  |
| n5_array | `blk_diff_r8_c256_s4_lsbthin` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n5_array | `blk_diff_r8_exact` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % |  |
| n5_array | `blk_diff_unshielded_xcancel` | 37,156 | 6.64 | 375.6 | 422.6 | -31.0 % |  |
| n5_array | `blk_diff_r256_wseg8` | 80 | 3.57 | 34.8 | 557.9 | -99.8 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_r512_wseg16` | 213 | 6.89 | 68.7 | 854.7 | -99.6 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n5_array | `blk_diff_r1024_hier_wseg32` (no feasible design found) | 0 | 0.00 | 0.0 | 12.1 | -100.0 % | N5 verdict infeasible (settling / write bitline / as-quantized rho / coupling, N5.md) |
| n6_readout | `sar_27h1` | 44,987 | 7.45 | 414.1 | 414.1 | -16.5 % |  |
| n6_readout | `integrator_coarse_sar` | 790 | 1.10 | 64.1 | 71.1 | -98.5 % |  |
| n6_readout | `integrator_cascade_k4` | 2,030 | 1.85 | 108.3 | 121.5 | -96.2 % |  |
| n6_readout | `null_sar_sky130_port` | 47,196 | 7.51 | 416.9 | 426.9 | -12.4 % | N6 verdict infeasible (N6.md) |
| n6_readout | `sar_sampled` | 53,388 | 8.44 | 459.6 | 560.5 | -0.9 % |  |
| n6_readout | `sar_direct` | 51,763 | 13.10 | 651.3 | 775.8 | -3.9 % |  |
| n6_readout | `sar_direct_redundant` | 53,217 | 10.73 | 558.2 | 714.0 | -1.2 % |  |
| n6_readout | `sar_direct_stack` | 37,001 | 5.68 | 328.1 | 341.0 | -31.3 % |  |
| n6_readout | `sar_direct_pool_k4` | 52,782 | 12.50 | 628.5 | 778.3 | -2.0 % |  |
| n6_readout | `sar_direct_stack_pool` | 49,410 | 11.98 | 608.3 | 708.1 | -8.3 % |  |
| n6_readout | `sar_vtc_fine` | 53,864 | 9.01 | 485.1 | 595.4 | +0.0 % |  |
| n6_readout | `sar_vtc_fine_bpdac` | 53,151 | 8.09 | 443.8 | 508.4 | -1.3 % |  |
| n6_readout | `sar_direct_residue_amp` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n6_readout | `sar_ra_bpdac` | 53,864 | 9.65 | 512.8 | 637.1 | +0.0 % |  |
| n6_readout | `sar_direct_redundant_bpdac` | 52,157 | 7.97 | 438.5 | 491.4 | -3.2 % |  |
| n6_readout | `sar_vtc_pool` | 53,830 | 11.16 | 575.9 | 741.3 | -0.1 % |  |
| n6_readout | `flash_sar_hybrid` | 52,312 | 12.21 | 617.2 | 701.2 | -2.9 % |  |
| n6_readout | `flash` | 18,508 | 3.18 | 194.4 | 197.6 | -65.6 % |  |
| n6_readout | `flash_per_plane` | 9,994 | 1.59 | 101.1 | 101.5 | -81.4 % |  |
| n6_readout | `sense_amp_1b` | 9,274 | 1.42 | 86.4 | 87.4 | -82.8 % | N6 verdict infeasible (N6.md) |
| n6_readout | `ramp_single_slope` (no feasible design found) | 0 | 0.00 | 0.0 | 2.5 | -100.0 % |  |
| n6_readout | `ramp_cis_coupled` | 1,450 | 2.14 | 123.7 | 135.9 | -97.3 % |  |
| n6_readout | `cco_per_column` | 4,251 | 0.68 | 41.6 | 49.3 | -92.1 % |  |
| n6_readout | `dsm_incremental` | 6,990 | 3.57 | 213.2 | 220.0 | -87.0 % |  |
| n6_readout | `pipelined_shared` | 36,529 | 5.55 | 321.3 | 321.3 | -32.2 % | N6 verdict infeasible (N6.md) |
| n7_dataflow | `lean_int8_rail` | 53,864 | 10.41 | 544.9 | 688.1 | +0.0 % |  |
| n7_dataflow | `digital_rail` | 52,870 | 8.39 | 457.3 | 616.5 | -1.8 % |  |
| n7_dataflow | `fp16_rail` | 50,968 | 11.98 | 608.4 | 801.4 | -5.4 % |  |
| n7_dataflow | `mixed_rail` | 53,864 | 10.39 | 544.2 | 687.8 | +0.0 % |  |
| n7_dataflow | `lns_rail` | 53,864 | 10.36 | 542.9 | 687.2 | +0.0 % |  |
| n7_dataflow | `tdm_noc` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n7_dataflow | `unicast_buffer` | 53,864 | 10.41 | 544.9 | 688.1 | +0.0 % |  |
| n7_dataflow | `no_pingpong` | 48,358 | 8.27 | 451.9 | 505.1 | -10.2 % |  |
| n7_dataflow | `global_mesh` | 53,864 | 10.41 | 544.9 | 688.1 | +0.0 % |  |
| n8_quality | `snr28_w4a8` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g_paper_28_38` | 59,281 | 21.08 | 911.5 | 1,184.3 | +10.1 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g43_lossless` | 35,813 | 6.99 | 392.6 | 392.6 | -33.5 % |  |
| n8_quality | `g40_lossless_lowA` | 41,267 | 6.28 | 350.5 | 358.3 | -23.4 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g46_lossless_highA` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g47_top1_97` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g38_3pct` | 47,138 | 7.51 | 416.8 | 533.4 | -12.5 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g33_10pct` | 59,281 | 21.08 | 911.5 | 1,184.3 | +10.1 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `g43_w4_acceptable` | 30,244 | 4.59 | 270.6 | 270.6 | -43.9 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `lv_affine_cal` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % |  |
| n8_quality | `lv_tile_range` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % |  |
| n8_quality | `lv_dynamic_fs` | 19,296 | 2.96 | 181.4 | 181.4 | -64.2 % |  |
| n8_quality | `lv_interleave` | 46,644 | 7.31 | 407.4 | 458.8 | -13.4 % |  |
| n8_quality | `lv_hadamard` | 51,026 | 14.66 | 708.0 | 777.8 | -5.3 % |  |
| n8_quality | `lv_smooth` | 7,140 | 1.54 | 96.9 | 97.6 | -86.7 % |  |
| n8_quality | `lv_gptq` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % |  |
| n8_quality | `lv_group32_scales` | 5,628 | 1.95 | 121.6 | 122.6 | -89.5 % |  |
| n8_quality | `lv_outlier_1pct` | 5,477 | 0.85 | 54.9 | 55.1 | -89.8 % |  |
| n8_quality | `lv_outlier_3pct` | 5,003 | 0.78 | 49.8 | 49.8 | -90.7 % |  |
| n8_quality | `lv_protect_tensor` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n8_quality | `lv_water_fill` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % |  |
| n8_quality | `lv_head_digital` | 28,832 | 4.78 | 281.5 | 306.8 | -46.5 % |  |
| n8_quality | `lv_cell_predistort` | 35,823 | 5.57 | 322.2 | 322.2 | -33.5 % |  |
| n8_quality | `lv_noise_inject_ft` | 43,080 | 6.71 | 379.2 | 386.8 | -20.0 % |  |
| n8_quality | `lv_hwa_distill` | 46,671 | 7.29 | 406.7 | 519.0 | -13.3 % |  |
| n8_quality | `lv_lora_digital` | 45,545 | 6.93 | 387.4 | 397.1 | -15.4 % |  |
| n8_quality | `lv_kv8` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % |  |
| n8_quality | `lv_lsb_truncation` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % |  |
| n8_quality | `lv_resistive_ir` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % | N8: resistive domains only (n/a) |
| n8_quality | `lv_nvm_program` | 19,051 | 2.89 | 176.1 | 178.1 | -64.6 % | N8: program-once NVM only (n/a) |
| n8_quality | `bundle_lead` | 50,223 | 11.88 | 604.4 | 711.2 | -6.8 % |  |
| n8_quality | `bundle_raw` | 51,078 | 12.14 | 614.6 | 805.0 | -5.2 % |  |
| n8_quality | `bundle_rot_dfs` | 44,747 | 7.31 | 407.6 | 431.9 | -16.9 % |  |
| n8_quality | `bundle_lead_lowA` | 52,047 | 13.07 | 649.9 | 880.0 | -3.4 % | N8 gate policy, not a design lever (sensitivity row) |
| n8_quality | `bundle_hwa` | 52,047 | 10.31 | 541.0 | 684.5 | -3.4 % |  |
| n9_circuits | `lead` | 51,939 | 9.34 | 499.4 | 749.5 | -3.6 % |  |
| n9_circuits | `single_rail` | 51,939 | 9.34 | 499.4 | 499.4 | -3.6 % |  |
| n9_circuits | `ntv_rail_045` | 33,303 | 6.77 | 381.9 | 430.4 | -38.2 % |  |
| n9_circuits | `analog_rail_09` | 51,939 | 8.43 | 459.3 | 662.2 | -3.6 % | ARCH_METRIC: VDD in [0.45, 0.7] V; a supply rail above 0.7 V on ASAP7 thin oxide (reliabil |
| n9_circuits | `vt_lvt_logic` | 52,870 | 8.39 | 457.3 | 616.5 | -1.8 % |  |
| n9_circuits | `vt_slvt_logic` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n9_circuits | `vt_slvt_all` | 34,498 | 5.40 | 313.6 | 313.6 | -36.0 % | N9 verdict infeasible (N9.md) |
| n9_circuits | `colsw_midrail_tg_rvt` | 49,447 | 15.81 | 747.8 | 904.3 | -8.2 % |  |
| n9_circuits | `colsw_midrail_tg_lvt` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `colsw_midrail_nmos_rvt` | 49,447 | 14.92 | 717.1 | 859.9 | -8.2 % |  |
| n9_circuits | `colsw_ground_nmos_rvt` | 49,447 | 14.92 | 717.1 | 859.9 | -8.2 % |  |
| n9_circuits | `colsw_ground_slvt` | 44,956 | 6.83 | 384.8 | 399.7 | -16.5 % | N9 verdict infeasible (N9.md) |
| n9_circuits | `colsw_ground_lvt` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `colsw_bootstrap_lvt` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `clk_sync_tree` | 48,315 | 9.11 | 489.6 | 671.2 | -10.3 % |  |
| n9_circuits | `clk_self_timed` | 51,590 | 8.22 | 449.7 | 642.6 | -4.2 % |  |
| n9_circuits | `clk_gals_local` | 51,342 | 8.22 | 449.7 | 642.6 | -4.7 % |  |
| n9_circuits | `clk_dll_replica` | 51,939 | 8.22 | 449.7 | 642.6 | -3.6 % |  |
| n9_circuits | `clk_tt_no_margin` | 51,939 | 9.34 | 499.5 | 749.5 | -3.6 % |  |
| n9_circuits | `ref_ratiometric_decap` | 36,508 | 5.55 | 315.3 | 324.9 | -32.2 % | N9 verdict infeasible (N9.md) |
| n9_circuits | `ref_reservoir` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `ref_bandgap_ldo` | 51,939 | 10.07 | 530.8 | 823.2 | -3.6 % |  |
| n9_circuits | `amp_none` | 51,939 | 7.99 | 439.1 | 621.2 | -3.6 % |  |
| n9_circuits | `amp_ota_integrator` | 51,939 | 9.34 | 499.4 | 749.5 | -3.6 % | N9 verdict infeasible (N9.md) |
| n9_circuits | `amp_twostage_integrator` | 51,939 | 9.34 | 499.4 | 749.5 | -3.6 % | N9 verdict infeasible (N9.md) |
| n9_circuits | `amp_telescopic` | 51,939 | 9.34 | 499.4 | 749.5 | -3.6 % |  |
| n9_circuits | `drv_inv_bitserial` | 51,939 | 8.37 | 456.7 | 657.1 | -3.6 % |  |
| n9_circuits | `drv_row_dac` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `drv_row_dac_ms` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `drv_nibble_dac` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `drv_ml3_dac` | 46,671 | 7.29 | 406.7 | 438.4 | -13.3 % |  |
| n9_circuits | `drv_sf_dac` | 44,956 | 6.83 | 384.8 | 399.7 | -16.5 % | N9 verdict infeasible (N9.md) |
| n9_circuits | `drv_pwm` | 49,447 | 18.24 | 827.1 | 1,023.0 | -8.2 % |  |
| n10_wildcards | `none` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n10_wildcards | `residual_tiles` | 52,157 | 12.33 | 621.8 | 771.3 | -3.2 % |  |
| n10_wildcards | `ensemble_avg` | 19,634 | 3.88 | 233.1 | 243.4 | -63.5 % |  |
| n10_wildcards | `pedestal_sub` | 53,864 | 10.45 | 546.7 | 689.7 | +0.0 % |  |
| n10_wildcards | `analog_psum` | 48,392 | 7.45 | 414.2 | 802.0 | -10.2 % |  |
| n10_wildcards | `dps48` | 45,406 | 7.18 | 401.5 | 401.5 | -15.7 % |  |
| n10_wildcards | `dps48_int4` | 646 | 0.12 | 8.1 | 8.2 | -98.8 % |  |
| n10_wildcards | `strassen` | 41,458 | 6.47 | 367.3 | 375.3 | -23.0 % |  |
| n10_wildcards | `strassen_int4` | 34,621 | 5.36 | 311.6 | 311.6 | -35.7 % |  |
| n10_wildcards | `dps48_strassen` (no feasible design found) | 0 | 0.00 | 0.0 | 5.0 | -100.0 % | N10 verdict infeasible (N10.md) |
| n10_wildcards | `dps48_strassen_orbit` | 24,070 | 3.67 | 218.7 | 225.8 | -55.3 % |  |
| n10_wildcards | `unary_pwm` | 14,670 | 2.23 | 139.3 | 139.3 | -72.8 % |  |
| n10_wildcards | `stack3d` | 40,145 | 6.18 | 351.3 | 351.3 | -25.5 % |  |
| n10_wildcards | `residue_imc` | 39,175 | 6.37 | 362.4 | 417.7 | -27.3 % |  |
| n10_wildcards | `karatsuba` | 16,581 | 4.37 | 260.0 | 267.7 | -69.2 % |  |
| n10_wildcards | `factorized` | 44,195 | 8.29 | 452.7 | 508.9 | -17.9 % |  |
| n10_wildcards | `moe_experts` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N10 verdict infeasible (N10.md) |
| n10_wildcards | `cam_topk_kv` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N10 verdict infeasible (N10.md) |
| n10_wildcards | `iterative_refinement` (no feasible design found) | 0 | 0.00 | 0.0 | 0.0 | -100.0 % | N10 verdict infeasible (N10.md) |

## How the search works

`scripts/compiler/metrics/arch_eval/search.py` (single process, about 2 h on this machine, under a 4 GB cap):

1. **Space.** Every option of every node module (3 + 18 + 16 + 67 + 39 + 25 + 9 + 35 + 33 + 19 = 264) and the
   swept params `adc_bits, kv_bits, k_dig, cu_fF, mos_fins, share_fins, wire_x, ra_gain, v_exc_frac,
   rail_headroom, buffer_MB, mcast, double_buffer`. VDD (0.45 to 0.7 V), clock fraction and concurrency are
   operating points inside the metric, as `model.py` defines them. The n10 `CANDIDATES` are seeds.
   The full product is about 10^17 designs, so the search does not enumerate it.
2. **Beam + polish.** Width 6, single moves (one option or one param value), 10 iterations, seeded with the
   default, the node leads (N5 and N9 stacks, N5's robust R16 fallback, ADC 10 to 14 b) and the n10
   candidates. Coordinate descent from every beam state follows. Infeasible designs are ordered by their
   best gate margin, so the beam can climb out of the region where nothing passes. The shipped default is
   infeasible (gate margin -10.5 dB).
3. **Counterfactuals.** For each of the 264 options: fix it, then run coordinate descent over everything
   else (2 passes), starting from the winner with that option swapped in and from the best explored design
   that already carries it. These are **lower bounds** on the best design reachable with that option, not
   proofs of optimality. Rule-pruned options are re-optimized as well, so the table shows what each rule
   costs. The winner is the best admissible design found by any of these descents.
4. **Baseline and sensitivity.** `baseline_systolic.evaluate` under both condition sets, with the PE
   numbers from `ppa.json` (derived from the s16 synthesis) and with the literature PE (projected). Then
   descent from the top 5 again under each changed knob.

Reproduce: `python3 scripts/compiler/metrics/arch_eval/search.py`. Self-check: `search.py --selfcheck`
(the Pareto sweep against `metric.pareto`, and the guards against the known holes). After the run the
guards were made to apply to infeasible designs as well. All 304 reported designs were re-scored and
match results.json; the only flag that changed is the already rule-pruned `digital_cim_ref` row. To score any design file in all three
frames, run `search.py --score <file>`. `cli.py <file>` gives the core frame only.

### Three scorer frames (same design JSON)

| frame | what it adds to `model.evaluate` (= `cli.py`) | use |
|---|---|---|
| core | nothing | the shared contract as it is today |
| **joint** | N9 `evaluate_full` hooks (driver, reference, column switch, clock energy and area, droop/INL accuracy terms; charge arrays only, which is N9's model scope); N4 `tile_effects` (true unit count, conversions per scale block, slice merge, input-side digital work); N8 `q_rail_macs_frac` charged on the digital rail | **ranking frame**: these are costs the owners priced and the core has not yet adopted |
| credit | joint + N2's hybrid relief (6.02 dB per digital MSB plane) credited to the gate | N2/N4's claim, which N8 has not adopted. It is reported here and never decides the winner |

The frames disagree by 35 % on the winner itself (39,997 core against 53,864 joint), and the core frame's best fails the gate in the joint frame (table below). **The integration of the node
models is now a bigger uncertainty than any choice inside the winning plateau.** The core should adopt the
three hooks and the guards below (`REQUIRED_TOOLING`-class request to the core owner).

### Model holes this search hit, and the guard that now closes each one

Each of these produced a false winner during this run. Every guard lives in `search.py` and is logged per
design (`pruned_counts` in results.json):

| hole | false result it produced | guard |
|---|---|---|
| Overriding `rows` under an n5 option that carries geometry-specific laws (`blk_diff_r8_exact` at R128 drops the ADC term) | 54,329 tok/s, weight area 0 | n5 geometry params are not swept; each n5 option is a geometry |
| n4 `tile_effects` × n2 current-domain cell rescales the weight area to 0 | same design | weight area must be >= 0.1 um² per weight |
| `blk_diff_r8_exact` scored without its own conditions (`score_params` 48.7 dB, `score_fmts`, `score_bits`) | 47,351 tok/s winner in the smoke run | the option's conditions are imposed and checked |
| N8's lossless gate checks only `wbits >= 8`, so LNS6 (`f_tier` acceptable, +13 % proxy PPL, 6-b HBM storage) passed | 54,685 tok/s winner (run 1) | n4 `tier` must be `lossless` under the G43 gate |
| KV4 is QServe's acceptable tier, not lossless (N8 `lv_kv8`), but nothing checked it | 88,059 tok/s winner (probe) | `kv_bits >= 8` |
| N9's PWM driver divides the array energy by the plane count; applied to a **time-domain** array it cut a delay-chain energy 6x | 54,568 tok/s winner (run 2); 24,339 in the core frame | N9 hooks only on charge arrays |
| N4 amplitude C-DAC input (law 8: a C-DAC on the bottom plates) on time/current arrays collapses 6 radix planes to 1 slot | 54,991 tok/s (run 3 counterfactual) | `amp`/`nib_amp`/`thermo` encodings need a charge array |
| N8 levers that require rotation (`lv_hadamard`, `bundle_*`) credited on a non-rotated n4 format | lv_hadamard row 51,026 | lever `requires.rot` needs n4 `f_rot`; lever `requires.rho` is imposed |

### What may not be picked (rules, logged, re-optimized in the counterfactual table)

- n1 `resident`: ARCH_METRIC says weights stream (user decision).
- n2 `digital_cim_ref` and any hybrid with every input plane digital: ARCH_METRIC scope (analog/mixed only).
- n3 `sram6t_*`: ARCH_METRIC constraint 2 (no SRAM bitcells in the tile).
- n3 `gaincell_mos_r08*` and n9 `analog_rail_09`: a supply rail above ARCH_METRIC's 0.7 V on thin oxide. N3
  and N9 both list a reliability check as a precondition.
- Options a node marked infeasible (N4: k16, lsb4, fp8 per element, ternary/binary/W3/W2, A6, A4, PWM inputs
  under constraint 3; N5: R >= 256 flat or segmented, as-quantized rho, single-ended rotated, unshielded;
  N6: pipelined_shared, the sky130 null-SAR port, 1-b sense amp; N9: vt_slvt_all, colsw_ground_slvt, the
  decap-only reference, the OTA integrators, the SF DAC; N10: dps48_strassen, MoE, CAM top-k, iterative
  refinement; N8: the NVM/resistive levers).
- n8 gate policies (snr28, g_paper, g33, g38, g40, g46, g47, g43_w4_acceptable, bundle_lead_lowA). The gate is
  N8's G43 lossless gate. The other policies appear only in the counterfactual table and in the gate-step
  sensitivity.
- Constraint 3 (no PWM by default) is honored by letting PWM drive (n9 `drv_pwm`) compete: it is admissible
  only because the metric decides whether it wins on tok/s.

## Limits of this round (read before acting on a number)

- **Counterfactual rows are lower bounds.** Coordinate descent can miss two-step moves, and this run
  shows it: the third run found a +2 % design reachable only through a chimera, which a guard now
  closes. The winner is the best admissible design among about 160k evaluated, not a proven optimum of
  the 10^17 space.
- **The schedule is the core's lockstep waves.** N1/N7's continuous batching and two-group interleave
  are not in the core. Their own frames claim +10 to +17 %, for the baseline as well.
- **Not in the metric:** one-time GPU-hours (HWA distillation is 46,000 GPU-h; protect-tensor and
  Hadamard need about 1 GPU-h), weight retention (N1's R1/R2 rows; the winner's gain-bit cell is the
  refreshed live cell, which N1 lists as unaffected) and corners (TT 25 °C per ARCH_METRIC).
- **Baseline PE.** ppa.json comes from an open-source flow with placement RC and no power-aware sizing.
  Its own note calls the energy "an upper bound". The literature PE is 2.5x lower in energy. The TOPS/W
  verdict flips between those two frames, and the deferred synthesis decides it.
- **The Sohu die is 1,063 mm²** (`metric.sohu_area()`, recalibrated from ppa.json), not the 666 mm² in
  ARCH_METRIC's text.
- **Notes used:** the 27h1 converter thermal law (N6/N5 ADC terms), 27n1 bit-normalized TOPS/W (the CLI
  prints it), 27l4 (a scale block shorter than R forces R/g conversions, N4 law 6), 27h9 (PWM costs 2^b
  time steps; constraint 3), and 27a2 / 27l1 (reuse R = V, which sets N1's exposure). The gate is N8's,
  built from the notes and the literature, and the proxy runs above corroborate its Hadamard credit.

## What to run next (decision-ranked)

1. **Quality harness:** block-32 activation scales on the analog path, and per-tensor protection of the
   FFN-down outlier tensor. This decides r01 (no rotation, protect tensor) against the measured-safe
   Hadamard design.
2. **Core adoption** of the N4/N8/N9 hooks and of this file's guards (tier, KV, encoding × domain, N9 ×
   charge, rotation, option conditions). The frames currently disagree by 35 % on the winner, and on feasibility for others.
3. **The systolic synthesis** (deferred). The baseline's TOPS/W differs 2.3x between ppa.json and the
   literature, which decides whether the IMC wins TOPS/W at all.
4. **ESPice** of the winning column (R8 differential, 256 columns, residue-amp SAR at 11 b) to confirm
   9.0 effective bits and the 38.5 dB class-weighted SNR. The margin is 0.26 dB.
5. **HBM/KV-capacity levers** (N1's 8-of-16-channel PHY option, KV formats). tok/s is pinned by
   B = KV-capacity, so these move the king metric more than any tile choice does.
