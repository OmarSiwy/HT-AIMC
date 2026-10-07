# imc_tile: Verilog-A verification of the chosen IMC tile

2026-10-06. This block checks the round-1 pick (`docs/src/content/Project/ARCH_CHOSEN.md`) with the
round-2 ASAP7 measurements (`ArchResearch/nodes/N2_r2, N3_r2, N5_r2, N6_r2, N9_r2`). It covers B1 to B6
and B10. A digital driver (`digital/imc_driver`) runs the tiles the way a weight-stationary systolic
array is run, on the same jobs as the systolic reference (`digital/sysreference`).

**Labels.** M = measured (ASAP7 ESPice, from the round-2 reports). D = derived (a law applied to M).
P = projected (ARCH_CHOSEN target). **Every result in the tables below is a simulation of these models.**
The models' parameters are M, D or P as listed. Nothing here is a transistor-level result.

## 1. What is built

| block | file | what it models |
|---|---|---|
| B1 gain-cell store | `va/imc_gc.va` | One weight per instance: 8 storage nodes (sign + 7 magnitude bits), a continuous sample-and-hold write through WL, retention droop to vmin1 in t_ret |
| B1/B3 crosspoint | `va/imc_xp.va` | Unit caps of one weight (2^b units per bit, frozen mismatch σ·√units). Each row's contribution to the four top plates (2 slices × 2 sides) is `q = units·cu·V(rail)/C_slice`. Sign steering: side + follows rp for w ≥ 0 and rn for w < 0 |
| B2 row drive | `va/imc_rowdrv.va` | Per row: two rails (rp, rn) of c_row through r_sw onto the selected level net. ml2 uses V/3, 2V/3 and V. Bit-serial uses V. Optional constant-charge dummies |
| B5 reference / level nets | `va/imc_ref.va` | A Thevenin source (v0, r_out, c_dec) with class-A supply accounting. Used for the C-DAC reference, the ml2 mid levels and the V rail (R_PDN) |
| B3 column + merge | `va/imc_col.va` | Event model: top-plate reset with kT/C. Per-slot share onto C_acc (r_acc = 1/3 for ml2, 1 for bit-serial) with incomplete settling and kT/C. 1:16 slice merge with ratio error and kT/C. Ping-pong accumulators |
| B4 SAR | `va/imc_sar.va` | Behavioural pooled-round SAR: samples AS columns, then converts one per sar_clk round in BITS + 1 timed steps. Each step draws its C-DAC switching charge from the vref node, and each decision reads V(vref) at its own instant, so droop during bit cycling reaches the code. Offset-binary search over mismatched DAC weights, comparator noise per decision, code on `b[]` and on the `cv` monitor |
| B6, B10, requant | `digital/imc_driver/src/imc_chain.v` | Code capture, per-column affine calibration, the 24-b chain across K-adjacent tiles, the edge accumulator for K > chain, and requant to INT8 |
| driver | `digital/imc_driver/src/imc_driver.v`, `imc_seq.v`, `imc_wstage.v` | Descriptor schedule with systolic skew, HBM weight stream into ping-pong stage banks, just-in-time array writes in the merge slot, a stall when weights are late, gain-cell refresh from the stage bank every `RefreshPasses` (default 128) passes, the phase generator (conversions back to back, no handoff gap), and row codes |
| golden | `scripts/golden/imc_tile.py` (+ `test_imc_tile.py`) | Bit-true integer path plus the analog-error model with the same laws and parameter names as the `.va` files |

The tile contract is fixed by the golden's docstring:

- **Weights.** Sign-magnitude, |w| ≤ 127 (−128 is written as −127). There are two slices: hi = |w| >> 4
  (7 × 1 fF) and lo = |w| & 15 (15 × 0.25 fF).
- **Activations.** Sign-magnitude rows, |x| ≤ 127. ml2 drives the digits of 2|x|, 2 bits per slot. Bit-serial
  drives 7 planes of |x|. Either way each column swings 0 to VDD.
