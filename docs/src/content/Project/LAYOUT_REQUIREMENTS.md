# AnalogIOC layout requirements (per component)

Source of truth for device sizes: `analog/schematics/specs.py` (executable
design math) and `analog/schematics/sizing/SIZING.md`. This table drives the
substrate2 generators in `analog/layout/`. Sizes below reflect the O1 re-bias
(OTA I_side = 6 uA).

## 1. weight_tile (16 rows x 17 cols differential)

| Device/group | Type | W/L or value | Count | Matching/layout constraint |
|---|---|---|---|---|
| Cap unit C_U | MOM cap | 0.15 fF, binary-weighted 2^0..2^3 | 16x17x2 banks x4 bits | All banks share exact C_U; differential C+/C- |
| Ballast C_BALL | MOM cap | 4 fF per bank top | 16x17x2 | Top-plate impulse absorber |
| Rail ballast C_RAIL | MOM cap | 500 fF per column | 17 | Absorbs charge impulses; never disconnected |
| Transfer TG | CMOS switch | N 0.42/0.15, P 0.42/0.15 equal-width | 16x17x2 | Equal-width n/p (overdrives match at 0.9 V rail) |
| Recharge TG | CMOS switch | N 0.42/0.15, P 0.42/0.15 | 16x17x2 | Pull to vcm during phi1 |
| Dummy pair | N+P, S=D | 0.42/0.15 each | 16x17x2 | Nulls channel injection |
| Row drivers | pwm_driver | see below | 16 | One per row |
| Phi buffers | Inverter chain | final 4/8 N/P | 4 | 2:1 P:N |

Structure: 16 rows x 17 columns (16 data + checksum). Crosspoint = 2 4-bit
banks (C+/C-). Column rails → integrator virtual grounds. Common-centroid
within banks.

## 2. gain_cell_array (8x8)

| Device/group | Type | W/L or value | Count | Constraint |
|---|---|---|---|---|
| Write switch | NFET | 0.42/0.5 | 64 | Long L for retention; Ron ≤ 64 kΩ at 0.9 V |
| Storage cap Cs | MOM | 30 fF | 64 | Isolate from coupling |
| Read device | NFET | 0.42/0.5 | 64 | Gate on storage node, subthreshold read |

Wiring: wdata row-shared, wsel column one-hot, rd row source line (0.9→0 V
pulse), col rails to integrators (≤10 uA/column class-A budget).

## 3. integrator_conv (one per differential column pair, 17 total)

| Device/group | Type | W/L or value | Count | Constraint |
|---|---|---|---|---|
| OTA input pair | NFET | 0.54/0.3 | 2 | gm/ID=12, 6 uA/side, pair-matched |
| OTA n-cascode | NFET | 0.37/0.3 | 2 | gm/ID=10 |
| OTA p-cascode | PFET | 2.63/0.5 | 2 | gm/ID=10, Vds ≥ 0.25 V |
| OTA p-mirror | PFET | 2.63/0.5 | 2 | Pair-matched to cascode |
| OTA tail | NFET | 7.06/0.5 | 1 | gm/ID=18, 12 uA, vb_tail 0.665 V |
| C_int | MOM | 200 fF | 1 | ±0.25 V swing about vcm 0.9 V |
| Reset TG | CMOS switch | 0.42/0.15 pair | 1 | phi1 gated |
| Kick filter R | precision res | ~5.3 kΩ | 2 | Matched pair, coarse comp inputs |
| Kick filter C | MOM | ~60 fF | 2 | Hold caps |
| Coarse + SAR comparators | StrongARM | see below | 2 | |
| Ref mux TGs | wide TG | N 1.68/0.15, P 3.36/0.15 | 3 coarse + 4 SAR | vcm/thr_p/thr_n; vref/vref_o |
| Packet bank | tile bank clone | C_u x 2^b + 4 fF ballast | 1 | SAME design as tile bank (1:1 charge ratio) |
| SAR CDAC | MOM array | 30 fF unit: 8/4/2/1 + 0.5 + 0.5 | 6 caps | Binary-weighted, mid-tread half-LSB |
| SAR anti-kick | R+C | 8 kΩ + 60 fF | 2 | Against hard vcm |
| Ref reservoirs | MOM | 5 pF | 2 | vref/vref_o rails |

