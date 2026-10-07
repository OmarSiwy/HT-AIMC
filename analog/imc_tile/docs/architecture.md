# imc_tile: the upgraded IMC tile, Verilog-A and ASAP7 transistor level

2026-10-06. This block implements the tile of `docs/src/content/Project/ARCH_CHOSEN.md` after the tile
upgrade: BS6H bit-serial row drive (`ArchResearch/nodes/DRIVE_ALT.md`), the E-trim noise-aware SAR
(`ArchResearch/nodes/COMPARATOR_ALT.md`), 3 columns per converter, and block-8 operands with the dequant
multiply in the RTL. It covers B1 to B6 and B10 in Verilog-A (`va/`) and, for B1 to B5, as a
transistor-level ASAP7 netlist (`netlist/imc_tile.py`, §5). A digital driver (`digital/imc_driver`) runs the
tiles the way a weight-stationary systolic array is run, on the same jobs as the systolic reference
(`digital/sysreference`).

**Labels.** M = measured (ASAP7 ESPice: this block's transistor runs, or the round-2 / DRIVE_ALT /
COMPARATOR_ALT reports). D = derived (a law applied to M). P = projected (an ARCH_CHOSEN target). The
Verilog-A results are simulations of models whose parameters are M, D or P as listed.

## 1. What is built

| block | file | what it models |
|---|---|---|
| B1 gain-cell store | `va/imc_gc.va` | One weight per instance: 8 storage nodes (sign + 7 magnitude bits), a continuous sample-and-hold write through WL, retention droop to vmin1 in t_ret |
| B1/B3 crosspoint | `va/imc_xp.va` | Unit caps of one weight (2^b units per bit, frozen mismatch σ·√units). Each row's contribution to the four top plates is `q = units·cu·V(rail)/C_slice`. Sign steering: side + follows rp for w ≥ 0 and rn for w < 0 |
| B2 row drive | `va/imc_rowdrv.va` | Per row: two rails (rp, rn) of c_row. Bit-serial (`law 1`): every rail on V charges with τ(n) from the measured droop table (n rows on V, dummies counted), the golden's `E_TAB` at R_PDN 0.4 Ω. ml2 (`law 0`, replaced): r_sw onto the level nets. Optional constant-charge dummies |
| B5 reference / level nets | `va/imc_ref.va` | A Thevenin source (v0, r_out, c_dec) with class-A supply accounting: the C-DAC reference and the ml2 levels |
| B3 column + merge | `va/imc_col.va` | Event model: top-plate reset with kT/C; per-slot share onto bank `V(bank)` (two banks) with incomplete settling and kT/C; at `phi_mrg` the idle bank merges 1:16 (ratio error, kT/C) and resets |
| B4 SAR | `va/imc_sar.va` | Pooled-round SAR: samples AS columns, converts one per sar_clk round in NDEC + 1 timed steps of the E-trim bipolar search (6 fast decisions, the redundant 32-LSB step, 7 quiet ones, a σ per class). Each step draws its C-DAC charge from vref and each decision reads V(vref) at its instant |
| B4 SAR logic | `va/imc_sar_logic.va` | The transistor converter's asynchronous decision loop: comparator clocks, bank/column enables, the 12 step caps' bottom-plate controls, the code |
| transistor tile | `netlist/imc_tile.py` | ASAP7 SpiceRack netlist of B1-B5 (§5) |
| B6, B10, requant | `digital/imc_driver/src/imc_chain.v` | Code capture (converters may serve fewer columns than AdcShare), per-column affine calibration, the block-8 dequant `(c·sig_x·sig_w) << (14 − e_x − e_w)`, the chain (24 b, 52 b with block-8) across K-adjacent tiles, the edge accumulator, requant to INT8 (6-b shift) |
| driver | `digital/imc_driver/src/imc_driver.v`, `imc_seq.v`, `imc_wstage.v` | Descriptor schedule with systolic skew, HBM weight stream into ping-pong stage banks, just-in-time array writes in a write window that opens only on weight-change or refresh passes, stalls when weights are late, refresh every `RefreshPasses`. `imc_seq`: BS6H slots, the hand-off of each driven bank to a merge engine (merge and sample under the next pass), `bank`, `phi_brst`, back-to-back conversions |
| golden | `scripts/golden/imc_tile.py` (+ `test_imc_tile.py`) | Bit-true integer path (incl. block8 codes and dequant) plus the analog-error model with the same laws and parameter names as the `.va` files |

