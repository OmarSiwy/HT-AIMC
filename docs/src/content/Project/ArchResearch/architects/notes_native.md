# Architect: notes-native (KV 4/8 sink+recent on the Hadamard charge-rail tile)

2026-10-06. Architect panel, angle "notes-native and novel". Scored against `ARCH_METRIC.md`
(tok/s per 100 mm² die > TOPS/W > tok/W > tok/J, Llama-3-8B, 512 + 128).

Files (all mine):

- design: `scripts/compiler/metrics/arch_eval/designs/notes_native.json`
- cost model, scorer, quality and entropy measurements: `designs/notes_native.py`
  (`--selfcheck` PASS, `--quality`, `--entropy`, no flag = score)
- outputs: `designs/notes_native.score.json` (projected), `designs/notes_native.quality.json` (measured)

**Labels.** **M** = measured here (SmolLM2-135M proxy, numpy). **D** = derived (node laws on measured
parameters). **P** = projected (literature or law only). Every tok/s, TOPS/W, tok/W and tok/J below
is **P**: the search's joint-frame evaluator plus my memory-format hook. The KV-format quality numbers
are **M** on the proxy. Nothing here is SPICE, synthesis or silicon.

## Bottom line

| design | tok/s/die | TOPS/W | tok/W | tok/J | B | label |
|---|---|---|---|---|---|---|
| **notes_native** (pick: KV 4/8, sink 8 + recent 120) | **69,689** | **15.66** | **829.5** | **887.5** | 587 | P |
| notes_native, tight window (sink 4 + recent 28) | 76,017 | 15.73 | 854.7 | 916.1 | 677 | P |
| search winner r01 (KV8) | 53,864 | 10.45 | 546.7 | 689.7 | 368 | P |
| search's quality-safe pick (`cf_n8_quality__lv_hadamard`, KV8) | 51,026 | 14.66 | 708.0 | 777.8 | 368 | P |
| **notes_native / r01** | **1.29x** | **1.50x** | **1.52x** | **1.29x** | | |

