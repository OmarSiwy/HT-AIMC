# Architecture decision, round 1

2026-10-06. This page scores everything against `ARCH_METRIC.md`:

- the search winner (`search/SEARCH.md`);
- the three architect proposals (`architects/*.md`);
- the three judge passes (analog feasibility, system, quality);
- the final node results (`nodes/N1..N10.md`);
- the transform study (`lit/LIT_SYSTOLIC_ALGOS.md`).

The pick's spec is `../ARCH_CHOSEN.md`.

Labels: **M** measured here (simulation or the quality harness), **D** derived (a repo law applied
to measured parameters), **P** projected (literature or law only). Every tok/s, TOPS/W, tok/W and
tok/J on this page is **P** unless marked otherwise, because `arch_eval` is a projected model (its
README). No SPICE, synthesis or place-and-route ran for this decision. Every score was re-run on
2026-10-06 with `arch_eval`, as single processes capped at 4 GB. The scratch scripts are
`scratchpad/dec_base.py`, `dec_xf.py`, `dec_x2.py`, `dec_x3.py` and `dec_frame.py`. They patch
`arch_eval` in memory and change no repo file.

## The decision

**Pick: `notes_native`, amended (P).** It keeps the search's Hadamard charge-rail tile and the
position-tiered KV 4/8 cache (sink 8 + recent 120), with three changes:

- a **16 MB** activation buffer. This is the system judge's repair for the spill; it fits in the
  unused 17 mm².
- the class-A **buffered reference** (N9 `lead`) in place of `ref_bandgap_ldo`. ASAP7 has no BJT
  or resistor models, so a bandgap cannot be signed off.
- **adopted from the transform study:** the output-stationary **accumulator chain** between
  K-adjacent tiles (T2). It is exact and changes no model. I re-priced its hop at the pick's real
  tile pitch of 138 µm instead of the study's 50 µm.

| ARCH conditions (Llama-3-8B, 512/128, 100 mm²) | tok/s/die | TOPS/W | tok/W | tok/J |
|---|---|---|---|---|
| pick, as scored, joint frame (P) | 67,922 | 15.56 | 825 | 834 |
| **pick, judge-corrected, pessimistic (P)** | **48,700** | **9.3** | **551** | **550** |
| Sohu conditions (Llama-3-70B FP8, 2048/128, B 1000, 1,063 mm²): as scored (P) | 101,125 | 14.94 | 97.2 | 104.1 |
| **Sohu conditions, judge-corrected (P)** | **72,500** | **9.0** | **64.8** | **68.7** |

The operating point is B = 587 (the KV limit), 38.2 tok/s per stream, VDD 0.5 V for logic and
0.7 V for analog, and a 66 W die. Prefill is bound by tile compute and decode by HBM.

**This is a conditional go.** After the corrections, the pick beats the lever-matched systolic
baseline on the king metric under both condition sets, but only against the synthesized (ppa.json)
PE: **1.05x under ARCH and 1.16x under Sohu**. Against the literature PE it loses both (0.80x and
0.84x), and it loses TOPS/W in every frame. The case survives only if the Verilog-A and SPICE
ladder recovers most of what the judges took away. `ARCH_CHOSEN.md` §6 has the kill criteria.

**The transforms do not change the ranking. They make the analog-vs-baseline ratio worse**
(§5). The biggest of them (2:4 sparsity) lifts the digital baseline more than it lifts the tile.

## 0. Reproduction, and the 40.0k vs 53.9k reconciliation

Both numbers reproduce exactly with today's evaluator. They are the same design read in two
scorer frames:

| design (ARCH) | core frame (`cli.py`, `model.evaluate`) | joint frame (`search.evaluate`, the declared ranking frame) |
|---|---|---|
| search winner r01 (`search/designs/winner.json`) | **39,997** / 10.71 / 557.5 / 605.8 | **53,864** / 10.45 / 546.7 / 689.7 |
| the pick | 44,806 / 11.03 / 620.1 / 624.3 | 67,922 / 14.84 (15.56 with T2) / 794 / 818 |

- **The transform study used the core frame.** Its scratch wrapper calls `model.evaluate`, so its
  40.0k is right for what it ran. SEARCH.md, the architects, the judges and this decision use the
  joint frame. `search.py` declares that frame the **RANKING FRAME**: it adds the N9 circuit laws,
  the N4 tile effects and the N8 rail hook, which the core has not adopted.
