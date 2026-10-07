# COMPARATOR_ALT: replacing the noisy StrongARM in the column SAR (B4)

2026-10-06. Scope: the comparator of the imc_tile SAR (`analog/imc_tile/va/imc_sar.va`, golden
`scripts/golden/imc_tile.py`). Scratch: `<scratchpad>/cmp_alt/` (decks `sa.py`, `dt.py`, `fia.py`, runner `es.py`,
golden copy `gold_cmp.py` + `imc_tile_snap.py`, schedules `sched.py`, budget `budget*.py`, evaluator wrapper
`score_cmp.py`; every ESPice result is a line of `results.jsonl`).

**Labels.** M = measured (ASAP7 BSIM-CMG, ESPice `.trannoise`, intrinsic devices, no layout parasitics).
D = derived (a law or the golden error model applied to M). P = projected. Every comparator σ is a probit
count (note 19q): N decisions at a constant ±dv, σ = dv / Φ⁻¹(P_correct), quoted with its ±1σ binomial band.

## 0. Answer

- **The budget is 12x looser than 86 µV, but the measured StrongARM is still 3.5x too noisy.** At today's operating
  point (block-8 operands, vref 1.411 V, one code = 64 MAC, LSB 344.5 µV, bit-serial) G2 reaches zero margin at a
  comparator σ of **1.07 mV at TT, 0.99 mV at FF and 0.73 mV at SS** (D, golden). The measured IMC StrongARM is
  3.5–4.2 mV (M). That is genuine input-referred thermal noise, not an artefact.
- **The StrongARM cannot be sized out of it.** Adding load cap makes it *noisier* (2 → 50 fF: 3.5 → 32 mV, M).
  Scaling every device 4x only halves σ, at 4x the energy (κ = E·σ² stays at 4–5e-20 J·V², M).
- **Recommended: a noise-aware SAR built from double-tail comparators** (Schinkel ISSCC 2007 topology).
  - The first 6 decisions use a minimum double-tail (1.82 mV, 4.55 fJ, 26 ps).
  - One redundant step of 32 LSB follows.
  - The last 7 decisions use a **tail-starved double-tail**: a 4-fin clocked tail pushes the input pair toward
    weak inversion. At 2x size it measures **0.654 mV, 11.2 fJ, 48 ps** (M, TT). κ = 4.8e-21, 9x better than the
    StrongARM.
  - The quiet class is built as three switchable 2x slices. A test-time trim bit turns on one slice on TT and FF
    dies, and all three on SS dies.
  - G2: **40.81 dB at TT (+1.03)**, 40.22 at FF (+0.44), and **39.92 at SS (+0.14, D from the measured 4x SS
    point)**.
  - Cost: 277 fJ per conversion at TT (1.09x the 253.5 fJ booking), t_conv 1.61 ns (a 13-tick round instead of
    11), about 1.3x converter area.
- **tok/s.** Under ARCH: 66,599 if the 13-tick round hides under bit-serial's 56-tick drive, 62,367 if the pass is
  conversion-bound. Under Sohu: 72,220 either way, because Sohu is attention-bound. The booked all-StrongARM
  design scores 67,760 / 72,220, but it fails G2 by 7.9 dB with its measured comparator, so that is not a valid
  score (§6).
- **meets the criteria?** Not all of them. Energy is within 9 %. t_conv is 2 % over 1.576 ns. Area is 1.3x. The SS
  margin rests on a κ-law projection from measured points. §9 says what kills it.

## 1. The comparator budget at the current operating point

The Verilog-A phase moved the operating point away from the one ARCH's 86 µV was derived for (LSB 172 µV,
vref 0.705 V, pool K = 4). I took the golden error model (frozen copy of `scripts/golden/imc_tile.py` at 18:48),
the real SmolLM2-135M blk.0 attn_q Hadamard-rotated job with block-8 scaling (12 chunks of 8 rows × 256 columns,
as `analog/imc_tile/test/tb_accuracy.py`), switched every term on alone, and swept σ_cmp (D):