The design beats the search's winner on all four metrics, on a tile whose quality the search's
harness already measured (the Hadamard path). The tok/s gain does not come from the tile. It comes
from moving the system ceiling that pins every search design at 53,864: B ≤ KV capacity. **The KV
format is a symmetric lever** (N8 fairness rule: the baseline gets the candidate's KV width), so the
claim that matters is the comparison with a baseline that carries the same KV format:

| systolic baseline, same KV 4/8 format | tok/s/die | TOPS/W | tok/W | tok/J | notes_native / it |
|---|---|---|---|---|---|
| W8, PE from ppa.json (D) | 46,398 | 10.61 | 600.1 | 967.7 | 1.50x / 1.48x / 1.38x / 0.92x |
| W8, literature PE (P, the deferred-synthesis frame) | 61,005 | 18.30 | 938.5 | 1,704.5 | **1.14x** / 0.86x / 0.88x / 0.52x |
| W4, literature PE (P, strongest; W4 fails G1 for the IMC) | 68,846 | 18.49 | 992.3 | 1,883.5 | 1.01x / 0.85x / 0.84x / 0.47x |
| at KV8 for reference: W8 ppa / W8 LIT / W4 LIT | 41,356 / 46,401 / 53,832 | | | | |

For the same tile, the lead over the fair W8 baseline grows when the format is applied to both: from
1.10x to 1.14x with literature PE, and from 1.23x to 1.50x with ppa PE. The reason is that the binding
constraint moves. At KV8, B is capacity-capped and prefill hides the tile's density. At KV 4/8, B rises
1.6x and prefill becomes tile-compute-bound for both dies, so the IMC tile's MAC density, which is its
real advantage, counts on the king metric. Against the strongest baseline (W4, literature PE) it is a tie (1.01x), the same
verdict the search reached at KV8. TOPS/W is won only against the synthesized PE, and tok/J is lost
in every frame, as in the search.

Sohu condition set (FP8 KV is part of the conditions, so my KV format is **not** applied there):
the design's tile at KV8 scores 101,613 / 13.86 / 90.7 / 112.2. That is 1.62x the FP8 baseline with
ppa PE (62,571) and 1.18x with literature PE (86,229), both P. The search's Sohu-retuned winner
(105,709) is 4 % higher. I did not re-tune for Sohu.

## What is new here, and why the grid could not express it

The search grid has `kv_bits ∈ {4, 8, 16}` and prunes KV4 as "acceptable tier (QServe), not lossless".
That is correct for uniform KV4: I measure **+28.8 % proxy PPL** for plain per-token KV4 and **+4.7 %**
with a Hadamard rotation (M). The format the grid cannot express is a **position-tiered KV cache**,
taken from the notes and the paper and moved from the analog domain into a digital number format:

1. **27l10** (*Analog Attention Requires Solving Noise Sensitivity That Is Non-Uniform Across the
   Cache*). Zero-mean noise on stored keys inflates every competing softmax term by e^{σ²}, so the
   dominant keys (sink and recent) lose most, and protecting the fixed set {1..m} ∪ {t−r+1..t} by
   index alone recovers near-clean PPL (feng2026selective: m = 8, k = 128). The note's argument does not
   depend on the noise being analog: KV quantization error is the same zero-mean score perturbation.
2. **Paper `sec_attention.tex`** (Resident-Attention Engine). The paper co-designs 4/4/8-bit K/V/score
   quantization with per-head scales and protects m = 8 sinks + 120 recent tokens digitally. Its KV
   tiles are analog gain-cell arrays, which AGENTS.md scopes out ("don't add analog attention blocks").
   I keep the paper's quantizer and protection policy and drop the analog KV tile: the cache stays
   digital in HBM.
3. **27l2** (*The KV Cache, Not the Weight Matrices, Is the Part of Attention Analog Is Best Placed to
   Absorb*). I_KV = 1 for any B, so KV bytes, not weights, set B and decode bandwidth. That is exactly
   the ceiling the search hit: at KV8, 15 GB of KV caps B at 368 and decode KV traffic (13.9 GB per
   step) exceeds the weight stream (8 GB).
4. **Digital Design, Number Formats / Fixed-Point Format Narrowing.** The recent window is stored as
   the 4 b bulk code plus a 4 b residual plane (the 4 b code of the bulk quantizer's error at 1/15 of
   its LSB). When a token leaves the window, the residual plane is dropped, which is a narrowing with a
   bounded rounding error and no requantization pass. The bulk plane is written once, at token creation.
5. **QuaRot rotation** (LIT_QUALITY §1), reused from the tile's own `lv_hadamard` lever. One randomized
   Hadamard per KV head (q·k and o = p·V·Hᵀ are invariant) spreads K/V outliers before the 4 b
   quantizer. A single compiler transform now serves two purposes: the tile's 4.5 dB SNR credit and
   the KV format.

**Measured on the SmolLM2-135M proxy** (`notes_native.quality.json`, 4 × 512-token windows, 2,044
scored tokens, seed 0, weights exact so that only the KV path is perturbed; M):

| KV format | ΔPPL | ± se | top-1 agree |
|---|---|---|---|
| KV8 per token-head (the search's lossless `lv_kv8`) | +0.20 % | 0.09 | 98.6 % |
| KV4 per token-head | +28.8 % | 2.4 | 73.1 % |
| KV4 + Hadamard | +4.74 % | 0.99 | 86.4 % |
| KV 4/8, sink 8 + recent 120, no rotation | +0.71 % | 0.35 | 95.2 % |
| **KV 4/8, sink 8 + recent 120, Hadamard (the pick)** | **+0.21 %** | 0.18 | 97.8 % |
| KV 4/8, sink 4 + recent 28, Hadamard (tight variant) | +0.30 % | 0.29 | 95.7 % |
| KV 3/8, sink 8 + recent 120, Hadamard | +1.19 % | 0.46 | 93.2 % |
| combined with the tile's error (Hadamard W8A8, R8, 39.8 dB): KV16 | +0.58 % | 0.32 | 94.1 % |
| combined with the tile's error: KV 4/8 sink 8 + recent 120 | **+1.04 %** | 0.36 | 93.2 % |

Neither lever is enough alone. Rotation alone leaves +4.7 %, and protection alone leaves +0.71 %.
Together they match KV8 (+0.21 % against +0.20 %), so the format earns the lossless tier on the proxy
at **5.01 effective bits** instead of 8.

**Loud caveat from the combined run.** The tile-only row reproduces the search's spot-check exactly
(+0.58 %). With the KV format added, the total is **+1.04 ± 0.36 %**: the KV format adds +0.46 % on
top of the tile's error, about twice its KV-only cost (+0.21 %). One seed cannot tell an interaction
apart from noise (the unpaired se is about 0.3 %). The total sits at the 1 % G2 budget edge, but that
budget applies to the analog increment and the KV cost belongs to the G1 format tier. The case for
the tier holds on the proxy, with no margin to spare. A KV8 + tile run and 5 seeds are the next
measurement.

**Coverage caveat (read this before trusting the tier).** In a teacher-forced 512-token window the
recent set covers more of each query's context than in the target workload. Counted over (query, key)
pairs, the pick puts 56 % of pairs on 4 b codes on the proxy, against about 78 % at Llama decode
(mean context 576). The tight variant (sink 4 + recent 28) puts 87.5 % of pairs on 4 b and still
measures +0.30 ± 0.29 %, so the target's 78 % sits between two measured points that both pass. That is
a bracket on one 135M proxy with one seed, not a Llama-3-8B result.

## Block diagram (text)

```
HBM3 stack (819 GB/s, 24 GB): W8 weights (8.0 GB), KV cache 4/8 (~15 GB -> B = 587 streams x 640 tok)
   |  bulk plane: 4 b K,V codes + fp16 scale per (token, KV head)      [written once at creation]
   |  ring plane: 4 b residual codes for sink 8 + recent 120 tokens    [overwritten as the window slides]
   v
HBM PHY 13 mm2 --- TDM NoC (mcast 16) --- 8 MB activation buffer
   |                                   |
   |  weights (just-in-time rewrite)   |  activations (INT8, per-token scale, Hadamard-rotated)
   v                                   v
3,401 IMC tiles, 64.4 mm2 (each 18,942 um2):
   gain-cell (4T) bits on MOM6 caps, 8 rows x 256 differential cols x 2 slices,
   all input planes passive charge on rail bottom plates (charge_rail),
   128 shared SAR ADCs (12 b, direct, pooled k4), bandgap+LDO reference,
   t_pass 6.3 ns, 124 fJ/MAC (converters 63, buffer 22, recombination 11, ref 10, colsw 8, array 8)
   |
   v  INT outputs, digital recombination, requant
Digital rail 4.6 mm2: Q.K^T and P.V lanes (q8 x k4 for the bulk, q8 x k8 for the protected 22 %),
   online softmax (base-2 ROM exp), RMSNorm/RoPE/SwiGLU, Hadamard on q, k, v, o
```

Peak point: VDD 0.55 V, full clock, B = 587 (the KV-capacity limit), 38.2 tok/s per stream (floor 20),
67.5 W die + 16.5 W HBM. Prefill is bound by tile compute and decode by HBM.

## Node choices and justification

The tile is the search's measured quality-safe stack (`cf_n8_quality__lv_hadamard`). I re-ran the
search's coordinate descent (`search.descend`, 2 passes, n8 frozen to `lv_hadamard` and KV frozen to
the 4/8 format) under the new regime. It returned the same tile; the only move it found was the
`tdm_noc` default rail headroom, +0.8 % tok/s for −13 % TOPS/W. I did not take that move, because 0.8 %
is below the model's resolution (the search's p08 argument).