- **The cause of the gap, for the pick** (D, `dec_frame.py`):

  | | t_pass | converter energy per pass | t_prefill |
  |---|---|---|---|
  | core | 15.3 ns | 259.6 pJ | 5.04 s |
  | joint | 6.3 ns | 129.8 pJ | 2.18 s |

  Two hooks account for nearly all of it:
  - **the 1:16 charge slice merge** (`w8a8_lead_tokact` has `f_merge = True`, giving one
    conversion per weight in place of one per 4-b slice, with asymmetric 0.25 fF LSB units);
  - **N9's 4-level row drive** (`ml2_rails`: 4 slots per word instead of 8 bit-serial).
- **What it means.** Both are real circuit claims in the pick, and neither has been simulated.
  **If both fail, the pick reads 44.8k, which is below the lever-matched ppa baseline (46.4k).**
  That is why the merge (V2) and the row drive (V4) are at the top of the verification plan.
- **The number used** is the joint frame, the one I can reproduce: 53,864 for r01 and 67,922 for
  the pick. The 40.0k is reported as the core-frame reading of the same design. It is not an
  error in either document. It is an unverified-credit gap.

**Correction to `ARCH_METRIC.md` (loud).** Its Sohu table gives a 666 mm², 537 W, 16.5 TOPS/W
Sohu-equivalent. That was the pre-synthesis calibration. With the sysreference ppa.json now in the
tree, `cli.py --sohu-target` gives:

| | Sohu-equivalent (D-PE / P) |
|---|---|
| die | 1,063.4 mm² |
| power | 820.8 W die + 49.7 W HBM |
| tok/s per chip | 62,571 |
| TOPS/W | 10.82 |
| tok/W | 71.9 |
| tok/J | 124.3 |
| tok/s per mm² | 58.8 |
| tok/s per mm² per W | 0.0717 |

Every Sohu number on this page uses the 1,063 mm² die.

## 1. The quality gate, settled from N8 (numeric)

N8 (`nodes/N8.md`, option `g43_lossless`) defines the gate. The settlement fixes which lever
credits count.

### G1, format: lossless tier, W8A8 class

The whole format stack (weights, activations, KV and any model-changing transform) may cost at most
**+3.0 % PPL** over FP on the SmolLM2-135M proxy.

Measured on the chosen format (Hadamard, W8 per channel, A8 per token):

| part | ΔPPL (M) | source |
|---|---|---|
| W/A | +0.06 ± 0.23 % | `search/quality_spotcheck.json` |
| KV 4/8 (sink 8 + recent 120, Hadamard) | +0.21 ± 0.18 % | `designs/notes_native.quality.json`, seed 0, 4 × 512 tokens |
| KV8, for reference | +0.20 % | same file |

These fail G1 (M):

- uniform KV4: +28.8 %
- KV4 with Hadamard: +4.7 %

KV 3/8 measures +1.19 % (M). It passes G1, but uses up 40 % of the budget.

### G2, analog increment

- **The analog increment may be at most KL 0.01 nats, about +1.0 % PPL**, over the same format
  run digitally.
- In circuit form, the class-weighted SNR_eff must be at least:

      43.0 (A = 2e4) + 0.27 (32 layers) + 1.0 (die cushion) − credit = 44.27 dB − credit

- The range must be clip-free to **±32 σ**.
- **A credit counts only when it was measured on the analog path in the harness.**
  - Hadamard (`lv_hadamard`): **4.5 dB** (D, band 3 to 8.5). That makes the target **39.78 dB**.
  - `lv_protect_tensor`: **0 dB** until it is measured. Its 6 dB was measured digitally, unrotated,
    on one tensor. Without it, the no-rotation path measures +1.63 % at 38.5 dB, which fails G2 (M).
- The strict end of the band (A = 3.8e4, giving 42.6 dB with the credit) is a sensitivity. It
  does not gate.

### G3 and the corner rule

- **G3: top-1 agreement** is reported and does not gate. Reaching ≥ 97 % needs about 47 dB (D).
- **Corner rule for this phase.** The G2 margin must be ≥ 0 dB at SS (0.63 V, 100 °C) and at FF
  (85 °C), under the corner model in `designs/robust.py` or under trim or adaptive VDD that costs
  ≤ 3 % tok/s.

### The transform rule (new)