The tile contract is fixed by the golden's docstring:

- **Weights.** Sign-magnitude, |w| ≤ 127. Two slices: hi = |w| >> 4 (7 × 1 fF) and lo = |w| & 15 (15 × 0.25 fF).
- **Activations.** Sign-magnitude rows, |x| ≤ 127, 7 bit-serial planes on 0/V rails; each column swings 0 to VDD.
- **Converter scaling.** One code is 64 MAC units (vref = 1.411 V differential peak-to-peak): the ideal code is
  `floor((S + 32) / 64)`, and the E-trim search reaches it exactly when noise-free.
- **Block-8.** Each 8-row block of x (per token) and w (per column) carries a scale byte (3-b exponent, 5-b
  mantissa) under a per-tensor / per-column base. Dequant per conversion; the chain sum is
  `acc · base_x · base_w / 2^20`.
- **Calibration and requant.** cal is `(g·code + o + 2^13) >> 14`. Requant is the systolic reference's formula
  on `64·acc` with a 6-b shift.

### Choices made here (stated plainly)

1. **Signed activations.** The activation sign rides a second rail per row (rp/rn); the weight sign picks
   which rail its units follow. Offset-binary would cost about 12 dB at 1 % unit mismatch.
2. **Full rail.** 7 bit-serial planes put each column at up to VDD (+6 dB on every noise term against VDD/2).
3. **AdcShare 3** (§4.1): 3 rounds of 13 ticks hide under the 42-tick drive. 256 / 3 leaves one converter with
   one column (86 converters); the RTL and the golden handle the short converter.
4. **Hidden merge.** At the end of a pass the sequencer hands the bank to a merge engine and starts the next
   pass at once; `bank` flips one tick later (never on the edge that closes the last share), the merge
   falls two ticks into the next pass, and the sample waits for the converter. The RTL waits (StWait) only
   when the previous bank has not been sampled yet. The write window opens only when a tile needs new
   weights or a refresh.
5. **Block-8 scale format.** 5-b mantissa: 0.11 dB below exact scales; E4M3's 3-b mantissa costs 0.45 dB
   (quick budget, 6 chunks: exact 40.75 / 3-b 40.30 / 5-b 40.64 dB at TT). The x scale rides the activation
   word; the w scales come from a per-(group, tile) table (ponytail: a real tile latches its 256 bytes with
   the weight load, +12.5 % of the stream).
6. **Pooling.** pool_k = 1: block-8 scales differ per tile, so tiles cannot be charge-pooled.

## 2. Parameters (defaults)