| node | choice | why (notes / literature) |
|---|---|---|
| N1 | `stream_single`, KV **4/8 sink+recent** (new) | User rule: weights stream (ARCH_METRIC). 27l1: a streamed weight is paid back over its reuse R = B, so B is the throughput lever. 27l2: the KV cache, not the weights, caps B. 27l10 + the paper: the position-tiered format. |
| N2 | `hybrid_msb_digital`, k_dig 0 (= charge rail) | 27i1 (*Charge-Domain Compute Wins on Linearity Because a Capacitor Ratio Is a Lithographic Quantity*), 27i3 (no DC current). Every other domain lost by 21-99 % in the search's counterfactuals. |
| N3 | `gaincell_mom_caps_mom6` | ARCH_METRIC constraint 2 (no SRAM bitcells). 27i6 (*Gain Cells Give an Analog Weight at DRAM Density Without an eNVM Module*). Retention is not an issue because weights are rewritten every pass. |
| N4 | `w8a8_lead_tokact` (INT8, two slices, per-token activations, Hadamard) | N8 G1: W8A8 is the lossless tier, and W4 fails on the proxy. Per-token activations are what the harness measures (quality_spotcheck: +0.06 % format). 27l4: a scale block shorter than R forces extra conversions; per-token scales avoid that. |
| N5 | `blk_diff_r8_c256_s4` | 27c1 (signed weights stored differentially). 27h6: ADC bits = log2 N + w + x bits, so R = 8 keeps the converter at 12 b. 27g2: kT/C sets the cap floor (thermal 43.3 dB). |
| N6 | `sar_direct_pool_k4`, 12 b | 27h1: the column ADC dominates once resolution passes 5 b. It is 63 of 124 fJ/MAC here, so the converter is pooled. 27h4: sharing is set by the column pitch. |
| N7 | `tdm_noc`, rail headroom 2.0, mcast 16 | DD Network-on-Chip (TDM circuit switching drops the VC buffers). DD Multipliers: lane area ∝ b_q·b_kv, so 4 b KV lanes are about half an 8 b lane, priced in my hook. |
| N8 | `lv_hadamard` (G43 gate, 4.5 dB credit) | The only lever the harness measured directly: format +0.06 %, noise at 39.8 dB +0.58 % (quality_spotcheck, M). The winner's `lv_protect_tensor` credit is unconfirmed. |
| N9 | `ref_bandgap_ldo` | Search Hadamard-path optimum. 27l5: the digital wrapper is where much of the system energy goes. The reference is 10 fJ/MAC. |
| N10 | none | The search's wildcards (DPS-48, Strassen, analog psum, stack3d) all lost 10-26 %. |