- A transform that changes the model (2:4 sparsity, codebook weights, any KV format) must keep the
  **cumulative G1 total ≤ +3.0 %** on SmolLM2-135M.
- Any retraining or distillation it needs is counted as co-design, as ARCH_METRIC requires.
- Until that measurement exists, the transform is **conditional**, and its gain is not part of the
  ranked score.
- KV 4/8 is the exception: it is measured (above), over one seed. A 5-seed confirmation is V8.

### What the settlement does to the finalists

| design | rotation | credit claimed | SNR_eff / settled target | verdict |
|---|---|---|---|---|
| r01 (search winner) | no | protect 6 dB | 38.54 / 44.27 dB | **fails, −5.7 dB: disqualified** |
| r02, r03 | yes | protect 6 dB | 38.54 / 39.78 dB | **fails, −1.24 dB: disqualified** |
| maximalist (p08 tile) | no | protect 6 dB | 38.32 / 44.27 dB | **fails, −6.0 dB: disqualified** |
| robust | yes | Hadamard 4.5 dB | 42.11 / 39.78 dB | passes, +2.33 dB (SS +0.52, FF +0.86, D) |
| notes_native and the pick | yes | Hadamard 4.5 dB | 39.84 / 39.78 dB | passes, **+0.05 dB at TT only** |

The quality judge rated r01, r02, r03 and maximalist "weakened, untested". Under the settled gate
they are **disqualified until fixed**, and the fix is the Hadamard tile, which is the pick's tile.

## 2. Judge-corrected scoreboard (both condition sets)

The rules:

- Where judges disagree, take the most pessimistic credible correction.
- Corrections for independent effects (the converter envelope, spill, corners) compound.
- A gate failure disqualifies.

The ratios (all P):

- **pick:** the feasibility judge gives 50,000 / 69,689 = **0.717** on tok/s. That is the ADC at
  ×2 energy and ×1.25 time, plus a 0.89 corner closure. It gives 0.60 on TOPS/W and about 0.66 on
  tok/W and tok/J.
- **robust:** 36,600 / 47,766 = **0.766** on tok/s and 0.666 on TOPS/W. Its corners are already
  closed.
- The system judge's spill is removed by the 16 MB buffer, whose cost is now inside the score.

| design | ARCH, as scored | **ARCH, corrected** | Sohu, as scored | **Sohu, corrected** | gate |
|---|---|---|---|---|---|
| **pick** (+16 MB, buffered ref, T2) | 67,922 / 15.56 / 825 / 834 | **48,700 / 9.3 / 551 / 550** | 101,125 / 14.94 / 97.2 / 104.1 | **72,500 / 9.0 / 64.8 / 68.7** | +0.05 dB |
| pick without T2 | 67,922 / 14.84 / 794 / 818 | 48,700 / 8.9 / 530 / 540 | 97,064 / 13.36 / 87.6 / 101.9 | 69,600 / 8.0 / 58.4 / 67.3 | +0.05 dB |
| notes_native as proposed (2 MB, bandgap) | 69,689 / 15.66 / 830 / 888 | 48,900 / 9.3 (min of judges) | not re-run | not re-run | +0.05 dB; the bandgap cannot be signed off |
| **robust + KV 4/8 + 16 MB** (new, §5) | 62,014 / 10.42 / 591 / 605 | **47,500 / 6.9 / 393 / 403** | 75,081 / 10.28 / 68.5 / 72.2 (FP8 KV) | 57,500 / 6.8 / 45.6 / 48.1 | +2.33 dB, corners closed |
| robust as proposed (KV8, 2 MB) | 47,766 / 9.63 / 512 / 549 | 35,400 / 6.4 | as above | as above | +2.33 dB |
| r01, search winner | 53,864 / 10.45 / 547 / 690 | 43,600 (circuits) / 44,258 (system): compounds to about 35.8k | 98,524 / 13.90 / 90.9 / 100.1 | about 66k | **disqualified** |
| maximalist | 96,564 claimed (TP-8, CB, 96 MB); plain joint rescore 46,578 / 20.0 | 41,600 at η = 0.85 | 102,035 / 17.33 (plain) | about 73k | **disqualified** |

**Lexicographic result, ARCH:**

| design | tok/s (corrected) | TOPS/W |
|---|---|---|
| pick | 48.7k | 9.3 |
| notes_native | 48.9k (tie within resolution; its bandgap is infeasible) | 9.3 |
| robust + KV 4/8 | 47.5k | 6.9 |
| robust | 35.4k | 6.4 |