| parameter | value | label / source |
|---|---|---|
| rows × cols, slices | 8 × 256 differential, 2 (7 × 1 fF, 15 × 0.25 fF) | P (ARCH B1) |
| C_slice, C_acc | 56 fF (MSB), 30 fF (LSB); C_acc = C_slice per bank, 2 banks; merge rho = 0.134 (1:16) | D |
| VDD_A | 0.7 V | P |
| t_tick, slot | 141.5 ps (RTL 142 ps); BS6H 6 ticks = 0.849 ns: reset 1, rails to the share edge 4 (0.566 ns), share 3 ending one tick before the slot end | D (DRIVE_ALT) |
| drive law | measured plate error at the share edge, R_PDN 0.4 Ω (golden `E_TAB`, TT and SS; 1.3 Ω kept for comparison): 8 rows on V 0.078 % (TT), 0.238 % (SS) | M (DRIVE_ALT E3) |
| c_row, τ_row | 7.47 pF, 16.1 ps (ml2 level-net law only) | P, M-fit (N2_r2) |
| τ_col | 39.2 ps | M-fit (N2_r2); the transistor tile measures far slower share settling (§5) |
| unit mismatch | 1 % at 1 fF, 2 % at 0.25 fF | P |
| merge / acc ratio σ | 0.1 % / 0.1 % | P |
| SAR | E-trim: 13 decisions (steps 1024 .. 32, 32, 16 .. 1), σ 1.82 mV fast / 0.654 mV quiet at TT, 1.99 / 0.747 FF, 3.35 / 0.585 (trimmed) SS; t_conv 1.61 ns; 276.8 fJ; 13-tick rounds; AdcShare 3 | M (σ), D (schedule, time, energy) |
| C-DAC | unit σ 2.45 %, mid-scale and every step cap carry σ·√units (bipolar search); c_dac 60 fF | D; P |
| reference | r_ref 0.5 Ω behind c_ref 200 pF, shared by the tile's converters | P; D |
| block-8 scales | per-tensor x base, per-column w base; scale byte 3-b exponent + 5-b mantissa | D (this block) |
| gain-cell refresh | every 128 passes (0.76 µs at 5.94 ns) | D (inside ARCH's 1.32 µs 6σ retention) |
| gain cell | write 0.631 / −0.072 V, 44.3 ps to 99 %, 0.52 fJ per '1', retention 2.08 µs to vmin1 0.58 V | M (N3_r2) |

## 3. How to run

```sh
./env.sh mixed                                  # vera, espice, iverilog, numpy, cktimg-json
python3 scripts/golden/test_imc_tile.py         # golden self-check
make -C digital/imc_driver test                 # driver RTL + ideal tiles, systolic + block8 jobs, bit-exact
make -C analog/imc_tile lint units              # vera lint + ESPice unit benches of B1-B5
make -C analog/imc_tile cosim                   # RTL -> Verilog-A tiles -> RTL chain, bit-serial (BS6H)
make -C analog/imc_tile timing accuracy         # t_pass / stalls / settling; SNR per term, corners
make -C analog/imc_tile netlist schematics      # transistor netlist -> output/netlist, cktImg -> output/schematics
make -C analog/imc_tile spice                   # ESPice checks of the transistor netlist (about 40 min)
python3 analog/imc_tile/netlist/imc_tile.py --sim settle --gcbuf --fins xp_tg=4,smx=8   # sizing sweeps
cd analog/imc_tile/test && python3 tb_cosim.py ml2 ideal                                 # ml2 (replaced)
```

Do not wrap these benches in an outer `flock` on the shared lock file: `va_lib` and `netlist/imc_tile.py` take
the lock per ESPice run (an outer holder sets `SPICE_LOCK_HELD=1` for `va_lib`). Every run is capped at 4 GB.

The co-simulation is **open loop**, as before: ESPice holds at most 64 unknowns per device, so the 192-pin driver
cannot be a `.v` device. (1) the driver RTL runs in iverilog with ideal tiles and writes a pin trace (now with
`bank`); (2) ESPice runs the Verilog-A tiles from that trace; (3) the RTL runs again with each tile replaced by
its ESPice codes. Configuration: 2 tiles of 8 rows × 8 columns, 3 E-trim SARs per tile (3, 3 and 2 columns).

## 4. Results (2026-10-06, the upgrade)

### 4.0 Verdict

- **The upgraded tile meets G2 at TT in its own operand format** (Verilog-A laws, block-8 SmolLM2 data,
  24 chunks): class-weighted 40.62 dB, 90 % interval [40.30, 40.94], margin **+0.84 dB**, no V2 per-term
  failure. FF passes at +0.25 dB but its interval reaches 39.71 (MARGINAL).
- **SS fails by 0.07 dB** at 0.63 V and 373 K (kT/C 42.5 dB binds, not the drive: 7-tick slots give −0.04).
  Holding the signal rail at 0.7 V on SS dies (adaptive VDD) passes at **+0.53 dB**.
- **t_pass 5.96 ns** on the RTL (42 ticks, drive-bound), against round 1's 6.30 ns target and 7.95 ns for the
  plain bit-serial tile. AdcShare 4 would be 7.38 ns.
- **The digital path is bit-exact**: 25 driver cases including block-8 dequant, the 4-tile chain, refresh,
  starved HBM, AdcShare 2/3/4 and SmolLM2 attn_q; the Verilog-A co-simulation matches the golden.
- **The transistor-level tile does not yet meet the BS6H slot** (§5). The comparators reproduce their measured
  noise and the converter converts, but the share event kicks the bottom plates, and the crosspoint chain of
  N3_r2's gain cell recovers in about 130 ps: 5.4 % plate error at the 6-tick share edge (the golden assumes
  39 ps; run through the golden, 133 ps costs about 8 dB of G2). DRIVE_ALT's 0.078 % measured the rail
  without the share. Buffered gate drive and 4× crosspoint switches bring it to 0.51 %, still 5× the spec.