| σ_cmp (µV) | 86 | 200 | 400 | 600 | 800 | 1000 | 1200 | 1500 | 2000 | 4050 |
|---|---|---|---|---|---|---|---|---|---|---|
| comparator term (dB) | 59.95 | 53.18 | 47.91 | 44.86 | 42.62 | 40.86 | 39.35 | 37.55 | 35.18 | 29.34 |
| G2, bit-serial TT (dB) | 42.33 | 42.20 | 41.80 | 41.29 | 40.69 | 40.04 | 39.35 | 38.36 | 36.78 | 31.93 |
| G2, ml2 TT (dB) | 39.92 | 39.84 | 39.61 | 39.25 | | | | | | 31.68 |

The 86 µV and 4.05 mV rows reproduce the block doc (42.34 / 31.9 dB). Zero margin (39.78 dB):

| corner | other terms alone (G2 without comparator) | LSB | σ at zero margin | σ at +0.5 dB |
|---|---|---|---|---|
| TT 300 K, 0.7 V | 42.37 dB | 344.5 µV | **1.07 mV** (3.1 LSB) | 0.93 mV |
| SS 373 K, 0.63 V signal | 41.13 dB | 310.0 µV | **0.73 mV** (2.4 LSB) | 0.59 mV |
| FF 358 K | 41.88 dB | 344.5 µV | **0.99 mV** | 0.84 mV |
| ml2 TT | 40.20 dB | 344.5 µV | 0.27 mV | – |

So the binding number is **σ ≤ 0.73 mV rms at SS**, input-referred, on the decisions that set the final code.
Bit-serial is assumed (ml2 fails its drive, and its kT/C leaves the comparator only 0.27 mV).

What changed from 86 µV: the LSB doubled (vref 1.411 V for clip-free block-8), the comparator term no longer has
to share a 43.3 dB ADC budget with a C-DAC at 193 µV (the golden's DAC term is 48.8 dB), and the class weight
(−3 dB) applies to it. The SNR-relevant comparator noise is per decision: the golden draws a new sample per
decision exactly as `imc_sar.va` does.

## 2. The 4.05 mV measurement, reproduced

ESPice's `.trannoise` was checked first (M): an R-C gives √(kT/C) for any R and step (1.960 / 2.043 / 0.971 mV
against 2.036 / 2.036 / 1.018), and a triode NMOS on 2 fF gives 1.434 mV against 1.439. The channel thermal noise
is right.

Round 2's deck (`a5/cmp_tn.py`: in 16, tail 8, latch 4/4, reset 2 fins, +2 fF on P/Q, VCM 0.55 V, 1 GHz) rebuilt as
`sa.py`:

| run | σ (mV) | band | E/decision | t_dec @1 mV |
|---|---|---|---|---|
| 400 decisions, constant +3 mV | 3.50 | 3.22–3.82 | 2.93 fJ | 32.8 ps |
| flicker off (NOIA = NOIB = NOIC = 0) | 3.95 | 3.61–4.34 | 2.93 | |
| input sign alternating per cycle | 4.18 | 3.80–4.61 | 2.93 | |
| step 0.2 ps (0.5 ps above) | 3.45 | 3.07–3.88 | 2.91 | |
| VCM 0.45 V / 0.35 V | 2.84 / 3.43 | | 2.81 / 2.70 | 42.3 / 92.3 ps |

**It is input-referred thermal noise of the decision** (M): flicker contributes nothing resolvable, the result is
step-independent, and the sign pattern does not matter. The four runs average 3.8 mV, consistent with 4.05 ± 12 %.
Its caveat is the usual one: intrinsic devices, no layout parasitics.

Why it is 3x the closed form (19p gives 1.24 mV): the closed form is the noise integrated on P/Q until the latch
fires, and 19p itself warns it is a lower bound because noise keeps accumulating after V_THN. The sweep says that
remainder dominates here (M):