r01 and maximalist are disqualified.

**Under Sohu** the order is the same: pick 72.5k, then robust 57.5k.

### The near-tie is new, and it matters

Robust's tile with the pick's KV format and buffer sits only **2.5 %** behind the pick on tok/s.
That gap is inside the model's resolution. It also rests on something unproven:

- the pick's correction *assumes* its corner closure costs 0.89x (P);
- robust's corners are already closed (D).

If V3 shows the pick's closure costs more than about 0.87x, robust + KV 4/8 wins tok/s. The pick
still wins TOPS/W (9.3 against 6.9) and tok/W. Robust + KV 4/8 is the named **fallback** in
`ARCH_CHOSEN.md` §6.

### Converter correction, my own check (D)

I patched `n6_readout.adc` on the pick (energy ×2, time ×1.25) and got 61,824 / 10.13 / 576 / 589.
That is milder than the judge's ratio. With the 0.89 corner closure it compounds to 54,800. Under
the pessimistic rule the scoreboard uses the judge's ratio.

At ×4 energy and ×1.5 time the pick falls to 37,964 / 6.29. **The converter is the single largest
swing.**

## 3. Against the systolic baseline and the Sohu-equivalent

The baseline is `baseline_systolic.py`, run in two versions:

- with the ppa.json PE: **D-PE**, from ASAP7 open-source synthesis of `digital/sysreference`
  (commit b08c37f);
- with the literature PE: **P**.

Under N8's fairness rule it gets the pick's KV 4/8 format under ARCH. The pick's numbers are with
T2.

**ARCH conditions**

| baseline | tok/s | TOPS/W | tok/W | tok/J | pick corrected / baseline (tok/s, TOPS/W, tok/W, tok/J) | pick as scored / baseline (tok/s, TOPS/W) |
|---|---|---|---|---|---|---|
| W8 KV8, ppa PE | 41,356 | 7.66 | 424 | 839 | 1.18x / 1.22x / 1.30x / 0.66x | 1.64x / 2.03x |
| W8 KV8, lit PE | 46,401 | 17.74 | 811 | 1,339 | 1.05x / 0.53x / 0.68x / 0.41x | 1.46x / 0.88x |
| **W8 KV4/8, ppa PE** (lever-matched) | 46,398 | 10.61 | 600 | 968 | **1.05x** / 0.88x / 0.92x / 0.57x | 1.46x / 1.47x |
| **W8 KV4/8, lit PE** (lever-matched) | 61,005 | 18.30 | 939 | 1,705 | **0.80x** / 0.51x / 0.59x / 0.32x | 1.11x / 0.85x |
| W4 KV4/8, lit PE (strongest) | 68,846 | 18.49 | 992 | 1,884 | 0.71x | 0.99x |

**Sohu conditions** (FP8 weights and KV fixed, B = 1000, TP-8, 1,063 mm²)

| | tok/s | TOPS/W | tok/W | tok/J | tok/s/mm² | tok/s/mm²/W | pick corrected / this |
|---|---|---|---|---|---|---|---|
| **Sohu-equivalent** = systolic ppa PE (D-PE / P) | 62,571 | 10.81 | 71.9 | 124.3 | 58.8 | 0.0717 | **1.16x** / 0.83x / 0.90x / 0.55x |
| systolic, lit PE | 86,229 | 18.77 | 119.8 | 255.6 | 81.1 | 0.124 | **0.84x** / 0.48x / 0.54x / 0.27x |
| pick, as scored | 101,125 | 14.94 | 97.2 | 104.1 | 95.1 | 0.099 | |
| pick, corrected | 72,500 | 9.0 | 64.8 | 68.7 | 68.2 | not derived (the corrections do not give die power) | |

**The extra (unranked) metrics under ARCH:**

| | tok/s/mm² | tok/s/mm²/W |
|---|---|---|
| pick, as scored | 679 | 10.3 |
| pick, corrected | 487 | |
| lever-matched ppa baseline | 464 | 7.0 |

**Reading.**

- The king metric is won against the synthesized PE under both sets, by 1.05x and 1.16x.
- Against the literature PE it is lost under both sets once the tile corrections are applied.
- TOPS/W and tok/J are lost against the literature PE in every frame.
- Two unknowns decide whether the IMC is worth building:
  - which PE frame is right (the ppa.json PE is open-source synthesis, not signoff);
  - the ladder's measured converter, merge, drive and corner numbers.