## Ideas from the notes I tried and dropped (honest negatives)

- **Analog KV tiles** (paper §Resident-Attention, 27l2, 27l9 CAM prefilter). These are the most
  notes-native move, but AGENTS.md scopes them out, and the search's `cam_topk_kv` is N10-infeasible.
  I took the paper's KV quantizer and protection policy and left out its analog KV tile.
- **Entropy-coded weight stream** (Huffman INT8 codes, decoded at the PHY). Measured on the proxy
  (`--entropy`, M): per-channel INT8 codes carry 7.24 b/weight (Huffman), and 7.33 b after the
  Hadamard rotation the tile needs. Rotation makes weights more Gaussian and less compressible. That
  is 8.4 % fewer bytes, worth **+1.7 % tok/s** (70,888 against 69,689, P) for a projected 1.5 mm²,
  1 pJ/B decoder. The gain is below model resolution, so I did not include it. Llama-3-8B may have
  heavier tails and compress more (P, unmeasured).
- **KV3 bulk.** +1.19 ± 0.46 % (M) is outside the KV8-equivalent band, so it is not taken.
- **Log-domain tile (ARCH_METRIC hypothesis 5).** The search's counterfactuals put it at ≤ 5.9k
  tok/s. The notes (27g4, 28m3: analog energy for N bits of SNR grows as 2^{2N}) give no reason to
  revisit it at this gate.

## Why it beats the search's winner on tok/s per die