### 4.1 AdcShare 3 or 4

The conversion takes AdcShare × 13 ticks: 52 ticks at 4 columns per converter, which binds the pass (7.38 ns on
the RTL), and 39 ticks at 3, which hides under the 42-tick drive (5.96 ns). Scored with `arch_eval` (live frame;
a scratch patch of `model.tile` with the BS6H word, the E-trim conversion, 256 × 276.8 fJ, converters at 1.30×
area, the 108 pJ drive delivery and the ping-pong bank caps; `arch_eval` itself untouched):

| | ARCH tok/s | ARCH TOPS/W | Sohu tok/s | Sohu TOPS/W |
|---|---|---|---|---|
| **AdcShare 3**, bank caps priced (88 pF, 18.4k µm²) | **49,168** | **13.21** | **69,002** | **12.60** |
| AdcShare 4, bank caps priced | 43,196 | 12.78 | 59,615 | 12.16 |
| AdcShare 3, bank caps in shared BEOL | 66,565 | 11.60 | 72,220 | 11.00 |
| AdcShare 4, bank caps in shared BEOL | 61,312 | 11.20 | 72,220 | 10.80 |

AdcShare 3 wins on tok/s in every frame (+8.6 to +16 %) and on TOPS/W (+3 to +4 %), for 86 instead of 64
converters (+1.2k µm² per tile). The ping-pong bank caps, which neither ARCH nor the evaluator priced, cost
26 % of ARCH tok/s if they need their own MOM area.

### 4.2 Unit benches (ESPice, `test/tb_va_units.py`)

| block | check | measured | result |
|---|---|---|---|
| B1 | write levels; '1' at 1 µs | within 0.06 mV of 0.631 / −0.072 V; 0.6065 V (law 0.6065) | PASS |
| B2 | bit-serial rails on the measured law, share edge (0.566 ns), n = 1 / 4 / 8 rows on V | 0.0032 / 0.0180 / 0.0885 % against the table's 0.0027 / 0.0154 / 0.0780 % | PASS (model = table) |
| B2 | constant-charge dummies: one row sees the 8-row error | 0.0885 % at 1 and 7 rows (0.0032 / 0.0594 % without) | PASS |
| B2 | ml2 (replaced): levels, sign steering, mid levels at n = 8 | exact; mid levels 0.674 % (law 0.637 %), the 0.1 % spec missed | PASS as model = law |
| B3 | merged differential vs k·S, pass on bank 0 merged under bank 1 | ≤ 1.2 ppm of full scale, both modes | PASS |
| B4 | E-trim codes (13 decisions, redundant step) over the range and at the clips | equal to `floor(v/LSB + ½)` at 9 inputs; 0.2768 pJ per conversion | PASS |
| B5 | 86 and 128 converters on one reference, decisions read per step | Verilog-A codes = golden codes exactly; droop at the 13 decisions within 4.6 / 5.1 % of the golden law | PASS (model = law) |
| B5 | droop against ARCH B5's 3.7 µV per conversion | 130 µV per conversion (86 and 128 converters) | **FAIL by 35×** (a calibrated static error: the ref term is 85 dB) |