| P/Q load cap | 2 fF | 8 fF | 20 fF | 50 fF |
|---|---|---|---|---|
| σ (mV) | 3.5 | 6.1 | 8.8 | 32 |
| E (fJ) / t_dec @1 mV (ps) | 2.9 / 33 | 8.8 / 74 | 20 / 151 | 39 / 226 |

19p predicts σ ∝ 1/√C₁. It goes the other way: a slower P/Q descent leaves the cross-coupled pair regenerating
from a smaller differential for longer, so the latch's own noise grows. Uniform 4x scaling (64-fin pair, 8 fF)
gives 2.17 mV at 11.5 fJ and the same 33 ps: κ = 5.4e-20 against 4.2e-20 (M). **The StrongARM's κ is fixed at about
5e-20 J·V² on ASAP7**, so σ = 0.73 mV costs about 90 fJ per decision. That is the case against resizing.

## 3. Comparators measured (TT 27 °C, 0.7 V unless stated)

κ = E·σ² is the figure of merit: at fixed topology σ² ∝ 1/E. Energy is the supply integral plus the clocked gates
(fins × 59.8 aF × V², D; the clocks are ideal sources).

| comparator | σ mV (band) | E fJ | t_dec | κ J·V² | note |
|---|---|---|---|---|---|
| StrongARM, IMC grade | 3.5–4.2 | 2.93 | 33 ps @1 mV | 4.2e-20 | §2 |
| StrongARM ×4, 8 fF | 2.17 (1.99–2.37) | 11.5 | 33 ps | 5.4e-20 | resizing |
| **Double-tail** (in 16, tail 8, MR 8, latch 2/2, 2 fF on Di) | 1.82 (1.64–2.02) | 4.55 | 26 ps @2 mV, 39 ps @0.1 mV | 1.5e-20 | fast class |
| double-tail, 6 / 10 fF on Di | 1.15 / 1.17 | 9.3 / 14.0 | 38 / 56 ps | 1.2e-20 / 1.9e-20 | cap saturates |
| double-tail ×4 | 0.93 (0.85–1.01) | 18.0 | 26 ps | 1.6e-20 | |
| double-tail, VCM 0.35 V | < 0.71 (bound; P = 1.0 at 2 mV) | 6.5 | 61 ps | | low CM starves the tail |
| tail-starved double-tail, tail 2 / 1 fin | 1.14 / 0.83 | 5.6 / 7.3 | 49 / 80 ps | 7.3e-21 / 5.1e-21 | integration-time control |
| **tail-starved double-tail ×2** (in 32, tail 4, MR 16, latch 4/4, 4 fF) | **0.654 (0.609–0.701)** | **11.17** | **48 ps @0.75 mV, 56 ps @0.1 mV** | **4.8e-21** | quiet class |
| FIA (Tang JSSC 2020; 16 fins, Cres 160 fF, Co 20 fF) + StrongARM latch, 300 ps | 0.471 (0.433–0.513) | 13.5 | 319 ps | 3.0e-21 | A = 9.8 |
| FIA half / quarter, 300 ps | 0.564 / 0.794 | 7.44 / 3.88 | 319 ps | 2.4e-21 / 2.45e-21 | best κ |
| FIA, window 150 / 100 / 50 ps | 0.623 / 0.97 / 1.54 | 13.5 | 170 / 120 / 70 ps | 5.2e-21 / 1.3e-20 / 3.2e-20 | A 6.0 / 4.4 / 2.6 |
| FIA half, 150 ps | 0.80 (0.74–0.87) | 7.45 | 170 ps | 4.8e-21 | |
| FIA LVT input, 100 ps | 0.64 | 22.6 | 120 ps | 9.3e-21 | |

Reading the table:

1. **The double-tail beats the StrongARM 3x on κ and is faster.** Its first stage integrates on Di and only then
   releases the latch, so the latch noise is divided by a real gain. Unlike the StrongARM, it responds to Di cap
   until about 6 fF.
