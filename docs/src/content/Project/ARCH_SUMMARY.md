# Architecture summary

2026-10-07. A one-page summary. The spec is `ARCH_CHOSEN.md`, the decision record
`ArchResearch/DECISION.md` and the metric `ARCH_METRIC.md`. Labels: **M** measured (SPICE,
RTL simulation, quality harness), **D** derived (a law on measured parameters), **P** projected
(`arch_eval` model or literature). Scores are tok/s per die / TOPS/W / tok/W / tok/J.

### Architecture

Photo:

![IMC accelerator architecture](../../../architecture/imc_architecture.png)

`docs/architecture/imc_architecture.pdf` is the full drill-down: every block drawn with its
transistor circuit inside, from `analog/imc_tile/netlist/imc_tile.py` through cktImg.
Regenerate it with `docs/architecture/gen_architecture.py`.

A streaming, charge-domain IMC die. Weights stream from HBM into analog tiles just ahead of the
activations that use them. Each tile multiplies by passive charge sharing and reads out once per
weight column. A digital rail does attention, softmax and the KV cache.

Blocks:

| # | Block | Implementation | Key numbers |
|---|---|---|---|
| B1 | Weight store | Gain cell holding W8 as two 4-b slices of charge on MOM capacitors (MSB 1 fF, LSB 0.25 fF units), differential | 8 rows × 256 columns × 2 slices per tile; write 0.70 fJ/bit; retention ≥ 1.32 µs (P). At transistor level it needs a buffered output: 5 T per bit, not 3 (M) |
| B2 | Row drive | BS6H: bit-serial \|x\| planes on 0/V rails, 6-tick (0.849 ns) slots, 7 slots per word | Settling 0.067 % at the share edge (M); needs R_PDN ≤ 0.4 Ω per tile; 108 pJ per pass (D) |
| B3 | Column | Bootstrapped share switch, C_col 56 fF, two ping-pong accumulation banks, 1:16 MSB/LSB charge merge on the idle bank | Merge hidden under the next pass; 88 pF of bank caps per tile (D, not yet priced in the score) |
| B4 | Column ADC | E-trim noise-aware 12-b SAR: 6 decisions on a fast double-tail (1.82 mV), a redundant step, then 7 on a quiet tail-starved double-tail (0.60 mV); 3 columns per converter; the MSB bank is the C-DAC | 1.61 ns and 277 fJ per conversion (D on M); 86 converters per tile |
| B5 | Reference | Class-A buffered C-DAC reference, shared per tile | ≤ 3.7 µV droop per conversion (spec; the Verilog-A bench shows 130, open) |
| B6 | Calibration and dequant | Per-column affine calibration, then the block-8 scale multiply (5-bit-mantissa scale bytes) | 0.11 dB format cost (D); bit-exact RTL (M) |
| B7 | Activation buffer and NoC | 16 MB SRAM, TDM NoC with multicast 16 | 4.7 mm² |
| B8 | Digital rail | Q·Kᵀ and P·V lanes, online softmax, RMSNorm/RoPE/SwiGLU, Hadamard (FWHT) rotation, KV pack/unpack. KV 4 b, plus a 4-b residual for 8 sink and 120 recent tokens | 14.7 TMAC/s; KV quality +0.21 % PPL (M, proxy) |
| B9 | HBM | One HBM3 stack per 100 mm² die | 819 GB/s, 24 GB, 13 mm² PHY |
| B10 | Accumulator chain | Output-stationary 24-b partial-sum chain down the K-adjacent tiles | Exact; one hop per pass |
| — | Controller | `digital/imc_driver`: systolic-style sequencer, weight stager, chain, requant | Pass 5.96 ns on the RTL (M); 25 cases bit-exact (M) |

One pass is 2,048 MACs (8 × 256, both slices) in 5.94 ns, drive-bound (D; RTL 5.96 ns, M).

Justification:

- **Stream everything (user constraint).** Weights and activations both come from HBM, and each
  weight write pays off over every activation it meets before it is replaced. That makes the
  write path (B1) and reuse the first-order costs.
- **Charge domain, passive share.** The multiply-accumulate is charge sharing: no static current
  and 3.66 fJ per MAC in the array (P). Time-domain/PWM inputs need 2ᵇ steps per pass, and
  current-mode unary packets are dominated (N2_r2: 60.1k, below the lead).
- **Gain cell, no SRAM (user constraint).** Weights are analog charge. The 3T gain cell (N3_r2)
  cut transistors per weight by 30 %. The transistor run then showed the bottom-plate kick needs a
  buffered output (M).