- **Converter scaling.** One code is 64 MAC units (vref = 1.411 V differential peak-to-peak), so the ideal
  code is `floor((S + 32) / 64)`. The full 8-row range never clips.
- **Calibration and requant.** cal is `(g·code + o + 2^13) >> 14`. The chain is 24 b. Requant is
  `requant_int8(64·acc, …)`, the systolic reference's own function.

### Choices the documents left open (made here, stated plainly)

1. **Signed activations.** ARCH gives 4 unipolar rails, so the activation sign rides a second rail per row
   (rp/rn). The weight's sign then picks which rail its units follow. Offset-binary was rejected: with a
   1 % unit mismatch it costs about 12 dB.
2. **Using the full rail.** |x| ≤ 127 is driven as 2|x| over the 4 ml2 slots, or as 7 bit-serial planes.
   This puts each column at up to VDD instead of VDD/2 and is worth +6 dB on every noise term. Bit-serial
   then needs 7 slots, not 8.
3. **Conversion rounds.** Each converter serves AdcShare = 4 columns, one conversion per merged column:
   4 rounds of 11 ticks, 6.25 ns, matching ARCH's 4 × 1.576 ns. ARCH's "128 converters per tile" with
   4 rounds would be 512 conversions per pass, which is inconsistent with one conversion per weight
   column after the merge. We use 256 conversions per pass (64 converters).