### 4.3 Checks

| # | check | target | measured | result |
|---|---|---|---|---|
| a1 | driver RTL + ideal tiles vs the bit-true golden: systolic jobs (bit-serial and ml2), 4-tile chain, 8 × 16 tile, AdcShare 2 and 4, **block-8 GEMM / GEMV with dequant**, starved HBM, refresh every 4 passes, SmolLM2 attn_q | bit-exact | **25 of 25** bit-exact; block-8 GEMM 0.7 % rms against the float GEMM | PASS |
| a2 | co-sim, ideal models vs the bit-true golden (4 jobs) | ≤ 1 code per K-chunk | max 1 code; 72–99 % exact | PASS |
| a4 | co-sim, all error terms on: Verilog-A vs golden rms error per job | ratio 0.75–1.33 | 1.27, 1.01, 1.29, 1.12 | PASS |
| b1 | class-weighted SNR_eff, the pick (block-8, BS6H 0.4 Ω, E-trim, AdcShare 3), 24 chunks | ≥ 39.78 dB, interval above, V2 per term | **40.62 [40.30, 40.94]**, no V2 fail | **PASS** |
| b2 | corners | ≥ 39.78 dB | SS 39.71 (FAIL −0.07); SS + 7-tick slots 39.74 (FAIL); **SS + adaptive VDD 0.7 V 40.31 (PASS +0.53)**; FF 40.03 [39.71, 40.37] (MARGINAL) | SS needs the VDD closure |
| b3 | fallbacks and sensitivities | as b1 | BS6H-cc 40.59; dt_x2 (fallback D) 40.65; AdcShare 4 40.64; ideal reference 40.62; linear drive law 40.62; R_PDN 1.3 Ω 39.80 (drive term 47.5 dB, V2 FAIL); 86 µV comparator 41.72 | PASS / MARGINAL |
| b4 | replaced choices | as b1 | all-StrongARM 31.76 (−8.0); ml2 38.82 (−0.96, kT/C 40.9); tokact operands 27.22 (−12.6) | FAIL (as expected) |
| b5 | adversarial popcount (every row on V in every slot) | as b1 | 42.47 (drive 62.3 dB) | PASS |
| c1 | t_pass on the RTL schedule | ≤ the golden plan | bit-serial AdcShare 3: **5.964 ns** (42 ticks); AdcShare 4: 7.384 ns (52); ml2: 5.538 ns (39, conversion-bound) | PASS |
| c2 | no stall, weights before activations | 0 after fill | 0 in all three | PASS |
| c3 | GEMV at the ARCH per-tile HBM share | B9 law | 28,144 ticks against the 28,032 law; tile busy 1.8 % | PASS |
| c4 | BS6H settling, 8 rows on V (measured table) | ≤ 0.1 % | TT 0.078 %; SS 0.238 % (open; 7-tick slots 0.043 %); 1.3 Ω 2.23 % | PASS at TT |
| e | energy per pass per 256-column tile (supplies integrated + booked events) | — | 138–187 pJ (supplies 39–88, events 98: conversions 276.8 fJ, column switches) | report |

### 4.4 Per-term SNR, the pick (dB, each term alone over the ideal quantizer, 24 K-chunks)

