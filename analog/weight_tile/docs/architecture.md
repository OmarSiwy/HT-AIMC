# weight_tile — charge-domain capacitive crossbar, reprogrammable

Schematic, drawn by cktImg from `netlist/weight_tile.spice` (`make import NETLIST=weight_tile`): [weight_tile.svg](weight_tile.svg)

The MVM array of AnalogIOC: 16 rows × (16 + 1 ABFT checksum) columns of differential 4b
cap banks. Row `i` is driven by its own `pwm_driver` from the PWM nibble on
`xin_p_r<i>` / `xin_n_r<i>`; column `j` dumps charge onto `col<j>`, the virtual ground
of `integrator_conv` `j` (see `analog/docs/architecture.md` §Signal chain). AnalogIOC
source: `components/weight_tile/weight_tile.py` (`generate`, `read_caps`).

Weights are runtime state (`analog/analogioc/docs/INTERFACE.md` D7, D10, D11, §7): every
crosspoint stores its codes Cp[3:0], Cn[3:0] in 8 write-only 6T bitcells, written one row
at a time through `wwl`/`wd`. The netlist is the same for every pass.

## Interface

`build(n_rows, n_cols)`; `analogioc` instantiates `build(16, 17)` and wires `w_wl`/`w_data`
straight through (§7.5):

```
.subckt weight_tile xin_p_r0 xin_n_r0 .. xin_p_r15 xin_n_r15 col0 .. col16
+ wwl0 .. wwl15 wd0 .. wd135 phi1 phi1e phi2 vcm vdd vss
```

| Port | Dir | Meaning |
|------|-----|---------|
| xin_p_r*i*, xin_n_r*i* | in | row PWM envelope, positive / negative rail (A5 format, width = nibble × t_chop) |
| col*j* | inout | column rail = integrator virtual ground (col16 = ABFT checksum) |
| wwl*i* | in | word line of row *i* (= `w_wl[i]`): while high, row *i*'s 136 bits follow `wd`; the value at its fall is stored |
| wd*k* | in | row data (= `w_data[k]`): column *j* = `wd[8j+7:8j]`, Cp = `[8j+3:8j]`, Cn = `[8j+7:8j+4]`; `row_word(cp, cn)` builds it |
| phi1 | in | bank tops to vcm (recharge); parked high outside the window |
| phi1e | in | phi1 with a stretched fall, gates the row drivers (pwm_driver) |
| phi2 | in | bank tops to the column rail (transfer); parked low outside the window |
| vcm | in | `specs.VCM_FRAC` × VDD |
| vdd, vss | supply | `pdk_specs.vdd`, 0 — logic, drivers, storage and tile on one rail |

The **canonical deck** (`netlist/weight_tile.spice`: layout, `DUT=sch`,
`va/weight_tile.va`) is one crosspoint, R = C = 1:
`.subckt weight_tile xin_p_r0 xin_n_r0 col0 wwl0 wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 phi1 phi1e phi2 vcm vdd vss`.
Testbenches program tiles through the port (`test/tile.py`): a write phase with the tile
parked, then the chop grid. `DUT=sch` builds the exact R × C tile, `DUT=va` / `DUT=pex`
stack one crosspoint per (row, column).

Convention: +W·+x moves charge that raises the integrator output (`vout` of the test
fixture): one MAC code unit = `specs.c_u()` × VDD / `specs.c_int()` = `specs.u1()` of
excursion. Q = 1 puts a bit cap on its row line.

## Topology

Per tile: two phi buffers (phi1, phi2 → true/complement `phi*_i`, `phi*_b_i`, three
inverters each), one `pwm_driver` per row (`rowa`/`rowb`), one WL buffer per row (2
inverters), one bitline driver per `wd` bit (BLB = !wd, BL = !BLB; vertical bitlines, 16
cells each), one C_RAIL per column. Per bank (C+ on `rowa`, C− on `rowb`), every code:

| Device | Role | Nets |
|--------|------|------|
| bit caps b0..b3 | C_u·2^b, all four always present | top — bit bottom |
| `weight_tile_bit` ×4 | write-only 6T (`weight_tile_cell`: cross-coupled inverters + 2 access nfets) and its bottom-plate selector: TG bottom—row (n gate Q, p gate QB), nfet bottom—vss (gate QB) | bottom, row, wl*i*, bl/blb, qb |
| ball | top-plate ballast | top — vss |
| code-zero gate | en = NAND4(QB0..3) (code ≠ 0); st = phi2_i·en (NAND2 + inverter), stb = !st one inverter later | local |
| sv (`weight_tile_tg`) | recharge TG, phi1_i/phi1_b_i | top — vcm |
| st (`weight_tile_tg`) | transfer TG, st/stb (a zero bank never connects) | top — col |
| dun / dup | complementary-clocked S = D = rail dummies on stb/st | col |
| rail | column rail ballast (never disconnects) | col — vss |

The top-plate cap is 15 C_u + C_BALL for every code; the selectors are static during
integration, so they inject nothing onto the summing node. A zero bank is gated off the
column: without the gate every one of a column's 32 banks dumps its 6 fF top onto the
column every phi2 whatever its code, a switched capacitance that hands the OTA's
virtual-ground residual back to vcm each cycle (measured: a lone W = 13 bank in a 16-row
column read 63 % of its charge, a W = 0 column drifted −3..−15 LSB per window). The
fixed-code AnalogIOC tile had the same property for free: it emitted no zero bank.
This gate is the one addition to INTERFACE §7.2's crosspoint ("sv/st TGs and dummies
unchanged"): st and its dummies now take a per-bank st/stb instead of the shared
phi2_i/phi2_b_i. No port changes.

Canonical deck: 198 FETs (pwm_driver 34, phi buffers 12, WL buffer 4, 8 bitline drivers
32; per bank 58 = 4 × (6T + 3 selector) + gate 16 + sv/st 4 + dummies 2) + 11 MIM caps.
Full 16 × 17 tile: ~32.7 k FETs, 13,056 of them storage (2176 bits).

## Specs

LSB = `specs.u1()` = 1.35 mV (C_u 0.15 fF, C_int 200 fF, VDD 1.8 V). Measured on the
real column integrator (migrated `ota` + replica bias, C_int, reset TG — AnalogIOC's
instrument), chop grid of `tb_pwm_driver` (t_chop = `specs.TQ_SIM`), weights written
through the port first.

| Metric | Min | Typ | Max | Unit | Testbench |
|--------|-----|-----|-----|------|-----------|
| Single-crosspoint linearity, Cp 0..15 at nibble 10 | 0.999 | | | R² | `tb_weight_tile` |
| Slope vs design nibble·u1 | 90 | | 110 | % | `tb_weight_tile` |
| Differential null Cp = Cn = 8 | | | 1.5 | LSB | `tb_weight_tile` |
| Sign mirror −x vs +x, Cp = 8 | | | 2 | % | `tb_weight_tile` |
| Cancelling column 32:32 units/cycle (real worst 34) | | | 1.5 | LSB | `tb_weight_tile` |
| Cancelling column 64:64 (2× beyond real) | | report | | LSB | `tb_weight_tile` |
| K-window charge accumulation, pass_05, K = 1/2/4, after one per-column gain | | | 1 | LSB at K·D | `tb_cascade` |
| Chain time vs `specs.cascade_window_chain_time(K)`; chain(K) < K·chain(1) | | | 40 | ns | `tb_cascade` |
| kT/C CSNR, pass_05 / pass_09 | `SNR_S_DB` + 6 = 40 | | | dB | `tb_csnr` |
| Unit-cap mismatch CSNR (A_c 1 %·µm, projected) | | report | | dB | `tb_csnr` |
| Charge delivery into an ideal virtual ground, 4/11/21 units | 98 | | | % | `tb_csnr isolate` |
| Null \|µ\| + 3σ, Monte Carlo (mismatch) | | | 1.5 | LSB | `tb_weight_tile_mc` |
| **A11** write → read back by MAC, rows 0/15, (v,0)/(0,v)/(v,v) with v and 15 − v, nibble 7: \|read − 7W\| (tile charge / u1 / k_cal) | | | 3 | LSB | `tb_weight_readback` |
| **A11b** all 16 rows rewritten to the complement during the hold: \|Δvout\| vs idle | | | 1 | LSB | `tb_weight_write_disturb` |
| Cell write margin (BL level flipping a stored 1, WL = BLB = VDD) | `wm_min()` | | | V | `tb_weight_write` (+ corners) |
| Row write at 0.9 VDD: every bit of a full row stores; wwl↑ → Q 50 % | | | `T_WRITE_CELL` = 2 | ns | `tb_weight_write` (+ corners) |
| Storage leakage, 2176 bits | | | 1 % of OTA static | W | `tb_weight_write` (+ corners) |
| Row-line 10–90 % edge, full programmed row (`specs.c_row()`) | | | TQ_SIM/3; reported vs t_q_floor/3 | s | `tb_weight_write` |
| Write energy per row / per pass (Q13) | | report | | pJ | `tb_weight_write` |
| Write yield, Monte Carlo of one cell: every sample writes; mean − zσ ≥ 0 for `YIELD` over 2176 bits | 0.999 | | | | `tb_weight_write_mc` |