2. **Starving the tail is the cheap lever.** A 2–4-fin clocked tail lifts the tail node, the pair's V_GS falls
   toward 0.3 V and its gm/ID rises from about 6 to above 20 /V (ASAP7 table `nfet_L0.021.csv`: 5.6 /V at 0.55 V,
   21.8 at 0.35 V). By 19p, V_n,in² ∝ V_ov = 2/(gm/ID), so the noise falls. The cost is integration time
   (26 → 48 ps). The low-CM run (VCM 0.35 V, quieter and slower) is the same mechanism. This is the
   "integration-time-controlled / bandwidth-limited dynamic bias" family (Bindra JSSC 2018 gets 2.5x energy at
   equal noise with a tail capacitor), done with a sized switch.
3. **The FIA has the best κ (2.4e-21) but needs ≥ 150 ps windows** to get below 0.8 mV. Its gain builds slowly
   (A = 2.6 at 50 ps, 9.8 at 300 ps). Its measured κ is 2.3x round 2's derived 1.29e-21, the same direction as the
   StrongARM's 3.3x.

## 4. SAR schedules (golden copy, block-8, bit-serial; D on the M comparators)

`gold_cmp.Tile2` replaces the golden's binary search with a **bipolar** search (first comparison at mid-scale, then
±steps), the form a redundant SAR needs because a wrong early decision can be undone both ways. With binary steps
and noise off it is bit-identical to the golden; with noise its rms error matches the golden's within 0.3 %.
A tier boundary adds one redundant step e = 2^⌈log₂(4σ_fast/LSB)⌉ after the first decision of the next tier.
Calibration is the golden's per-column affine fit. Time per decision = t_cmp + t_loop, t_loop = 80 ps (D: 2 FO4
logic, DAC settle τ 4.63 ps × ~8.6, 2 FO4; N6_r2 law), plus 80 ps of metastability slack per conversion (D,
τ_reg 4.35 ps from the 48 → 68 ps spread between 0.7 mV and 10 µV, for about 1e-9 per conversion). Energy per
conversion = comparators + 150 fJ DAC and reference (ARCH n6 breakdown, D) + 2 DFF per decision (0.82 fJ, D).

| schedule | decisions | G2 TT | comparator fJ | E_conv fJ | t_conv ns | verdict |
|---|---|---|---|---|---|---|
| all StrongARM (as built) | 12 | 32.94 | 35 | 205 | 1.44 | **infeasible**: −6.8 dB |
| all double-tail | 12 | 37.18 | 55 | 225 | 1.35 | infeasible: −2.6 dB |
| all double-tail ×4 | 12 | 39.99 | 216 | 386 | 1.35 | TT +0.21, fails SS |
| all FIA 100 ps | 12 | 39.86 | 162 | 332 | 2.48 | too slow |
| all FIA quarter 300 ps | 12 | 40.42 | 47 | 217 | 4.87 | too slow except at AdcShare 2 |
| StrongARM ×5 + FIA quarter ×8 | 13 | 40.40 | 46 | 217 | 3.84 | too slow |
| double-tail ×6 + FIA quarter ×7 | 13 | 40.40 | 54 | 225 | 3.51 | too slow |
| double-tail ×6 + FIA half 150 ps ×7 | 13 | not run (σ_q 0.80 mV ⇒ ≈ 40.6, D) | 79 | 250 | 2.47 | too slow (evaluator: infeasible) |
| StrongARM ×5 + StrongARM majority-of-25 ×8 | 13 (205 comparisons) | 40.14 | 601 | 771 | 11.2 | infeasible |
| **all tail-starved double-tail ×2 (D)** | 12 | **40.83** | 134 | 304 | 1.62 | viable, simplest |
| **double-tail ×6 + tail-starved ×2 ×7 (E)** | 13 | **40.81** | 106 | 277 | 1.61 | **lead** (needs the SS trim, §5) |