- **W8 as two slices, merged in charge.** W8A8 with Hadamard rotation is the lossless quality tier
  (G1). Merging the slices 1:16 in charge before converting halves the conversions (one per weight
  column, not one per slice).
- **BS6H drive.** The four-level drive cannot settle: 0.64 % against 0.1 % (M), and buffers stiff
  enough would draw about 140 W per die (D). Bit-serial 0/V rails settle. 6-tick slots, with the
  merge hidden on the idle bank, bring the word to 5.94 ns at no extra area or energy.
- **E-trim SAR.** The measured StrongARM noise (4.05 mV) fails the accuracy gate by 7.9 dB.
  Resizing it to about 1 mV costs 16× the size and about 40 % of tok/s. Splitting the search
  into fast and quiet decisions meets the gate at 1.09× the converter energy.
- **3 columns per converter.** With 4 the conversion binds the pass (7.36 ns). With 3 the drive
  binds (5.94 ns): +8.6 to +16 % tok/s and +3 % TOPS/W for 1.2k µm² per tile (P).
- **Block-8 operands.** Per-token activation scaling fails the accuracy gate by 12 dB on this tile.
  Rescaling each 8-row block fixes it at 0.11 dB.
- **Class-A reference, not a bandgap.** ASAP7 has no BJT or resistor models to sign off a bandgap.
- **Accumulator chain (T2).** It is exact, removes partial-sum traffic from the buffer and gives
  +4.9 % TOPS/W (P).
- **KV 4/8 and 16 MB.** The compressed KV cache raises the batch at the KV limit (more streams
  share each weight fetch). The buffer hides the prefill activation spill.

**Where it stands (P).** With the same weight and KV formats, the analog die ties the systolic
baseline on tok/s (1.01× ARCH, 1.00× Sohu, `cli.py`) and leads on TOPS/W (1.04×). The decision
record's corrected frame gives 1.05× (ARCH) and 1.16× (Sohu) against the synthesized PE, and
0.80× / 0.84× against the literature PE. Decode is HBM-bound on both machines
(`docs/architecture/roofline.pdf`). The tile is correct at the logic level (M) and meets the
accuracy gate at TT (+0.84 dB, D on M), but the transistor-level MAC residual (0.72 % vs 0.2 %) and
converter INL (6.8 vs 4 LSB) still fail (M).

### Tradeoffs between blocks (The pareto set)

**Design-level points** (ARCH conditions; joint frame unless marked, all P):

| Design | tok/s | TOPS/W | tok/W | tok/J | Where it sits |
|---|---|---|---|---|---|
| Round-1 pick, as scored | 67,922 | 15.56 | 825 | 834 | Rested on the four-level drive, which failed |
| Round-1 pick, judge-corrected | 48,700 | 9.3 | 551 | 550 | Pessimistic converter and corner penalties |
| **Upgraded tile, bank caps in shared metal** | **66,565** | 11.60 | | | BS6H, E-trim, 3 columns per converter |
| **Upgraded tile, bank caps priced** | **49,168** | **13.21** | | | The same, with 18.4k µm² of caps per tile |
| r2_A5 (2 b per slot on two extra supply nets) | 68,488 | 10.47 | 611 | 625 | Highest tok/s; needs mid-rail nets ≤ 1.3 Ω |
| r2_A2 (bottom-plate sampled, constant charge) | 64,188 | 9.78 | 559 | 571 | No new nets; low TOPS/W |
| r2_A1 (residue-amp SAR on 4 pooled tiles) | 60,835 | 11.22 | 629 | 643 | Fewer, faster converters |
| Robust tile + KV 4/8, corrected | 47,500 | 6.9 | 393 | 403 | Corners already closed |
| Search p08 (KV8, round-1 frame) | 52,157 | 16.38 | 767 | 945 | Balanced point |
| Search p22 (KV8, round-1 frame) | 34,976 | 27.17 | 1,069 | 1,115 | TOPS/W end: slow reference, 32 MB buffer |
| Systolic, lever-matched, synthesized PE | 46,398 | 10.61 | 600 | 968 | Baseline |
| Systolic, lever-matched, literature PE | 61,005 | 18.30 | 939 | 1,705 | Strongest baseline |

The upper-left of the front (tok/s) is set by the system ceiling: batch at the KV limit and decode
on HBM. Dozens of designs tie there, and moving along the front trades tok/s for TOPS/W through
the tile's converters, reference and logic voltage. The search's p01 → p22 walk gives up 35 % of
tok/s for 2.6× TOPS/W.

**Block-level tradeoffs** (what each knob buys and costs):

