# weight_tile — charge-domain capacitive crossbar

The MVM array of Chip 1: 16 rows × (16 + 1 ABFT checksum) columns of differential 4b
cap banks. Row `i` is driven by its own `pwm_driver` from the PWM nibble on
`xin_p_r<i>` / `xin_n_r<i>`; column `j` dumps charge onto `col<j>`, the virtual ground
of `integrator_conv` `j` (see `analog/docs/architecture.md` §Signal chain). AnalogIOC
source: `components/weight_tile/weight_tile.py` (`generate`, `read_caps`).

## Interface

`build(Cp, Cn, chk)` is AnalogIOC's `generate()`: the ports follow the shape the codes make.

`.subckt weight_tile xin_p_r0 xin_n_r0 .. xin_p_r{R-1} xin_n_r{R-1} col0 .. col{C-1} phi1 phi1e phi2 vcm vdd vss`

| Port | Dir | Meaning |
|------|-----|---------|
| xin_p_r*i*, xin_n_r*i* | in | row PWM envelope, positive / negative rail (A5 format, width = nibble × t_chop) |
| col*j* | inout | column rail = integrator virtual ground (col16 = ABFT checksum) |
| phi1 | in | bank tops to vcm (recharge) |
| phi1e | in | phi1 with a stretched fall, gates the row drivers (pwm_driver) |
| phi2 | in | bank tops to the column rail (transfer) |
| vcm | in | `specs.VCM_FRAC` × VDD |
| vdd, vss | supply | `pdk_specs.vdd`, 0 |

The full tile (R = 16, C = 17, weights from `read_caps(caps.spice)`) is what `analogioc`
instantiates. The **canonical deck** (`netlist/weight_tile.spice`: layout, `DUT=sch`,
`va/weight_tile.va`) is one crosspoint, R = C = 1, with both banks at code 15 — every
device a crosspoint can own:
`.subckt weight_tile xin_p_r0 xin_n_r0 col0 phi1 phi1e phi2 vcm vdd vss`.
Weights are compile-time constants: a zero bit has no capacitor. The testbenches program
columns from it (`test/tile.py`): `DUT=sch` rebuilds the exact column with `build()`,
`DUT=va` / `DUT=pex` stack one programmed crosspoint per row on one rail.

Convention: +W·+x moves charge that raises the integrator output (`vout` of the test
fixture): one MAC code unit = `specs.c_u()` × VDD / `specs.c_int()` = `specs.u1()` of
excursion.

## Topology (AnalogIOC's, device for device)

Per tile: two phi buffers (phi1, phi2 → true/complement `phi*_i`, `phi*_b_i`, three
inverters each), one `pwm_driver` per row (`rowa`/`rowb`), one C_RAIL per column. Per
nonzero bank (C+ on `rowa`, C− on `rowb`):

| Device | Role | Nets |
|--------|------|------|
| bit caps b0..b3 | C_u·2^b, only the bits set in the code | top — row line |
| ball | top-plate ballast | top — vss |
| sv (`weight_tile_tg`) | recharge TG, phi1 | top — vcm |
| st (`weight_tile_tg`) | transfer TG, phi2 | top — col |
| dun / dup | complementary-clocked S = D = rail dummies | col |
| rail | column rail ballast (never disconnects) | col — vss |

Canonical deck: 58 FETs (pwm_driver 34, phi buffers 12, 4 TGs 8, 4 dummies) + 11 MIM caps.

## Specs

LSB = `specs.u1()` = 1.35 mV (C_u 0.15 fF, C_int 200 fF, VDD 1.8 V). Measured on the
real column integrator (migrated `ota` + replica bias, C_int, reset TG — AnalogIOC's
instrument), chop grid of `tb_pwm_driver` (t_chop = `specs.TQ_SIM`).

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
| Null |µ| + 3σ, Monte Carlo (mismatch) | | | 1.5 | LSB | `tb_weight_tile_mc` |

Rows 1–6 are AnalogIOC's `tb_weight_tile` thresholds. Not ported (need the migrated
`integrator_conv` converter): tb_cascade codes vs golden and energy/pass; tb_csnr
`logs`/`uncorr`/`lever`/`gainsweep` and its converter-CSNR verdict; `diag_countinl`
(coarse-loop INL vs packet count — every mode runs the converter);
`a10_closure_driver` (per-column measured gain through `tb_tile_mvm`, writes
`CASCADE.md`). They belong to `integrator_conv` / `analogioc`.

## Sizing

Derived in `netlist/weight_tile.py` from `get_pdk()`, `specs`, `pwm_driver.j_on` and a
gate-capacitance measurement on the PDK's own models (`netlist/char/<pdk>.json`). No FET
has a gm/ID coordinate: every one is a switch or logic driven rail to rail.

| Device | Derivation | sky130 | AnalogIOC hand |
|--------|-----------|--------|--------------|
| TG (sv, st) | R_on: vcm clamp recharges 15·C_u + C_BALL to B_Y bits in phi1 (1.6 ns); square-law triode at vcm with W_p = W_n (equal widths balance n/p injection at mid-rail); min_w floor | 0.42/0.15 both | 0.42/0.15 both |
| dummy | W_tg/2 (a dummy takes half the switch's channel charge), min_w floor | 0.42/0.15 | 0.42/0.15 |
| phi buffer i1 | logic: min_w, P for equal current (J_ON ratio) | 0.42 / 1.16 | 0.42 / 0.84 |
| phi buffer i2, i3 | 10–90 % edge in PHI_GAP/2 = 0.2 ns into a full tile's switch gates (2·16·17 banks × (C_g,n·W_tg + C_g,p·W_dum)) | 10.36 / 28.56 | 4 / 8 |
| C_u | `specs.c_u()` (swing law) | 0.15 fF | 0.15 fF |
| C_BALL | a code-15 top floating through a VDD bottom step stays above VCM/4 | 3.75 fF | 4 fF |
| C_RAIL | worst same-sign burst 34·C_u·VDD bounces the rail < the OTA pair's 0.5 %-linear input (√(3·0.005)·2/(gm/ID)_in) | 450 fF | 500 fF |

All L = min_l. Caps go through `devices.mim_cap` (area + perimeter). C_u, its binary bits
and C_BALL are below sky130's 1 µm MIM minimum: exact in simulation (warned on stderr),
MOM/fringe caps in silicon — AnalogIOC used ideal C.

## Findings

* **Unit-cap mismatch vs the stage SNR.** AnalogIOC's `tb_csnr` budget, recomputed here:
  with a projected A_c = 1 %·µm the 0.15 fF unit alone gives CSNR 31.0 dB on pass_05
  and 34.8 dB on pass_09, against `specs.SNR_S_DB` = 34. The mismatch power goes as
  1/C_u, and C_u is fixed by the swing law, so fixing it is an architecture change: C_u
  up with C_int (tile + converter), or a measured A_c. Reported, not gated.

## Results

RESULTS