## 4. strongarm

| Device/group | Type | W/L | Count | Constraint |
|---|---|---|---|---|
| Input pair | NFET | 7.0/0.15 | 2 | gm/ID≈13, pair-matched |
| Latch N | NFET | 1.0/0.15 | 2 | Cross-coupled, matched |
| Latch P | PFET | 4.5/0.15 | 2 | 4.5x N width (un/up≈3) |
| Tail | NFET | 0.42/0.15 | 1 | Min-size, clocked |
| Precharge | PFET | 1.0/0.15 | 2 | Reset outputs high |

Offset uncritical for coarse loop (threshold shift only); latch pairs matched.

## 5. rstring_ladder (two instances: coarse thresholds + SAR refs)

| Device/group | Type | Value | Count | Constraint |
|---|---|---|---|---|
| Segments | precision poly res | 8 kΩ each | 15 | Equal-value, monotone by construction |
| Per-tap decap | MOM | 29 pF | 14 | Kick hold; silicon only needs used taps |
| Tap mux TG | wide TG | N 3.36/0.15, P 6.72/0.15 (4x) | 16 | Ron ≈ 7 kΩ into CDAC |
| 4:16 decoder | NAND2/NOR2/INV | min-size | 16 sets | One-hot |

## 6. write_dac (two per sidecar: wda/wdb)

Same structure as rstring_ladder, smaller: 15 x 10 kΩ segments (vss..vref
0.9 V), baseline TGs N 0.42/0.15 P 0.84/0.15, 4:16 decoder. LSB 60 mV.

## 7. pwm_driver (16 per tile)

NAND2 logic (outa = (inp&phi1e)|(inn&!phi1); outb mirror) + 2-stage buffers
(mid 0.84/1.68, final 4.0/8.0 N/P) for ~100 fF row load. outa/outb slew
matching = equal charge fraction both signs.

## 8. lora_sidecar

A(16) + B(16) gain cells (same 2T cell as gain_cell_array), A.x integrator
(telescopic OTA + 1 pF C_int + reset TG), ramp PFET 0.875/0.5 (~2 uA) +
enable PFET 2.52/0.15 + 100 GΩ bleed, comparator OTA + 3-inverter chain
(stage-1 skewed N 1.26/0.15) + NAND, B-driver N 100/0.15 pull-down + P
10/0.15 restore, 2x write_dac. colb drains tie to tile integrators.

## 9. async_ctrl

Reset chain 10 stages + settle chain 20 stages (inverter pairs 0.42/0.84 +
220 fF loads), Muller C-element (P-series 1.0/0.15, N-series 0.5/0.15,
keepers), tq_chain 4 taps x 2 inverters + 550 fF loads (~10 ns/tap).

## Inter-component interfaces

- Column summing rails: tile cols + sidecar colb + gain-cell cols all tie to
  OTA virtual grounds (inn). Charge-domain: matching = summed caps correct.
- OTA BIAS (vb_nc 1.25, vb_pc 0.29, vb_tail 0.665 V) shared across all 17
  column OTAs + sidecar OTAs.
- Ladder taps broadcast: thr_p/thr_n to all coarse comparators, sar_p/sar_n
  to all CDACs. Ratiometric to Q_UNIT (measured 0.9906x ideal).
- Packet bank must be a layout CLONE of the tile bank (charge ratio 1:1).
- phi1/phi1e/phi2 global; clock gating outside integration window (A8 fix)
  is a tile_fsm silicon feature.

## Gate lengths needed (drives Tech trait scope)

150 (switches, latches, logic), 300 (OTA in/ncasc), 500 (OTA p-side/tail,
gain cells, ramp). Upstream sky130 ATOLL MOS tile only ships
L150 — custom long-L tile required (first work item in analog/layout).