| term | TT | SS 0.63 V | SS 0.7 V | FF | budget (ARCH_CHOSEN) |
|---|---|---|---|---|---|
| quantization (12 b, one code = 64 MAC) | 58.5 | 58.5 | 58.5 | 58.5 | — |
| comparator (E-trim) | 44.1 | 44.2 | 45.0 | 43.1 | — |
| C-DAC | 45.6 | 45.6 | 45.6 | 45.6 | — |
| ADC class (unweighted) | 41.7 | 41.8 | 42.2 | 41.1 | 41.5 |
| thermal kT/C | 44.4 | 42.5 | 43.5 | 43.6 | 43.31 |
| unit mismatch | 48.1 | 48.1 | 48.1 | 48.1 | 46.02 |
| drive (measured table) | 72.7 | 60.6 | 60.6 | 72.7 | 54.81 |
| reference droop (after calibration) | 85.2 | 85.2 | 85.2 | 85.2 | 53.98 |
| merge / acc ratio | 82.3 / 73.9 | same | same | same | — |
| booked: hold, coupling, injection, row coupling, row gain | 60.7, 63.0, 73.9, 74.8, 76.9 | same | same | same | |
| **total / class-weighted** | **39.33 / 40.62** | 38.67 / 39.71 | 39.26 / 40.31 | 38.74 / 40.03 | 39.78 |

The block-8 scale format costs: 5-b mantissa 0.11 dB under exact scales; E4M3 (3-b) 0.45 dB (quick budget).

## 5. Transistor-level netlist (`netlist/imc_tile.py`)

One SpiceRack file. The top holds the configuration as plain constants (ROWS, COLS, SLICES, N_TILES,
DRIVE_MODE `bs6h` | `bs6h_cc`, ADC_SHARE, COMPARATOR `etrim` | `dt_x2` | `strongarm`, fins per device class,
VDD, CORNER, R_PDN, plus SHARE_SW and GC_BUF). Devices go through `analog/common/devices.fet` (W → fins; this
block added the `nfet_hvt` = `nmos_sram` kind), MOM units are ideal C as the PDK declares, and the PDN, row
strap and rail wire are interconnect elements. The SAR logic is Verilog-A (`va/imc_sar_logic.va`).

| subckt | what it is |
|---|---|
| `gc3t` | gain bit: SRAM-Vt write FET + inverter; with GC_BUF (default) a second inverter drives the crosspoint gates (gc5t) |
| `xp`, `smx`, `half`, `wcell` | crosspoint TG + ground leg per bit, sign mux per column side, 7 MOM units per side, one W8 weight |
| `rdrv`, `rows` | bit-serial row driver per row (NAND2 + rail inverter on the tile supply, strap, rail wire; bs6h_cc adds the dummy), 8 rows |
| `bsw`, `bank`, `col`, `ctl` | bootstrapped share switch; one accumulation bank (share switches, LSB acc + C_m merge cap, MSB acc as the 12 step caps of the C-DAC with sized enable TGs and idle pull-downs, bank reset); a column pair (4 top-plate resets, 4 banks); the per-bank phase decode |
| `dtf`, `dtq`, `sarm` | fast double-tail, quiet tail-starved double-tail (three ×2 slices, slices 2-3 on the trim bit), StrongARM |
| `bpd2_<f>`, `refbuf`, `conv` | 3-level bottom-plate drivers sized per step; class-A Miller follower for VCM; one converter (column/bank mux, comparators, drivers, logic) |
| `arr`, `cgrp`, `tile`, `tiles` | the array; 3 columns + their converter; a tile; N_TILES tiles on their R_PDN with the shared VCM buffer |

`--emit` writes `output/netlist/imc_tile.spice` (the full 8 × 256 tile ×2: 356 MOSFET cards in the subcircuit
bodies, 373,878 transistors per tile flattened, 130 per weight). `--draw` writes cktImg views to
`output/schematics/` (`<view>.spice`, `.json`, `.svg`, and `views.json`): each cell, or each stage of one, at the
full tile's sizing (the comparators as preamp and two half-latches, the bank as share / merge / step, a captioned
slice where a structure repeats), and block views of `half`, `wcell`, `rows`, `arr`, `col`, `conv`, `cgrp`,
`tile`, `tiles` at 2 rows × 3 columns with the nets an instance shares with one neighbour bundled into a bus.
Ports take their role from the `*@` sides. `docs/architecture/gen_architecture.py` draws them into the
architecture diagram (`docs/architecture/imc_architecture.pdf`). `--sim` runs the checks below (ESPice, the shared lock, 4 GB, `.tran 2p`).