What redundancy can and cannot absorb (D, golden): it removes the *early* decisions' noise completely when the
step it adds covers ±4σ of those decisions (StrongARM ×5 + quiet ×8 equals uniform-quiet within 0.03 dB). It does
nothing for the last decisions, which set the final residue, and it caps how many decisions the noisy comparator
may take: the quiet tier must start at a step ≥ 4σ_fast. With the StrongARM (11 LSB) that is step 64, i.e.
8 quiet decisions. With the double-tail (5.3 LSB) it is step 32, 7 quiet decisions. Majority voting is the wrong
tool at 4 mV: 25 votes per decision buy only 40.1 dB.

## 5. Corners of the lead

Measured σ (M; SS = ss models, 100 °C, 0.63 V; FF = ff models, 85 °C, 0.7 V; VCM 0.55 V):

| comparator | TT | SS 0.63 V | SS, rail held at 0.7 V | FF |
|---|---|---|---|---|
| double-tail, fast class | 1.82 mV, 26 ps, 4.55 fJ | 3.35 mV (2.96–3.84), 37 ps, 3.48 fJ | | 1.99 mV (D, √T) |
| tail-starved ×2 | 0.654 mV, 48 ps, 11.2 fJ | 1.06 mV (0.95–1.18), 66 ps, 8.2 fJ | 0.90 mV (0.82–0.99), 63 ps | 0.747 mV (0.68–0.82), 44 ps, 12.0 fJ |
| tail-starved ×4 | 0.476 mV (0.44–0.52), 48 ps, 22.3 fJ | 0.717 mV (0.66–0.78), 66 ps, 16.4 fJ | | 0.52 mV (D, √T) |
| tail-starved ×2, VCM 0.45 V | 0.622 mV, 62 ps, 12.5 fJ | | | |

SS raises the quiet class's noise 1.5–1.6x, far more than √(373/300) = 1.12. Holding the rail at 0.7 V removes a
third of that. From ×2 to ×4 at SS, σ falls 1.48x (κ law: 1.41x), so the law holds at the corner.

G2 for each schedule (D, golden at the corner, redundancy fixed by the TT design, measured σ unless marked):

| schedule | TT | FF | SS 0.63 V | SS, adaptive VDD 0.7 V | E_conv TT |
|---|---|---|---|---|---|
| D: all ×2, 12 decisions | 40.83 | 40.22 | 38.57 | 39.71 | 304 fJ |
| E: fast ×6 + ×2 ×7 | 40.81 | 40.22 | 38.61 | 39.71 | 277 fJ |
| E4: fast ×6 + ×4 ×7 | 41.26 | 40.77 (D σ) | 39.57 | ≈ 40.6 (D) | 355 fJ |
| D4: all ×4 | 41.27 | 40.79 (D σ) | 39.59 | | 437 fJ |
| graded: fast ×6 + ×2 ×3 + ×4 ×4 | 41.18 | | 39.29 | | 320 fJ |
| **E-trim: E at TT/FF, three ×2 slices (= ×6) on SS dies** | **40.81** | **40.22** | **39.92 (D: 0.585 mV)** | **40.69 (D)** | **277 fJ** |

A graded quiet tier does not help much. Decisions on the larger steps are near threshold less often, but every
quiet decision still counts. The width trim is the cheap closure, because the SS dies pay the energy, not the TT
dies the score is taken at. ARCH V3 lets a trim close SS if it costs ≤ 3 % tok/s; this one costs about 1 %
(area only).

## 6. tok/s (arch_eval, `notes_native` joint frame, the ARCH_CHOSEN design)

`score_cmp.py` runs the unmodified evaluator with n6's e_conv, t_conv and area scaled by the candidate's ratio to
the imc_tile booking (253.5 fJ, an 11-tick 1.556 ns round, 43.45 µm²).