## 4. Why not the others

- **r01, r02, r03 (the search winner's family).**
  - A system ceiling pins them at 53,864 (B = 368 at the KV limit).
  - Their gate pass rests on an unmeasured 6 dB credit, and they under-charge activation spill by
    18 %.
  - With KV 4/8, r01 would score 75,247 (P), above the pick. **It does not count: it fails G2.**
- **maximalist.**
  - The system levers (TP-8, continuous batching, 96 MB) are priced and legitimate, but they are
    symmetric: the literature-PE baseline with the same levers reaches 83.0k.
  - Its tile sits at +0.04 dB on the unmeasured credit, which disqualifies it.
  - Its `sar_vtc_pool` converter is the furthest past the speed envelope (Schreier FoM 184.0 dB).
  - The levers become a phase-2 system study, applied to both dies alike.
- **robust.** It has the best quality and corner case on the board.
  - As proposed (KV8, 2 MB), it loses tok/s to every baseline frame once corrected.
  - With the pick's KV format and buffer, it is the fallback (§2).

## 5. Transforms, stacked (all P; conditional ones flagged)

Here are the transforms from `LIT_SYSTOLIC_ALGOS.md` §4.2 applied to the pick, the runners-up and
the baseline, re-scored in the joint frame (`dec_xf.py`):

| | transform | evaluator delta |
|---|---|---|
| T1 | 2:4 sparsity | passes ×0.575, weight bytes ×0.625, useful MACs ×0.5, e_pass ×0.957; baseline passes ×0.55 |
| T2 | accumulator chain | psum buffer bytes replaced by a 24-b add + hop per column: 37 fJ at 50 µm, **90 fJ at 138 µm** (used) |
| T3 | DPS-48 with a column adder | `dps48`, `bil_c_terms = 0.26` |
| T4 | 4-b lattice codebook | weight bytes ×0.5, +2.2e7 rail ops per token |
| T5 | analog psum across K = 2 tiles | `analog_psum`, `psum_K = 2` |
| KV4 | the KV 4/8 format | already in the pick under ARCH; Sohu fixes FP8 KV |

The baseline gets T1, T4 and KV 4/8, because those help it equally. T2, T3 and T5 are
analog-specific.

### 5.1 Each transform on the pick, as scored

The pick's searched point is ARCH 67,922 / 14.84 and Sohu 97,064 / 13.36.

| transform | ARCH | Sohu | status |
|---|---|---|---|
| T2 accumulator chain (138 µm hop) | 67,922 / **15.56** / 825 (+5 % TOPS/W; +10.5 % at 50 µm) | **101,125 (+4.2 %)** / 14.94 (Sohu is power-capped, so lower energy buys VDD) | **adopted** |
| T1 2:4 | **91,945 (+35 %)** / 12.69 / 1,247 | **130,362 (+34 %)** / 12.01 | conditional (quality) |
| T4 lattice codebook | 77,785 (+14.5 %) / 14.85 | **95,289 (−1.8 %)**: the rail's FWHTs land on an attention-bound prefill | conditional (quality); negative alone under Sohu |
| T5 analog psum, K = 2 | **infeasible**: −0.59 dB against a +0.05 dB margin | infeasible | rejected for the pick |
| T3 DPS-48, column adder | **infeasible**: −0.13 dB against +0.05 dB | infeasible | rejected |
| T3 + bit-serial drive (bought +0.15 dB) | 60,098: below the bit-serial pick without T3 (61,740) | 59,719 | rejected: net negative even when feasible |
| T1 + T2 | 91,945 / 14.30 / 1,363 | 130,362 / 14.27 / 172.0 | conditional |
| **T1 + T2 + T4** (the full feasible stack) | **100,432 / 13.49 / 1,347 / 1,381** (138 µm hop) | **135,048 / 13.55 / 165.5 / 175.4** | conditional |
| + T5 or + T3 | infeasible | infeasible | — |

### 5.2 Winner and runners-up, searched against stacked

These use the full feasible stack, with judge corrections applied as ratios (P; the ratios were
fitted on the unstacked designs).

| design | ARCH searched, corrected | **ARCH stacked, as scored / corrected** | Sohu searched, corrected | **Sohu stacked, as scored / corrected** |
|---|---|---|---|---|
| **pick** (T1 + T2 + T4) | 48,700 / 9.3 | 100,432 / **72,000 / 8.1** | 72,500 / 9.0 | 135,048 / **96,800 / 8.1** |
| robust + KV 4/8 + 16 MB (T1 + T2 + T4) | 47,500 / 6.9 | 93,117 / **71,300 / 6.6** | 57,500 / 6.8 | 124,549 / **95,400 / 6.4** |
| robust + T5 (T1 + T2 + T4 + T5; robust's 2.33 dB margin can pay for T5) | — | 94,482 (2 MB) / about 70,600 / 8.3, margin 1.22 dB | — | 123,167 / about 94,300 / 8.2 |
| r01 (disqualified), KV 4/8, T1 + T2 + T4 | (35.8k) | 109,863 / (about 73k) | (about 66k) | 147,940 / (about 98k) |
| maximalist (disqualified), KV 4/8, T1 + T2 + T4 | (41.6k) | 91,191 / 22.7 | (about 73k) | 146,257 |

### 5.3 Do the transforms change the ranking?

**No.** The pick stays first on the king metric under both sets. Its lead over robust shrinks
to about 1 % (ARCH) and 1.5 % (Sohu). The disqualified designs stay disqualified, because no
transform repairs a G2 failure.

The one structural change: **T5 is usable only on robust's margin.** So if the ladder hands the
pick extra margin, or moves the decision to robust, T5 comes back.

### 5.4 The analog-vs-baseline ratio, with the transforms applied to both

The baseline takes its own best feasible stack. Its T1 + T4 under Sohu ppa (93,522) scores below
T1 alone (103,656), a non-monotone model artefact, so the higher one is used.

| frame | baseline searched | baseline stacked | pick/baseline, searched (as scored / **corrected**) | pick/baseline, stacked (as scored / **corrected**) |
|---|---|---|---|---|
| ARCH, ppa PE (KV 4/8) | 46,398 | 82,124 (T1 + T4) | 1.46x / **1.05x** | 1.22x / **0.88x** |
| ARCH, lit PE (KV 4/8) | 61,005 | 94,015 (T1 + T4) | 1.11x / **0.80x** | 1.07x / **0.77x** |
| Sohu, ppa PE = Sohu-equivalent | 62,571 | 103,656 (T1) | 1.62x / **1.16x** | 1.30x / **0.93x** |
| Sohu, lit PE | 86,229 | 121,677 (T1 + T4) | 1.17x / **0.84x** | 1.11x / **0.80x** |
| off-condition: Sohu with KV 4/8 on both, ppa / lit | 71,149 / 103,412 | 114,080 / 158,943 | — | 1.60x / 1.15x as scored |

**Loud negative: the transforms lower the analog advantage.**

- 2:4 lifts the ppa baseline by +65 to +77 %, and the tile by only +35 %. The baseline's PE
  array halves its work outright. The tile still pays the converter for every surviving pass, and
  its cell gains a 4:1 mux (×1.15 area).
- With the transforms applied to both, the corrected pick **loses** to the synthesized-PE
  baseline under both sets (0.88x ARCH, 0.93x Sohu).
- So no transform gain may be quoted as an analog win except T2 (+5 % TOPS/W, and +4 % tok/s
  under Sohu). T2 is the only analog-specific transform the pick can use.

### 5.5 Overclaims in the transform study, corrected

1. **Frame.** Its 40.0k base and every delta it reports are core-frame. In the joint frame the
   deltas differ (T1: +35 % here against +37 % there; T4: +14.5 % against +13.5 %; T4 under Sohu:
   −1.8 % here against +3 %).
2. **The hop length.** T2's 30 fJ hop assumes 50 µm. The pick's tile is 18,962 µm², about 138 µm
   on a side, so the hop is about 83 fJ. That halves T2's TOPS/W gain (+10.5 % → +4.9 %).
3. **T5 and T3 are infeasible on every Hadamard design except robust.** The study scored them on
   a winner with 0.81 dB of margin. That margin was core-frame, and the joint-frame gate gives
   r01 only 0.26 dB.
4. **2:4 quality.**
   - "98.4 % recovery" is a vendor accuracy figure after 13 B tokens of distillation. It is not a
     ΔPPL.
   - One-shot 2:4 pruning (SparseGPT) roughly doubles wikitext PPL on 7B-class models (P, from
     knowledge). Expect worse on the 135M proxy.
   - So T1 needs counted retraining to have any chance at G1 ≤ +3 %.

## 6. Honest negatives (loud)

1. **The search winner's 53,864 overclaimed by 18 %** (no activation spill), and its gate pass is
   not supported by a measurement. The "1.30x the baseline" headline does not survive.
2. **After correction, no design beats the lever-matched literature-PE baseline on any metric,
   under either condition set.**
3. **The pick sits on the gate edge: +0.05 dB at TT.** At the strict end of A it is infeasible.
   The only margin knobs that cost little are:
   - the bit-serial drive: +0.15 dB for −9 % tok/s;
   - 1 dB more converter SNR.

   A 13-b nominal ADC halves tok/s (38.7k).
4. **The converter carries the case.** 253.5 fJ for 9.63 ENOB at 635 MS/s is a Schreier FoM of
   182.7 dB, 5 to 8 dB past the published SAR envelope above 500 MS/s (P). It is 48 % of tile
   energy.
5. **One third of the pick's tok/s is unverified credit from the joint frame:** the 1:16 charge
   slice merge and the 4-level row drive. Without them the pick reads 44.8k, below the
   lever-matched ppa baseline (§0).
6. **The KV 4/8 quality rests on one proxy, one seed and 512-token windows.** With the tile's noise
   included, the total is +1.04 ± 0.36 %, which leaves no G2 slack.
7. **The judges' converter penalty is itself projected.** It is an envelope argument, not a
   measurement. The ladder replaces it either way.
8. **Transforms help the digital baseline more than the tile** (§5.4).
9. **ARCH_METRIC's Sohu table is stale** (666 mm²; it is 1,063 mm² now, §0).

## 7. What to verify first (ordered by what can flip the decision)

The pass/fail numbers are in `ARCH_CHOSEN.md` §5 and §6.

1. **The converter.** The 12-b pooled SAR (K = 4) at 0.7 V analog: ENOB ≥ 9.63 at ≥ 635 MS/s,
   at ≤ 253.5 fJ.
2. **The 1:16 charge slice merge and the 4-level row drive.** These are the joint-frame credits.
   Verilog-A first, then the V/3 and 2V/3 buffers in ASAP7 SPICE.
3. **The column.** The Verilog-A column (R8 × C256 differential, 2 slices merged, passive charge
   rail): class-weighted SNR_eff ≥ 39.78 dB against the bit-exact golden.
4. **Corner closure** at SS and FF for ≤ 3 % tok/s. Above about 0.87x, switch to robust + KV 4/8.
5. **The buffered reference** under 128 simultaneous conversions.
6. **The gain cell and MOM6 units:** retention, leakage, and 1 fF / 0.25 fF mismatch. Then the
   bootstrapped switch.
7. **Non-circuit:**
   - quality on the analog path (ideal 12-b ADC, static per-cell error);
   - KV 4/8 over 5 seeds;
   - SmolLM2 2:4 and 4-b lattice-codebook ΔPPL, to gate T1 and T4;
   - the T2 adder and hop energy from synthesis.

## Sources

- **Repo:**
  - `ARCH_METRIC.md`, `nodes/N8.md`, `nodes/N1.md`, `nodes/N10.md`
  - `search/SEARCH.md`, `search/quality_spotcheck.json`, `search/designs/winner.json`
  - `architects/{maximalist,robust,notes_native}.md`
  - `lit/LIT_SYSTOLIC_ALGOS.md`, `lit/LIT_STREAMING_LOG.md`
  - in `scripts/compiler/metrics/arch_eval/`: `search.py` (frame definitions),
    `nodes/n4_formats.py` (`tile_effects`, `f_merge`), `designs/notes_native.{py,quality.json}`
    and `designs/robust.result.json`
- **Notes:**
  - 27l2: KV intensity caps B.
  - 27l10: sink and recent protection.
  - 27i1: a capacitor ratio cancels PVT.
  - 27i5: a nominal-corner figure says nothing about a macro.
  - 27h1: the converter law.
  - 27n1: precision-normalized TOPS/W.
  - 27l1, 27l3: weight reuse and analog psum.
- **Paper:** `sec_attention.tex` (4-b KV with 8 sinks and 120 recent) and `sec_strassen.tex`
  (the bilinear verdicts).