Rows 1–6 are AnalogIOC's `tb_weight_tile` thresholds. A11/A11b are the tile side of
INTERFACE §11 (the converter is not migrated yet, so the "code" is the integrator charge
in LSB after `k_cal`; the full-width MAC readback through the converter is the analog
top's A11). The wd → (column, bit) mapping of all 17 columns is checked bit by bit on
the storage nodes by `tb_weight_write` (row tile, 136 bits, word and complement); the WL
addressing of rows 0 and 15 and the Q → MAC path by `tb_weight_readback` on a 16-row
column. Not ported (need the migrated `integrator_conv`): tb_cascade codes vs golden and
energy/pass; tb_csnr `logs`/`uncorr`/`lever`/`gainsweep` and its converter-CSNR verdict;
`diag_countinl`; `a10_closure_driver`.

## Sizing

Derived in `netlist/weight_tile.py` from `get_pdk()`, `specs`, `pwm_driver.j_on` and
measurements on the PDK's own models (`netlist/char/<pdk>.json`: gate cap, write margin;
`pdk_char`: drain cap). No FET has a gm/ID coordinate: every one is a switch, logic or a
latch driven rail to rail.

| Device | Derivation | sky130 | AnalogIOC hand |
|--------|-----------|--------|--------------|
| TG (sv, st) | R_on: vcm clamp recharges 15·C_u + C_BALL to B_Y bits in phi1 (1.6 ns); square-law triode at vcm with W_p = W_n (equal widths balance n/p injection at mid-rail); min_w floor | 0.42/0.15 both | 0.42/0.15 both |
| dummy | W_tg/2 (a dummy takes half the switch's channel charge), min_w floor | 0.42/0.15 | 0.42/0.15 |
| phi buffer i1 | logic: min_w, P for equal current (J_ON ratio) | 0.42 / 1.16 | 0.42 / 0.84 |
| phi buffer i2, i3 | 10–90 % edge in PHI_GAP/2 = 0.2 ns into a full tile's switch gates (2·16·17 banks × (C_g,n·W_tg + C_g,p·W_dum)) | 10.36 / 28.56 | 4 / 8 |
| 6T pull-down, access | min W/L: no read port, so no β ratio; least leakage and BL/WL load | 0.42/0.15 | — |
| 6T pull-up | min W; L stepped from 2 min_l (INTERFACE §7.2) until the worst write margin over 5 corners × −40/27/125 °C ≥ `wm_min()` = z·σ_Pelgrom(access + pull-up), z = 4.9 for `YIELD` 0.999 over 2176 bits | 0.42/0.30 (first step holds: worst 561 mV at fs/125 °C vs 89 mV) | — |
| selector TG + pull-down | min W/L: R_on into ≤ 8 C_u is ps-scale; larger only loads the row line and Q/QB | 0.42/0.15 | — |
| code-zero gate | NAND4 / NAND2 at logic sizes; st/stb inverters `ST_DRIVE` × logic: the injection balance wants fast local edges (32:32 column 1× −2.74, 2× −1.77, 4× −1.14 LSB) | 1.68 / 4.64 | — |
| WL buffer | logic → drive: 10–90 % in `WRITE_EDGE` = T_WRITE_CELL/4 into 2·8·17 access gates + 17 crosspoints of wire | 1.2 / 3.31 | — |
| bitline driver | same edge into 16 access drains + 16 crosspoints of wire; floored at logic | 0.42 / 1.16 | — |
| C_u | `specs.c_u()` (swing law) | 0.15 fF | 0.15 fF |
| C_BALL | a code-15 top floating through a VDD bottom step stays above VCM/4 | 3.75 fF | 4 fF |
| C_RAIL | worst same-sign burst 34·C_u·VDD bounces the rail < the OTA pair's 0.5 %-linear input (√(3·0.005)·2/(gm/ID)_in) | 450 fF | 500 fF |

All L = min_l except the pull-up. Wire loads use `specs.XP_PITCH` (15 wire pitches per
crosspoint) × `specs.C_WIRE` (0.2 fF/µm), the convention of `specs.t_q_floor`. Caps go
through `devices.mim_cap` (area + perimeter). C_u, its binary bits and C_BALL are below
sky130's 1 µm MIM minimum: exact in simulation (warned on stderr), MOM/fringe caps in
silicon — AnalogIOC used ideal C.

**Row line and t_q_floor (§7.5).** `specs.c_row()` = 17 banks × 15 C_u (every bit on) +
the selectors' drains (per bit 3 n + 2 p min-W drains, `pdk.cd_n/p_ff_um`) + wire =
101 fF on sky130 (was 53 fF for 16 code-15 banks, no selectors). Row RC 16.1 ps (was
8.5 ps), so `t_q_floor` stays jitter-bound at 200 ps. The measured row edge with a full
programmed row is 127 ps — pwm_driver's C_ROW = 100 fF design point now carries no
margin, and the edge already exceeds t_q_floor/3 = 67 ps (it did before: 136 ps into
100 fF, pwm_driver docs). A silicon-t_q tile needs a stronger row driver.

## Findings

* **Write disturb (Q10) is negligible pre-layout.** Rewriting all 16 rows to the bitwise
  complement (every bit of the column toggles) while the integrator holds moves vout by
  0.004 LSB peak (5.6 µV), 0.000 LSB at the end. With the tile parked the row lines sit
  at 0, so a selector flip moves its bottom plate 0 → 0; what remains is gate coupling
  through the off transfer TG. Ping-pong weight banks are not needed on this evidence.
  Re-check post-layout: the WL/BL wires crossing the column rails are the coupling
  path this netlist cannot see.
* **Write energy (Q13).** 13.2 pJ per row with every bit toggling, 0.46 pJ with none
  (WL + leakage); random data ≈ ½ → 109 pJ per pass (16 rows), 7.5 % of
  `specs.pass_energy_pj()` (1461 pJ); worst 211 pJ. Dominated by the 272 bitlines
  (BL + BLB, ~19 fF each with wire). Pre-layout wire model, nominal tt/27 °C.
* **Charge per unit dropped 1.6 %.** The code-independent top (15 C_u + C_BALL) keeps
  more of each transfer behind than the fixed-code tile's code·C_u + C_BALL: slope
  97.5 % (was 99.1 %). `specs._CAL["sky130"]["k_cal"]` re-measured by the A7 method:
  263.18 aC/unit = 0.9747 (was 267.45 aC = 0.9906); the converter's reference spans
  follow it.
* **Unit-cap mismatch vs the stage SNR.** AnalogIOC's `tb_csnr` budget, recomputed here:
  with a projected A_c = 1 %·µm the 0.15 fF unit alone gives CSNR 31.0 dB on pass_05
  and 34.8 dB on pass_09, against `specs.SNR_S_DB` = 34. The mismatch power goes as
  1/C_u, and C_u is fixed by the swing law, so fixing it is an architecture change: C_u
  up with C_int (tile + converter), or a measured A_c. Reported, not gated.

## Results

Simulator ESPice (SpiceRack backend `espice`, main 1b2b91e) unless noted; ngspice 45 ran
the same benches before the switch, and every number below agreed to the digits shown
(write margin, write time, energy, edge, A11b identical; tb_weight_tile within 0.06 LSB;
null MC σ 22.0 vs 20.6 LSB — different RNG, same spread).

| Rung | Bench | Result |
|------|-------|--------|
| golden model (`DUT=va`) | `make test` | PASS all 7: R² 1.000000, slope 98.8 %, null +0.18, mirror 0.73 %, 32:32 −0.39 LSB; A11 worst 0.60 LSB; A11b 0.000 LSB; cascade K=1/2/4 worst 0.55/0.24/0.23 LSB; csnr PASS |
| pre-layout (`DUT=sch`, tt 27 °C) | `tb_weight_tile` | PASS: R² 0.999899, slope 97.5 %, null +0.32 LSB, mirror 0.98 %, 32:32 −1.20 LSB (info 64:64 −5.18) |
| | `tb_weight_readback` (A11) | PASS: worst 1.79 LSB over rows 0/15 × 6 runs (4/12 outside ±1) |
| | `tb_weight_write_disturb` (A11b, Q10) | PASS: 0.004 LSB peak (5.7 µV), 0.000 at end; busiest pass_05 column (13, mac −89) |
| | `tb_weight_write` | PASS: margin 774 mV (≥ 89), 9.1 pA/bit (0.036 µW tile), row write 628 ps at 1.62 V / 512 ps at 1.8 V, row edge 127 ps, 13.2 pJ/row all toggling, 109 pJ/pass |
| | `tb_csnr` | PASS: kT/C 50.3 / 54.8 dB; ideal-VG delivery ≥ 1.02; busy-column nominal 0.92 |
| | `tb_cascade` | CASCADE |
| corners (`tb_weight_write`, 5 corners × −40/27/125 °C) | `corners.py` | PASS 15/15 (table below) |
| Monte Carlo | `tb_weight_write_mc` (200 seeds, tt_mm) | PASS: 200/200 write; margin 772 ± 19.4 mV (Pelgrom estimate 18 mV), min 712; mean − 4.91σ = 677 mV |
| | `tb_weight_tile_mc` (30 seeds) | **FAIL, pre-existing**: null mean −3.8, σ 22.0 LSB. The fixed-code deck it replaces fails the same way (10 seeds, ngspice: mean +9.5, σ 15.4); with an ideal OTA σ falls to 5.5 LSB, so the integrator's input offset × the switched bank capacitance dominates, not the tile. Owner: ota / integrator_conv (offset sampling or chopping); the 1.5 LSB gate was never met post-migration. |

Write corners (ESPice, `tb_weight_write`; write time at 1.62 V, budget 2 ns):

| corner | margin mV (−40/27/125) | write ps (−40/27/125) | leakage pA/bit at 125 °C | row edge ps |
|---|---|---|---|---|
| tt | 762 / 774 / 784 | 658 / 628 / 603 | 33.8 | 125–134 |
| ss | 678 / 691 / 703 | 986 / 914 / 860 | 11.4 | 166–170 |
| ff | 857 / 863 / 867 | 472 / 466 / 468 | 375 | 99–114 |
| sf | 942 / 964 / 993 | 798 / 721 / 654 | 519 | 172–178 |
| fs | 573 / 571 / 561 | 612 / 617 / 638 | 409 | 96–116 |

Worst write margin 561 mV (fs, 125 °C); slowest write 986 ps (ss, −40 °C, 1.62 V);
worst leakage 519 pA/bit (sf, 125 °C) = 2.0 µW for the tile, 0.55 % of OTA static.
Write energy over corners 12.7–14.1 pJ/row, 105–116 pJ/pass.