### 5.1 Results (M = this ESPice run, D = derived)

| check | target | measured | result |
|---|---|---|---|
| bit-serial MAC, 8 × 4 tile, 3 passes on banks 0 / 1 / 0, merged V_diff against the golden's k·S | gain 0.80–1.05, residual after gain/offset ≤ 0.2 % FS | gc5t, 2/4-fin TGs, 64-fin reset: gain 0.922, offset 1.35 mV, residual 0.72 % FS, worst 16.8 mV (M). gc3t (N3_r2 sizing): gain 0.832, residual 2.12 % FS | FAIL (residual) |
| plate settling at the 6-tick share edge, 8 rows on V (worst popcount), share included | ≤ 0.1 % | 0.067 % (M; rail 0.020 %, tile supply min 0.579 V); gc3t 3.3 %, gc5t with 1-fin TGs 0.44 % | PASS |
| comparator noise, `.trannoise`, 198 decisions each | within COMPARATOR_ALT's band | fast 1.823 mV (1.645–2.017) against 1.82; quiet 0.601 mV (0.544–0.660) against 0.654 (M) | PASS |
| 8 full conversions on the bank C-DAC (VREF 0.7 V, VCM from `refbuf`) | gain ≤ 1.05, residual ≤ 4 LSB rms | codes 607, −448, −1, 1791, −1305, 156, −32, −1505 against the ideal-cap law 594, −446, 0, 1782, −1277, 148, −30, −1485; gain 1.012, residual 6.8 LSB rms (worst 10.8); 27.8 fC per conversion from VREF | FAIL (INL) |

How the transistor runs moved the design (each a sizing the behavioural models had hidden):

1. **The share kicks the bottom plates.** Opening the share moves the top plate (about 0.35 V for an all-ones
   plane) and kicks every unit's bottom plate through its cap; the drive must restore it inside the share.
   DRIVE_ALT's 0.078 % measured the rails without that event. With N3_r2's gc3t (the TG NMOS gated by the
   floating storage node, 1-fin TGs) the plate is 3.3 % off at the share edge (M); a buffered gate (gc5t)
   gives 0.44 %, and 2-fin bit TGs with a 4-fin sign mux 0.075 % (M, PASS; 4/8 fins 0.035 %). Before the
   bank fix below, larger TGs on the raw storage node made it worse (23.7 % at 4/8 fins, M): the rail swing
   couples into the floating node.
2. **The C-DAC bank must be held hard while it accumulates.** With 1-fin idle pull-downs the 27.6 fF MSB step
   cap's bottom floats on a 276 ps time constant, the share settles in about 130 ps (the golden assumes 39 ps;
   run through the golden, 133 ps costs about 8 dB of G2, D), and conversions inherit the previous bank state.
   Pull-downs and enable TGs now scale with the step (8 and 32 fins on the 1024 cap).
3. **The top-plate reset must clear 56 fF in half a tick.** With 4 fins the plane weights drift (the first
   plane counts 2.7× too much, plane ratio 23 instead of 64); 64 fins restore 64.9 (M).
4. **The DAC drivers and enables are sized per step** (32 fins for the 1024 cap) to settle inside t_dac
   45 ps; the redundant step absorbs the early residue.
5. **Converter INL.** 6.8 LSB rms over 8 points, ±11 LSB, with ideal caps: CM-dependent comparator input
   capacitance and the VCM start (+0.30 V on both sides) pushing a side towards VDD at large inputs (D).
   The golden has no INL term; at this size it would cap the ADC term near 33 dB (D). Next item.
