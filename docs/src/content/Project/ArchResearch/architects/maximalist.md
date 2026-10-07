# Architect panel: the tok/s maximalist

2026-10-06. Angle: the highest tok/s per die any legal combination can reach, pushing whichever
constraint binds as far as physics allows, even at a TOPS/W cost. Scored against
`ARCH_METRIC.md` (tok/s per 100 mm² die > TOPS/W > tok/W > tok/J, Llama-3-8B, 512 + 128, ASAP7 TT).

Files: design `scripts/compiler/metrics/arch_eval/designs/maximalist.json`, scorer
`scripts/compiler/metrics/arch_eval/designs/maximalist.py` (`--selfcheck` PASS; `python3
designs/maximalist.py` prints the frames below).

**Labels.** Every tok/s, TOPS/W, tok/W and tok/J here is **projected**. The tile numbers are the
search's joint-frame laws (node laws on measured sky130 anchors, measured ASAP7 device tables and
literature constants), the system law is N1's continuous-batching law, and the tensor-parallel
d2d cost is N1's `tp_d2d`. Baseline rows with the ppa.json PE are **derived**, and rows with the
literature PE are **projected**. No SPICE and no P&R were run for this proposal. The search's
quality spot-check (`quality_spotcheck.json`) is **measured** and is cited, not re-run.

## Bottom line

| | tok/s/die | TOPS/W | tok/W | tok/J |
|---|---|---|---|---|
| **maximalist** (η = 1 ceiling of the CB law) | **96,564** | **20.58** | **991** | **1,096** |
| maximalist at N7's realistic overlap η = 0.85 | 82,080 | 20.58 | 991 | 1,096 |
| search winner r01, as published (core lockstep, no activation spill charged) | 53,864 | 10.45 | 546.7 | 689.7 |
| ratio (η = 1 / η = 0.85) | **1.79x / 1.52x** | 1.97x | 1.81x | 1.59x |

Generated-only throughput is 19.3k tok/s per die, 966 tok/s per mm², and 13.6 tok/s per mm² per W.
The peak point is VDD 0.55 V at full clock, 4,097 streams over an 8-die group (512 per die), 37.7
tok/s per stream, 71.2 W per die (the 100 W cap is not binding), and HBM at 819 GB/s.

**What wins, said plainly.** None of the gain comes from the tile. The tile is p08's from the
search's Pareto front, unchanged. The gain comes from three system levers that the core
evaluator cannot express, and all three are already priced in existing node code:

1. **A tensor-parallel group of 8 dies, each with its own HBM stack.** The weight copy splits
   8 ways, so a die's KV capacity grows from 24 − 8 to 24 − 1 GB (B_max 368 → 4,373 for the
   group), and each decode sweep's weight bytes are shared by 8x more streams.
2. **Continuous batching with chunked prefill on the decode weight sweeps.** This is
   Sarathi-Serve style, with N1/N7's two-group interleave. Prefill (rail- and compute-bound) and
   decode (HBM-bound) stop taking turns. In the core's lockstep schedule the HBM sits idle for
   the whole prefill phase.
3. **A 96 MB activation buffer** (28 mm², in place of 8 MB). Under continuous batching each
   weight chunk serves V = 20,484 vectors. With 8 MB their inputs spill to HBM at 8.4 MB/token,
   which is more than the KV traffic, so (2) alone loses (40.6k). At 96 MB the spill is
   0.44 MB/token.

With all three in place the die reaches 90 % of the **HBM-KV roofline** (106.7k tok/s/die =
819 GB/s ÷ 7.67 MB of KV8 traffic per processed token). At the 512 + 128 workload, KV8 and one
stack per die, no architecture, analog or digital, can exceed that ceiling (27a2: KV reads have
reuse 1, so they sit at the far left of the roofline, and no in-memory trick removes them).

## Loud corrections this work surfaced