4. **Overlapped passes.** For conversion to overlap the next drive (ARCH's t_pass = max of the two), the
   merged sample has to leave the column. The default is therefore ping-pong accumulation banks: the
   merge happens on C_acc only and its kT/C is on that smaller cap. `merge_on_top = True` is the
   column-as-sampler alternative: merge on C_col + C_acc, with no overlap.
5. **Pooling K.** `pool_k` exists in the golden, and the RTL implements the per-tile T2 chain
   (pool_k = 1). Pooling across tiles is valid only when the pooled row blocks share their scales
   (N5_r2 finding 1).

## 2. Parameters (defaults)

| parameter | value | label / source |
|---|---|---|
| rows × cols, slices | 8 × 256 differential, 2 (7 × 1 fF, 15 × 0.25 fF) | P (ARCH B1) |
| C_slice | 56 fF (MSB), 30 fF (LSB); the merge ratio rho = 0.134 gives the 1:16 weighting | D |
| VDD_A | 0.7 V | P |
| t_tick, slot | 142 ps; ml2 8 ticks = 1.136 ns; bit-serial 7 ticks = 0.99 ns | P (ml2), D (bit-serial; M lead 0.94 ns, N2_r2) |
| phases per slot | reset 1 tick (top plate released mid-tick, rails dropped half a tick before the reset), rails driven to share edge 6 ticks, share 3 ticks ending 1 tick before slot end | D |
| SAR | 12 b, 4 rounds × 11 ticks (1.562 ns, P ≤ 1.576), t_conv 1.3 ns | P |
| c_row, τ_row | 7.47 pF, 16.1 ps | P, M-fit (N2_r2) |
| level nets | mid r = 2.54 Ω (class-AB SSF), top r = 1.30 Ω (R_PDN) | M-fit (N9_r2 §2.3), D (N9_r2) |
| τ_col | 39.2 ps | M-fit (N2_r2) |
| unit mismatch | 1 % at 1 fF, 2 % at 0.25 fF | P |
| merge / acc ratio σ | 0.1 % / 0.1 % | P |
| comparator σ | 86 µV (budget); sensitivity at 4.05 mV | P; M (N9_r2) |
| C-DAC unit σ | 2.45 % | D (from the 193 µV budget) |
| C-DAC, reference | c_dac 60 fF per converter; reference r_ref 0.5 Ω behind c_ref 200 pF, shared by the tile's 64 converters | P; P; D (B5 area 5,798 µm² × ~35 fF/µm² MOS decap) |
| gain-cell refresh | every 128 passes (0.80 µs at 6.25 ns) | D (inside ARCH's 1.32 µs 6σ retention) |
| gain cell | write 0.631 / −0.072 V, 44.3 ps to 99 % (τ 9.6 ps), 0.52 fJ per '1', retention 2.08 µs to vmin1 0.58 V | M (N3_r2) |
| energy events | conversion 253.5 fJ, column switches 67.6 fJ per column-pass | P |

## 3. How to run

```sh
./env.sh mixed                                  # vera, espice, iverilog, numpy
python3 scripts/golden/test_imc_tile.py         # golden self-check
make -C digital/imc_driver test                 # driver RTL + ideal tiles, systolic jobs, bit-exact
make -C analog/imc_tile lint units              # vera lint + ESPice unit benches of B1-B5
make -C analog/imc_tile cosim                   # RTL -> Verilog-A tiles -> RTL chain, ml2 + bit-serial
make -C analog/imc_tile timing accuracy         # t_pass / stalls / settling; SNR per term
cd analog/imc_tile/test && python3 tb_va_snr.py bitserial 4   # SNR of Verilog-A codes vs golden, pooled
cd analog/imc_tile/test && python3 tb_quality.py              # V9: PPL of tokact vs block8 (heavy: lock + 4 GB)
```

Do not wrap these benches in an outer `flock` on the shared lock file: `va_lib` takes the lock per
ESPice run, and an outer holder deadlocks it. A caller that already holds the lock sets
`SPICE_LOCK_HELD=1`.

Every ESPice run takes the shared lock with a 4 GB cap (`test/va_lib.py`). The co-simulation is
**open loop**. ESPice compiles each device with 64-bit unknown masks, so a VerA `.v` device takes at most
64 pins in this build (VerA itself allows 256), and this configuration needs 192. The tile's inputs never
depend on its outputs, so the loop is cut exactly:

1. the driver RTL runs in iverilog with ideal tiles and writes a pin trace;
2. ESPice runs the Verilog-A tiles from PWL sources built from that trace;
3. the same RTL runs again with each tile replaced by its ESPice codes, round by round.

The co-simulated configuration is 2 tiles of 8 rows × 8 columns (2 SARs per tile, AdcShare 4). Row
capacitance and level resistances are scaled by cols/256, which keeps the full-tile time constants.

## 4. Results (re-run 2026-10-06 after the review)

### 4.0 Verdict

**ARCH_CHOSEN as written does not work.** In its own operand format (n4 `w8a8_lead_tokact`:
INT8 per-token x and per-channel w, the format the interface specifies and the systolic reference
computes), the class-weighted per-pass SNR_eff is 26.1 dB in ml2 and 29.1 dB in bit-serial against
39.78 dB (G2). With B4's pooling K = 4 it is 25.3 dB. Each case fails by 10.7 to 14.5 dB. The ideal
12-b quantizer alone gives 44.0 dB on this data. The V9 quality check of that path also fails: +2.81 %
PPL of analog increment against +1.0 %.

**A modified variant passes conditionally:** bit-serial drive, block8 operands (scales per 8-row block
of x and w), no pooling, and the 86 µV comparator budget. It gives 42.25 dB, with a 90 % interval of
41.92 to 42.62 dB and no V2 per-term failure. It still needs four things closed:

1. a dequant multiply per conversion and a per-block x quantizer (neither is in the RTL; §5.2);
2. a converter whose comparator noise meets about 0.46 mV or better. The measured IMC StrongARM's
   4.05 mV fails by 7.9 dB; N6_r2's residue-amp SAR would pass at +1.8 dB (D);
3. a pass time of 7.95 ns, not 6.30 ns (0.79× the ARCH throughput);
4. corners (V3), which none of this simulates. N9_r2 measured the bit-serial lead failing SS by 2.1 dB
   and FF by 1.7 dB (M).

ml2 with block8 is **marginal and fails V2**. Its 39.89 dB has a 90 % interval of 39.55 to 40.27, and
its kT/C term is 41.1 dB against a budget of 43.31 − 0.5. Its rails also miss the 0.1 % settling spec
at the worst popcount, and the adversarial job fails G2 by 2.1 dB.

### 4.1 Unit benches (ESPice, `test/tb_va_units.py`)

| block | check | measured | result |
|---|---|---|---|
| B1 | write levels; '1' at 1 µs | within 0.06 mV of 0.631 / −0.072 V; 0.6065 V (law 0.6065) | PASS |
| B2 | top level V, 8 rows on it, share edge | ml2 0.0130 % (law 0.0117 %); bit-serial 0.0587 % (law 0.0529 %) | PASS (model = law) |
| B2 | **ml2 mid levels V/3 and 2V/3, 8 rows on one level** (new) | 0.674 % of the level on both (law 0.637 %) | PASS as model = law; **the 0.1 % spec is MISSED** |
| B2 | ml2 levels, sign steering; constant-charge dummies | exact; l3 sag 570 / 572 mV at 1 / 7 rows with cc | PASS |
| B3 | merged differential vs k·S | ≤ 1.2 ppm of full scale, both modes | PASS |
| B4 | ideal codes and clipping (now sequential bit steps) | equal to `floor(v/LSB + ½)`; 0.2535 pJ per conversion | PASS |
| B5 | **64 and 128 converters on one reference, decisions read per step** (new) | Verilog-A codes = golden `sar_convert` codes exactly (8/8 and 8/8). Droop at the 12 decisions: Verilog-A 8.47 / 15.83 mV against golden 8.54 / 15.83 mV, worst difference 5.5 / 6.4 % of the peak | PASS (model = law) |
| B5 | **droop against ARCH B5's 3.7 µV per conversion** (new) | 144.5 µV per conversion (peak 9.25 mV / 64) and 144.9 µV (18.5 mV / 128), with r_ref 0.5 Ω and c_ref 200 pF | **FAIL by 39×** |

The B5 spec miss is real for any reference whose decap fits B5's area. A 12-b conventional C-DAC on
60 fF takes about c_dac·vref ≈ 85 fC per conversion (D). For 128 simultaneous conversions to drop the
reference by only 128 × 3.7 µV, the decap alone would need about 23 nF (D), against about 200 pF in
5,798 µm². What saves the SNR is that most of the droop repeats from conversion to conversion: it acts
as a fixed bit-weight error that calibration removes. After calibration the reference term is
74.4 dB, against a budget of 53.98 dB (§4.3). The reference is therefore an energy and V5 item, not an
SNR blocker, **provided** calibration runs on the same reference load.

### 4.2 Checks against the task's targets

| # | check | target | measured | result |
|---|---|---|---|---|
| a1 | driver RTL + ideal tiles vs the bit-true golden (24-b chain, INT8 requant). Systolic-reference jobs in both modes, 4-tile chain, 8 × 16 tile, starved HBM, **refresh every 4 passes (new)**, **SmolLM2 attn_q 9 × 576 → 32 in both modes (new)** | bit-exact | **21 of 21 cases** bit-exact. Refresh: 6 rewrites per job, outputs unchanged. (The previous report said 20; the run had 18.) | PASS |
| a2 | co-sim, ideal models vs the bit-true golden (4 jobs × 2 modes) | ≤ 1 code per K-chunk | {A2} | {A2R} |
| a3 | vs the systolic array's exact INT8 result, ideal converter | (format property) | rms 2.9–158 MAC against rms(S) 4k–216k; 84–100 % of INT8 outputs equal | report |
| a4 | co-sim, all error terms on: Verilog-A vs golden rms error per job | ratio 0.75–1.33 (tightened from 0.5–2) | {A4} | {A4R} |
| a5 | **SNR of Verilog-A codes, pooled** (`tb_va_snr`, new): 4 runs × 18 tokens × 16 columns, block8 data, own static draws, against the golden over 8 seed sets | \|ΔSNR\| ≤ 0.5 dB | {A5} | {A5R} |
| b1 | class-weighted SNR_eff, **tokact** (the architecture as specified), 24 K-chunks | ≥ 39.78 dB | ml2 26.07 [22.96, 28.17]; bit-serial 29.07 [25.96, 31.14]; bit-serial with pool_k = 4 25.26. V2 per-term fails: kT/C, mismatch, ADC | **FAIL by 10.7–14.5 dB** |
| b2 | the same with **block8**, bit-serial | ≥ 39.78 dB, CI above it, V2 per-term | **42.25 [41.92, 42.62]**, no V2 fail | PASS (variant) |
| b3 | block8, ml2 | as b2 | 39.89 [39.55, 40.27]; V2 fail: kT/C 41.1 dB against 43.31 − 0.5 | **MARGINAL / FAIL by V2** |
| b4 | block8 sensitivities | as b2 | ml2 class-A level buffers 39.50 (FAIL). ml2 with merge on the column 42.10 (PASS, but no overlap, t_pass about 11.9 ns). Bit-serial: merge on the column 42.98; cc 42.22; ARCH LSB 172 µV 42.31; ideal reference 42.25 (the reference costs < 0.01 dB after calibration). **Measured comparator 4.05 mV: 31.92 (FAIL by 7.86)**; N6_r2 residue-amp SAR at 0.46 mV (D): 41.60 (PASS) | mixed |
| b5 | **adversarial popcount** (new): every row on one level in every slot, block8 w | ≥ 39.78 dB | ml2 37.71 (drive term 43.9 dB; **FAIL by 2.07**); bit-serial 43.95 (drive 65.4 dB, PASS) | ml2 FAIL |
| b6 | **V9 quality** (new, `tb_quality`, SmolLM2-135M, 2,044 tokens, Hadamard) | analog increment ≤ +1.0 % PPL | tokact: digital INT8 +0.26 ± 0.23 %, analog path (8 rows, 12 b, measured bit-serial error power) +3.07 ± 0.66 %, **increment +2.81 %: FAIL**. block8: digital +0.35 ± 0.11 % (top-1 98.6 %). Its analog path is not run, because the harness's analog path takes one x scale per token | tokact FAIL; block8 incomplete |
| c1 | t_pass on the RTL schedule | ≤ 6.30 ns | **ml2 6.248 ns** (44 ticks: the 2-tick handoff is removed, conversions run back to back); bit-serial 7.952 ns (56 ticks) | ml2 PASS; bit-serial **FAIL** (+26 %) |
| c2 | no stall, weights before activations | 0 after fill | 0 in both modes (M = 16 and 32); starved HBM stalls 607 ticks, still exact | PASS |
| c3 | GEMV at the ARCH per-tile HBM share | B9 law | 28,153 ticks against the 28,032 law; tile busy 1.9 % | PASS |
| c4 | ml2 rails settle, worst popcount | ≤ 0.1 % | class-AB SSF 0.637 % (needs 1.160 ns of the 0.849 ns); class-A 7.8 %. Verilog-A gives 0.674 % | **FAIL (gating for ml2)** |
| c5 | bit-serial rails settle | ≤ 0.1 % | 0.053 % (needs 0.648 ns of 0.707) | PASS |
| d | 24-b chain bit-exact across tiles | bit-exact | bit-exact (a1) | PASS |
| e | energy per pass per 256-column tile (supplies integrated, booked events) | ≤ 256 pJ | {E} | {ER} |

### 4.3 Per-term SNR, block8 operands (dB, each term alone over the ideal quantizer, 24 K-chunks)

| term | ARCH budget | ml2 | bit-serial |
|---|---|---|---|
| quantization (12 b, one code = 64 MAC) | — | 58.7 | 58.7 |
| ADC class (quantization + comparator + C-DAC, unweighted) | 43.30 | 47.9 | 47.9 |
| thermal kT/C | 43.31 | **41.1 (V2 FAIL)** | 44.6 |
| unit mismatch | 46.02 | 48.2 | 48.2 |
| drive (settling + code-dependent droop) | 54.81 | 84.3 (adversarial 43.9, FAIL) | 85.3 (adversarial 65.4) |
| reference droop (per-step, after calibration) | 53.98 | 74.4 | 74.4 |
| merge ratio / acc ratio | — | 82.5 / 78.8 | 82.5 / 74.2 |
| booked, not simulated: hold droop, coupling, injection, row coupling, row gain | 60.7, 63.0, 73.9, 74.8, 76.9 | at budget | at budget |
| **total (incl. booked) / class-weighted** | 38.96 / 39.84 | **39.60 / 39.89** | **41.70 / 42.25** |

The booked terms cost 0.15 to 0.25 dB. Without them the totals would read 39.8 dB (ml2) and 41.9 dB
(bit-serial).

## 5. Findings

1. **The digital architecture is correct.** The schedule, systolic skew, JIT weights, refresh,
   calibration, 24-b chain and requant are bit-exact on 21 jobs. The Verilog-A tiles reproduce the
   golden within one code per K-chunk with errors off.
2. **The analog architecture as specified fails G2 by 10.7 to 14.5 dB in its own operand format, and
   fails V9.** Block8 operands recover the per-pass SNR, but they are an architecture change:
   - **Dequant cost** (N5_r2, P). One 30 µm² unit (12 × 4-b multiply, exponent shift, 24-b
     accumulate, x-scale apply) per 2 converters is 32 units, about 960 µm² per tile for this tile's
     64 converters (+1,920 µm² at ARCH's 128). It also costs 2 INT8-MAC equivalents of energy per
     conversion, i.e. 512 per pass of 2,048 MACs, and E4M3 weight-scale bytes add 12.5 % to the
     weight stream.
   - **x-block quantizer.** 72 x-scales per token at K = 576, computed once per token on the digital
     rail (absmax and scale per 8 values). That is negligible beside the MVM, but it is a new datapath.
   - **The chain.** It accumulates dequantized values, so the integer T2 chain is no longer
     bit-comparable to the INT8 systolic reference.
   - **Pooling.** B4's K = 4 pooling cannot be used (N5_r2 finding 1).
   - **Quality.** Block8 digital quantization costs +0.35 % PPL (tokact +0.26 %). The block8 analog
     increment remains to be measured: the harness needs a per-conversion x scale for that.
   - **Not done here.** Neither the dequant nor the block-x path is in the RTL. Nothing has been
     re-scored in ARCH_METRIC.
3. **ml2 fails on three independent counts:**
   - settling, 0.637 % at the worst popcount against 0.1 %;
   - V2's kT/C rule, because the merge sits on the ping-pong C_acc. Merging on the column passes but
     loses the overlap;
   - the adversarial job, 37.71 dB.
   Its t_pass now meets 6.30 ns (6.248 ns).
4. **Bit-serial is the only drive mode that passes, and only conditionally** (§4.0). Its 7.95 ns pass
   is word-bound (7 × 0.99 ns + merge). N2_r2's 0.94 ns slot would give about 7.6 ns.
5. **The comparator stays gating.** At 4.05 mV the variant fails by 7.86 dB. The residue-amp SAR of
   N6_r2 brings the input-referred noise to about 0.46 mV, i.e. sqrt((4.05/9.54)² + 0.182²) mV (D,
   assuming redundancy absorbs the coarse decisions), and passes at +1.82 dB. That converter costs
   947 fJ per conversion (N6_r2), not 253.5 fJ, which ARCH_METRIC must re-price.
6. **The reference misses B5 by 39×** but costs < 0.01 dB after calibration (§4.1). That holds only if
   calibration sees the same reference load. Its energy (CV² of 64 × 85 fC per round) belongs in V5.
7. **Retention is handled.** The driver rewrites a group's rows from its stage bank every 128 passes
   (0.80 µs), inside the 1.32 µs 6σ retention. The bank now stays full while its group is live, and
   the loader runs one group ahead instead of two. A refresh is 16 write ticks on this 2-tile build
   (shared bit lines, one row per tick). It stretches its pass by about 5 ticks in ml2 and 10 in
   bit-serial, which is an occupancy of about 0.09 % and 0.14 % (D), against ARCH's ≤ 0.04 %. The fix
   is a write port per tile instead of shared bit lines. The same serial write makes a GEMV with
   fast HBM run at 7.24 ns per pass in ml2, though GEMV is HBM-bound anyway (c3).
8. **Energy.** Only the rail, level and reference-load CV² is simulated. The converter and
   column-switch energies are ARCH's per-event values (P). The class-A reference bias is not modelled.

### 5.1 Logs

- `output/accuracy.json`, `output/accuracy.log`: §4.2 b and §4.3.
- `output/quality.log`, `output/quality_b8.log`, `output/quality.json`: b6.
- `output/cosim_all.log`, `output/cosim_*`: a2, a4, a5 and e.
- `digital/imc_driver/build/test/*`: the driver traces and replays.

### 5.2 Tool limits hit (for REQUIRED_TOOLING / TOOL_ISSUES; not filed from here)

- An ESPice device holds at most 64 unknowns. This applies to Verilog-A and to `.v` devices, which
  are therefore limited to 64 pins, not VerA's 256. Hence the per-weight `imc_gc` / `imc_xp` split and
  the open-loop co-simulation.
- An ESPice B-source takes at most 8 probes, so event energies are booked in python.
- A Verilog-A device with `@(cross)` events that probes fast-moving inputs continuously drives the
  ESPice timestep to 0.1 fs. `imc_col` therefore probes its q inputs only inside its events.
- `vera --check` fails on every model, including the reference block `strongarm.va` (a contract
  `isDenseEnum` comptime error). Lint is the gate used here.
- VerA's event engine is IEEE 1364 only, so the RTL is Verilog-2001 with the `_d/_q` discipline.
- The quality harness's analog path asserts one x scale per token, so block8's analog path cannot be
  scored there.
- The shared lock is per ESPice run. An outer `flock` on the same file deadlocks `va_lib`, and a
  long heavy-python holder made a queued ESPice run time out once at a 900 s wait. The wait is now
  3,600 s.

## 6. Review responses

Each item is a finding of the adversarial review, what was changed, and the re-run evidence.

| # | finding (verdict) | response | evidence |
|---|---|---|---|
| 1 | "works = true" overclaimed (refuted) | **Agreed.** The verdict is now: ARCH as written fails, and the variant (bit-serial + block8 + no pooling) passes conditionally on the dequant, comparator, t_pass and corners (§4.0). | b1: tokact 26.07 / 29.07 / 25.26 dB over 24 chunks (the reviewer's 4-chunk quick run gave 21.3 / 24.3 / 19.4; both fail by more than 10 dB). V9 tokact +2.81 % |
| 2 | ml2 block8 pass is inside sampling noise; terms missing; V2 rule not applied (refuted) | **Agreed.** Now 24 K-chunks, each on its own tile draw, with a 90 % bootstrap interval over chunks. ARCH's unsimulated terms are booked at budget (golden `BOOKED_DB`). The V2 per-term rule is applied (`BUDGET_DB`). ml2 block8 is reported as MARGINAL and failing V2 | 39.89 [39.55, 40.27]; kT/C 41.1 < 42.81. The booked terms cost 0.15–0.25 dB |
| 3 | Reference droop not reaching the code; weak check; cosim r_out not scaled (weakened) | **Agreed and fixed.** imc_sar now runs BITS + 1 timed steps. Each step draws its C-DAC switching charge, and each decision reads V(vref) at its instant. The golden `sar_convert` implements the same law. tb_cosim scales r_ref / sc and c_ref · sc to the full-tile load, and uses a stiff source when the ref term is off. The bench now uses 64 and 128 converters against 3.7 µV per conversion | B5: Verilog-A codes = golden exactly; decision droop within 6.4 %; spec FAIL 144.5 µV per conversion. Ref term after calibration 74.4 dB |
| 4 | Drive settling validated only on the top level; the law is circular; data hides the worst case (weakened) | **Agreed on the gaps**, now covered: Verilog-A cases with n = 8 on l1 and l2, and an adversarial-popcount job in tb_accuracy. The 0.1 % settle FAIL stays gating for ml2. **On circularity:** yes, the Verilog-A network and the law are both a first-order Thevenin RC fitted to N9_r2's SSF transistor run. The Verilog-A check only proves that the netlist (8 rails switching onto one net, with the sign steering) behaves like the law. The physics rests on the N9_r2 fit (M), and only a transistor-level re-run at n = 8 can confirm 0.64 % | mid n = 8: Verilog-A 0.674 %, law 0.637 %. Adversarial ml2 37.71 dB (FAIL) |
| 5 | Comparator 4.05 mV is gating (upheld) | **Agreed.** No pass is claimed at the 86 µV budget alone. The residue-amp variant is added as a sensitivity row (D): 41.60 dB. imc_sar does not model the residue amplifier itself; the effective input-referred σ is used | b4 |
| 6 | Models faithful; gaps in c_par, injection, coupling, corners (upheld) | Injection, coupling, hold, row coupling and row gain are **booked at ARCH budget** rather than modelled. c_par stays 0, which flatters kT/C slightly: any top-plate parasitic attenuates the signal relative to the column kT/C. **Corners are not run**, because the models are behavioural with TT parameters. N9_r2's measured SS −2.1 / FF −1.7 dB for the bit-serial lead is cited as the corner evidence, and it is a fail | §4.3 booked row |
| 7 | Driver: 18 not 20 cases; SmolLM2 only in ml2; no refresh; no dequant (upheld) | **Count corrected** (now 21 cases, printed by the runner). SmolLM2 now runs in both modes. **Refresh is added** to imc_wstage/imc_driver (`RefreshPasses`), with a test that forces it every 4 passes. **The dequant is not added**: block8 is not adopted by ARCH, and adopting it needs a re-score and a V9 analog run first. Its cost is priced in §5 item 2 | a1 |
| 8 | Co-sim gate too loose; every SNR claim comes from the golden; nested-lock deadlock (weakened) | **Agreed.** The per-job window is tightened to 0.75–1.33. A new bench, `tb_va_snr`, computes the SNR of Verilog-A-generated codes pooled over 1,152 chain outputs with independent static draws, against the golden over 8 seed sets, gated at 0.5 dB. The deadlock is documented in §3 and `va_lib.py`, with a `SPICE_LOCK_HELD=1` bypass | a4, a5 |
| 9 | Timing (upheld) | **ml2 handoff removed.** `imc_seq` lets the merge leave two ticks before the last capture, so the next conversion starts on the tick after it. ml2 now runs at 44 ticks = 6.248 ns ≤ 6.30. Bit-serial stays 7.952 ns and needs re-scoring in ARCH_METRIC at 0.79× throughput (not done here: outside this block) | c1 |
| 10 | Block8 is an architecture change; ARCH contradicts itself (weakened) | **Agreed.** It is stated as a variant everywhere. The dequant, scale bytes and x quantizer are priced from N5_r2. Pooling K = 4 is excluded for block8. V9 is run: block8 digital +0.35 %; the analog increment cannot be scored in the harness (§5.2). The ARCH_METRIC re-score is not done here | b6, §5 item 2 |

One point of disagreement, on finding 2's arithmetic. The reviewer's quick 4-chunk run (39.42 dB)
and the previous 12-chunk run (39.94 dB) both sit inside the new 24-chunk interval
[39.55, 40.27]. The central value is still above 39.78. The ml2 FAIL therefore rests on V2's per-term
rule, settling and the adversarial job, not on the central SNR.