- "13t" is a 13-tick round with the pass conversion-bound (×1.167).
- "bs-free" is a 13-tick round that hides under bit-serial's 56-tick drive pass (4 × 13 + 2 = 54 ticks).
- Area deltas count devices and caps only. The booking already holds two trimmed comparator classes (ARCH's 13
  decisions, 5 quiet).
- Sensitivities (D): e_conv ×1.5 → −11 %, ×2 → −28 % (the power cap binds); t_conv ×1.17 → −6.3 %; area ×1.25 →
  −1.4 % (ARCH).
- Sohu is attention-bound until e_conv passes about 1.3x, and then the power cap takes over.
- The evaluator's operating-point search is not monotone in these factors (E4: 13t scores above bs-free), so
  differences under about 3 % are noise.

| candidate | xE / xT / xA | ARCH tok/s, TOPS/W, tok/W | Sohu tok/s, TOPS/W |
|---|---|---|---|
| booked all-StrongARM (fails G2 by 7.9 dB) | 1 / 1 / 1 | 67,760, 11.25, 630.5 | 72,220, 10.56 |
| StrongARM ×16 (σ ≈ 1.1 mV, D) | 2.86 / 1.0 / 1.10 | 41,042, 6.31, 378.8 | 38,575, 5.37 |
| all double-tail ×4 (fails SS, FF) | 1.53 / 1.0 / 1.03 | 60,098, 9.46, 543.2 | 59,719, 8.14 |
| D all tail-starved ×2, 13t / bs-free | 1.20 / 1.167, 1.0 / 1.05 | 63,343 / 67,552, 10.37 / 10.52 | 72,220, 9.94 |
| E noise-aware ×2, 13t / bs-free | 1.092 / 1.167, 1.0 / 1.10 | 63,155 / 67,369, 10.75 / 10.92 | 72,220, 10.29 |
| **E-trim (recommended), 13t / bs-free** | 1.092 / 1.167, 1.0 / 1.30 | **62,367 / 66,599, 10.79 / 10.96, 608.6 / 616.8** | **72,220, 10.38, 69.2 tok/W** |
| E4 noise-aware ×4, 13t / bs-free | 1.40 / 1.167, 1.0 / 1.18 | 62,851 / 60,098, 9.75 / 9.89 | 60,185 / 59,719, 8.26 / 8.47 |
| FIA quarter at AdcShare 2 | 0.86 / 1.55 / 2.10 | 51,477, 11.77, 655.2 | 72,981, 11.26 |
| pipelined residue-amp SAR (N6_r2 A1) | 3.74 / 1.0 / 7.94 | 31,379, 5.68, 311.9 | 41,044, 5.68 |

Against the booking, E-trim costs −1.7 % (bs-free) or −8.0 % (13t) ARCH tok/s and nothing under Sohu. The booking
itself is infeasible with the measured comparator.

## 7. Candidates ranked

