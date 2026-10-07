# DRIVE_ALT: an alternative B2 row drive (beyond ml2 and bit-serial)

2026-10-06. Motivated by the imc_tile Verilog-A results (`analog/imc_tile/docs/architecture.md`):

- ml2 does not settle: 0.64 % against 0.1 %.
- Bit-serial settles, but t_pass is 7.95 ns against 6.30 ns.
- G2 fails at the measured comparator noise.

Nothing under `analog/imc_tile/`, `digital/imc_driver/` or `scripts/golden/imc_tile.py` was edited. All work is in
scratchpad `drive_alt/`:

| file | what it does |
|---|---|
| `galt.py` | the golden extended with the new modes; self-check PASS |
| `run_acc.py`, `run_acc2.py` | the SNR budgets |
| `sp_rail.py` | ESPice |
| `tok.py`, `score.py` | the evaluator |
| `energy.py` | the delivery energy |

**Labels.**
- **M**: measured, ASAP7 BSIM-CMG in ESPice.
- **D**: derived, a law applied to M.
- **P**: projected.

Every SNR is the golden's error model, with the tb_accuracy block8 data (SmolLM2 attn_q, rotated, 12 chunks) and
the same budget function. It reproduces bit-serial at 42.34 dB and ml2 at 39.94 dB exactly.

## 1. Recommendation

**BS6H.** Keep the bit-serial 0/V rails. Change two things:

- **Shorter slot.** Cut the slot from 7 ticks to 6 (0.849 ns, of which 0.566 ns is rail time).
- **Merge overlap.** Overlap each pass's slice merge with the next pass's first slot, on the ping-pong accumulator
  banks the tile already has.

This gives:

| quantity | value | label |
|---|---|---|
| drive word | 7 × 0.849 = **5.94 ns**, against the converter's 6.25 ns (t_pass 6.30–6.53 ns) | D, on the RTL tick plan |
| added devices | none; the change is a schedule change | |
| area | +0 | |
| drive energy | the same as bit-serial | |
| G2 (block8, 86 µV comparator) | **41.14 dB (+1.36)** at the measured supply droop of a 1.3 Ω tile PDN; **≥ 42.2 dB (+2.45)** once the droop is held below 0.1 % | M droop → D SNR |

The settling criterion (≤ 0.1 %) fixes the tile PDN:

- **PDN spec (preferred).** R_PDN ≤ 0.4 Ω per tile with no slow local decap. Measured: 0.078 % worst case
  (8 rows on V, TT) at the 6-tick share edge.
- **Fallback.** If the PDN cannot reach that, add constant-charge dummies (BS6H-cc). The droop then becomes a
  calibrated static gain, with a 0.067 % residual at 3 % dummy tracking.

BS6H beats both references:

- **Against bit-serial:** 2.0 ns faster for −1.0 dB of G2.
- **Against honest ml2:** +1.2 dB and faster (6.89 ns). It needs no mid-level buffers (no 7 mW per tile of SSF
  bias).

**The one observation that kills it:** an extracted tile PDN (bumps + mesh + whatever decap the tile carries) on
which 8 rows switching 0 → V leave more than 0.1 % plate error at 0.566 ns. That forces constant charge. Under the
imc_tile delivery accounting, cc doubles the rail energy (205 against 108 pJ per pass). The ARCH die then hits its
power cap: tok/s falls to 52.4k, below plain bit-serial.

## 2. The decisive measurement: the grid-driven rail is worse than the law (E1, M)

Deck: `sp_rail.py`. Per row:

1. an RVT inverter of 4096 fins (128 segments × 32 fins, the N2_r2 lead);
2. the segment strap and 0.3 pF of rail wire;
3. the crosspoint TGs (2048 fins);
4. 7.17 pF of bottom plates;
5. one explicit 56 fF floating top plate.

All 8 rows hang on one tile supply, `R_PDN` from 0.7 V. The error is the plate error at the share edge, by slot
length in ticks; rail time = (T − 2) × 141.5 ps.