r01 and every search design sit at 53,864 because B = 368 (KV8 fills 15 GB) and decode is HBM-bound.
The KV 4/8 format stores 5.01 effective bits per element (4 + 0.125 scale + 4 × 128/576.5 residual),
so B = 587. Decode KV traffic per step is about constant at the capacity limit (B·kvb is fixed), while
1.6x more streams share each weight sweep, and decode tok/s rises 1.6x. Prefill then moves from
attention-bound (r01) to compute-bound, so tile density starts to matter. That is why r01's denser tile
with the same KV format would score 75,247 (P). I do not pick it, because its protect-tensor credit is
unmeasured. The tight variant (sink 4 + recent 28) reaches 76,017 on the safe tile, and I list it as
the next step once Llama-scale quality is measured.

## Risks

1. **Proxy-to-target KV quality.** Combined with the tile's noise the total is +1.04 %, on the edge.
   One seed, 135M parameters, 512-token context. Llama-3-8B
   (GQA 4:1, dh 128, longer contexts under the Sohu set) can behave differently. KV8 itself costs
   +0.20 % here, so the band is small. KVQuant/KIVI/QuaRot-class literature supports KV4-class
   near-lossless results with rotation or outlier handling (P).
2. **The win over the strongest baseline is a tie** (1.01x against W4 with literature PE). The IMC's
   case rests on the W8 baseline (1.14x literature PE, 1.50x ppa PE) and on the deferred systolic
   synthesis, which decides the PE frame.
3. **The gate margin is +0.05 dB** (inherited from the Hadamard tile). Every search optimum sits on the
   gate edge, and the tighter end of N8's band makes the tile infeasible.
4. **Rail model.** My lane-mix hook prices 22 % of attention on 8 b lanes by area. The 2-plane KV
   read for the window (bulk plus residual from two HBM regions) is charged as bytes, not as extra
   access granularity or paging overhead.
5. **Lockstep schedule.** Continuous batching (not modeled) helps both dies. Sink/recent bookkeeping
   is per-stream index math, with no runtime predictor (27l10).
6. **The KV format is outside the search's lossless list.** A Scorer with `kv_min=8` prunes this
   design. My scorer lifts that guard only for this format, on the measured evidence above. N8 has to
   adopt the format (`lv_kv48_sinkrecent`) for the search to agree.

## What Verilog-A, then SPICE, must prove first

The new part of this design is digital (KV format and rail lanes). The analog risk sits in the
inherited tile, at a +0.05 dB margin, so the ladder starts there.

1. **Verilog-A (VerA → ESPice): the R8 × C256 differential charge-rail column with the shared 12 b
   SAR.** Prove the passive charge-share MAC, the two-slice merge and the pooled-k4 SAR timing
   (t_word 5.7 ns, t_conv 6.3 ns at clk_frac 1, VDD 0.55 V), and that the end-to-end column SNR is at
   least 39.8 dB (the G43 target after the Hadamard credit) with the n5 parts budget (thermal 43.3,
   mismatch 46.0, ADC 43.3, ref droop 54.0 dB). Self-checking testbench: random INT8 vectors against
   the bit-exact golden dot product (`scripts/golden`), with PASS/FAIL on SNR ≥ 39.8 dB.
2. **ASAP7 SPICE (BSIM-CMG, tt/ff/ss): the gain-cell + MOM6 unit and the column switch at 0.55 V.**
   Prove kT/C plus charge injection and the gain-cell read under bottom-plate drive. These are the
   terms within 0.05 dB of the gate, so measure them before any layout.
3. **SPICE: the 12 b SAR's comparator noise and the bandgap+LDO reference droop** under 128
   simultaneous conversions. The ref-droop term (54 dB) and the converter energy (63 fJ/MAC, half the
   tile) are the energy-metric risks.
4. **RTL (outside the analog ladder, before the systolic synthesis): the rail's q8 × k4/k8 attention
   lane with residual-plane dequant**, so that the area ratio my hook assumes (DD Multipliers law) is
   measured, not projected.
5. **Llama-scale KV check.** `forward_kv` runs on any `quality.Model(path)`. A Llama-3-8B GGUF at
   2,048 context with 5 seeds is the test to run before the format is credited outside the proxy. The
   numpy harness holds fp32 weights (about 32 GB for 8B), so that run has to wait for a machine with
   enough RAM, or for a layer-streamed harness.