- **The search winner's 53,864 is an overclaim of about 18 % under the repo's own spill law.**
  The core's lockstep prefill makes every weight chunk serve B·P = 188k vectors. Their inputs
  (up to 2.7 GB for FFN-down) cannot sit in an 8 MB buffer, and the core charges no activation
  spill. With N1's `act_spill` law charged at the same operating point, r01 scores **44,258**
  (`maximalist.lockstep_spill`). p08, with 32 MB, is unaffected (52,157). Every lockstep row in
  SEARCH.md carries this hole, and so does the baseline's lockstep row.
- **Continuous batching is not a free +10–17 %.** With the default 8 MB buffer it **loses**
  (r01: 40,630 against 53,864) because of the spill. It wins only together with a buffer sized to
  V·K·a.
- **The CB law is an η = 1 ceiling.** N7 measured the overlap inefficiency of the
  QKV → attention → O dependency at η ≈ 0.85 (N7.md, critic 1). The realistic headline is
  **82k**, and the band is 82k to 96.6k. The same η applies to the baseline, so the ratios
  below do not move.
- **Equal levers help the baseline too** (next table). The IMC's margin over the digital
  baseline is much smaller than the 1.79x over the search winner.

## Against the baseline at equal levers (same TP group, CB law, d2d charge; buffer optimized per design)

| comparison | tok/s/die | TOPS/W | tok/W | tok/J | maximalist ratio |
|---|---|---|---|---|---|
| baseline W8 KV8, ppa.json PE (derived), best: 1 die, 32 MB, compute-bound | 55,380 | 10.47 | 546.0 | 839.2 | 1.74x / 1.97x / 1.82x / 1.31x |
| baseline W8 KV8, literature PE (projected), TP-8, 32 MB, HBM-bound | 83,020 | 18.06 | 864.6 | 1,640 | **1.16x / 1.14x / 1.15x / 0.67x** |
| baseline W4 KV8, literature PE (W4 fails the IMC's lossless tier), TP-8, 32 MB | 87,330 | 18.17 | 894.9 | 1,657 | 1.11x / 1.13x / 1.11x / 0.66x |
| r01's tile under the same levers (the search winner's tile) | 96,560 | 16.36 | 834.1 | 836.6 | 1.00x / 1.26x / 1.19x / 1.31x |
| Hadamard tile (`cf_n8_quality__lv_hadamard`, the measured-safe credit), 64 MB | 92,713 | 15.50 | 792.3 | 869.4 | 1.04x / 1.33x / 1.25x / 1.26x |

Against the strongest baseline (literature PE), the IMC wins tok/s by 1.11–1.16x and TOPS/W by
1.13–1.14x. With the levers, TOPS/W is won in both PE frames, while the search winner lost TOPS/W
to the literature PE. tok/J is still lost to the literature PE (0.67x). The literature baseline
is HBM-bound too, so on tok/s the two dies meet the same roofline. The IMC gets closer to it
because its energy per token keeps it under the power cap and its 96 MB buffer still leaves
enough tiles.

**Sohu conditions** (Llama-3-70B, FP8, 2,048 + 128, batch 1,000, 8 chips, 1,063 mm² die). The same
tile and the same levers, with the buffer re-tuned to 512 MB (166 mm²), score **149,600 / 19.95 /
125.4 / 148.0**. That point is power-capped at 1,063 W, the first design here where the power cap
binds. The comparisons: literature baseline with CB, 128 MB: 136,200 / 18.77 / 116.9 / 255.8 →
**1.10x** / 1.06x / 1.07x / 0.58x. ppa.json baseline: 80,580 / 10.75 / 69.1 / 124.3 → 1.86x. The
search's re-tuned `sohu_best` (105,709) → 1.42x.

## Block diagram (one die of the 8-die TP group)