| PDN | rows on V | 5 t | 6 t | 7 t | 8 t | golden law at 7 t |
|---|---|---|---|---|---|---|
| 1.3 Ω, no decap (the imc_tile l3 values) | 1 | 0.13 % | 0.011 % | 0.001 % | — | |
| | 8 | 6.66 % | 2.23 % | **0.742 %** | 0.246 % | **0.053 %** |
| 1.3 Ω + 100 pF decap | 8 | 9.72 % | 5.27 % | 2.87 % | 1.56 % | |
| 1.3 Ω + 450 pF decap (the array footprint as MOS decap) | 8 | 7.85 % | 6.34 % | 5.13 % | 4.16 % | |
| 0.5 Ω, no decap | 8 | 0.90 % | 0.145 % | 0.023 % | 0.004 % | |
| **0.4 Ω, no decap** | 8 | 0.57 % | **0.078 %** | 0.011 % | | |
| 0.3 Ω, no decap | 8 | 0.33 % | 0.037 % | 0.004 % | | |
| 0.4 Ω, no decap, **SS** | 8 | 1.33 % | 0.238 % | 0.043 % | | |
| 0.3 Ω, no decap, SS | 8 | 0.90 % | 0.140 % | 0.022 % | | |

Findings:

1. **The level-net law in the golden and `imc_ref.va` understates the 8-row error by 14×.** The law gives 0.053 %;
   the circuit gives 0.742 %. The tile supply sags to 0.437 V and the inverters weaken with it. As a result
   imc_tile check **c5 (bit-serial settles, PASS) would fail on devices**. ml2's V level has the same problem.
   This is for the review agent that owns those files; the measured table is `drive_alt/etab_r13.json`.
2. **Decap makes it worse.** It turns a fast sag into a slow droop that recovers through R·C_dec. The code-dependent
   droop N2_r2 found (α ≈ 1.5 % per row) is confirmed.
3. **The 2:1 cap-split sub-rails behave exactly like bit-serial.** Measured: digit 3 on all rows is identical to
   n = 8; digit 1 on all rows gives 0.014 % (7 t), the equivalent of n = 2.67.
4. **Energy from the source** (M): 31.2 pJ per slot with all 8 rows on (3.9 pJ per row). It is the same with and
   without decap.

## 3. Candidates against the criteria

The criteria:

| | criterion |
|---|---|
| (1) | ≤ 0.1 % settling or code-dependent error, or deterministic and cheaply calibrated |
| (2) | drive word ≤ 6.25 ns |
| (3) | drive energy |
| (4) | G2 ≥ 39.78 dB, block8 operands |
| (5) | area |
| (6) | no SRAM, no PWM |

Notes on the table:

- **G2** uses the measured droop table at R_PDN 1.3 Ω unless the row says "law". The comparator is the 86 µV
  budget.