| # | candidate | verdict | why |
|---|---|---|---|
| 1 | **E-trim**: noise-aware SAR, minimum double-tail ×6 + 32-LSB redundant step + tail-starved double-tail ×7 as three switchable ×2 slices | **lead** | TT +1.03, FF +0.44, SS +0.14 (D); 1.09x energy; 1.61 ns; best tok/s of the feasible options |
| 2 | D: tail-starved ×2 alone, binary 12 b (with the same SS width trim) | viable | same G2 and tok/s; −3.6 % TOPS/W; no change to the SAR logic, no second comparator |
| 3 | E4: noise-aware with the quiet class fixed at ×4 | viable, dominated by 1 | closes SS only with adaptive VDD (−0.21 dB at 0.63 V); 1.40x energy; Sohu −17 % |
| 4 | Double-tail ×4 alone | infeasible at corners | fastest (1.35 ns, fits today's 11-tick round); TT +0.21; fails SS and FF |
| 5 | FIA preamp + latch | dominated on tok/s | best κ (2.4e-21) and best TOPS/W, but needs ≥ 150 ps per quiet decision, so conversions take 2.5–4.9 ns; viable only with AdcShare 2 (−24 % ARCH tok/s) |
| 6 | StrongARM resizing (fins, caps, Vt, VDD) | dominated | κ is fixed near 5e-20; load cap raises σ; LVT/SLVT are noisier (N9_r2: 5.2 / 5.4 mV); 0.7 V is the ceiling; σ = 1.07 mV costs about 550 fJ of comparators |
| 7 | Pipelined residue-amp SAR (A1) | dominated | built for an 86–182 µV budget: 947 fJ, 345 µm² per physical conversion |
| 8 | Repeated or majority-voted decisions | infeasible | 205 comparisons for 40.1 dB |
| 9 | Redundancy alone | not a fix | absorbs early-decision noise only (§4) |
| 10 | Time-domain / VCO comparators | infeasible on speed | published 12-b single-comparator SARs reach about 30 MS/s; this SAR needs about 620 MS/s per converter |
| 11 | Moving the budget (2x column C; vref) | dominated | 2x C relaxes the TT budget only to 1.24 mV (D), at 2x array C; vref is already full-rail |

## 8. Integration plan (for the review agent that owns these files; nothing here was edited)

- **`analog/imc_tile/va/imc_sar.va`.** Parameters `NDEC` (13), `steps[]` (1024, 512, 256, 128, 64, 32, **32**,
  16, 8, 4, 2, 1), `sig_fast` (1.82e-3), `sig_quiet` (0.654e-3), `n_fast` (6). Replace the offset-binary 0/1 search
  with the bipolar search of `gold_cmp.Tile2.convert` (est starts at mid-scale; d = ±1; est += d·step;
  code = est − [d_last < 0]). DAC mismatch per step is sig_dac·√step. Defaults `t_conv` 1.3e-9 → **1.61e-9** and
  `e_conv` 253.5e-15 → **276.8e-15**. For option 2 only `sig_cmp` → 0.654e-3, t_conv 1.62e-9, e_conv 303.7e-15.
- **`scripts/golden/imc_tile.py`.** The same bipolar search in `sar_convert`, with the reference-droop bookkeeping
  per step. `sig_cmp` 86e-6 → a per-decision schedule (`sig_cmp_fast`, `sig_cmp`, `n_fast`), `round_ticks`
  11 → **13**, `t_conv` 1.3e-9 → 1.61e-9. Keep the self-check: bipolar binary with noise off must equal
  `ideal_code`.
- **RTL (`digital/imc_driver`).** `RoundTicks` 11 → 13. Codes stay 12 b, because the redundant-to-binary sum is
  inside the converter's SAR logic. Bit-serial t_pass stays 56 ticks (4 × 13 + 2 = 54 ≤ 56). ml2 becomes 54 ticks,
  7.64 ns. No other change.
- **Evaluator (`nodes/n6_readout.py`).** Measured comparator constants: KAPPA_SA 4.5e-21 (derived) → **4.2e-20
  (M)**, plus a `cmp_cls` table entry for the two DT classes (σ, E, t_cmp above). A new option `r3_dt_noise_aware`:
  13 decisions, 6 fast + 7 quiet, `t_model="meas"` loop, cheap class at the measured DT energy. The quiet-decision
  energy law becomes E_q = κ_DT / σ_q² with κ_DT = 4.8e-21 and a floor at the measured 11.2 fJ.
- **Corner trim.** The quiet class is three identical ×2 slices with separate clock enables. One trim bit per
  die (or per tile) enables all three at SS. In the golden and `imc_sar.va` this is `sig_cmp` per corner: 0.654 mV
  at TT, 0.747 mV at FF, 0.585 mV with three slices at SS. The RTL needs one static enable to the converters.

## 9. What kills the lead

**A post-layout `.trannoise` of the three-slice quiet class at SS (0.63 V, 100 °C, at the SAR's real input common
mode) above 0.73 mV rms.** Its intrinsic projection is 0.585 mV (κ law on the measured ×4 SS point, 0.717 mV), so
layout parasitics on the Di nodes may cost at most 25 % of σ. Past that, no fast comparator here closes SS inside
the energy band, and the SAR needs the FIA's long windows (the AdcShare-2 option, −24 % ARCH tok/s).

Second-order risks:

- **Inter-comparator offset.** There are two classes. The redundant step covers ±32 LSB minus 4σ of the fast class,
  which leaves about 3.8 mV for the residual after trim.
- **Input common mode.** The double-tail's NMOS input wants VCM ≥ 0.45 V to stay near 48 ps (62 ps at 0.45 V,
  slower again at 0.35 V).