```
             HBM3 stack 819 GB/s, 24 GB  (1/8 of W8 weights = 1 GB, KV8 for 1 of 8 KV heads)
                                   |
                     HBM PHY 12 mm2 + d2d PHY (ring all-reduce, 0.92 MB/token, 2 TB/s)
                                   |
   +-------------------------------+---------------------------------------------------+
   |  96 MB activation buffer (28.2 mm2, multicast 16)    lean INT8 rail (3.9 mm2)      |
   |   holds V = 20k vectors' inputs per weight chunk      attention lanes h = 2x,       |
   |   -> spill 0.44 MB/token                              base-2 exp, online softmax,   |
   |                                                       KV head local to the die      |
   |                    NoC (mesh, 0.7 mm2)                                              |
   |   +--------------------------------------------------------------------------+     |
   |   | 1,892 IMC tiles (33.2 mm2): R8 x C256 differential charge-rail columns,  |     |
   |   |  4T gain-cell bits on min-pitch MOM unit caps (no SRAM bitcells),        |     |
   |   |  INT8 weights in 2 slices + merge, block-32 INT8 activations as passive  |     |
   |   |  bottom-plate charge (no PWM), 11-b SAR (VTC fine, K=4 charge pooling),  |     |
   |   |  LVT logic, 16-fin share switch; skewed just-in-time single-bank rewrite |     |
   |   +--------------------------------------------------------------------------+     |
   |  scheduler: continuous batching, decode-first, chunked prefill on each weight sweep,|
   |             2 micro-batch groups (attention of one overlaps tiles of the other)     |
   +-------------------------------------------------------------------------------------+
   Balance at the peak (per die): HBM 96.6k (binds) < compute 98.5k < attention 105.0k tok/s
```

## Node choices and why

| node | choice | why (notes / literature / this run) |
|---|---|---|
| N1 system | `stream_single` (weights streamed, one bank, skewed JIT rewrite) **+ TP-8 group + continuous batching** | The streaming rule is the user's (ARCH_METRIC). TP-8 is ARCH_METRIC-legal: tok/s is "per iso-area die the system uses", d2d is a priced knob, and Sohu's conditions use 8. All-reduce: 2 per layer at 16 b, 0.92 MB/token, 3.7 µJ/token (`n1.tp_d2d`), 2.2M tok/s link ceiling (not binding). 8 KV heads over 8 dies = one head per die, so attention stays local. The gain past 8 dies is under 0.1 % (16: 96,608; 32: 96,651), so 8. CB law and spill: N1.md (Sarathi-Serve, NanoFlow, DeepSeek-V3 two-micro-batch overlap via LIT_SYSTEMS). 27l1: E_eff = E_read + E_prog/R, and here R = V = 20,484, exposure 2.4e-6. |
| N2 domain | `hybrid_msb_digital` at k_dig = 0 (passive charge rail) | Survives the joint search. Current-mode, translinear-log and time-domain arrays reach ≤ 42k even lockstep (SEARCH counterfactuals), and the log-domain hypothesis is not competitive at ASAP7. |
| N3 cell | `gaincell_mom_caps_mom6` | Constraint 2 (no SRAM bitcells). Linear MOM caps. SRAM6T would add 26 % TOPS/W at equal tok/s (rule-pruned). |
| N4 format | `w8a8_lead_norot` (INT8 2-slice + merge, block-32 A8, LSB unit 0.25x) | Every W<8, FP, LNS and MX format died at the lossless gate. W8 is the format the KV8 roofline is computed with. 27n1 bit-normalized TOPS/W is 1,317 (20.58 × 64). |
| N5 array | `blk_diff_r8_c256_s4` | The node lead. 27l4: a scale block shorter than R forces R/g conversions, so R8 matches block-32 activations with no extra conversions. |
| N6 readout | `sar_vtc_pool` at 11 b | p08's pick on the Pareto front: the same tok/s as the residue-amp SAR, more TOPS/W. 27h1: above ~5 b the column ADC dominates macro energy (converters are 45 of 186 pJ per pass here), and K = 4 charge pooling divides the fixed costs (27l3). |
| N7 dataflow | `lean_int8_rail`, h = 2, **buffer 96 MB**, mcast 16 | Buffer size is the lever that makes CB pay: spill goes from 8.40 to 0.44 MB/token. The optimum sits on the HBM/compute knife edge: 88 MB gives 95,550 and 104 MB turns compute-bound at 91,570. |
| N8 quality | `lv_protect_tensor` (G43 + one FFN-down tensor digital, 6 dB) | The only lever that lets a W8 tile pass at this energy. The gate margin is +0.04 dB (see risks). Fallbacks at the same tok/s: r01's tile, +0.26 dB, 16.36 TOPS/W. The Hadamard tile, whose credit the proxy measured, reaches 92.7k (−4 %). |
| N9 circuits | `vt_lvt_logic`, share_fins 16, v_exc_frac 0.43 | p08's bundle. At the HBM roofline, energy per token is what keeps the die under 1 W/mm² (see risks), so the lower-energy bundle wins the tie. |
| N10 | `none` | No wildcard helps: every one loses 3–70 % (SEARCH). |