- **E** is the rail delivery energy per pass in the imc_tile accounting (c_row 7.47 pF, block8 activity), D.
- **tok/s** is ARCH / Sohu, live / judge frame (the evaluator's own energy laws). The chosen design as scored is
  67,760 / 49,369 and 72,220 / 50,835.

| # | candidate | (1) worst-case error | (2) t_word | (3) E | (4) G2 margin | (5) area | tok/s ARCH live / judge | tok/s Sohu live / judge | verdict |
|---|---|---|---|---|---|---|---|---|---|
| **R1** | **BS6H**: bit-serial, 6-t slots, merge overlapped, R_PDN ≤ 0.4 Ω | 0.078 % (M, TT); 0.24 % at SS | **5.94 ns** | 108 pJ | +1.36 at 1.3 Ω (M→D); ≈ +2.4 at 0.4 Ω | 0 | **67,969 / 61,872** | **91,573 / 72,220** | **lead** |
| R1' | BS6H-cc (constant-charge dummies, if the PDN fails) | static 2.23 % gain, calibrated; residual 0.067 % at 3 % dummy tracking | 5.94 | 205 pJ | +2.45 | +1.1k µm² (dummies + drivers, N2_r2 P) | 66,421 / 60,274 (52,377 / 41,206 with imc delivery) | 91,573 / 72,220 | viable fallback; energy-limited |
| R2 | **cr2**: capacitor-ratio 2 b/slot. Each weight's units are split 2:1 into hi/lo sub-stacks; 4 rails per row, all 0/V; ml2's digit stream and radix-4 column | 0.742 % (M, n_eff 8) | **5.09** (3.96 with the merge overlapped) | **57 pJ** | **−0.04** (M); +0.03 (law); 0.00 at a 0.1 % systematic split error, −0.12 at 0.3 % | +6 T per weight bit (a second rail mux per sub-stack): +0.71 µm² per weight beyond the FEOL slack, **+2.26k µm² per tile (+12 %)** (D) | 64,899 / 58,734 | 91,573 / 72,220 | viable, dominated on G2 and area. It is the best on energy and time (64.9k ARCH even with imc delivery) |
| R3 | hybrid k_dig 2: the top 2 planes in a per-column digital adder tree, 5 analog bit-serial planes | 0.742 % (M) | 4.95 hidden / 6.08 | 77 + 32.5 pJ tree | **+14.7**; **+4.23 at the measured 4.05 mV comparator** | +6.2k µm² per tile (+33 %, n2 `_dig` liberty FA/NAND, D); the weight bits feed logic gates | 60,228 / 53,978 | 87,662 / 58,438 | infeasible on area; **the only drive change that rescues the comparator** (k1: +8.7 dB at 86 µV) |
| R4 | ml2 on die-level mid-rail nets (N9_r2 `n9_ml2_buf=pdn`) | each net has the same droop law (M, as V): 0.25 % at 8 t, 1.3 Ω | 5.66 | 57 pJ × η 0.5 regulator | +0.16 (law) | tile 0; 2 die nets + a 3:1 regulator (P) | 67,876 / 61,776 | 97,064 / 72,220 | viable; G2 thin, needs 2 extra die supply nets |
| ref | ml2 + SSF buffers (imc_tile) | 0.64 % (imc_tile) | 6.89 honest (1.44 ns slot) | 57 pJ + 7 mW per tile static | +0.16 | 0 | 65,351 / 49,369 | 72,220 / 50,835 | fails (1) and (2) |
| ref | bit-serial 7 t (imc_tile RTL) | 0.742 % (M) | 7.95 | 108 pJ | +2.37 (M) | 0 | 61,623 / 61,623 | 89,758 / 72,220 | fails (2) |
| x1 | bit-serial, 6 t, merge overlapped, no cc, **at 1.3 Ω** | 2.23 % (M) | 5.94 | 108 pJ | +1.36 | 0 | as R1 | as R1 | fails (1) unless the PDN is ≤ 0.4 Ω (that is R1) |
| x2 | unequal slots (5,5,6,6,7,7,7 LSB first) | law: 0.095 % weighted; **M: 0.99 % weighted** (6.66 % on the LSB planes) | 6.08 hidden | 108 pJ | +2.56 (law) | 0 | — | — | killed by E1. With cc, every plane gets its own static gain: a nonlinearity in x that affine calibration cannot remove |
| x3 | cr2b: balanced complementary rails (constant charge with no dummies, two's-complement digits) | static gain | 5.09 | 117 pJ | **−0.87**: mismatch falls to 43.8 dB because the weight-dependent offset Σw/2 carries the unit mismatch, and it changes every load | 0 extra beyond cr2 | — | — | dominated |
| x4 | 3-level (0, V/2, V), radix 3 | mid-level buffer, as ml2 | 5 slots | | **−5.6 dB on every analog term**: 3⁵ = 243 > 127 wastes the range (D) | | — | — | dominated |
| x5 | overdrive / pre-emphasis | the timing must track popcount and PVT; the error stays code-dependent | | | | a second supply | — | — | not pursued: cc or a stiff PDN does the same job deterministically |
| x6 | bottom-plate sampling (N2_r2 bps2) | M (N2_r2) | 6.56 (0.94 ns slot × 7) | | +0.14 | +5.3 % | 64,188 (N2_r2 live) | | dominated by R1 on time |
| x7 | popcount-dependent settling calibration | the droop multiplies each plane's partial sum, which never exists digitally (only the merged code does) | | | | | | | not calibratable after the merge; cc is its analog form |
| x8 | current-mode / charge-packet injection, PWM | N2_r2 O8: unary packets are dominated (60.1k). On a capacitive cell, PWM only sets how long the plate sits at the level (`n9 drv_pwm` note) | | | | | | | excluded (no PWM unless it wins) |
| x9 | interleaving two tiles' drive slots | the rail charge per slot is unchanged; it only shifts load on a shared PDN | | | | | | | no gain |

**Per-term SNR (dB, block8, measured droop at 1.3 Ω):**

| mode | kT/C | mismatch | drive | others | total / class-weighted |
|---|---|---|---|---|---|
| bit-serial 7 t | 44.45 | 48.25 | 56.0 | as imc_tile | 41.51 / 42.15 |
| BS6H (6 t, 1.3 Ω) | 44.45 | 48.25 | 47.3 | | 40.54 / 41.14 |
| BS6H-cc | 44.45 | 48.25 | 58.3 | | 41.48 / 42.23 |
| cr2 7 t | 41.02 | 47.45 | 58.2 | | 39.43 / 39.74 |

The cc drive term floors at about 58.4 dB whatever the droop. The floor is the B6 calibration requantizing any
static gain error to integer codes (`cal_apply`), about one extra quantization step. It is not the droop.

## 4. Why cr2 is not the lead (radix-4 is a kT/C ceiling)

cr2 does exactly what the ml2 levels were meant to do, with bit-serial physics:

- the input is encoded in capacitor ratios (lithographic, notes 27i1);
- every rail is 0/V;
- it uses half the delivery energy of bit-serial;
- its drive word is 3.96–5.09 ns.

But every 2 b/slot scheme accumulates at radix 4, so C_acc = C_col/3. The hold node then keeps 1/3 of the signal
energy of radix 2 (equipartition: no passive transfer gets it back). kT/C is 41.0 dB against 44.45 dB, and that
leaves ml2's +0.16 dB at best.

The split also needs a second {rp, rn, gnd} mux per weight bit, because weight-sign steering is per crosspoint.
That overflows the cell's 0.65 µm² FEOL slack (feol 2.27, BEOL 2.93 µm² per weight).

One side observation is not in any area model yet:

- Bit-serial's radix-2 ping-pong accumulators need **88 pF per tile**: 256 × 2 banks × 2 sides × (56 + 30) fF.
  Radix 4 needs 29 pF. At 4.78 fF/µm² MOM that is 18.4k against 6.1k µm² (D).
- Neither the evaluator nor ARCH prices these caps. The review owner should put them in the area model. It favours
  ml2/cr2 if they cannot share BEOL with the periphery.

## 5. Integration plan for BS6H

**Verilog-A** (copies only until the review agent releases the files):

- `imc_rowdrv.va`: no change (mode 1, cc available for the fallback).
- `imc_ref.va` as the V net: r_out 0.4 Ω (the spec). Better, replace the linear Thevenin with the measured
  supply-sensitive law (`etab_r13.json`, extended at 0.4 Ω). The linear law understates the droop 14×.
- `imc_col.va`: make the ping-pong explicit. Add a `bank` pin, two `vacc` sets, merge and reset of bank b while
  shares go to bank 1 − b. Today the merge event resets the only accumulator set.
- `imc_xp.va`: no change.

**RTL** (`imc_seq.v`, `imc_driver.v`):

- `SlotTicks = 6` for bit-serial.
- Add a `bank_q` that toggles each pass, and output `bank_o` to the tile.
- After the last slot, go straight to the next pass's `StDrive` whenever no array write is pending. Assert
  `phi_mrg` on the idle bank during the first slot, then `phi_samp` for the converter on that bank.
- Keep `StMerge` and the 8-tick write window only on passes whose weights change. That is 1 per B vectors per
  load (B = 587 at decode): negligible.
- `merge_ok`'s conversion handshake stays: a new sample may not start before the previous conversion ends.
- The steady-state t_pass then equals the conversion: 44 ticks + 2 handoff = 6.53 ns. That is finding 5's converter
  term, not the drive.

**Golden** (`imc_tile.py`, owner):

- `slot_ticks_bs = 6`.
- `timing()`: `t_word = n_slots · slot` plus the merge only on weight-change passes.
- The drive law: replace it with the measured table (galt's `E_TAB` mechanism).
- Add `merge_hidden` to the contract.

**Evaluator:**

- `n9` `drv_inv_bitserial` with a 0.849 ns slot and the merge slot removed from t_word (7 × 0.849 = 5.94 ns).
- A new R_PDN ≤ 0.4 Ω per tile supply spec, priced in die-level bump/mesh metal (P).
- The cc fallback as `const_charge`, already priced in n2 `charge_rail_bps2_cc`.

**V-tests that confirm it:**

1. Extract the tile PDN and re-run E1 at 6 ticks with 8 rows on. Pass: ≤ 0.1 %.
2. Run the co-sim with the overlapped merge. Pass: bit-exact chain; G2 ≥ 39.78 with the measured table.

**SS corner:** 0.24 % at 0.4 Ω, so SS needs 7-tick slots or R ≤ 0.25 Ω. This is part of the open corner-closure
item.

## 6. Tok/s impact

From `tok.py`, the chosen stack with the drive's t_word, energy and area replaced. The `imc` columns add the
imc_tile delivery energy to the evaluator's.

| | ARCH live | ARCH judge | ARCH live (imc) | Sohu live | Sohu judge | Sohu live (imc) |
|---|---|---|---|---|---|---|
| chosen, ml2 as scored (infeasible drive) | 67,760 | 49,369 | 60,098 | 72,220 | 50,835 | 59,719 |
| ml2 SSF, honest slot | 65,351 | 49,369 | 60,098 | 72,220 | 50,835 | 59,719 |
| bit-serial 7 t (imc_tile) | 61,623 | 61,623 | 61,623 | 89,758 | 72,220 | 72,220 |
| **BS6H** | **67,969** | **61,872** | **65,920** | **91,573** | **72,220** | **72,220** |
| BS6H-cc | 66,421 | 60,274 | 52,377 | 91,573 | 72,220 | 59,719 |
| cr2 | 64,899 | 58,734 | 64,899 | 91,573 | 72,220 | 80,753 |
| hybrid k2 | 60,228 | 53,978 | 60,228 | 87,662 | 58,438 | 72,220 |

BS6H against bit-serial: **+10.3 % ARCH live, +0.4 % judge, +2.0 % Sohu live, 0 % Sohu judge** (Sohu is
attention-bound). Against the chosen design as scored: +0.3 % and +25 % (judge, ARCH).

## 7. Runs

ESPice (ASAP7, `$ASAP7_ROOT/models/espice/asap7.lib`, 0.7 V, 27 °C; every run under the shared lock with
MemoryMax 4 G):

| run | file | what it covers |
|---|---|---|
| E1 | `sp_rail_base.json` | TT, R_PDN 1.3 Ω, no decap: bit-serial n = 1, 2, 4, 8 and six cr2 digit patterns |
| E2 | `sp_rail_pdn.json` | TT, decap 100 / 450 pF at 1.3 Ω and 0.5 Ω, and 0.5 Ω with no decap |
| E3 | `sp_rail_rspec_tt.json`, `sp_rail_rspec_ss.json` | R_PDN 0.3 / 0.4 / 0.5 Ω, TT and SS |

Golden budgets:

- `acc_all.json`: law;
- `acc_meas.json`, `acc_meas2.json`: measured table;
- the hybrid at the 4.05 mV comparator is in `acc_meas2.json`.

Not simulated: the MOM split ratio (ASAP7 has no MOM mismatch data, so it stays P) and the PDN extraction.