- **Loading.** The quiet class's input gates (32–96 fins) load the C-DAC top plate by 1.5–4 fF of 60 fF, a
  calibrated gain error.
- **Timing.** t_loop = 80 ps is derived. Every +10 ps per decision adds 0.13 ns per conversion.

**Operational note.** The `.trannoise` CSV rawfiles (about 1 GB each) filled the shared disk for a while during this
work, and a few late runs failed with `DeliveryFailed`. The files were deleted, and `es.py` now removes each rawfile
after reading it. Every result above comes from a completed run.

## Sources

- B. Razavi, "The StrongARM latch", IEEE SSC Magazine 2015; notes 19j–19q, 19p, 19p1, 19q (digest AD-Comparators-2);
  redundancy 23r, 24s (AD-SARADCs-2).
- D. Schinkel et al., "A Double-Tail Latch-Type Voltage Sense Amplifier with 18ps Setup+Hold Time", ISSCC 2007
  (92 fJ, 1.5 mV noise, 90 nm). <https://research.utwente.nl/en/publications/double-tail-latch-type-voltage-sense-amplifier-with-18ps-setuphol/>
- X. Tang et al., "An Energy-Efficient Comparator With Dynamic Floating Inverter Amplifier", JSSC 55(4) 2020
  (46 µV at 1 pJ, > 7x vs StrongARM). <https://sunlab.ee.tsinghua.edu.cn/en/publication/jssc_202001_xiyuan-tang_8947992/>
- H. S. Bindra et al., "A 1.2-V Dynamic Bias Latch-Type Comparator in 65-nm CMOS With 0.4-mV Input Noise", JSSC
  53(7) 2018 (2.5x energy at equal noise). <https://research.utwente.nl/en/publications/a-12-v-dynamic-bias-latch-type-comparator-in-65-nm-cmos-with-04-m/>
- V. Giannini et al., "An 820 µW 9b 40 MS/s Noise-Tolerant Dynamic-SAR ADC in 90nm Digital CMOS", ISSCC 2008
  (low-power comparator for early bits, low-noise one after the redundancy).
  <https://www.researchgate.net/publication/4332069_An_820mW_9b_40MSS_noise-tolerant_dynamic-SAR_ADC_in_90nm_digital_CMOS>
- P. Harpe et al., "A 10b/12b 40 kS/s SAR ADC With Data-Driven Noise Reduction", ISSCC 2014 / JSSC 2015
  (repeat only the noise-critical comparisons).
  <https://www.semanticscholar.org/paper/A-10b%2F12b-40-kS%2Fs-SAR-ADC-With-Data-Driven-Noise-up-Harpe-Cantatore/87df67447f1e5dc119141a8961ba8413407b1f46>
- VCO-based comparators for SAR (speed ceiling about 30 MS/s at 12 b with one time-domain comparator):
  <https://ieeexplore.ieee.org/document/8702448/>, <https://www.researchgate.net/publication/355625944_VCO-Based_Comparator_A_Fully_Adaptive_Noise_Scaling_Comparator_for_High-Precision_and_Low-Power_SAR_ADCs>
- Round 2: N6_r2 (FIA deck, loop law, A1 converter), N9_r2 (StrongARM per flavour, 4.05 mV).