Constraint 3 (no PWM): honored. Constraint 1 (lightweight tile): honored. The maximalist moves
area **out of** tiles (63 → 33 mm²) and into buffer, because the tile is not the bottleneck.

## Why it beats the search winner, and what it cannot beat

The search found the king metric pinned at a system ceiling (B = KV limit, decode HBM-bound,
prefill rail-bound) and stopped there, because the core's schedule and single die define that
ceiling. The maximalist moves the ceiling itself:

- KV capacity: 368 → 4,373 streams for the group, via TP weight sharding.
- HBM idle during prefill: removed by continuous batching.
- The spill that continuous batching creates: removed by the buffer.

What is left is the hard roofline, BW_HBM / KV bytes per token = 106.7k tok/s/die. The design
sits at 90 % of it, 77 % at η = 0.85. Every remaining lever is outside the rules or outside physics:

- **KV4** would roughly double the ceiling. It is QServe's acceptable tier, not lossless, and the
  guard rejects it.
- **More HBM per die** is a knob, not a design choice. At hbm x2 the design reaches 134.5k and
  becomes power-capped.
- **KV on die** gives fewer than 10 streams per die (N1 `kv_on_die`), and every request moves
  4.9 GB.
- **Analog attention** is out of scope (AGENTS.md).

So the maximalist's honest claim is that the IMC die gets 1.79x the search winner's
system-limited number, but only 1.11–1.16x the literature digital baseline given the same
system. On the king metric, this workload is a memory-system benchmark.

## Sensitivity (same design, re-optimized buffer)

| case | tok/s/die | TOPS/W | binding |
|---|---|---|---|
| SRAM access 30 / 45 fJ/bit (from 15) | 96,560 / 96,560 | 20.58 / 20.57 | hbm (multicast amortizes it) |
| HBM x0.5 | 48,500 | 23.03 | hbm |
| HBM x2 | 134,500 | 20.42 | power cap |
| per-stream floor 50 tok/s | 95,140 | 20.56 | hbm |
| die 50 mm² | 48,750 | 22.60 | compute |
| die 400 mm² | 98,920 | 15.85 | hbm (per mm² falls 3.9x) |
| gate one step tighter (45.8 dB; `sens_gate_tighter` design + levers) | 39,570 | 6.01 | **power cap** |
| bare G43, no lever (`g43_lossless` + levers) | 47,610 | 7.23 | power cap |
| gate one step looser (`sens_gate_looser`, HWA 46,000 GPU-h) | 67,620 | 10.26 | power cap |

The gate rows matter most. Once the HBM ceiling is lifted, **the power cap becomes the next
constraint, so tile energy turns into tok/s**. The roofline needs at most 100 W ÷ 96.6k =
1.04 mJ/token of die energy. p08's tile spends 0.74 mJ and r01's 0.93 mJ, but the tiles that pass
a tighter gate spend 2.5 mJ.

## Risks

1. **The gate margin is +0.04 dB** and rests on the protect-tensor 6 dB credit, measured
   unrotated on one proxy tensor. The harness cannot yet emulate block-32 activations or
   per-tensor protection. If the margin fails, r01's tile (+0.26 dB) keeps 96.6k at 16.36
   TOPS/W. If the protect credit fails altogether, the bare-G43 tiles are power-capped at 47.6k.