6. **The reference buffer's feedback had to go to the mirror's diode side** (the PMOS output stage inverts).

Not done at transistor level: corners and Monte Carlo, the LSB-slice radix with the larger reset (plane ratio
94 for 64), the V7 bootstrap reliability check, energy of the drivers, and the full RTL schedule in ESPice.

## 6. Findings

1. **The digital path is correct and now hides the merge.** The hand-off sequencer runs BS6H at 42 ticks per
   pass with the conversion of the previous pass underneath, the write window opens only on weight-change and
   refresh passes, and the block-8 dequant is bit-exact against the golden (25 driver cases).
2. **AdcShare 3 is the pick** (§4.1): the drive binds at 5.94 ns, +8.6 to +16 % tok/s against AdcShare 4 for
   +34 % converters.
3. **G2 holds at TT (+0.84 dB) and FF (+0.25, marginal); SS needs adaptive VDD** (−0.07 dB at 0.63 V,
   +0.53 at 0.7 V). Its binding term is kT/C, so the 7-tick SS slots of DRIVE_ALT do not close it.
4. **The ping-pong banks are the largest unpriced cost**: 88 pF per tile, −26 % ARCH tok/s at MOM density
   if they need their own area. The MSB bank doubles as the C-DAC, which ARCH booked as 60 fF per converter.
5. **The transistor tile changes four sizings and one cell** (§5.1): the gain cell needs a buffered output
   (gc5t, +2 T per bit) and 2-fin crosspoint TGs; the top-plate reset needs 64 fins; the C-DAC enables,
   pull-downs and drivers scale with the step. The share event, not the rail rise, sets the slot.
6. **Open at transistor level:** the MAC residual (0.72 % FS after gain/offset, §5.1), the converter's INL (6.8 LSB rms), the LSB-slice
   radix with the larger reset, corners, and the B5 reference droop (130 µV per conversion against 3.7 µV;
   a calibrated static error in the Verilog-A budget, ref term 85 dB).
7. **The cost of the cell and switch fixes is not priced**: gc5t and 2-fin TGs raise the FEOL per weight
   past the 2.93 µm² BEOL MOM, so the array area grows; the arch_eval rows in §4.1 do not include it.

### 6.1 Logs

- `output/accuracy.json`, `output/accuracy.log`: §4.3 b and §4.4.
- `output/cosim_all.log`, `output/cosim_*`: a2, a4, e.
- `output/spice/results.json`, `output/spice/*/deck.sp`: §5.1 (keys tagged with the cell and sizing).
- `digital/imc_driver/build/test/*`: the driver traces and replays.

### 6.2 Tool limits hit

- An ESPice device holds at most 64 unknowns, ports and branch currents included: the driver co-simulates
  open loop, and `imc_sar_logic` drives its 35 outputs as Norton sources (a `V()` contribution per output
  would add 35 branch currents).
- A Verilog-A vector port is sized from the module's default parameter (`imc_sar AS=4` on a default-3 module
  fails `WrongNodeCount`): every converter instance uses AS = 3 and a short converter repeats its last column.
- `.tran 1p` with a PWL corner half-way between grid points (the 141.5 ps tick) collapses the step to
  2.6e-23 s (`TimestepTooSmall`); the transistor benches use `.tran 2p` with corners on the grid.
- An ESPice B-source takes at most 8 probes (event energies are booked in python); `@(cross)` on fast inputs
  drives the timestep to 0.1 fs (`imc_col` probes its inputs only inside events); `vera --check` fails on
  every model (lint is the gate).
- The shared lock is per ESPice run: an outer `flock` on the same file deadlocks `va_lib`.

## 7. Review responses (the pre-upgrade Verilog-A review, kept for the record)

The numbers in this table are the pre-upgrade run (ml2 / bit-serial 7-tick, StrongARM budget, AdcShare 4);
§4 supersedes them.

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