| Block | Options | Gain | Cost | Choice |
|---|---|---|---|---|
| Row drive | ml2 (2 b/slot) · bit-serial 7-tick · **BS6H** · BS6H-cc · cr2 (capacitor ratio) | cr2 is a faster word (3.96 ns with the merge hidden); ml2 5.66 ns | ml2 does not settle; cr2 +12 % area and G2 at 0.00 dB; cc doubles drive energy | BS6H (cc as the fallback) |
| Comparator | StrongARM · DT ×4 · **E-trim** · DT ×2 binary · FIA preamp · residue-amp SAR | More decisions on the quiet class → more margin | Energy ∝ 1/σ² (κ law): StrongARM ×16 → −40 % tok/s; FIA 2.5–4.9 ns per conversion; residue-amp 3.7× energy | E-trim (DT ×2 as fallback) |
| Converter share | 2 · **3** · 4 · 6 (pooled) | Fewer converters → less area and energy | Conversion binds the pass from 4 up | 3 |
| Bank caps | priced MOM · shared metal | Hidden merge (no merge slot) | 88 pF per tile; −26 % ARCH tok/s if they need their own area | Open: decided by layout |
| Gain cell | 3T · **buffered 5T** · round-1 cell | 3T: −30 % transistors | 3T gives 3.3 % share error (M) | Buffered, cost not yet priced |
| C_col / unit cap | 56 fF; cu 1.25–2.5 fF | Larger C: more kT/C margin, closes corners | Energy and area grow with C (cu 2.5 closes SS at −28 % tok/s) | 56 fF; SS closed with adaptive VDD |
| Weights | **W8 two-slice** · W4 | W4 halves HBM bytes and doubles KV room | Acceptable tier only, not lossless | W8 |
| KV cache | 16 · 8 · **4/8 sink+recent** | Batch 368 → 587 at the KV limit | +0.21 % PPL | 4/8 |
| Buffer | 2 · **16** · 32 MB | Hides prefill spill | Area from the unused margin | 16 MB |
| Reference | bandgap+LDO · **class-A** · reservoir | Reservoir and bandgap save energy | Bandgap cannot be signed off at ASAP7; reservoir costs tok/s | Class-A |

### Application where it can beat turn Decode from memory bound into Compute Bound

Decode is compute-bound when its arithmetic intensity passes the die's ridge point:
**1,230 ops per HBM byte** under ARCH (1,007 TOPS over 819 GB/s), 2,626 under Sohu. Plain decode
reaches 527 at the KV-limited batch of 736 and can never pass about 810 at any batch, because
every stream reads its own KV cache (D, `roofline.py`). An application turns decode compute-bound
by sharing each HBM byte across more tokens:

| Application | Mechanism | Crosses the ridge when (ARCH, D) |
|---|---|---|
| Speculative decoding, multi-token prediction | The big model verifies k drafted tokens per step: each weight and KV read serves k tokens | k ≥ 3: 1,580 ops/B at B = 736. The step becomes 33.6 ms of compute (26.1 ms of memory) for 3 tokens: 2.3× decode throughput |
| Parallel sampling, beam/tree search, agents sharing one system prompt | n streams share one prompt's KV, so it is read once per group, and more streams fit | n ≥ 4: 1,475 ops/B (B = 1,835) |
| Short-context, high-batch generation (classification-style outputs, short chat turns) | Less KV per stream, so weights dominate the bytes and the batch can grow | 256 tokens: B ≥ 1,578; 128 tokens: B ≥ 885; 64 tokens: B ≥ 726 |
| Small-KV models (MQA, MLA-class) | 8–16× fewer KV bytes per token | B ≥ 744 (MQA), B ≥ 666 (MLA-class) |
| Does not work: long context, batch 1, MoE | KV dominates (2,048 tokens: 172 ops/B); no reuse (2 ops/B); fewer tokens per expert's weights | — |

Under Sohu conditions (ridge 2,626, decode 348 at B = 1,000), speculative decoding needs k ≥ 8.

**Where the analog die then beats the systolic die.** Once decode is compute-bound, throughput is
the lower of the compute roof and the power roof (1 W/mm² × TOPS/W), and both machines sit near
their power roofs. The analog advantage becomes its TOPS/W ratio:
- 1.04× with the round-1 tile against the synthesized systolic PE (P);
- about 1.2× for the upgraded tile with its bank caps priced (13.21 against 10.61, P, from two different scoring frames);
- a loss (about 0.7×) against the literature systolic PE at 18.3 TOPS/W.

So these applications are where the analog tile can matter, and the energy per MAC (bottleneck 2
in `ARCH_CHOSEN.md` §10) decides whether it wins. The mechanisms themselves are digital and
compiler work (draft model, KV sharing, scheduler), outside the tile.