2. **The CB law is a steady-state η = 1 ceiling.** N7's η = 0.85 gives 82k. An event-driven
   scheduler simulation has not been run. Real HBM sustains about 85–90 % of peak, which stacks
   with η, so the plausible band is roughly 70–97k. The baseline carries the same law, so its
   ratio is safer than its absolute value.
3. **Three resources balanced within 2–9 %** (HBM 96.6k, compute 98.5k, attention 105.0k). A
   tile pass 2 % slower than 5.24 ns at 0.55 V moves the bind to compute.
4. **Buffer physics.** The buffer energy law is size-independent (15 fJ/bit + tile-pitch wire,
   multicast 16), and the spill law is N1's analytic loop-order law. A 96 MB SRAM 28 mm² away
   from the tiles has longer global wires than the model charges.
5. **Weight-chunk lifetime is V·t_pass ≈ 107 µs.** The 4T gain-cell bit must hold that long at
   0.55 V and 25 °C, and corners are not in the metric. N1 lists the refreshed gain bit as
   unaffected, but no ASAP7 retention simulation exists for this cell.
6. **The system is 8 dies plus 8 HBM stacks.** Per-die normalization makes it fair, but
   ARCH_METRIC's default knob is `system_dies = 1`. The metric owner has to accept a TP group as
   a design choice. The baseline gets the identical group.
7. **The core does not score this design.** `cli.py` / `search.py --score maximalist.json` give
   30.4k (core) and 46.6k (joint) lockstep, single-die. The levers live in
   `designs/maximalist.py` until the core adopts N1's CB law, the TP d2d charge and the spill law.

## What Verilog-A, then SPICE, must prove first

Ordered by what moves the number:

1. **Verilog-A (VerA → ESPice): one R8×C256 differential charge-rail column slice.** Gain-cell
   bit model, 2-slice merge, passive block-32 input charge, VTC-pool 11-b SAR (K = 4 pooling).
   It must show a class-weighted SNR of at least 37.05 dB with real margin (≥ +0.5 dB, against
   +0.04 dB projected) and a pass of at most 5.24 ns at 0.55 V. Below that, compute binds before
   the HBM.
2. **ASAP7 SPICE (BSIM-CMG tt, 0.55 V) of the gain-cell storage node and its write path.**
   Retention of at least 107 µs at half-LSB droop (V·t_pass), and a row write inside t_load so
   the 2.4e-6 exposure holds.
3. **ASAP7 SPICE of the VTC-pool SAR comparator and the K = 4 pooling switch at 0.55 V.** Noise,
   metastability and energy against the 45 pJ-per-pass converter budget. That budget sets the
   tile energy, and tile energy decides whether the power cap binds (see sensitivity).
4. **Not circuit, but decisive:** an event-driven CB + TP-8 scheduler simulation (paged KV, two
   micro-batch groups, real HBM efficiency) to replace η, and the quality harness with block-32
   activations and per-tensor protection (SEARCH next step 1).

## Notes used

- **27a2** (analog wins where the workload is bandwidth-bound and low-precision; I = B/b_w; KV
  is the far-left roofline): the HBM-KV ceiling argument.
- **27l1** (E_eff = E_read + E_prog/R): CB raises R to V = 20k.
- **27a3** (the advantage is not moving weights): a streamed design's win is set by how far R is
  pushed.
- **27h1** (the column ADC dominates above ~5 b): the converter share of tile energy.
- **27l4** (scale block vs R): R8 with block-32 activations.
- **27n1**: bit-normalized TOPS/W.
- **27h9** (PWM costs 2^b steps): constraint 3 is kept.
- Literature through N1/N7: Sarathi-Serve (chunked prefill), NanoFlow (intra-device nano-batch
  overlap), vLLM (paged KV), Megatron-style TP all-reduce.
